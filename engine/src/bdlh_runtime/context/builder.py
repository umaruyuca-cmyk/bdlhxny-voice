from __future__ import annotations

from collections.abc import Iterable

from .compression import ContextCompressor, StructuredTextCompressor
from .models import (
    ContextAction,
    ContextBudgetError,
    ContextBuildRequest,
    ContextBuildResult,
    ContextClassification,
    ContextDecision,
    ContextItem,
    ContextMessage,
    ContextReport,
    ContextRole,
    ContextStrategy,
    ContextWindowError,
    ItemScore,
)
from .scoring import MultiFactorScorer
from .summary import ExtractiveSummarizer, HistorySummarizer
from .token_count import ConservativeTokenCounter, TokenCounter


class ContextBuilder:
    def __init__(
        self,
        counter: TokenCounter | None = None,
        compressor: ContextCompressor | None = None,
        summarizer: HistorySummarizer | None = None,
        scorer: MultiFactorScorer | None = None,
    ) -> None:
        self._counter = counter or ConservativeTokenCounter()
        self._compressor = compressor or StructuredTextCompressor()
        # single-summary 基准的独立摘要器:与 budgeted 使用的 StructuredTextCompressor 分离
        self._summarizer = summarizer or ExtractiveSummarizer()
        # budgeted v2 多因子评分器(公式五/六);None=保持 v1 直接 priority 排序
        self._scorer = scorer

    @property
    def summarizer(self) -> HistorySummarizer:
        """当前注入的摘要器(LLM 摘要器在此暴露用量,供编译器取回)。"""

        return self._summarizer

    @property
    def scorer(self) -> MultiFactorScorer | None:
        return self._scorer

    def build(self, request: ContextBuildRequest) -> ContextBuildResult:
        eligible, isolated = self._separate_owner_data(request)
        original_tokens = sum(self._counter.count(self._render(item, item.content)) for item in request.items)
        scores: tuple[ItemScore, ...] = ()

        if request.strategy is ContextStrategy.FULL:
            selected, decisions = self._build_full(eligible, request.token_budget)
        elif request.strategy is ContextStrategy.RECENT_N:
            selected, decisions = self._build_recent(eligible, request)
        elif request.strategy is ContextStrategy.SINGLE_SUMMARY:
            selected, decisions = self._build_single_summary(eligible, request)
        elif self._scorer is not None:
            # budgeted v2:多因子评分(公式五)+ 性价比选择(公式六)
            selected, decisions, scores = self._build_budgeted_v2(eligible, request)
        else:
            selected, decisions = self._build_budgeted(eligible, request)

        decisions.extend(isolated)
        messages = self._to_messages(selected)
        working_tokens = sum(self._counter.count(message.content) for message in messages)
        if working_tokens > request.token_budget:
            raise ContextWindowError(working_tokens, request.token_budget)
        required_ids = tuple(
            item.item_id for item in request.items if item.classification is ContextClassification.REQUIRED
        )
        retained_required_ids = tuple(
            decision.item_id
            for decision in decisions
            if decision.item_id in required_ids
            and decision.action in {ContextAction.KEPT, ContextAction.COMPRESSED, ContextAction.REFERENCED}
        )
        warnings = []
        if set(required_ids) != set(retained_required_ids):
            warnings.append("one or more required context items were not retained")
        if working_tokens > request.token_budget:
            warnings.append("working context exceeds the configured token budget")

        report = ContextReport(
            strategy=request.strategy,
            token_budget=request.token_budget,
            original_tokens=original_tokens,
            working_tokens=working_tokens,
            required_item_ids=required_ids,
            retained_required_item_ids=retained_required_ids,
            decisions=tuple(decisions),
            warnings=tuple(warnings),
            scores=scores,
            # 评分只作用于 budgeted;其余策略不受注入 scorer 影响(受控对照前提)
            scoring_version=(
                self._scorer.weights.version
                if self._scorer is not None and request.strategy is ContextStrategy.BUDGETED
                else ""
            ),
        )
        return ContextBuildResult(messages=messages, report=report)

    def _separate_owner_data(self, request: ContextBuildRequest) -> tuple[list[ContextItem], list[ContextDecision]]:
        eligible = []
        isolated = []
        for item in request.items:
            if request.owner_id and item.owner_id and item.owner_id != request.owner_id:
                input_tokens = self._counter.count(self._render(item, item.content))
                isolated.append(
                    ContextDecision(
                        item_id=item.item_id,
                        action=ContextAction.ISOLATED,
                        reason="item belongs to a different user scope",
                        input_tokens=input_tokens,
                        output_tokens=0,
                        source_id=item.source_id,
                    )
                )
                continue
            eligible.append(item)
        return eligible, isolated

    def _build_full(
        self, items: list[ContextItem], token_budget: int
    ) -> tuple[list[tuple[ContextItem, str]], list[ContextDecision]]:
        selected = [(item, self._render(item, item.content)) for item in self._ordered(items)]
        total = sum(self._counter.count(rendered) for _, rendered in selected)
        if total > token_budget:
            raise ContextWindowError(total, token_budget)
        decisions = [self._decision(item, ContextAction.KEPT, "full strategy", rendered) for item, rendered in selected]
        return selected, decisions

    def _build_recent(
        self, items: list[ContextItem], request: ContextBuildRequest
    ) -> tuple[list[tuple[ContextItem, str]], list[ContextDecision]]:
        """recent-window 基准:公共系统规则等 required 始终保留,再从最后一个
        事件向前选择完整条目,直到预算或 recent_n 条数上限;选中项按原序输出。
        工具调用/结果配对由序列化层合并为单条目,窗口天然不拆对。"""

        required = [item for item in items if item.classification is ContextClassification.REQUIRED]
        selected, decisions, remaining = self._keep_required(required, request.token_budget)
        optional = [
            item for item in items if item.classification is not ContextClassification.REQUIRED
        ]
        ordered = self._ordered(optional)

        window: list[ContextItem] = []
        window_full = False
        for item in reversed(ordered):
            if len(window) >= request.recent_n:
                window_full = True
                break
            tokens = self._counter.count(self._render(item, item.content))
            if tokens > remaining:
                break
            window.append(item)
            remaining -= tokens
        window.reverse()
        kept_ids = {item.item_id for item in window}

        for item in ordered:
            rendered = self._render(item, item.content)
            if item.item_id in kept_ids:
                selected.append((item, rendered))
                decisions.append(self._decision(item, ContextAction.KEPT, "within recent window", rendered))
            else:
                reason = "outside recent-n window" if window_full else "token budget exhausted"
                decisions.append(self._decision(item, ContextAction.OMITTED, reason, ""))
        return selected, decisions

    def _build_single_summary(
        self, items: list[ContextItem], request: ContextBuildRequest
    ) -> tuple[list[tuple[ContextItem, str]], list[ContextDecision]]:
        """single-summary 独立基准:required 原文保留 + 最近事件原文保留
        (summary_recent_tokens)+ 更早事件一次性摘要(summary_max_tokens)。
        摘要器与 budgeted 的规则压缩器分离,不读取 priority/gold。"""

        required = [item for item in items if item.classification is ContextClassification.REQUIRED]
        selected, decisions, remaining = self._keep_required(required, request.token_budget)
        optional = self._ordered(
            item for item in items if item.classification is not ContextClassification.REQUIRED
        )

        recent: list[ContextItem] = []
        recent_used = 0
        recent_budget = min(request.summary_recent_tokens, remaining)
        for item in reversed(optional):
            tokens = self._counter.count(self._render(item, item.content))
            if recent_used + tokens > recent_budget:
                break
            recent.insert(0, item)
            recent_used += tokens
        earlier = optional[: len(optional) - len(recent)]
        recent_ids = {item.item_id for item in recent}

        summary_item: ContextItem | None = None
        if earlier:
            summary_budget = min(request.summary_max_tokens, max(0, remaining - recent_used))
            summary_text = self._summarizer.summarize(
                [self._render(item, item.content) for item in earlier], summary_budget, self._counter
            )
            if summary_text:
                summary_item = ContextItem(
                    item_id="history-summary",
                    content=summary_text,
                    classification=ContextClassification.COMPRESSIBLE,
                    role=ContextRole.USER_DATA,
                    sequence=earlier[0].sequence,
                    source_id=",".join(item.item_id for item in earlier[:8]),
                )
                summary_rendered = self._render(summary_item, summary_item.content)
                if self._counter.count(summary_rendered) > remaining - recent_used:
                    summary_item = None

        if summary_item is not None:
            selected.append((summary_item, self._render(summary_item, summary_item.content)))
        for item in earlier:
            decisions.append(
                self._decision(
                    item,
                    ContextAction.COMPRESSED if summary_item is not None else ContextAction.OMITTED,
                    "represented by single history summary"
                    if summary_item is not None
                    else "history summary could not fit the remaining budget",
                    "",
                )
            )
        for item in recent:
            rendered = self._render(item, item.content)
            selected.append((item, rendered))
            decisions.append(self._decision(item, ContextAction.KEPT, "recent event kept verbatim", rendered))
        return selected, decisions

    def _build_budgeted(
        self, items: list[ContextItem], request: ContextBuildRequest
    ) -> tuple[list[tuple[ContextItem, str]], list[ContextDecision]]:
        required = [item for item in items if item.classification is ContextClassification.REQUIRED]
        selected, decisions, remaining = self._keep_required(required, request.token_budget)

        candidates = [
            item
            for item in items
            if item.classification
            in {
                ContextClassification.COMPRESSIBLE,
                ContextClassification.REFERENCE_ONLY,
            }
        ]
        candidates.sort(key=lambda item: (-item.priority, item.sequence, item.item_id))

        for index, item in enumerate(candidates):
            original_rendered = self._render(item, item.content)
            original_tokens = self._counter.count(original_rendered)
            if remaining <= 0:
                decisions.append(self._decision(item, ContextAction.OMITTED, "token budget exhausted", ""))
                continue

            if item.classification is ContextClassification.REFERENCE_ONLY:
                value = self._reference(item, original_tokens)
                action = ContextAction.REFERENCED
                reason = "reference-only item represented by source metadata"
            else:
                remaining_candidates = max(1, len(candidates) - index)
                fair_share = max(request.minimum_compressed_tokens, remaining // remaining_candidates)
                header_tokens = self._counter.count(self._render(item, ""))
                target = min(
                    original_tokens,
                    max(request.minimum_compressed_tokens, int(original_tokens * request.compression_ratio)),
                    max(0, fair_share - header_tokens),
                )
                value = self._compressor.compress(item, target, self._counter)
                action = ContextAction.KEPT if value == item.content else ContextAction.COMPRESSED
                reason = "fits budget without compression" if action is ContextAction.KEPT else "compressed to budget"

            rendered = self._render(item, value)
            tokens = self._counter.count(rendered)
            if value and tokens <= remaining:
                selected.append((item, rendered))
                remaining -= tokens
                decisions.append(self._decision(item, action, reason, rendered))
            else:
                decisions.append(self._decision(item, ContextAction.OMITTED, "item does not fit remaining budget", ""))

        for item in items:
            if item.classification is ContextClassification.DISTRACTOR:
                decisions.append(
                    self._decision(
                        item,
                        ContextAction.ISOLATED,
                        "distractor excluded from budgeted working context",
                        "",
                    )
                )

        selected.sort(key=lambda pair: (pair[0].sequence, pair[0].item_id))
        return selected, decisions

    def _build_budgeted_v2(
        self, items: list[ContextItem], request: ContextBuildRequest
    ) -> tuple[list[tuple[ContextItem, str]], list[ContextDecision], tuple[ItemScore, ...]]:
        """公式五/六驱动选择(设计稿 §4):按 selection_value 降序遍历,
        每条目依次尝试 完整→压缩(fair_share 上限)→引用;全部放不下才省略。

        - REQUIRED 语义不变;公平份额保留为单条压缩目标的上限约束;
        - 排序值用「header+压缩目标」的确定性估算,接受前按实际压缩结果复核预算;
        - 引用表示排序键恒 -1.0,防止低分母抢占完整/压缩名额(§3.3 陷阱);
        - 依赖闭包:被选中条目引用的来源条目若被省略,至少以引用表示补入。
        """

        assert self._scorer is not None
        required = [item for item in items if item.classification is ContextClassification.REQUIRED]
        selected, decisions, remaining = self._keep_required(required, request.token_budget)

        candidates = [
            item
            for item in items
            if item.classification in {ContextClassification.COMPRESSIBLE, ContextClassification.REFERENCE_ONLY}
        ]
        candidate_ids = {item.item_id for item in candidates}
        # 公平份额按「必需项后剩余预算 ÷ 候选数」一次性冻结,保证排序值确定
        fair_share = max(request.minimum_compressed_tokens, remaining // max(1, len(candidates)))

        priorities: dict[str, float] = {}
        full_tokens: dict[str, int] = {}
        compress_target: dict[str, int] = {}
        pairs: list[tuple[float, int, str, str, ContextItem]] = []
        for item in candidates:
            priority, _factors = self._scorer.priority(item)
            priorities[item.item_id] = priority
            full = self._counter.count(self._render(item, item.content))
            full_tokens[item.item_id] = full
            if item.classification is ContextClassification.COMPRESSIBLE and full > 0:
                pairs.append(
                    (self._scorer.selection_value(priority, full), item.sequence, item.item_id, "full", item)
                )
                header = self._counter.count(self._render(item, ""))
                target = min(
                    full,
                    max(
                        request.minimum_compressed_tokens,
                        int(full * request.compression_ratio),
                    ),
                    max(0, fair_share - header),
                )
                compress_target[item.item_id] = target
                if target > 0:
                    # 排序用估算 token(header+目标长度);接受时按实际压缩结果复核
                    estimate = max(1, header + target)
                    pairs.append(
                        (self._scorer.selection_value(priority, estimate), item.sequence, item.item_id, "compressed", item)
                    )
            # 引用表示是兜底,排序键恒 -1.0:只在该条目完整/压缩都放不下时才会轮到
            pairs.append((-1.0, item.sequence, item.item_id, "reference", item))
        pairs.sort(key=lambda row: (-row[0], row[1], row[2], {"full": 0, "compressed": 1, "reference": 2}[row[3]]))

        chosen: dict[str, tuple[str, str]] = {}  # item_id -> (representation, rendered)
        for _value, _sequence, _item_id, representation, item in pairs:
            if item.item_id in chosen:
                continue  # 已有更优表示
            if representation == "full":
                rendered = self._render(item, item.content)
            elif representation == "compressed":
                compressed = self._compressor.compress(item, compress_target[item.item_id], self._counter)
                rendered = self._render(item, compressed)
                if not compressed.strip() or not rendered.strip():
                    continue
            else:  # reference:排序键恒 -1.0,天然只在完整/压缩都放不下时兜底
                rendered = self._render(item, self._reference(item, full_tokens[item.item_id]))
            tokens = self._counter.count(rendered)
            if tokens > remaining:
                continue  # 按实际表示复核预算;尝试更短表示(后续对)
            selected.append((item, rendered))
            remaining -= tokens
            chosen[item.item_id] = (representation, rendered)

        # 依赖闭包(设计稿 §4 步骤 5):被选中条目引用的来源若被省略,补引用表示
        for item in candidates:
            target = item.source_id
            if (
                target
                and target != item.item_id
                and target in candidate_ids
                and target not in chosen
                and item.item_id in chosen
            ):
                source_item = next(row for row in candidates if row.item_id == target)
                rendered = self._render(
                    source_item, self._reference(source_item, full_tokens[source_item.item_id])
                )
                tokens = self._counter.count(rendered)
                if tokens <= remaining:
                    selected.append((source_item, rendered))
                    remaining -= tokens
                    chosen[source_item.item_id] = ("reference", rendered)

        score_rows: list[ItemScore] = []
        for item in candidates:
            representation, rendered = chosen.get(item.item_id, ("omitted", ""))
            score_rows.append(
                self._scorer.score(
                    item,
                    representation=representation,
                    representation_tokens=self._counter.count(rendered),
                )
            )
        for item in candidates:
            if item.item_id in chosen:
                representation = chosen[item.item_id][0]
                action = ContextAction.KEPT if representation == "full" else (
                    ContextAction.COMPRESSED if representation == "compressed" else ContextAction.REFERENCED
                )
                score = next(row for row in score_rows if row.item_id == item.item_id)
                decisions.append(
                    self._decision(
                        item,
                        action,
                        f"v2 {representation} selection_value={score.selection_value:.6f} priority={score.priority:.4f}",
                        chosen[item.item_id][1],
                    )
                )
            else:
                decisions.append(self._decision(item, ContextAction.OMITTED, "v2 no representation fits remaining budget", ""))
        for item in items:
            if item.classification is ContextClassification.DISTRACTOR:
                decisions.append(
                    self._decision(item, ContextAction.ISOLATED, "distractor excluded from budgeted working context", "")
                )

        selected.sort(key=lambda pair: (pair[0].sequence, pair[0].item_id))
        return selected, decisions, tuple(score_rows)

    def _keep_required(
        self, required: list[ContextItem], token_budget: int
    ) -> tuple[list[tuple[ContextItem, str]], list[ContextDecision], int]:
        selected = []
        decisions = []
        required_tokens = 0
        for item in self._ordered(required):
            rendered = self._render(item, item.content)
            required_tokens += self._counter.count(rendered)
            selected.append((item, rendered))
            decisions.append(self._decision(item, ContextAction.KEPT, "required item", rendered))
        if required_tokens > token_budget:
            raise ContextBudgetError(required_tokens, token_budget)
        return selected, decisions, token_budget - required_tokens

    def _decision(
        self,
        item: ContextItem,
        action: ContextAction,
        reason: str,
        output: str,
    ) -> ContextDecision:
        return ContextDecision(
            item_id=item.item_id,
            action=action,
            reason=reason,
            input_tokens=self._counter.count(self._render(item, item.content)),
            output_tokens=self._counter.count(output),
            source_id=item.source_id,
        )

    def _render(self, item: ContextItem, content: str) -> str:
        if item.bare:
            return content
        if item.conversation:
            # 对话消息形态:不加 item 头;不可信工具内容仍需包裹
            if not item.trusted or item.role is ContextRole.UNTRUSTED_DATA:
                return f"<untrusted-data>\n{content}\n</untrusted-data>"
            return content
        source = f" source={item.source_id}" if item.source_id else ""
        header = f"[context item={item.item_id} type={item.classification.value}{source}]"
        body = f"{header}\n{content}"
        if not item.trusted or item.role is ContextRole.UNTRUSTED_DATA:
            return f"<untrusted-data>\n{body}\n</untrusted-data>"
        return body

    @staticmethod
    def _reference(item: ContextItem, original_tokens: int) -> str:
        source = item.source_id or item.item_id
        return f"[reference source={source} original_tokens={original_tokens}]"

    def _to_messages(self, selected: Iterable[tuple[ContextItem, str]]) -> tuple[ContextMessage, ...]:
        """指令合并为一条 system;普通数据条目合并为一条 user;
        conversation 条目(Session 历史、当前问题)逐条保持角色与顺序。"""

        instruction_parts = []
        data_parts = []
        conversation: list[ContextMessage] = []
        for item, rendered in selected:
            if item.conversation:
                role = "assistant" if item.role is ContextRole.ASSISTANT else "user"
                conversation.append(ContextMessage(role=role, content=rendered))
            elif item.role in {ContextRole.SYSTEM, ContextRole.INSTRUCTION} and item.trusted:
                instruction_parts.append(rendered)
            else:
                data_parts.append(rendered)

        messages = []
        if instruction_parts:
            messages.append(ContextMessage(role="system", content="\n\n".join(instruction_parts)))
        if data_parts:
            messages.append(ContextMessage(role="user", content="\n\n".join(data_parts)))
        messages.extend(conversation)
        return tuple(messages)

    @staticmethod
    def _ordered(items: Iterable[ContextItem]) -> list[ContextItem]:
        return sorted(items, key=lambda item: (item.sequence, item.item_id))
