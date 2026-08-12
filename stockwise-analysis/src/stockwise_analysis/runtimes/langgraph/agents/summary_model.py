"""最终表达模型边界。"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from stockwise_analysis.contracts.analysis import AnalysisResult

logger = logging.getLogger("stockwise_analysis.agents.summary")


class SummaryModel(Protocol):
    """将已验证事实转换为用户回答；禁止补造缺失市场数据。"""

    def compose(self, result: AnalysisResult) -> dict:
        """根据结构化 AnalysisResult 生成最终响应。"""
        ...


class DeterministicSummaryModel:
    """Phase 0/1 的无模型替身，确保 API 测试不依赖外部大模型。"""

    def compose(self, result: AnalysisResult) -> dict:
        return {
            "status": result.status,
            "analysis_id": result.analysis_id,
            "summary": result.conclusions[0]["text"] if result.conclusions else "暂无结论。",
            "limitations": result.limitations,
        }


# ── Prompt 模板：严格约束"只总结已有事实，不补造数据" ──
_SUMMARY_SYSTEM_PROMPT = (
    "你是股票分析总结器。只基于提供的 AnalysisResult 生成用户可读的中文总结。"
    "禁止补造任何未在结果中出现的价格、财务数据或结论。"
    "缺少数据时如实说明。输出简洁的自然语言段落。"
)


class LlmSummaryModel:
    """基于 LLM 的 Summary Model 实现。

    有 LLM 时把 AnalysisResult 喂给模型生成自然语言总结；无 LLM 或调用
    失败时降级回 DeterministicSummaryModel。降级保证 compose_response 节点
    始终能产出响应。
    """

    def __init__(self, llm: Any | None):
        self._llm = llm
        self._fallback = DeterministicSummaryModel()

    def compose(self, result: AnalysisResult) -> dict:
        if self._llm is None:
            return self._fallback.compose(result)

        try:
            # 把结构化结果序列化为 LLM 可读文本
            facts_text = self._format_result(result)
            response = self._llm.invoke([
                {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": f"分析结果：\n{facts_text}"},
            ])
            summary = response.content if hasattr(response, "content") else str(response)
            return {
                "status": result.status,
                "analysis_id": result.analysis_id,
                "summary": summary.strip(),
                "limitations": result.limitations,
            }
        except Exception as exc:
            logger.warning("LLM 总结失败，降级回确定性版: %s", exc)
            return self._fallback.compose(result)

    @staticmethod
    def _format_result(result: AnalysisResult) -> str:
        """把 AnalysisResult 格式化为 LLM 可读的结构化文本。"""
        lines = [f"状态: {result.status}"]
        if result.facts:
            lines.append("事实:")
            for f in result.facts[:10]:
                lines.append(f"  - {f}")
        if result.calculated_indicators:
            lines.append(f"指标: {result.calculated_indicators}")
        if result.conclusions:
            lines.append("结论:")
            for c in result.conclusions[:5]:
                text = c.get("text", c) if isinstance(c, dict) else str(c)
                lines.append(f"  - {text}")
        if result.risk_flags:
            lines.append(f"风险标记: {result.risk_flags}")
        if result.limitations:
            lines.append(f"限制: {result.limitations}")
        return "\n".join(lines)


def create_summary_model(llm: Any | None) -> SummaryModel:
    """工厂函数：有 LLM 用 LlmSummaryModel，无 LLM 用 DeterministicSummaryModel。"""
    return LlmSummaryModel(llm) if llm is not None else DeterministicSummaryModel()
