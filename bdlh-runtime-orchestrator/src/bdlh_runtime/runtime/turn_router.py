"""同 session 下一条消息的 Turn Router（ADR-014）。

有 pending 时禁止默认盲目 resume；仅强信号直接决策，弱信号 ask_which。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class TurnDecision(StrEnum):
    RESUME = "resume"
    NEW_TURN = "new_turn"
    ASK_WHICH = "ask_which"
    FRESH = "fresh"  # 无 pending，正常新开/继续无书签路径


ASK_WHICH_PROMPT = (
    "当前还有未完成的分析。回复「继续」以接着刚才的问题，或说明你想换一个新问题。"
)

_RESUME_EXACT = frozenset(
    {
        "继续",
        "接着",
        "接着说",
        "接着分析",
        "恢复",
        "resume",
        "continue",
        "是",
        "是的",
        "好",
        "好的",
        "行",
        "可以",
        "确认",
        "嗯",
        "嗯嗯",
        "ok",
        "okay",
        "yes",
        "y",
    }
)

_NEW_TURN_PATTERNS = (
    re.compile(r"(换一个|换个|换题|新问题|重新问|取消|算了|不要了|别继续|停止旧|abandon)", re.I),
    re.compile(r"^(新的?|另外|另一个).{0,8}(问题|分析|请求)", re.I),
)

_SYMBOL_ONLY = re.compile(r"^\s*(\d{6}|[A-Za-z]{1,5})\s*$")
_SYMBOL_IN_TEXT = re.compile(r"\b\d{6}\b")


@dataclass(frozen=True)
class TurnRoute:
    decision: TurnDecision
    reason: str
    pending_run_id: str | None = None


def route_turn(
    *,
    message: str,
    pending_run_id: str | None,
    awaiting_route_confirm: bool = False,
) -> TurnRoute:
    """根据 pending 与用户下一句判定 resume / new_turn / ask_which / fresh。"""

    text = str(message or "").strip()
    if not pending_run_id:
        return TurnRoute(decision=TurnDecision.FRESH, reason="NO_PENDING")

    lowered = text.casefold()
    if is_resume_signal(text):
        return TurnRoute(
            decision=TurnDecision.RESUME,
            reason="STRONG_RESUME" if not awaiting_route_confirm else "CONFIRM_RESUME",
            pending_run_id=pending_run_id,
        )
    if _is_new_turn_signal(text, lowered):
        return TurnRoute(
            decision=TurnDecision.NEW_TURN,
            reason="STRONG_NEW_TURN" if not awaiting_route_confirm else "CONFIRM_NEW_TURN",
            pending_run_id=pending_run_id,
        )
    if awaiting_route_confirm:
        return TurnRoute(
            decision=TurnDecision.ASK_WHICH,
            reason="STILL_AMBIGUOUS_AFTER_CONFIRM",
            pending_run_id=pending_run_id,
        )
    # 澄清场景：纯代码/短答视为对挂起问题的回答 → resume
    if _SYMBOL_ONLY.match(text) or (len(text) <= 24 and _SYMBOL_IN_TEXT.search(text)):
        return TurnRoute(
            decision=TurnDecision.RESUME,
            reason="CLARIFICATION_ANSWER",
            pending_run_id=pending_run_id,
        )
    # 拿不准：禁止擅自 resume
    return TurnRoute(
        decision=TurnDecision.ASK_WHICH,
        reason="AMBIGUOUS_WITH_PENDING",
        pending_run_id=pending_run_id,
    )


def is_resume_signal(message: str) -> bool:
    """纯续跑口令（「继续」等），不含澄清答案或新问题。"""

    text = str(message or "").strip()
    if not text:
        return False
    lowered = text.casefold()
    if lowered in _RESUME_EXACT:
        return True
    return bool(re.fullmatch(r"(继续|接着|恢复)(吧|啊|呀)?[!！。.~]*", text))


def resolve_resume_message(
    *,
    user_message: str,
    route: TurnRoute,
    prior_user_messages: list[str],
) -> str:
    """Resume 口令时回放挂起前的真实用户目标；澄清答案仍用本句。

    ADR-014 的 resume 当前是同 run 重入 Cognitive，不是 L0 checkpoint 续跑；
    因此至少要把「继续」还原成原问题，避免 selector 当成无标的追问。
    """

    text = str(user_message or "").strip()
    if route.decision != TurnDecision.RESUME:
        return text
    if route.reason == "CLARIFICATION_ANSWER" or not is_resume_signal(text):
        return text
    for prior in reversed(prior_user_messages):
        candidate = str(prior or "").strip()
        if not candidate or candidate == text or is_resume_signal(candidate):
            continue
        return candidate
    return text


def _is_new_turn_signal(text: str, lowered: str) -> bool:
    del lowered
    return any(pattern.search(text) for pattern in _NEW_TURN_PATTERNS)
