"""Output Guardrail: LLM 出答案后的出口检查（设计文档 §4.4 G-α/β/γ 补充）。

在 AgentLoop 产出 answer 后、返回调用方前执行：
1. NumberGroundingCheck — answer 中的非平凡数字必须来自某条 Observation
2. 可选的关键词拦截检查 — 由场景包注册(如危险动作 / 不当结论词表)

默认只启用数字溯源;垂直领域词表不进入平台默认路径。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol


class OutputCheck(Protocol):
    def check(self, answer: str, observations: list[Any]) -> list[GuardViolation]: ...


@dataclass
class GuardViolation:
    check_name: str
    severity: str
    detail: str
    original_fragment: str
    fixed_fragment: str | None = None
    footer: str | None = None


@dataclass
class GuardReport:
    violations: list[GuardViolation] = field(default_factory=list)
    original_answer: str = ""
    fixed_answer: str = ""

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)

    @property
    def audit_codes(self) -> list[str]:
        codes: list[str] = []
        for v in self.violations:
            if v.check_name not in codes:
                codes.append(v.check_name)
        return codes


_NUMBER_RE = re.compile(r"\d+\.?\d*")
_TRIVIAL_NUMBERS = frozenset({0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 100, 1000})
_YEAR_RE = re.compile(r"19\d{2}|20\d{2}")

_default_extra_checks: list[OutputCheck] = []


def reset_default_output_checks() -> None:
    """禁用场景包后清空额外出口检查。"""
    _default_extra_checks.clear()
    clear_live_compliance_keywords()


def append_default_output_check(check: OutputCheck) -> None:
    """场景包向默认出口闸门追加检查(按 check_name 去重)。"""
    name = getattr(check, "check_name", None) or type(check).__name__
    _default_extra_checks[:] = [
        c for c in _default_extra_checks if (getattr(c, "check_name", None) or type(c).__name__) != name
    ]
    _default_extra_checks.append(check)


def _extract_numbers(text: str) -> set[str]:
    return set(_NUMBER_RE.findall(text))


def _is_trivial(number_str: str) -> bool:
    try:
        return float(number_str) in _TRIVIAL_NUMBERS
    except ValueError:
        return False


def _obs_to_text(obs: Any) -> str:
    if hasattr(obs, "data"):
        data = getattr(obs, "data", None)
        if data is not None:
            return json.dumps(data, ensure_ascii=False, default=str)
    if isinstance(obs, dict):
        return json.dumps(obs, ensure_ascii=False, default=str)
    return str(obs)


class NumberGroundingCheck:
    """answer 里的非平凡数字必须出现在某条 Observation 中。"""

    def check(self, answer: str, observations: list[Any]) -> list[GuardViolation]:
        if not observations:
            return []
        answer_numbers = _extract_numbers(answer)
        obs_numbers: set[str] = set()
        for obs in observations:
            obs_numbers |= _extract_numbers(_obs_to_text(obs))
        hallucinated = answer_numbers - obs_numbers
        hallucinated = {n for n in hallucinated if not _is_trivial(n) and not _YEAR_RE.fullmatch(n)}
        return [
            GuardViolation(
                check_name="NUM_HALLUCINATION",
                severity="warning",
                detail=f"数字 {n} 不在任何工具结果中",
                original_fragment=n,
                fixed_fragment="[数据待核实]",
            )
            for n in sorted(hallucinated, key=float)
        ]


class KeywordBlockCheck:
    """可配置关键词拦截(场景包注入危险动作 / 不当结论等策略)。"""

    def __init__(
        self,
        *,
        check_name: str,
        keywords: tuple[str, ...] | list[str],
        fixed_fragment: str,
        detail_prefix: str = "命中策略词",
        severity: str = "critical",
        footer: str | None = None,
    ) -> None:
        self.check_name = check_name
        self._keywords = tuple(keywords)
        self._fixed_fragment = fixed_fragment
        self._detail_prefix = detail_prefix
        self._severity = severity
        self._footer = footer

    def check(self, answer: str, observations: list[Any]) -> list[GuardViolation]:
        return [
            GuardViolation(
                check_name=self.check_name,
                severity=self._severity,
                detail=f"{self._detail_prefix}：{kw}",
                original_fragment=kw,
                fixed_fragment=self._fixed_fragment,
                footer=self._footer,
            )
            for kw in self._keywords
            if kw in answer
        ]


# 兼容旧测试符号:空词表壳;未显式传 keywords 时读取场景包注入的实时词表
_LIVE_C1_KEYWORDS: tuple[str, ...] = ()
_LIVE_C2_KEYWORDS: tuple[str, ...] = ()
_LIVE_C2_FOOTER: str | None = "\n\n本结果仅为筛查草稿，不构成代替用户决策的建议。"


def set_live_compliance_keywords(
    *,
    c1: tuple[str, ...] | list[str] | None = None,
    c2: tuple[str, ...] | list[str] | None = None,
    c2_footer: str | None = None,
) -> None:
    """场景包启用/禁用时更新评测侧 C1/C2 实时词表。"""
    global _LIVE_C1_KEYWORDS, _LIVE_C2_KEYWORDS, _LIVE_C2_FOOTER
    if c1 is not None:
        _LIVE_C1_KEYWORDS = tuple(c1)
    if c2 is not None:
        _LIVE_C2_KEYWORDS = tuple(c2)
    if c2_footer is not None:
        _LIVE_C2_FOOTER = c2_footer


def clear_live_compliance_keywords() -> None:
    global _LIVE_C1_KEYWORDS, _LIVE_C2_KEYWORDS, _LIVE_C2_FOOTER
    _LIVE_C1_KEYWORDS = ()
    _LIVE_C2_KEYWORDS = ()
    _LIVE_C2_FOOTER = "\n\n本结果仅为筛查草稿，不构成代替用户决策的建议。"


class C1ComplianceCheck(KeywordBlockCheck):
    def __init__(self, keywords: tuple[str, ...] | list[str] | None = None) -> None:
        self._explicit_keywords = None if keywords is None else tuple(keywords)
        super().__init__(
            check_name="C1_VIOLATION",
            keywords=tuple(keywords or ()),
            fixed_fragment="（该操作不被允许）",
            detail_prefix="含危险执行语义",
        )

    def check(self, answer: str, observations: list[Any]) -> list[GuardViolation]:
        keywords = self._explicit_keywords if self._explicit_keywords is not None else _LIVE_C1_KEYWORDS
        return KeywordBlockCheck(
            check_name=self.check_name,
            keywords=keywords,
            fixed_fragment="（该操作不被允许）",
            detail_prefix="含危险执行语义",
        ).check(answer, observations)


class C2ComplianceCheck(KeywordBlockCheck):
    def __init__(self, keywords: tuple[str, ...] | list[str] | None = None) -> None:
        self._explicit_keywords = None if keywords is None else tuple(keywords)
        super().__init__(
            check_name="C2_VIOLATION",
            keywords=tuple(keywords or ()),
            fixed_fragment="（不构成代替用户决策的结论）",
            detail_prefix="含不当确定性结论",
            footer=_LIVE_C2_FOOTER,
        )

    def check(self, answer: str, observations: list[Any]) -> list[GuardViolation]:
        keywords = self._explicit_keywords if self._explicit_keywords is not None else _LIVE_C2_KEYWORDS
        return KeywordBlockCheck(
            check_name=self.check_name,
            keywords=keywords,
            fixed_fragment="（不构成代替用户决策的结论）",
            detail_prefix="含不当确定性结论",
            footer=_LIVE_C2_FOOTER,
        ).check(answer, observations)


class OutputGuardrail:
    """出口闸门：answer 产出后执行所有注册的 check。"""

    def __init__(self, checks: list[OutputCheck] | None = None) -> None:
        if checks is not None:
            self._checks = list(checks)
        else:
            self._checks = [NumberGroundingCheck(), *_default_extra_checks]

    def check(self, answer: str, observations: list[Any]) -> GuardReport:
        all_violations: list[GuardViolation] = []
        for chk in self._checks:
            all_violations.extend(chk.check(answer, observations))
        fixed = self._fix(answer, all_violations)
        return GuardReport(
            violations=all_violations,
            original_answer=answer,
            fixed_answer=fixed,
        )

    @staticmethod
    def _fix(answer: str, violations: list[GuardViolation]) -> str:
        fixed = answer
        footers: list[str] = []
        for v in violations:
            if v.fixed_fragment and v.original_fragment:
                fixed = fixed.replace(v.original_fragment, v.fixed_fragment)
            if v.footer and v.footer not in footers:
                footers.append(v.footer)
        for footer in footers:
            fixed += footer
        return fixed
