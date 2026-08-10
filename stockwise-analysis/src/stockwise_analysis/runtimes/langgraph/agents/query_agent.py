"""Query Agent 契约与本地开发实现。"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

logger = logging.getLogger("stockwise_analysis.agents.query")


class QueryIntent(BaseModel):
    """问题理解节点输出的受控意图，不包含任何工具调用。"""

    analysis_type: str
    symbol: str | None = None
    scope: str | None = None
    requires_portfolio: bool = False
    requires_confirmation: bool = False


class QueryAgent(Protocol):
    """生产 Query Agent 的接口；后续可替换为结构化 LLM 调用。"""

    def understand(self, request: dict[str, Any]) -> QueryIntent:
        """仅理解用户请求，禁止直接查询 MCP、Java 或数据库。"""


class RuleBasedQueryAgent:
    """Phase 0/1 的确定性替身，用于验证 Graph 和契约而非替代模型。"""

    def understand(self, request: dict[str, Any]) -> QueryIntent:
        message = str(request.get("message", ""))
        symbol_match = re.search(r"(?<!\d)([0369]\d{5})(?!\d)", message)
        lowered = message.lower()

        if any(word in message for word in ("综合", "全面", "完整")):
            analysis_type = "comprehensive"
        elif any(word in message for word in ("持仓", "账户", "组合")) or "portfolio" in lowered:
            analysis_type = "portfolio_impact"
        elif any(word in message for word in ("基本面", "财务", "财报")):
            analysis_type = "fundamental"
        elif any(word in message for word in ("估值", "PE", "PB", "市盈率")):
            analysis_type = "valuation"
        elif any(word in message for word in ("技术", "K线", "指标", "趋势")):
            analysis_type = "technical"
        else:
            analysis_type = "market_snapshot"

        return QueryIntent(
            analysis_type=analysis_type,
            symbol=symbol_match.group(1) if symbol_match else request.get("symbol"),
            scope=request.get("scope"),
            requires_portfolio=analysis_type == "portfolio_impact" or "持仓" in message,
            requires_confirmation=bool(request.get("require_confirmation", False)),
        )


# ── Prompt 模板：约束 LLM 只输出 JSON 意图，不做工具调用 ──
_QUERY_SYSTEM_PROMPT = (
    "你是股票分析意图识别器。只输出 JSON，不要解释。"
    "字段：analysis_type（market_snapshot/technical/fundamental/valuation/portfolio_impact/comprehensive）、"
    "symbol（6位A股代码或null）、scope（分析范围或null）、"
    "requires_portfolio（bool）、requires_confirmation（bool）。"
)

_QUERY_USER_TEMPLATE = "用户问题：{message}"


class LlmQueryAgent:
    """基于 LLM 的 Query Agent 实现。

    有 LLM 客户端时走结构化输出；LLM 调用失败时降级回 RuleBasedQueryAgent，
    保证理解节点始终能产出 QueryIntent——和 Mem0 的降级思路一致，
    外部依赖不可用时主流程照跑。
    """

    def __init__(self, llm: Any | None):
        """注入 ChatOpenAI 实例；为 None 时直接降级为规则版。"""
        self._llm = llm
        self._fallback = RuleBasedQueryAgent()

    def understand(self, request: dict[str, Any]) -> QueryIntent:
        # 无 LLM 直接走规则版
        if self._llm is None:
            return self._fallback.understand(request)

        message = str(request.get("message", ""))
        if not message:
            return self._fallback.understand(request)

        try:
            response = self._llm.invoke([
                {"role": "system", "content": _QUERY_SYSTEM_PROMPT},
                {"role": "user", "content": _QUERY_USER_TEMPLATE.format(message=message)},
            ])
            # DeepSeek 返回的 content 是 JSON 字符串
            raw = response.content if hasattr(response, "content") else str(response)
            data = json.loads(self._extract_json(raw))
            # 合并 request 里的显式字段（用户可能直接传了 symbol）
            if not data.get("symbol"):
                data["symbol"] = request.get("symbol")
            if not data.get("requires_confirmation"):
                data["requires_confirmation"] = bool(request.get("require_confirmation", False))
            return QueryIntent(**data)
        except (json.JSONDecodeError, ValidationError, Exception) as exc:
            logger.warning("LLM 意图解析失败，降级回规则版: %s", exc)
            return self._fallback.understand(request)

    @staticmethod
    def _extract_json(text: str) -> str:
        """从可能含 markdown 代码块的响应中提取 JSON 字符串。"""
        text = text.strip()
        if text.startswith("```"):
            # 去掉 ```json ... ``` 包裹
            lines = text.split("\n")
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            return "\n".join(lines)
        return text


def create_query_agent(llm: Any | None) -> QueryAgent:
    """工厂函数：有 LLM 用 LlmQueryAgent，无 LLM 用 RuleBasedQueryAgent。"""
    return LlmQueryAgent(llm) if llm is not None else RuleBasedQueryAgent()
