"""危险动作语义注册表(原 C-1 交易守卫的泛化形态)。

默认不加载任何领域词表;机制始终存在。场景包可注册档案
(如 finance 交易执行词表)。目录 ``register`` 调用
``is_dangerous_action_semantic`` 做物理拒绝。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DangerousActionProfile:
    """一类危险动作的匹配档案。"""

    profile_id: str
    en_pattern: re.Pattern[str] | None = None
    zh_terms: tuple[str, ...] = ()
    exempt_names: frozenset[str] = field(default_factory=frozenset)


_profiles: list[DangerousActionProfile] = []


def clear_profiles() -> None:
    _profiles.clear()


def register_profile(profile: DangerousActionProfile) -> None:
    _profiles[:] = [p for p in _profiles if p.profile_id != profile.profile_id]
    _profiles.append(profile)


def list_profiles() -> tuple[DangerousActionProfile, ...]:
    return tuple(_profiles)


def is_dangerous_action_semantic(name: str, description: str) -> bool:
    """名字或描述是否命中任一已注册危险动作档案。"""
    if not _profiles:
        return False
    normalized_name = re.sub(r"[._\-]", " ", name)
    haystacks = (normalized_name, description or "")
    for profile in _profiles:
        if name in profile.exempt_names:
            continue
        if profile.en_pattern is not None and any(profile.en_pattern.search(text) for text in haystacks):
            return True
        if any(term in text for text in haystacks for term in profile.zh_terms):
            return True
    return False


# 兼容旧测试名;语义已泛化
def is_trading_semantic(name: str, description: str) -> bool:
    return is_dangerous_action_semantic(name, description)
