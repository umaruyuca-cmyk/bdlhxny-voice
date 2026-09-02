"""四种上下文策略的 Session 派生输入编译器。

一份冻结 Session → 四份派生输入(full-session / recent-window /
single-summary / budgeted-session),每份生成后计算 hash 并冻结成工件；
统一原生 Tool Calling 执行底座复用这些工件，不在运行时重新生成。

编译器输入只有 session + variant 配置 + 公共系统规则——结构上无法读取
gold,答案泄漏在接口层面被阻断。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bdlh_runtime.context import (
    QWEN_TIKTOKEN_VERSION,
    TIKTOKEN_TOKENIZER_VERSION,
    ContextBuilder,
    ContextBuildRequest,
    ContextBuildResult,
    ContextClassification,
    ContextItem,
    ContextMessage,
    ContextRole,
    ContextStrategy,
    HistorySummarizer,
    ItemScore,
    MultiFactorScorer,
    TokenCounter,
    counter_from_env,
)

from .history_segments import HistorySegmentLike, SegmentUsage, inject_history_segments
from .loader import SessionCase, canonical_json_hash
from .serializer import SerializedItem, serialize_session

#: variants 配置中的 strategy 名 → 构建器策略(需求 §3.1 新旧标识映射)。
#: 旧名(full-session/recent-n/recent-window/budgeted-session/budgeted)仅为
#: 读取旧工件与旧配置兼容;新建任务一律使用新标识,不再暴露旧名称。
STRATEGY_BY_NAME: dict[str, ContextStrategy] = {
    "full": ContextStrategy.FULL,
    "full-session": ContextStrategy.FULL,  # 旧名读兼容
    "recent-n": ContextStrategy.RECENT_EVENTS_LEGACY,
    "recent-window": ContextStrategy.RECENT_EVENTS_LEGACY,  # 旧名读兼容(按事件)
    "recent-events-legacy": ContextStrategy.RECENT_EVENTS_LEGACY,
    "recent-turns": ContextStrategy.RECENT_TURNS,
    "single-summary": ContextStrategy.SINGLE_SUMMARY,
    "budgeted": ContextStrategy.BUDGETED,
    "budgeted-session": ContextStrategy.BUDGETED,  # 旧名读兼容
    "budgeted-hybrid-v1": ContextStrategy.BUDGETED,
    "budgeted-extractive": ContextStrategy.BUDGETED,
}

#: recent-turns 默认保留轮数(需求 §11.1:最近 12~20 个完整轮,默认 16)
DEFAULT_RECENT_TURNS = 16


def recent_turns_event_ids(events: tuple[Any, ...], keep_turns: int) -> frozenset[str]:
    """返回最近 ``keep_turns`` 个完整对话轮内的事件 id(需求 §8.4 轮次口径)。

    一条 user_message 开启一轮;其后到下一条 user_message 之前的助手消息、
    工具调用/结果与系统事件同属该轮,原子不拆;轮数不足时全保留。
    """

    turn_of: dict[str, int] = {}
    turn = 0
    for event in events:
        if str(getattr(event, "type", "")) == "user_message":
            turn += 1
        turn_of[str(getattr(event, "event_id", ""))] = turn
    total = turn
    keep_from = max(1, total - max(1, keep_turns) + 1)
    return frozenset(event_id for event_id, index in turn_of.items() if index >= keep_from)

#: budgeted 早期实现的算法版本号(与 run_telemetry 的 structured-text-v1 对齐)
STRUCTURED_TEXT_ALGO_VERSION = "structured-text-v1"


@dataclass(frozen=True)
class BuildMetrics:
    """摘要/压缩构建本身的成本(single-summary 模型摘要时由调用方填入)。

    口径(purpose=COMPRESSION):model_calls/tokens/cost 只含本轮真实模型
    请求(缓存命中不计);cache_hits 单独累计,不进入当前费用。
    """

    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    cache_hits: int = 0
    purpose: str = "COMPRESSION"
    batch_chunks: int = 0


@dataclass(frozen=True)
class CompiledContext:
    """一份派生输入工件(variants.compiled_context_artifact_required_fields 全集)。"""

    case_id: str
    case_version: int
    source_session_hash: str
    variant_id: str
    strategy_version: str
    token_budget: int
    compiled_messages: tuple[ContextMessage, ...]
    compiled_context_hash: str
    input_event_ids: tuple[str, ...]
    kept_event_ids: tuple[str, ...]
    compressed_event_ids: tuple[str, ...]
    referenced_event_ids: tuple[str, ...]
    omitted_event_ids: tuple[str, ...]
    original_tokens: int
    working_tokens: int
    build_duration_ms: int
    build_model_calls: int
    build_input_tokens: int
    build_output_tokens: int
    build_cost: float
    #: 构建用量口径(§11.1):COMPRESSION 与 Agent 主模型(AGENT)分开统计;
    #: 缓存命中数单独记录,build_* 字段只含本轮真实模型请求
    build_cache_hits: int = 0
    build_purpose: str = "COMPRESSION"
    build_summary_chunks: int = 0
    warnings: tuple[str, ...] = field(default_factory=tuple)
    strategy: str = ""
    required_retained: bool = True
    budget_fit: bool = True
    #: 计数口径版本(conservative-*/tiktoken-*);同批次内禁止混用两种口径
    tokenizer_version: str = ""
    #: 多因子评分明细(公式五/六;仅 budgeted v2 启用时非空)
    scores: tuple[ItemScore, ...] = field(default_factory=tuple)
    #: 评分权重版本(仅 budgeted v2 启用时非空,否则空串)
    scoring_version: str = ""
    #: LLM 辅助分类计量(§9.1/§10.3:语义分类辅助 0 或 1 次,与摘要分开计数)
    classify_model_calls: int = 0
    classify_input_tokens: int = 0
    classify_output_tokens: int = 0
    classify_truncated: bool = False
    #: 分类来源与分布:code_rules=代码预规则条数,llm_assist=LLM 判定条数
    classification_source: str = "code_rules_only"
    classification_stats: dict[str, int] = field(default_factory=dict)
    #: 底层构建结果(冻结喂入用;不进入机器可读工件)
    build_result: ContextBuildResult | None = None
    #: 历史轮 Segment(已注入 Compiler 的冻结摘要)追溯与计量(§6.4)
    memory_segment_ids: tuple[str, ...] = ()
    segment_cache_hits: int = 0
    segment_generated: int = 0
    segment_invalidated: int = 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "case_version": self.case_version,
            "source_session_hash": self.source_session_hash,
            "variant_id": self.variant_id,
            "strategy": self.strategy,
            "strategy_version": self.strategy_version,
            "token_budget": self.token_budget,
            "compiled_messages": [
                {"role": message.role, "content": message.content} for message in self.compiled_messages
            ],
            "compiled_context_hash": self.compiled_context_hash,
            "input_event_ids": list(self.input_event_ids),
            "kept_event_ids": list(self.kept_event_ids),
            "compressed_event_ids": list(self.compressed_event_ids),
            "referenced_event_ids": list(self.referenced_event_ids),
            "omitted_event_ids": list(self.omitted_event_ids),
            "original_tokens": self.original_tokens,
            "working_tokens": self.working_tokens,
            "build_duration_ms": self.build_duration_ms,
            "build_model_calls": self.build_model_calls,
            "build_input_tokens": self.build_input_tokens,
            "build_output_tokens": self.build_output_tokens,
            "build_cost": self.build_cost,
            "build_cache_hits": self.build_cache_hits,
            "build_purpose": self.build_purpose,
            "build_summary_chunks": self.build_summary_chunks,
            "warnings": list(self.warnings),
            "required_retained": self.required_retained,
            "budget_fit": self.budget_fit,
            "tokenizer_version": self.tokenizer_version,
            "scores": [_score_payload(row) for row in self.scores],
            "classification": {
                "source": self.classification_source,
                "stats": dict(self.classification_stats),
                "llm_calls": self.classify_model_calls,
                "llm_input_tokens": self.classify_input_tokens,
                "llm_output_tokens": self.classify_output_tokens,
                "truncated": self.classify_truncated,
            },
            "scoring_version": self.scoring_version,
            "memory_segment_ids": list(self.memory_segment_ids),
            "segment_cache_hits": self.segment_cache_hits,
            "segment_generated": self.segment_generated,
            "segment_invalidated": self.segment_invalidated,
        }


def _score_payload(row: ItemScore) -> dict[str, Any]:
    return {
        "item_id": row.item_id,
        "factors": dict(row.factors),
        "priority": row.priority,
        "representation": row.representation,
        "representation_tokens": row.representation_tokens,
        "selection_value": row.selection_value,
    }


class SessionCompiler:
    """编译入口;同一 Session 的四份派生输入共用一个实例保证口径一致。

    口径选择由环境变量控制(整批必须单一口径,中途不得切换):
    - ``LLM_TOKENIZER=tiktoken`` → tiktoken 精确计数,其余保守口径;
    - ``BUDGETED_SCORING=multi-factor-v2`` → budgeted 变体走公式五/六(v2);
    - summarizer/scorer 也可显式注入(单测用),注入优先于环境变量。

    注入(或经 ``from_env(llm_summary=True)`` 启用)LLM 摘要器时,**budgeted
    的压缩步骤同样切换为生成式**(SummarizerCompressor:被压缩条目的替代
    文本由摘要器生成,失败回退结构化抽取)——single-summary 的摘要语义不变;
    这是压缩方法对照实验(compression-method-comparison)的自变量开关。
    """

    def __init__(
        self,
        builder: ContextBuilder | None = None,
        counter: TokenCounter | None = None,
        *,
        tokenizer_version: str | None = None,
        summarizer: HistorySummarizer | None = None,
        scorer: MultiFactorScorer | None = None,
        classifier: Any | None = None,
    ) -> None:
        if counter is None or tokenizer_version is None:
            env_counter, env_version = counter_from_env()
            counter = counter or env_counter
            tokenizer_version = tokenizer_version or env_version
        self._counter: TokenCounter = counter
        self.tokenizer_version: str = tokenizer_version
        if builder is not None:
            self._builder = builder
        elif summarizer is not None:
            # LLM 摘要启用:budgeted 压缩走生成式(同一摘要器实例,用量与降级统一回流)
            from bdlh_runtime.context.compression import SummarizerCompressor

            self._builder = ContextBuilder(
                counter=self._counter,
                compressor=SummarizerCompressor(summarizer),
                summarizer=summarizer,
                scorer=scorer,
            )
        else:
            self._builder = ContextBuilder(counter=self._counter, scorer=scorer)
        #: LLM 辅助分类器(§9.1/§13.2 步骤 7):None=仅代码规则(对照轨道/关闭时)
        self._classifier = classifier

    @classmethod
    def from_env(cls, *, llm_summary: bool = False) -> SessionCompiler:
        """按环境变量装配:BUDGETED_SCORING(v2 评分)、LLM_SUMMARY(LLM 摘要)。

        未设置的开关保持既有基准行为(v1 排序、抽取式摘要),
        保证 v1/v2、抽取式/LLM 摘要可做受控对照。
        LLM 摘要默认启用「生成一次后冻结」缓存(engine/var/cache/),
        ``LLM_SUMMARY_FREEZE=0`` 关闭。
        """

        from bdlh_runtime.context import scorer_from_env

        summarizer = None
        classifier = None
        if llm_summary:
            from .llm_summary import LLMSummarizer

            summarizer = LLMSummarizer(
                cache_path=(Path(__file__).resolve().parents[3] / "var" / "cache" / "llm-summary.json")
            )
            # 分类辅助与摘要同一真实模型开关(§10.3 语义分类辅助 0 或 1 次);
            # CLASSIFY_LLM=0 可单独关闭(回退代码规则),对照轨道默认不装配
            import os

            if os.environ.get("CLASSIFY_LLM", "1").strip().lower() not in {"0", "false", "off"}:
                from .llm_classify import LLMContextClassifier

                classifier = LLMContextClassifier()
        return cls(scorer=scorer_from_env(), summarizer=summarizer, classifier=classifier)

    def compile(
        self,
        session: SessionCase,
        variant: dict[str, Any],
        *,
        common_rules: str,
        build_metrics: BuildMetrics | None = None,
        history_segments: tuple[HistorySegmentLike, ...] = (),
        segment_usage: SegmentUsage | None = None,
    ) -> CompiledContext:
        strategy = STRATEGY_BY_NAME.get(str(variant.get("strategy") or ""))
        if strategy is None:
            raise ValueError(f"未知上下文策略: {variant.get('strategy')!r}")
        variant_id = str(variant["variant_id"])
        token_budget = int(variant["token_budget"])

        serialized_source = serialize_session(session)
        # recent-turns(§8.4):先按完整轮过滤历史条目,再走事件窗口构建分支;
        # 预算语义不变(超预算从尾部保留到预算耗尽),只是截取粒度从事件变为轮
        if strategy is ContextStrategy.RECENT_TURNS:
            keep_ids = recent_turns_event_ids(
                session.events,
                int(variant.get("recent_turns") or DEFAULT_RECENT_TURNS),
            )
            serialized_source = tuple(
                entry for entry in serialized_source if set(entry.event_ids) & set(keep_ids)
            )
            strategy = ContextStrategy.RECENT_EVENTS_LEGACY
        # 历史轮 Segment 注入:被完整覆盖的连续条目替换为合成摘要条目;
        # 非法 Segment 拒绝注入并保留原文(warning 记入工件)
        injection = inject_history_segments(serialized_source, history_segments)
        serialized = injection.items
        # 生产工作台允许“首条用户消息”为当前请求，此时历史事件为空；
        # 当前问题仍作为 REQUIRED 条目构建，不应因无历史而崩溃。
        question_sequence = session.events[-1].seq + 1 if session.events else 1
        # ── 分类(§9.1/§13.2 步骤 6-7):仅 budgeted 系消费四分类语义 ──
        classify_usage: Any | None = None
        code_rule_count = 0
        if strategy is ContextStrategy.BUDGETED:
            serialized, classify_usage, code_rule_count = self._classify_items(serialized)
        items: list[ContextItem] = [
            ContextItem(
                # item id 与 loop.assemble_model_context 对齐,冻结喂入可按 id 命中
                item_id="system-prompt",
                content=common_rules,
                classification=ContextClassification.REQUIRED,
                role=ContextRole.SYSTEM,
                priority=100000,
                sequence=-1000,
                bare=True,
            )
        ]
        items.extend(entry.item for entry in serialized)
        items.append(
            ContextItem(
                item_id="current-question",
                content=session.current_question,
                classification=ContextClassification.REQUIRED,
                role=ContextRole.USER_DATA,
                priority=100000,
                sequence=question_sequence,
                conversation=True,
            )
        )

        reserved = dict(variant.get("reserved_tokens") or {})
        # LLM 摘要器按次记录用量:编译开始前清零,结束后取回(single-summary 之外恒为 0)
        take_usage = getattr(self._builder.summarizer, "take_usage", None)
        if callable(take_usage):
            take_usage()
        build_request = ContextBuildRequest(
            items=tuple(items),
            token_budget=token_budget,
            strategy=strategy,
            owner_id=None,
            # recent-window 由预算主导,条数上限取全部条目(说明 §3.2)
            recent_n=len(items),
            summary_recent_tokens=int(
                reserved.get("recent_session_events") or reserved.get("recent_session_events_max") or 1024
            ),
            summary_max_tokens=int(reserved.get("history_summary_max") or 2560),
        )
        self._prebuild_summary_map(
            items,
            build_request,
            precompressed_item_ids=frozenset(injection.precompressed_item_ids),
        )
        started = time.perf_counter()
        built = self._builder.build(build_request)
        duration_ms = round((time.perf_counter() - started) * 1000)

        event_ids_by_item = {entry.item.item_id: list(entry.event_ids) for entry in serialized}
        kept: list[str] = []
        compressed: list[str] = []
        referenced: list[str] = []
        omitted: list[str] = []
        for decision in built.report.decisions:
            ids = event_ids_by_item.get(decision.item_id, [])
            action = decision.action.value
            if not ids:
                continue  # 公共规则/当前问题等非事件条目不进入事件桶
            if action == "kept":
                kept.extend(ids)
            elif action == "compressed":
                compressed.extend(ids)
            elif action == "referenced":
                referenced.extend(ids)
            else:  # omitted / isolated(跨用户隔离按省略计)
                omitted.extend(ids)

        metrics, usage_warnings = self._collect_metrics(build_metrics, take_usage)
        payload_messages = [{"role": message.role, "content": message.content} for message in built.messages]
        # v2 评分启用时,strategy_version 升级为评分版本,保证受控对照口径可辨
        strategy_version = str(variant.get("strategy_version") or strategy.value)
        if built.report.scoring_version:
            strategy_version = built.report.scoring_version
        compiled_hash = canonical_json_hash(
            {
                "case_id": session.session_id,
                "case_version": session.session_version,
                "source_session_hash": session.source_hash,
                "variant_id": variant_id,
                "strategy_version": strategy_version,
                "token_budget": token_budget,
                "messages": payload_messages,
                "kept_event_ids": kept,
                "compressed_event_ids": compressed,
                "referenced_event_ids": referenced,
                "omitted_event_ids": omitted,
            }
        )
        warnings = list(built.report.warnings)
        warnings.extend(injection.warnings)
        warnings.extend(f"summary: {row}" for row in usage_warnings)
        if classify_usage is not None:
            warnings.extend(_classification_warnings(classify_usage, code_rule_count))
        warnings.append(f"algo_version={STRUCTURED_TEXT_ALGO_VERSION}")
        if self.tokenizer_version == TIKTOKEN_TOKENIZER_VERSION:
            warnings.append("tokenizer=cl100k_base 为 OpenAI 词表近似口径(非 Qwen 词表),跨口径数据不可直接比较")
        elif self.tokenizer_version == QWEN_TIKTOKEN_VERSION:
            warnings.append(
                "tokenizer=qwen 官方词表精确口径(与模型实际切分高度一致;若模型带扩展词表略有偏差),"
                "跨口径数据不可直接比较"
            )
        classification_stats: dict[str, int] = {}
        if strategy is ContextStrategy.BUDGETED:
            for entry in serialized:
                category = entry.item.classification.value
                classification_stats[category] = classification_stats.get(category, 0) + 1
            classification_stats["code_rules"] = code_rule_count
            classification_stats["llm_assist"] = len(classify_usage.decisions) if classify_usage else 0
        return CompiledContext(
            classification_source=_classification_source(classify_usage),
            classification_stats=classification_stats,
            classify_model_calls=classify_usage.model_calls if classify_usage else 0,
            classify_input_tokens=classify_usage.input_tokens if classify_usage else 0,
            classify_output_tokens=classify_usage.output_tokens if classify_usage else 0,
            classify_truncated=classify_usage.truncated if classify_usage else False,
            case_id=session.session_id,
            case_version=session.session_version,
            source_session_hash=session.source_hash,
            variant_id=variant_id,
            strategy_version=strategy_version,
            token_budget=token_budget,
            compiled_messages=built.messages,
            compiled_context_hash=compiled_hash,
            input_event_ids=session.event_ids,
            kept_event_ids=tuple(kept),
            compressed_event_ids=tuple(compressed),
            referenced_event_ids=tuple(referenced),
            omitted_event_ids=tuple(omitted),
            original_tokens=built.report.original_tokens,
            working_tokens=built.report.working_tokens,
            build_duration_ms=duration_ms,
            build_model_calls=metrics.model_calls,
            build_input_tokens=metrics.input_tokens,
            build_output_tokens=metrics.output_tokens,
            build_cost=metrics.cost,
            build_cache_hits=metrics.cache_hits,
            build_purpose=metrics.purpose,
            build_summary_chunks=metrics.batch_chunks,
            warnings=tuple(warnings),
            strategy=strategy.value,
            required_retained=built.report.required_retained,
            budget_fit=built.report.budget_fit,
            tokenizer_version=self.tokenizer_version,
            scores=tuple(built.report.scores),
            scoring_version=built.report.scoring_version,
            build_result=built,
            memory_segment_ids=tuple(injection.injected_segment_ids),
            segment_cache_hits=segment_usage.cache_hits if segment_usage is not None else 0,
            segment_generated=segment_usage.generated if segment_usage is not None else 0,
            segment_invalidated=segment_usage.invalidated if segment_usage is not None else 0,
        )

    def _classify_items(
        self,
        serialized: tuple[SerializedItem, ...],
    ) -> tuple[tuple[SerializedItem, ...], Any, int]:
        """budgeted 系条目分类(§9.1/§13.2 步骤 6-7):代码预规则 + LLM 辅助。

        - 代码预规则(语义可确定):已取代(同来源存在更新版本)→ distractor;
        - 其余条目属"语义不明确的候选",装配分类器时批量一次 LLM 判四分类
          (失败/超限/关闭 → 回退 COMPRESSIBLE,即既有行为);
        - Segment 合成条目(memory-segment:*)已是摘要,跳过 LLM 分类。

        返回 (新 serialized, 分类用量或 None, 代码预规则条数)。
        """

        import dataclasses

        items = [entry.item for entry in serialized]
        code_rule_ids: set[str] = set()
        replaced: dict[str, Any] = {}
        for item in items:
            if item.superseded and item.classification is not ContextClassification.DISTRACTOR:
                replaced[item.item_id] = dataclasses.replace(
                    item, classification=ContextClassification.DISTRACTOR
                )
                code_rule_ids.add(item.item_id)

        candidates: list[tuple[str, str, str]] = []
        for item in items:
            if item.item_id in replaced or item.item_id.startswith("memory-segment:"):
                continue
            role = "assistant" if item.role == ContextRole.ASSISTANT else (
                "tool" if item.role == ContextRole.UNTRUSTED_DATA else "user"
            )
            candidates.append((item.item_id, role, item.content))

        usage = None
        if self._classifier is not None and candidates:
            usage = self._classifier.classify(candidates)
            for item_id, (category, _reason) in usage.decisions.items():
                mapping = ContextClassification(category)
                base = next((row.item for row in serialized if row.item.item_id == item_id), None)
                if base is None or base.classification is mapping:
                    continue
                replaced[item_id] = dataclasses.replace(base, classification=mapping)
        # 无候选时不调用 LLM,usage 保持 None(纯代码规则口径)

        if not replaced:
            return serialized, usage, 0
        new_serialized = tuple(
            SerializedItem(item=replaced.get(entry.item.item_id, entry.item), event_ids=entry.event_ids)
            for entry in serialized
        )
        return new_serialized, usage, len(code_rule_ids)

    def _prebuild_summary_map(
        self,
        items: list[ContextItem],
        request: ContextBuildRequest,
        *,
        precompressed_item_ids: frozenset[str] = frozenset(),
    ) -> None:
        """生成式压缩预处理:先按预算收窄候选,再批量生成冻结摘要。

        只在压缩器是 SummarizerCompressor 且摘要器支持批量分块
        (``summarize_batch``)时启用。过去这里会把全部 COMPRESSIBLE
        条目先发给 LLM,再由 ContextBuilder 丢弃未入预算的条目；长 Session
        因而会为最终不用的内容付费。现在先执行与 budgeted v1 同口径的
        确定性预算预选,只为可能采用 compressed 表示的条目生成摘要。

        注入的历史 Segment 条目(``precompressed_item_ids``)本身已是
        摘要,不得再进入 LLM 候选;即使剩余候选为空也把压缩器置为
        「冻结映射已设置」状态,避免逐条摘要路径对 Segment 二次调用 LLM。
        Segment 超出最终预算时只允许确定性结构化收缩或引用。

        最终是否采用仍由 ContextBuilder 依据真实摘要长度复核；预选只是
        LLM 调用上界,不会提升条目分类或绕过 REQUIRED/owner 安全规则。
        """
        compressor = getattr(self._builder, "_compressor", None)
        summarizer = self._builder.summarizer
        if type(compressor).__name__ != "SummarizerCompressor":
            return
        summarize_batch = getattr(summarizer, "summarize_batch", None)
        set_map = getattr(compressor, "set_summary_map", None)
        if not callable(summarize_batch) or not callable(set_map):
            return
        selected = [
            row
            for row in self._select_summary_candidates(items, request)
            if row[0].item_id not in precompressed_item_ids
        ]
        if selected:
            entries = [(item.item_id, item.content.strip()) for item, _target in selected]
            targets = [target for _item, target in selected]
            target = max(min(targets), 1)
            mapping = summarize_batch(entries, max_tokens_per_item=target, counter=self._counter)
            set_map({item_id: text for item_id, text in mapping.items() if text.strip()})
        elif precompressed_item_ids:
            # 冻结映射已设置(空映射):Segment 条目若超预算只走结构化收缩
            set_map({})

    def _select_summary_candidates(
        self,
        items: list[ContextItem],
        request: ContextBuildRequest,
    ) -> list[tuple[ContextItem, int]]:
        """确定性估算 budgeted 可接纳的压缩条目,不调用摘要器。

        REQUIRED 先占预算；候选按 ContextBuilder v1 的 priority/sequence/id
        顺序处理。REFERENCE_ONLY 只占引用预算且不需要 LLM。可压缩条目按
        fair-share 估算表示长度；估算放不下的条目不会进入摘要批次。
        """

        render = self._builder._render
        reference = self._builder._reference
        required = [item for item in items if item.classification is ContextClassification.REQUIRED]
        required_tokens = sum(self._counter.count(render(item, item.content)) for item in required)
        remaining = max(0, request.token_budget - required_tokens)
        candidates = [
            item
            for item in items
            if item.classification in {ContextClassification.COMPRESSIBLE, ContextClassification.REFERENCE_ONLY}
        ]
        candidates.sort(key=lambda item: (-item.priority, item.sequence, item.item_id))
        selected: list[tuple[ContextItem, int]] = []
        for index, item in enumerate(candidates):
            if remaining <= 0:
                break
            original_rendered = render(item, item.content)
            original_tokens = self._counter.count(original_rendered)
            if item.classification is ContextClassification.REFERENCE_ONLY:
                referenced = render(item, reference(item, original_tokens))
                referenced_tokens = self._counter.count(referenced)
                if referenced_tokens <= remaining:
                    remaining -= referenced_tokens
                continue
            remaining_candidates = max(1, len(candidates) - index)
            fair_share = max(request.minimum_compressed_tokens, remaining // remaining_candidates)
            header_tokens = self._counter.count(render(item, ""))
            target = min(
                original_tokens,
                max(
                    request.minimum_compressed_tokens,
                    int(original_tokens * request.compression_ratio),
                ),
                max(0, fair_share - header_tokens),
            )
            estimated_tokens = header_tokens + target
            if target > 0 and estimated_tokens <= remaining:
                selected.append((item, target))
                remaining -= estimated_tokens
        return selected

    @staticmethod
    def _collect_metrics(build_metrics: BuildMetrics | None, take_usage: Any) -> tuple[BuildMetrics, list[str]]:
        """优先显式 build_metrics;否则取摘要器自记用量(LLM 摘要降级事件一并入 warnings)。"""

        if build_metrics is not None:
            return build_metrics, []
        if not callable(take_usage):
            return BuildMetrics(), []
        usage = take_usage()
        if usage is None:
            return BuildMetrics(), []
        return (
            BuildMetrics(
                model_calls=usage.model_calls,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cost=usage.cost,
                cache_hits=getattr(usage, "cache_hits", 0),
                purpose=getattr(usage, "purpose", "COMPRESSION"),
                batch_chunks=getattr(usage, "batch_chunks", 0),
            ),
            list(getattr(usage, "warnings", []) or []),
        )


def _classification_source(usage: Any | None) -> str:
    if usage is None:
        return "code_rules_only"
    if usage.decisions:
        return "llm_assist"
    if usage.error_code:
        return "llm_failed_fallback"
    return "code_rules_only"


def _classification_warnings(usage: Any, code_rule_count: int) -> list[str]:
    """分类辅助的告警(进工件 warnings;不改变构建结论)。"""

    rows: list[str] = []
    if code_rule_count:
        rows.append(f"classify: 代码预规则判 interruptions/已取代 {code_rule_count} 条为 distractor")
    if usage.error_code:
        rows.append(f"classify: LLM 辅助分类不可用({usage.error_code}),已回退代码默认分类(全部可压缩)")
    elif usage.truncated:
        rows.append("classify: 条目数超出输入预算,截断部分按代码默认分类(可压缩)")
    return rows
