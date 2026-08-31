"""LLMSummarizer 测试:fake LLM 注入、降级链、成本记录、提示词文件与温度冻结。"""

from __future__ import annotations

import pytest

from bdlh_runtime.context import ConservativeTokenCounter
from bdlh_runtime.session import LLMSummarizer, load_summary_system_prompt
from bdlh_runtime.session.llm_summary import SummaryUsage
from bdlh_runtime.session.llm_summary import load_summary_system_prompt as _load


class FakeMessage:
    def __init__(self, content: str, usage_metadata: dict | None = None, response_metadata: dict | None = None):
        self.content = content
        self.usage_metadata = usage_metadata
        self.response_metadata = response_metadata or {}


class FakeLLM:
    """记录调用并返回预置响应;raise_exc 时抛异常。"""

    def __init__(self, content: str = "", *, usage_metadata: dict | None = None, raise_exc: Exception | None = None):
        self.content = content
        self.usage_metadata = usage_metadata
        self.raise_exc = raise_exc
        self.calls: list[tuple[list, dict]] = []

    def invoke(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if self.raise_exc:
            raise self.raise_exc
        return FakeMessage(self.content, usage_metadata=self.usage_metadata)


def _texts() -> list[str]:
    return [
        "用户决定:数据库只用 PostgreSQL,不引入新依赖。",
        "助手确认:docs 目录结构保持三层,不再调整。",
        "用户补充:所有工具返回都是冻结 Mock,不得当作真实 API。",
    ]


# ── 提示词与温度 ──────────────────────────────────────────────────────────


def test_summary_system_prompt_loads_from_file() -> None:
    prompt = load_summary_system_prompt()
    assert "只依据给定材料" in prompt
    assert "已废弃" in prompt
    assert "Token 上限" in prompt
    assert _load is load_summary_system_prompt


def test_llm_call_uses_temperature_zero_and_file_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class RecordingLLM(FakeLLM):
        def invoke(self, messages, **kwargs):
            captured["messages"] = messages
            captured["kwargs"] = kwargs
            return super().invoke(messages, **kwargs)

    llm = RecordingLLM("摘要内容:保留 PostgreSQL 决定。", usage_metadata={"input_tokens": 100, "output_tokens": 20})
    summarizer = LLMSummarizer(llm=llm)
    counter = ConservativeTokenCounter()
    result = summarizer.summarize(_texts(), 200, counter)
    assert result.startswith("[history-summary method=llm-single-summary-v1")
    assert "PostgreSQL" in result
    messages, kwargs = captured["messages"], captured["kwargs"]
    assert messages[0]["role"] == "system"
    assert "只依据给定材料" in messages[0]["content"]  # 提示词来自文件而非内联
    assert kwargs.get("seed") == 0  # 冻结口径


def test_llm_unavailable_falls_back_to_extractive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    summarizer = LLMSummarizer()  # 无注入 → _ensure_llm 走 create_llm → None
    counter = ConservativeTokenCounter()
    result = summarizer.summarize(_texts(), 120, counter)
    assert "method=extractive-uniform-v1" in result
    usage = summarizer.take_usage()
    assert any("LLM 不可用" in w for w in usage.warnings)
    assert usage.model_calls == 0


def test_llm_exception_falls_back_to_extractive() -> None:
    llm = FakeLLM(raise_exc=TimeoutError("llm timeout"))
    summarizer = LLMSummarizer(llm=llm)
    counter = ConservativeTokenCounter()
    result = summarizer.summarize(_texts(), 120, counter)
    assert "method=extractive-uniform-v1" in result
    usage = summarizer.take_usage()
    assert any("调用失败" in w for w in usage.warnings)


def test_llm_empty_response_falls_back() -> None:
    llm = FakeLLM("   ")
    summarizer = LLMSummarizer(llm=llm)
    counter = ConservativeTokenCounter()
    result = summarizer.summarize(_texts(), 120, counter)
    assert "method=extractive-uniform-v1" in result
    assert any("返回空内容" in w for w in summarizer.take_usage().warnings)


def test_oversized_llm_output_shrinks_on_sentence_boundary() -> None:
    content = "。".join(f"第{i}条历史决定内容" for i in range(1, 30))
    llm = FakeLLM(content, usage_metadata={"input_tokens": 50, "output_tokens": 10})
    summarizer = LLMSummarizer(llm=llm)
    counter = ConservativeTokenCounter()
    result = summarizer.summarize(_texts(), 60, counter)
    assert counter.count(result) <= 60
    assert any("按句边界收缩" in w or "按句收缩" in w for w in summarizer.take_usage().warnings)


def test_unshrinkable_llm_output_falls_back_to_extractive() -> None:
    llm = FakeLLM("连续无句读长文本" * 100, usage_metadata={"input_tokens": 10, "output_tokens": 5})
    summarizer = LLMSummarizer(llm=llm)
    counter = ConservativeTokenCounter()
    result = summarizer.summarize(_texts(), 80, counter)
    assert "method=extractive-uniform-v1" in result


# ── 成本记录 ──────────────────────────────────────────────────────────────


def test_usage_and_cost_from_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PRICE_INPUT_PER_MTOK", "2.0")
    monkeypatch.setenv("LLM_PRICE_OUTPUT_PER_MTOK", "8.0")
    llm = FakeLLM("摘要:保留 PostgreSQL 决定与三层目录。", usage_metadata={"input_tokens": 1000, "output_tokens": 500})
    summarizer = LLMSummarizer(llm=llm)
    summarizer.summarize(_texts(), 400, ConservativeTokenCounter())
    usage = summarizer.take_usage()
    assert isinstance(usage, SummaryUsage)
    assert usage.model_calls == 1
    assert usage.input_tokens == 1000
    assert usage.output_tokens == 500
    assert usage.cost == pytest.approx(1000 * 2.0 / 1e6 + 500 * 8.0 / 1e6)
    assert usage.estimated is False
    # take_usage 取回后清零
    assert summarizer.take_usage().model_calls == 0


def test_usage_estimated_without_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_PRICE_INPUT_PER_MTOK", raising=False)
    monkeypatch.delenv("LLM_PRICE_OUTPUT_PER_MTOK", raising=False)
    llm = FakeLLM("摘要内容。", usage_metadata=None)
    summarizer = LLMSummarizer(llm=llm)
    summarizer.summarize(_texts(), 200, ConservativeTokenCounter())
    usage = summarizer.take_usage()
    assert usage.input_tokens > 0
    assert usage.estimated is True
    assert usage.cost == 0.0
    assert any("未配置" in w and "单价" in w for w in usage.warnings)
    assert any("估算值" in w for w in usage.warnings)


def test_usage_from_response_metadata_token_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    class LegacyLLM(FakeLLM):
        def invoke(self, messages, **kwargs):
            self.calls.append((messages, kwargs))
            return FakeMessage(
                "摘要内容。",
                response_metadata={"token_usage": {"prompt_tokens": 300, "completion_tokens": 40}},
            )

    monkeypatch.setenv("LLM_PRICE_INPUT_PER_MTOK", "1.0")
    monkeypatch.setenv("LLM_PRICE_OUTPUT_PER_MTOK", "1.0")
    summarizer = LLMSummarizer(llm=LegacyLLM("unused"))
    summarizer.summarize(_texts(), 200, ConservativeTokenCounter())
    usage = summarizer.take_usage()
    assert usage.input_tokens == 300
    assert usage.output_tokens == 40
    assert usage.cost == pytest.approx(340 / 1e6)
    assert usage.estimated is False


# ── 隔离红线 ──────────────────────────────────────────────────────────────


def test_summarizer_input_contains_only_event_texts(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list = []

    class CaptureLLM(FakeLLM):
        def invoke(self, messages, **kwargs):
            captured.extend(messages)
            return super().invoke(messages, **kwargs)

    llm = CaptureLLM("摘要。", usage_metadata={"input_tokens": 1, "output_tokens": 1})
    LLMSummarizer(llm=llm).summarize(_texts(), 200, ConservativeTokenCounter())
    user_content = next(m["content"] for m in captured if m["role"] == "user")
    for text in _texts():
        assert text in user_content
    # 不得出现 gold 评测标注字段
    for banned in ("expected_tool_plan", "answer_rubric", "current_active_constraints", "superseded_decisions"):
        assert banned not in user_content


def test_empty_texts_return_empty_string() -> None:
    llm = FakeLLM("不该被调用")
    summarizer = LLMSummarizer(llm=llm)
    assert summarizer.summarize([], 100, ConservativeTokenCounter()) == ""
    assert summarizer.summarize(["", "  "], 100, ConservativeTokenCounter()) == ""
    assert llm.calls == []


# ── 生成一次后冻结(summary_generate_once_and_freeze)────────────────────


def test_freeze_cache_returns_same_text_without_billed_usage(tmp_path) -> None:
    cache = tmp_path / "cache" / "llm-summary.json"
    llm = FakeLLM(
        "摘要:保留 PostgreSQL 决定、三层目录约束与冻结 Mock 边界。",
        usage_metadata={"input_tokens": 6124, "output_tokens": 4223},
    )
    counter = ConservativeTokenCounter()
    first = LLMSummarizer(llm=llm, cache_path=cache).summarize(_texts(), 400, counter)
    llm2 = FakeLLM("第二次生成必然不同——不应被采用", usage_metadata={"input_tokens": 1, "output_tokens": 1})
    second = LLMSummarizer(llm=llm2, cache_path=cache).summarize(_texts(), 400, counter)
    assert first == second  # 命中冻结缓存,文本逐字一致
    assert len(llm.calls) == 1 and llm2.calls == []  # 只生成了一次
    assert cache.is_file()
    summarizer = LLMSummarizer(llm=FakeLLM("x"), cache_path=cache)
    summarizer.summarize(_texts(), 400, counter)
    usage = summarizer.take_usage()
    # 缓存命中不计入本轮模型调用与费用(P0-2:修复历史累计用量回放)
    assert usage.model_calls == 0
    assert usage.input_tokens == 0 and usage.output_tokens == 0
    assert usage.cost == 0.0
    assert usage.cache_hits == 1
    assert usage.logical_calls == 1
    assert any("冻结摘要缓存" in w for w in usage.warnings)


def test_cache_entry_stores_incremental_usage_not_cumulative(tmp_path) -> None:
    """缓存条目只存该次生成请求自身的增量;多轮生成不产生三角累加。"""
    import json

    cache = tmp_path / "llm-summary.json"
    counter = ConservativeTokenCounter()
    summarizer = LLMSummarizer(
        llm=FakeLLM("第一次摘要内容。", usage_metadata={"input_tokens": 100, "output_tokens": 10}),
        cache_path=cache,
    )
    summarizer.summarize(["第一段材料。"], 200, counter)
    # 第二次不同输入:生成后再看缓存,两个条目的 generation_usage 均为自身增量
    summarizer.summarize(["第二段材料,内容不同。"], 200, counter)
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert len(data) == 2
    for entry in data.values():
        assert entry.get("version") == 2
        gen = entry.get("generation_usage") or {}
        assert gen.get("model_calls") == 1  # 每条只记自身一次调用
        assert gen.get("input_tokens") == 100


def test_v1_cache_entries_keep_text_but_drop_legacy_usage(tmp_path) -> None:
    """v1 缓存正文可复用;其累计用量不再回放进当前统计。"""
    import json

    cache = tmp_path / "llm-summary.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps({"some-v1-key": {"text": "[history-summary]v1 摘要。", "usage": {"model_calls": 5000}}}),
        encoding="utf-8",
    )
    summarizer = LLMSummarizer(llm=FakeLLM("新摘要。"), cache_path=cache)
    # v1 键由旧算法生成,新键不会命中;但文件在下次写入时会被升级备份
    summarizer.summarize(["新材料。"], 200, ConservativeTokenCounter())
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert data["some-v1-key"].get("untrusted_legacy_usage") is True
    assert "usage" not in data["some-v1-key"]
    assert data["some-v1-key"]["text"]  # 正文保留
    assert (tmp_path / "llm-summary.json.v1.backup.json").is_file()


def test_freeze_cache_disabled_by_env(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_SUMMARY_FREEZE", "0")
    cache = tmp_path / "llm-summary.json"
    counter = ConservativeTokenCounter()
    first = LLMSummarizer(llm=FakeLLM("第一次"), cache_path=cache).summarize(_texts(), 200, counter)
    second = LLMSummarizer(llm=FakeLLM("第二次"), cache_path=cache).summarize(_texts(), 200, counter)
    assert first != second  # 关闭冻结 → 每次真实生成


def test_freeze_cache_key_sensitivity(tmp_path) -> None:
    cache = tmp_path / "llm-summary.json"
    counter = ConservativeTokenCounter()
    LLMSummarizer(llm=FakeLLM("预算200版本"), cache_path=cache).summarize(_texts(), 200, counter)
    other = LLMSummarizer(llm=FakeLLM("预算300版本"), cache_path=cache).summarize(_texts(), 300, counter)
    assert "预算300版本" in other  # 预算不同 → 缓存键不同,重新生成


# ── 批量分块摘要(P0-1)──────────────────────────────────────────────────


class BatchFakeLLM(FakeLLM):
    """按请求中的条目数返回结构化 JSON 摘要;计数真实调用次数。"""

    def invoke(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if self.raise_exc:
            raise self.raise_exc
        user = messages[-1]["content"]
        ids = [line.split("=", 1)[1].split("]", 1)[0] for line in user.splitlines() if line.startswith("[item id=")]
        items = [{"item_id": i, "summary": f"{i} 的摘要。第一句。第二句。"} for i in ids]
        import json as _json

        return FakeMessage(
            _json.dumps({"items": items}, ensure_ascii=False),
            usage_metadata={"input_tokens": 50, "output_tokens": 10},
        )


def _batch_items(count: int) -> list[tuple[str, str]]:
    return [(f"event-{i:03d}", f"事件 {i} 的完整正文内容。" * 8) for i in range(count)]


def test_summarize_batch_caps_llm_calls(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("LLM_SUMMARY_MAX_CALLS_PER_BUILD", "2")
    monkeypatch.setenv("LLM_SUMMARY_MAX_INPUT_TOKENS_PER_CALL", "1024")  # 强制小分块
    llm = BatchFakeLLM()
    summarizer = LLMSummarizer(llm=llm, cache_path=tmp_path / "c.json")
    # 60 条 × 约几十 token > 单 chunk 预算下限(1024)× 2 → 分块数超过调用上限
    results = summarizer.summarize_batch(_batch_items(60), max_tokens_per_item=60, counter=ConservativeTokenCounter())
    assert len(results) == 60  # 全部有条目(超限项走抽取式回退)
    assert len(llm.calls) == 2  # 真实模型请求不超过配置上限
    usage = summarizer.take_usage()
    assert usage.model_calls == 2
    assert any("超过调用上限" in w for w in usage.warnings)


def test_summarize_batch_hits_cache_without_cost(tmp_path) -> None:
    cache = tmp_path / "llm-summary.json"
    counter = ConservativeTokenCounter()
    items = _batch_items(3)
    llm1 = BatchFakeLLM()
    LLMSummarizer(llm=llm1, cache_path=cache).summarize_batch(items, max_tokens_per_item=60, counter=counter)
    llm2 = BatchFakeLLM()
    results = LLMSummarizer(llm=llm2, cache_path=cache).summarize_batch(items, max_tokens_per_item=60, counter=counter)
    assert len(results) == 3
    assert len(llm2.calls) == 0  # 全部命中缓存
    # 再取一次用量验证:命中缓存不计费
    summarizer = LLMSummarizer(llm=BatchFakeLLM(), cache_path=cache)
    summarizer.summarize_batch(items, max_tokens_per_item=60, counter=counter)
    usage = summarizer.take_usage()
    assert usage.model_calls == 0
    assert usage.cache_hits == 3
    assert usage.logical_calls == 3


def test_summarize_batch_invalid_json_falls_back_without_loop(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("LLM_SUMMARY_MAX_INPUT_TOKENS_PER_CALL", "100000")
    llm = FakeLLM("这不是 JSON", usage_metadata={"input_tokens": 5, "output_tokens": 2})
    summarizer = LLMSummarizer(llm=llm, cache_path=tmp_path / "c.json")
    results = summarizer.summarize_batch(_batch_items(4), max_tokens_per_item=80, counter=ConservativeTokenCounter())
    assert len(results) == 4  # 整 chunk 回退抽取式,仍产出条目
    assert len(llm.calls) == 1  # 不重试不进入修复循环
    assert any("JSON" in w for w in summarizer.take_usage().warnings)


def test_summarize_batch_rejects_unknown_and_duplicate_ids(tmp_path) -> None:
    import json as _json

    class DupLLM(FakeLLM):
        def invoke(self, messages, **kwargs):
            return FakeMessage(
                _json.dumps(
                    {
                        "items": [
                            {"item_id": "event-000", "summary": "a"},
                            {"item_id": "event-000", "summary": "b"},
                            {"item_id": "ghost", "summary": "c"},
                        ]
                    }
                ),
                usage_metadata={"input_tokens": 1, "output_tokens": 1},
            )

    summarizer = LLMSummarizer(llm=DupLLM("unused"), cache_path=tmp_path / "c.json")
    results = summarizer.summarize_batch(_batch_items(2), max_tokens_per_item=80, counter=ConservativeTokenCounter())
    # 重复 item_id → chunk 无效 → 抽取式回退,ghost 项不出现
    assert "ghost" not in results
    assert set(results) == {"event-000", "event-001"}
    assert any("重复" in w for w in summarizer.take_usage().warnings)


def test_usage_purpose_and_chunks_exposed(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """§11.1 口径拆分:SummaryUsage 携带 purpose=COMPRESSION 与 chunk 计数。"""
    monkeypatch.setenv("LLM_SUMMARY_MAX_INPUT_TOKENS_PER_CALL", "1024")
    llm = BatchFakeLLM()
    summarizer = LLMSummarizer(llm=llm, cache_path=tmp_path / "c.json")
    summarizer.summarize_batch(_batch_items(60), max_tokens_per_item=60, counter=ConservativeTokenCounter())
    usage = summarizer.take_usage()
    assert usage.purpose == "COMPRESSION"
    assert usage.batch_chunks > 0
    assert usage.batch_chunks == usage.model_calls  # chunk 数 = 真实请求数
