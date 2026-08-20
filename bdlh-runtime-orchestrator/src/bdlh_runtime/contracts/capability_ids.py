"""内核中立的 Capability 稳定名真源。

护栏层（guardrails）与工具实现（tools）共同依赖这一份常量，避免同一
能力名在两处各写一份后漂移。放本层的原因：ADR-009 §3.3 禁止内核依赖
tools 实现包，而 tools 侧也需要同名常量，因此真源必须落在两侧都能
依赖的中立契约层。
"""

from __future__ import annotations

DEEP_SEARCH_CAPABILITY = "research.deep_search"
WEB_SEARCH_CAPABILITY = "research.web_search"

__all__ = ["DEEP_SEARCH_CAPABILITY", "WEB_SEARCH_CAPABILITY"]
