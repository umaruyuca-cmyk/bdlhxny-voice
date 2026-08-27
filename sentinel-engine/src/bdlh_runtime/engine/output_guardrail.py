"""Output Guardrail: LLM 出答案后的出口检查（设计文档 §4.4 G-α/β/γ 补充）。

在 AgentLoop 产出 answer 后、返回调用方前执行：
1. NumberGroundingCheck — answer 中的非平凡数字必须来自某条 Observation
2. C1ComplianceCheck — answer 不得含交易执行语义（C-1）
3. C2ComplianceCheck — answer 不得含适当性结论（C-2）

检测到违规时标记并修正（替换幻觉数字、替换交易建议、追加风险披露）。
修正后的 answer 作为 Treatment 组最终输出。
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
        hallucinated = {
            n for n in hallucinated
            if not _is_trivial(n) and not _YEAR_RE.fullmatch(n)
        }
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


class C1ComplianceCheck:
    """answer 不得含交易执行语义（C-1）。"""

    _KEYWORDS = (
        "买入", "卖出", "下单", "转账", "建议购买",
        "立刻买入", "清仓", "建仓", "加仓", "减仓",
        "委托买入", "委托卖出", "帮我买", "帮我卖",
    )

    def check(self, answer: str, observations: list[Any]) -> list[GuardViolation]:
        return [
            GuardViolation(
                check_name="C1_VIOLATION",
                severity="critical",
                detail=f"含交易语义：{kw}",
                original_fragment=kw,
                fixed_fragment="（该操作不被允许）",
            )
            for kw in self._KEYWORDS
            if kw in answer
        ]


class C2ComplianceCheck:
    """answer 不得含适当性结论（C-2）。"""

    _KEYWORDS = (
        "适合您", "推荐持有", "建议配置",
        "该标的适合", "适合投资", "推荐买入",
        "建议买入", "符合您的风险", "适合你的风险",
    )

    def check(self, answer: str, observations: list[Any]) -> list[GuardViolation]:
        return [
            GuardViolation(
                check_name="C2_VIOLATION",
                severity="critical",
                detail=f"含适当性结论：{kw}",
                original_fragment=kw,
                fixed_fragment="（不构成适当性结论）",
            )
            for kw in self._KEYWORDS
            if kw in answer
        ]


class OutputGuardrail:
    """出口闸门：answer 产出后执行所有注册的 check。"""

    def __init__(self, checks: list[OutputCheck] | None = None) -> None:
        self._checks = checks or [
            NumberGroundingCheck(),
            C1ComplianceCheck(),
            C2ComplianceCheck(),
        ]

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
        has_compliance = False
        for v in violations:
            if v.fixed_fragment and v.original_fragment:
                fixed = fixed.replace(v.original_fragment, v.fixed_fragment)
            if v.check_name in ("C1_VIOLATION", "C2_VIOLATION"):
                has_compliance = True
        if has_compliance:
            fixed += "\n\n本结果仅为风险匹配筛查草稿，不构成投资建议。"
        return fixed
