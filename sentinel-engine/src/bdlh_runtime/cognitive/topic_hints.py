"""主题覆盖提示（表达用，不发放权限、不缩小 allowed）。

``requested_topics`` 只描述数据主题；本表供 GoalCoverage / Planner 在
**已进入 allowed** 的能力中匹配主题覆盖，不是第二份能力目录。
"""

from __future__ import annotations

from bdlh_runtime.registry.models import VALID_TOPICS

TOPIC_COVERAGE_HINTS: dict[str, tuple[str, ...]] = {
    "news": ("market.get_news", "research.web_search"),
    "money_flow": ("market.get_money_flow",),
    "industry": ("market.get_industry_context",),
    "web_research": ("research.web_search",),
}


def topic_capabilities_for(topic: str) -> list[str]:
    if topic not in VALID_TOPICS:
        return []
    return list(TOPIC_COVERAGE_HINTS.get(topic, ()))
