"""会话 Skill 门禁（内核侧）。

不导入任何 Domain 实现；仅根据会话 ``enabled_skills`` 快照判断插件是否允许交接。
"""

from __future__ import annotations

import re

#: finance 域当前全部 Skill 的 Registry 裸 id；控制台发送「finance.」前缀形式。
FINANCE_SKILL_IDS = frozenset(
    {"stock-research", "portfolio-health", "suitability-evaluation"}
)

_FINANCE_PLUGIN_SIGNAL = re.compile(
    r"(?:股票|个股|证券|标的|行情|走势|估值|市盈率|市净率|市销率|研报|持仓|组合|"
    r"理财目标|投资目标|财务目标|目标规划|适当性|适合我|适不适合|"
    r"资金流|北向|板块|个股分析|股票分析|今天怎么样|涨了|跌了)"
)

_FINANCE_KNOWLEDGE = re.compile(
    r"(?:什么是|解释一下).*(?:市盈率|市净率|市销率|估值|换手率|PE|PB|PS|ROE|MACD)",
    re.IGNORECASE,
)


def finance_skill_enabled(enabled_skills: frozenset[str] | None) -> bool:
    """会话是否显式启用了任一 finance Skill。"""
    if not enabled_skills:
        return False
    return any(
        item in FINANCE_SKILL_IDS or item.startswith("finance.")
        for item in enabled_skills
    )


def message_suggests_finance_plugin(message: str) -> bool:
    """话面是否出现应尝试金融 Skill 的信号（与 needs_external 解耦）。"""
    text = message.strip()
    if not text:
        return False
    if _FINANCE_PLUGIN_SIGNAL.search(text):
        return True
    if _FINANCE_KNOWLEDGE.search(text):
        return True
    if re.search(r"(?<!\d)\d{6}(?!\d)", text):
        return True
    return False
