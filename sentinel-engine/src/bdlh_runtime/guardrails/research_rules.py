"""Deep Research / 公开研究相关的四时点规则（ADR-016 §13）。

领域无关：只认契约字段与稳定码；不调用 LLM、不访问 Provider。
供 Default* Guardrail 复用，也可被离线评测直接调用。
"""

from __future__ import annotations

from typing import Any

from bdlh_runtime.contracts.capability_ids import (
    DEEP_SEARCH_CAPABILITY,
    WEB_SEARCH_CAPABILITY,
)

DEEP_TRIGGER_TERMS = (
    "深度调研",
    "深入研究",
    "深度研究",
    "交叉验证",
    "证据链",
    "调研报告",
    "deep research",
    "cross-check",
    "cross check",
)

SECRET_LEAK_TERMS = (
    "api_key",
    "apikey",
    "authorization: bearer",
    "sk-",
    "dashscope.aliyuncs.com",
    "bdlh_bailian",
    "mcp token",
)

SUITABILITY_MIX_TERMS = (
    "适合你买入",
    "适合你持有",
    "推荐你买入",
    "该股适合你",
    "guarantee you",
)


def looks_like_research_bundle(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("schema_version") == "research-bundle.v1":
        return True
    if payload.get("capability") == DEEP_SEARCH_CAPABILITY:
        return True
    data = payload.get("data")
    return bool(isinstance(data, dict) and data.get("schema_version") == "research-bundle.v1")


def extract_research_bundle(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") == "research-bundle.v1":
        return payload
    data = payload.get("data")
    if isinstance(data, dict) and data.get("schema_version") == "research-bundle.v1":
        return data
    return None


def domain_request_signals_deep(objective: str, success_criteria: list[str] | None = None) -> bool:
    text = (objective or "").lower()
    if any(term.lower() in text for term in DEEP_TRIGGER_TERMS):
        return True
    criteria = [c.strip() for c in (success_criteria or []) if c and str(c).strip()]
    return len(criteria) >= 2


def plan_requires_deep_capability(
    *,
    objective: str,
    success_criteria: list[str] | None,
    authorized_capabilities: frozenset[str],
) -> str | None:
    """若上下文声明了能力白名单且请求像 Deep，则必须含 research.deep_search。

    ``authorized_capabilities`` 为空时不做能力门控（兼容尚未填充白名单的装配）。
    """
    if not authorized_capabilities:
        return None
    if not domain_request_signals_deep(objective, success_criteria):
        return None
    if DEEP_SEARCH_CAPABILITY in authorized_capabilities:
        return None
    return "DEEP_RESEARCH_NOT_AUTHORIZED"


def action_rejects_unauthorized_deep(
    *,
    objective: str,
    success_criteria: list[str] | None,
    authorized_capabilities: frozenset[str],
) -> str | None:
    return plan_requires_deep_capability(
        objective=objective,
        success_criteria=success_criteria,
        authorized_capabilities=authorized_capabilities,
    )


def evaluate_research_observation(payload: Any) -> tuple[str, str, str] | None:
    """返回 (audit_code, rule_id, reason) 表示应 BLOCK；None 表示本规则不拦截。"""

    if not looks_like_research_bundle(payload):
        return None

    bundle = extract_research_bundle(payload) or {}
    capability = str(payload.get("capability") or "")
    outer_status = str(payload.get("status") or "")
    blob = _flatten_text(payload)
    if any(term in blob.lower() for term in SECRET_LEAK_TERMS):
        return (
            "RESEARCH_SECRET_LEAK",
            "DATA-RESEARCH-SECRET-001",
            "研究观测不得包含 Provider/凭证细节",
        )

    sources = bundle.get("sources") if isinstance(bundle.get("sources"), list) else []
    findings = bundle.get("findings") if isinstance(bundle.get("findings"), list) else []
    limitations = bundle.get("limitations") if isinstance(bundle.get("limitations"), list) else []
    bundle_status = str(bundle.get("status") or "")

    if bundle_status == "COMPLETE" and not sources:
        return (
            "RESEARCH_COMPLETE_WITHOUT_SOURCES",
            "DATA-RESEARCH-COMPLETE-001",
            "无有效来源时不得将 ResearchBundle 标为 COMPLETE",
        )

    if bundle_status == "COMPLETE" and (
        "ATOMIC_SEARCH_UNAVAILABLE" in limitations or "ATOMIC_SEARCH_RATE_LIMITED" in limitations
    ):
        return (
            "RESEARCH_COMPLETE_WITH_PROVIDER_FAILURE",
            "DATA-RESEARCH-COMPLETE-002",
            "Provider 失败时不得升格为 COMPLETE",
        )

    source_ids = {str(item.get("source_id")) for item in sources if isinstance(item, dict) and item.get("source_id")}
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        refs = finding.get("source_ids") or []
        if not isinstance(refs, list) or not refs:
            return (
                "RESEARCH_FINDING_WITHOUT_SOURCE",
                "DATA-RESEARCH-FINDING-001",
                "finding 必须引用至少一个 source",
            )
        if not any(str(ref) in source_ids for ref in refs):
            return (
                "RESEARCH_FINDING_SOURCE_UNCLOSED",
                "DATA-RESEARCH-FINDING-002",
                "finding 的 source_ids 必须闭合到 sources",
            )

    for source in sources:
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or "")
        if url and not (url.startswith("http://") or url.startswith("https://")):
            return (
                "RESEARCH_URL_SCHEME_BLOCKED",
                "DATA-RESEARCH-URL-001",
                "研究来源 URL 仅允许 HTTP/HTTPS",
            )

    # Observation 外层把 FAILED Bundle 标成 FAILED/UNAVAILABLE 时，沿用通用 DATA_UNAVAILABLE
    if capability == DEEP_SEARCH_CAPABILITY and outer_status in {"FAILED", "UNAVAILABLE"}:
        return None
    return None


def evaluate_research_response_text(scanned_text: str) -> tuple[str, str, str] | None:
    lower = scanned_text.lower()
    if any(term in lower for term in SECRET_LEAK_TERMS):
        return (
            "RESEARCH_SECRET_LEAK",
            "RESPONSE-RESEARCH-SECRET-001",
            "公开回复不得泄露搜索 Provider 或凭证细节",
        )
    if any(term in scanned_text for term in SUITABILITY_MIX_TERMS):
        return (
            "RESEARCH_SUITABILITY_MIXED",
            "RESPONSE-RESEARCH-SUIT-001",
            "公开研究资料不得直接写成个性化适配/交易建议",
        )
    return None


def shallow_vs_deep_capability_hint(should_deep: bool) -> str:
    return DEEP_SEARCH_CAPABILITY if should_deep else WEB_SEARCH_CAPABILITY


def _flatten_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_flatten_text(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_text(v) for v in value)
    return ""
