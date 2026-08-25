from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ContextClassification(StrEnum):
    REQUIRED = "required"
    COMPRESSIBLE = "compressible"
    REFERENCE_ONLY = "reference_only"
    DISTRACTOR = "distractor"


class ContextRole(StrEnum):
    SYSTEM = "system"
    INSTRUCTION = "instruction"
    USER_DATA = "user_data"
    TOOL_DEFINITION = "tool_definition"
    TOOL_RESULT = "tool_result"
    REFERENCE = "reference"
    UNTRUSTED_DATA = "untrusted_data"
    #: 会话历史/当前问题的对话消息形态(assistant 侧)
    ASSISTANT = "assistant"


class ContextStrategy(StrEnum):
    FULL = "full"
    RECENT_N = "recent-n"
    SINGLE_SUMMARY = "single-summary"
    BUDGETED = "budgeted"


class ContextAction(StrEnum):
    KEPT = "kept"
    COMPRESSED = "compressed"
    REFERENCED = "referenced"
    OMITTED = "omitted"
    ISOLATED = "isolated"


class ContextBudgetError(ValueError):
    def __init__(self, required_tokens: int, token_budget: int) -> None:
        self.required_tokens = required_tokens
        self.token_budget = token_budget
        super().__init__(
            f"required context needs {required_tokens} tokens, but the working-context budget is {token_budget}"
        )


class ContextWindowError(ValueError):
    def __init__(self, working_tokens: int, token_budget: int) -> None:
        self.working_tokens = working_tokens
        self.token_budget = token_budget
        super().__init__(f"working context needs {working_tokens} tokens, but the configured budget is {token_budget}")


@dataclass(frozen=True)
class ContextItem:
    item_id: str
    content: str
    classification: ContextClassification
    role: ContextRole = ContextRole.USER_DATA
    priority: int = 0
    source_id: str | None = None
    observed_at: str | None = None
    owner_id: str | None = None
    trusted: bool = True
    sequence: int = 0
    #: 条目来源类型(如 rule/news/position/manual_led);构建语义只看 classification,
    #: item_type 仅供追溯展示(context_items.item_type)。
    item_type: str = "generic"
    #: bare=True 时按原文透传(不加 item 头、不包 <untrusted-data>);仅限可信指令
    #: 条目(如系统提示),保证构建器接入后主链系统提示逐字不变。
    bare: bool = False
    #: conversation=True 时按对话消息形态输出(不加 item 头,保持 role/顺序),
    #: 用于 Session 历史、当前问题和多轮工具消息;不可信工具内容仍会被包裹。
    conversation: bool = False
    # ── 多因子评分(公式五)输入字段;缺省时由 scorer 按类型默认表推导 ──
    #: 检索/场景规则给出的相关度档位 [0,1];缺省 0.5 中性
    relevance: float = 0.5
    #: 来源权威度 [0,1];None 时按 role/item_type 默认表推导
    authority_level: float | None = None
    #: 被哪些候选条目引用(条目 item_id 列表);citation_dependency 因子输入
    cited_by: tuple[str, ...] = ()
    #: 是否已被更新版本取代(staleness 因子输入;由序列化层检测同 source 更新时间)
    superseded: bool = False

    def __post_init__(self) -> None:
        if not self.item_id.strip():
            raise ValueError("item_id must not be empty")
        if not self.content.strip():
            raise ValueError(f"context item {self.item_id!r} must not be empty")
        if self.bare and (not self.trusted or self.role is ContextRole.UNTRUSTED_DATA):
            raise ValueError("bare context items must be trusted instruction entries")
        if self.bare and self.conversation:
            raise ValueError("bare and conversation are mutually exclusive rendering modes")


@dataclass(frozen=True)
class ContextBuildRequest:
    items: tuple[ContextItem, ...]
    token_budget: int
    strategy: ContextStrategy = ContextStrategy.BUDGETED
    owner_id: str | None = None
    recent_n: int = 10
    compression_ratio: float = 0.35
    minimum_compressed_tokens: int = 32
    #: single-summary 基准:最近事件原文的 Token 预留(更早事件进入一次性摘要)
    summary_recent_tokens: int = 1024
    #: single-summary 基准:历史摘要自身的最大 Token
    summary_max_tokens: int = 2560

    def __post_init__(self) -> None:
        if self.token_budget <= 0:
            raise ValueError("token_budget must be positive")
        if self.recent_n <= 0:
            raise ValueError("recent_n must be positive")
        if not 0 < self.compression_ratio <= 1:
            raise ValueError("compression_ratio must be in (0, 1]")
        if self.minimum_compressed_tokens <= 0:
            raise ValueError("minimum_compressed_tokens must be positive")
        if self.summary_recent_tokens < 0:
            raise ValueError("summary_recent_tokens must be non-negative")
        if self.summary_max_tokens <= 0:
            raise ValueError("summary_max_tokens must be positive")
        item_ids = [item.item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("context item ids must be unique")


@dataclass(frozen=True)
class ContextDecision:
    item_id: str
    action: ContextAction
    reason: str
    input_tokens: int
    output_tokens: int
    source_id: str | None = None


@dataclass(frozen=True)
class ItemScore:
    """公式五/六的单条目评分明细(可解释性证据,公开页可展示因子构成)。"""

    item_id: str
    factors: dict[str, float]
    priority: float
    representation: str
    representation_tokens: int
    selection_value: float


@dataclass(frozen=True)
class ContextMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ContextReport:
    strategy: ContextStrategy
    token_budget: int
    original_tokens: int
    working_tokens: int
    required_item_ids: tuple[str, ...]
    retained_required_item_ids: tuple[str, ...]
    decisions: tuple[ContextDecision, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)
    #: 多因子评分明细(公式五/六启用时逐条目记录;v1 排序时为空)
    scores: tuple["ItemScore", ...] = field(default_factory=tuple)
    #: 评分权重版本(进入缓存键;未启用评分时为空串)
    scoring_version: str = ""

    @property
    def required_retained(self) -> bool:
        return set(self.required_item_ids) == set(self.retained_required_item_ids)

    @property
    def budget_fit(self) -> bool:
        return self.working_tokens <= self.token_budget

    @property
    def counts(self) -> dict[str, int]:
        result = {action.value: 0 for action in ContextAction}
        for decision in self.decisions:
            result[decision.action.value] += 1
        return result


@dataclass(frozen=True)
class ContextBuildResult:
    messages: tuple[ContextMessage, ...]
    report: ContextReport
