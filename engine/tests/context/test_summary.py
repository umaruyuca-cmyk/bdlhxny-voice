"""single-summary 独立摘要基准测试(与自研规则压缩器分离)。"""

from __future__ import annotations

from bdlh_runtime.context import (
    ConservativeTokenCounter,
    ContextAction,
    ContextBuildRequest,
    ContextBuilder,
    ContextClassification,
    ContextItem,
    ContextRole,
    ContextStrategy,
    ExtractiveSummarizer,
)


def _history_item(item_id: str, content: str, sequence: int) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        content=content,
        classification=ContextClassification.COMPRESSIBLE,
        role=ContextRole.USER_DATA,
        sequence=sequence,
    )


def test_extractive_summarizer_is_deterministic_and_within_budget() -> None:
    counter = ConservativeTokenCounter()
    summarizer = ExtractiveSummarizer()
    texts = [f"第{i}段历史:团队决定了方案{i},理由是约束{i}。" for i in range(1, 6)]
    first = summarizer.summarize(texts, 60, counter)
    second = summarizer.summarize(texts, 60, counter)
    assert first == second
    assert counter.count(first) <= 60
    assert first.startswith("[history-summary")
    assert "method=extractive-uniform-v1" in first


def test_extractive_summarizer_cuts_on_sentence_boundaries() -> None:
    counter = ConservativeTokenCounter()
    text = "完整的第一句话保留。第二句也应该保留。这最后半句因为超预算被跳过且不截断半句"
    output = ExtractiveSummarizer()._leading_sentences(text, 15, counter)
    assert output.endswith("。")
    assert "这最后半句" not in output


def test_single_summary_uses_injected_summarizer_not_rule_compressor() -> None:
    """独立基准:摘要文本来自注入的摘要器,而非 StructuredTextCompressor 的
    头尾截断(其特征是 [compressed source=...] 标记)。"""

    class MarkerSummarizer:
        version = "marker-v1"

        def summarize(self, texts, max_tokens, counter):
            return f"[history-summary method=marker-v1] 共{len(texts)}条:{texts[0][:10]}"

    items = (
        ContextItem(
            item_id="rule",
            content="系统规则。",
            classification=ContextClassification.REQUIRED,
            role=ContextRole.SYSTEM,
        ),
    ) + tuple(
        _history_item(f"h-{index}", f"历史事件{index}" + "的详细经过。" * 20, index + 1)
        for index in range(1, 6)
    )
    builder = ContextBuilder(summarizer=MarkerSummarizer())
    result = builder.build(
        ContextBuildRequest(
            items=items,
            token_budget=400,
            strategy=ContextStrategy.SINGLE_SUMMARY,
            summary_recent_tokens=150,
            summary_max_tokens=200,
        )
    )
    joined = "\n".join(message.content for message in result.messages)
    assert "method=marker-v1" in joined
    assert "[compressed source=" not in joined  # 未走规则裁剪器
    decisions = {d.item_id: d for d in result.report.decisions}
    assert decisions["h-1"].action is ContextAction.COMPRESSED
    assert decisions["h-5"].action is ContextAction.KEPT
    assert result.report.required_retained
    assert result.report.budget_fit
