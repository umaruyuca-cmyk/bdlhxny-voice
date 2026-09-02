"""LLM 辅助上下文分类(§9.1/§13.2 步骤 7)的单元测试。

覆盖:分类器契约(JSON 解析/失败回退/输入截断/调用上限)、代码预规则
(已取代→distractor)、编译器集成(分类驱动预算选择)、工作台计量接线。
全部使用假分类器/假 LLM,不触网。
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage

from bdlh_runtime.session import SessionCompiler, load_session, load_variants
from bdlh_runtime.session.llm_classify import (
    ClassifyUsage,
    LLMContextClassifier,
    classify_call_cap,
    load_classify_system_prompt,
)

SESSION_DIR = "ctx-session-context-engine-debug-01"


class _FakeLLM:
    def __init__(self, content: Any, fail: Exception | None = None) -> None:
        self.content = content
        self.fail = fail
        self.prompts: list[str] = []

    def invoke(self, messages, **_kwargs):  # noqa: ANN001
        self.prompts.append(str(messages))
        if self.fail is not None:
            raise self.fail
        return AIMessage(content=self.content)


def _classifier(llm: _FakeLLM) -> LLMContextClassifier:
    return LLMContextClassifier(llm=llm)


def _entries(n: int = 3) -> list[tuple[str, str, str]]:
    return [(f"evt-{i}", "user" if i % 2 else "assistant", f"条目正文 {i}") for i in range(1, n + 1)]


# ── 分类器契约 ──


def test_classify_prompt_loads_and_defines_four_categories() -> None:
    prompt = load_classify_system_prompt()
    for token in ("required", "compressible", "reference_only", "distractor", "拿不准"):
        assert token in prompt


def test_classify_parses_valid_json_and_drops_unknown_ids() -> None:
    llm = _FakeLLM(
        '{"items":[{"item_id":"evt-1","classification":"required","reason":"约束"},'
        '{"item_id":"evt-9","classification":"distractor","reason":"请求外"},'
        '{"item_id":"evt-2","classification":"nonsense","reason":"非法类别"}]}'
    )
    usage = _classifier(llm).classify(_entries(2))
    assert usage.error_code is None
    assert set(usage.decisions) == {"evt-1"}  # 请求外 id 与非法类别被丢弃
    assert usage.decisions["evt-1"][0] == "required"
    assert usage.model_calls == 1


def test_classify_tolerates_fenced_json() -> None:
    llm = _FakeLLM('```json\n{"items":[{"item_id":"evt-1","classification":"reference_only"}]}\n```')
    usage = _classifier(llm).classify(_entries(1))
    assert usage.decisions["evt-1"][0] == "reference_only"


def test_classify_failures_are_honest_errors() -> None:
    for content in ("不是 JSON", '{"items": "不是列表"}'):
        usage = _classifier(_FakeLLM(content)).classify(_entries(2))
        assert usage.error_code == "LLM_INVALID_OUTPUT"
        assert usage.decisions == {}
        assert usage.model_calls == 1  # 真实请求如实计数
    usage = _classifier(_FakeLLM(None, fail=RuntimeError("request timed out"))).classify(_entries(1))
    assert usage.error_code == "LLM_TIMEOUT"


def test_classify_requires_llm_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    usage = LLMContextClassifier().classify(_entries(1))
    assert usage.error_code == "LLM_UNAVAILABLE"


def test_classify_call_cap_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert classify_call_cap() == 1  # §10.3 默认 1
    monkeypatch.setenv("CONTEXT_CLASSIFY_CALL_CAP", "0")
    usage = LLMContextClassifier(llm=_FakeLLM("{}")).classify(_entries(1))
    assert usage.error_code == "CLASSIFY_DISABLED"


def test_classify_truncates_oversize_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXT_CLASSIFY_MAX_CHARS", "200")
    big = _entries(20)
    usage = _classifier(_FakeLLM('{"items":[]}')).classify(big)
    assert usage.truncated is True  # 超预算部分不分类,回退代码默认


# ── 编译器集成 ──


def _compiled_with(classifier: Any):
    session = load_session(f"var/cases/{SESSION_DIR}/{SESSION_DIR}.session.json")
    variants = load_variants(f"var/cases/{SESSION_DIR}/{SESSION_DIR}.variants.json")
    variant = next(v for v in variants["context_variants"] if v["variant_id"] == "budgeted-hybrid-v1")
    compiler = SessionCompiler(classifier=classifier)
    return compiler.compile(session, variant, common_rules="系统规则"), session


def test_compile_without_classifier_stays_code_rules_only() -> None:
    art, _session = _compiled_with(None)
    assert art.classification_source == "code_rules_only"
    assert art.classify_model_calls == 0
    assert art.classification_stats.get("llm_assist", 0) == 0
    assert art.classification_stats.get("compressible", 0) > 0  # 无分类器:全部可压缩


def test_compile_llm_assist_drives_selection_and_counts() -> None:
    class Conservative:
        def classify(self, entries):
            usage = ClassifyUsage(model_calls=1, input_tokens=400, output_tokens=150)
            user_ids = [iid for iid, role, _t in entries if role == "user"][:2]
            for iid, _role, _text in entries:
                if iid in user_ids:
                    usage.decisions[iid] = ("required", "用户明确约束")
            return usage

    art, _session = _compiled_with(Conservative())
    assert art.classification_source == "llm_assist"
    assert art.classify_model_calls == 1
    assert art.classification_stats.get("required", 0) == 2
    assert art.classification_stats.get("llm_assist") == 2
    assert art.classification_stats.get("code_rules", 0) == 0
    # required 条目必须保留在最终上下文里(kept)
    payload = art.to_payload()
    assert payload["classification"]["source"] == "llm_assist"
    assert payload["classification"]["llm_calls"] == 1


def test_compile_llm_failure_falls_back_to_compressible() -> None:
    class Broken:
        def classify(self, entries):
            usage = ClassifyUsage(model_calls=1)
            usage.error_code = "LLM_UNAVAILABLE"
            return usage

    art, _unused = _compiled_with(Broken())
    assert art.classification_source == "llm_failed_fallback"
    assert art.classification_stats.get("compressible", 0) > 0
    assert any("classify" in row for row in art.warnings)  # 告警如实入工件


def test_compile_code_rule_superseded_becomes_distractor() -> None:
    """代码预规则:同来源存在更新版本 → 已取代 → distractor(语义可确定,不进 LLM)。"""

    from bdlh_runtime.context import ContextClassification, ContextItem, ContextRole
    from bdlh_runtime.session.serializer import SerializedItem

    captured: dict[str, Any] = {}

    class SpyClassifier:
        def classify(self, entries):
            captured["ids"] = [iid for iid, _role, _text in entries]
            return ClassifyUsage(model_calls=1)

    compiler = SessionCompiler(classifier=SpyClassifier())
    # 手工构造序列化条目:同 source_id 两条,旧条已被取代(真实流程由
    # serialize_session 的 _apply_reference_metadata 计算,这里直接置标志)
    import dataclasses as _dc

    items = []
    for seq in (1, 2):
        item = ContextItem(
            item_id=f"evt-{seq}",
            content=f"版本 {seq}",
            classification=ContextClassification.COMPRESSIBLE,
            role=ContextRole.USER_DATA,
            priority=10,
            source_id="same-source",
            observed_at=f"2026-08-{10 + seq}T00:00:00+08:00",
            sequence=seq,
            conversation=True,
        )
        if seq == 1:
            item = _dc.replace(item, superseded=True)
        items.append(SerializedItem(item=item, event_ids=(f"evt-{seq}",)))
    new_serialized, usage, code_count = compiler._classify_items(tuple(items))

    superseded_item = next(e.item for e in new_serialized if e.item.item_id == "evt-1")
    assert superseded_item.classification is ContextClassification.DISTRACTOR
    assert code_count == 1
    assert "evt-1" not in captured["ids"]  # 语义已确定的条目不进 LLM
    latest_item = next(e.item for e in new_serialized if e.item.item_id == "evt-2")
    assert latest_item.classification is ContextClassification.COMPRESSIBLE
    assert usage is not None


def test_compile_skips_segment_synthetic_items_in_llm_classify() -> None:
    from bdlh_runtime.context import ContextClassification, ContextItem, ContextRole
    from bdlh_runtime.session.serializer import SerializedItem

    calls: list[list[str]] = []

    class Recorder:
        def classify(self, entries):
            calls.append([iid for iid, _r, _t in entries])
            return ClassifyUsage(model_calls=1)

    items = tuple(
        SerializedItem(
            item=ContextItem(
                item_id=item_id,
                content="内容",
                classification=ContextClassification.COMPRESSIBLE,
                role=ContextRole.USER_DATA,
                priority=10,
                sequence=seq,
                conversation=True,
            ),
            event_ids=(item_id,),
        )
        for seq, item_id in enumerate(("memory-segment:s1", "evt-1"), start=1)
    )
    compiler2 = SessionCompiler(classifier=Recorder())
    _new, usage, _code = compiler2._classify_items(items)
    assert calls and calls[0] == ["evt-1"]  # Segment 合成条目跳过 LLM
    assert usage is not None and usage.model_calls == 1


# ── 工作台计量接线 ──


def test_workbench_reports_classification_metering(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """工作台 llm_usage.classification_* 来自编译器真实计数(不再是硬编码 0)。"""

    from bdlh_runtime.memory import ContextBuildStore, ContextWorkbenchService
    from tests.memory.test_agent_run import OWNER

    class Conservative:
        def classify(self, entries):
            usage = ClassifyUsage(model_calls=1, input_tokens=321, output_tokens=123)
            user_ids = [iid for iid, role, _t in entries if role == "user"][:1]
            for iid, _role, _text in entries:
                if iid in user_ids:
                    usage.decisions[iid] = ("required", "约束")
            return usage

    SessionCompiler_from_env = SessionCompiler.from_env

    def _fake_from_env(cls, **kwargs):  # noqa: ANN001
        compiler = SessionCompiler_from_env(**kwargs)
        compiler._classifier = Conservative()
        return compiler

    monkeypatch.setattr(SessionCompiler, "from_env", classmethod(_fake_from_env))

    from bdlh_runtime.memory.sources import FrozenSessionSource

    service = ContextWorkbenchService(ContextBuildStore(tmp_path), source=FrozenSessionSource())
    sessions = service.sessions()
    session_id = sessions[0]["session_id"]
    build, _ = service.store.create(
        owner_id=OWNER,
        session_id=session_id,
        current_request_event_id=service.overview(session_id)["default_current_request_event_id"],
        algorithm="budgeted-hybrid-v1",
        idempotency_key="classify-0001",
        source_type="FROZEN_FILE",
    )
    service.execute_build(build["build_id"], OWNER)
    row = service.store.get(build["build_id"], OWNER)
    assert row["status"] == "COMPLETED"
    usage = row["llm_usage"]
    assert usage["classification_calls"] == 1
    assert usage["classification_input_tokens"] == 321
    assert usage["classification_source"] == "llm_assist"
    artifact = service.store.artifact(build["build_id"], OWNER)
    assert artifact["classification"]["source"] == "llm_assist"
    assert artifact["classification"]["stats"].get("required", 0) >= 1
