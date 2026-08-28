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
    ContextBuildRequest,
    ContextBuildResult,
    ContextBuilder,
    ContextClassification,
    ContextItem,
    ContextMessage,
    ContextRole,
    ContextStrategy,
    ItemScore,
    MultiFactorScorer,
    HistorySummarizer,
    QWEN_TIKTOKEN_VERSION,
    TokenCounter,
    TIKTOKEN_TOKENIZER_VERSION,
    counter_from_env,
)

from .loader import SessionCase, canonical_json_hash
from .serializer import SerializedItem, serialize_session

#: variants 配置中的 strategy 名 → 构建器策略
STRATEGY_BY_NAME: dict[str, ContextStrategy] = {
    "full": ContextStrategy.FULL,
    "full-session": ContextStrategy.FULL,
    "recent-n": ContextStrategy.RECENT_N,
    "recent-window": ContextStrategy.RECENT_N,
    "single-summary": ContextStrategy.SINGLE_SUMMARY,
    "budgeted": ContextStrategy.BUDGETED,
    "budgeted-session": ContextStrategy.BUDGETED,
}

#: budgeted 早期实现的算法版本号(与 run_telemetry 的 structured-text-v1 对齐)
STRUCTURED_TEXT_ALGO_VERSION = "structured-text-v1"


@dataclass(frozen=True)
class BuildMetrics:
    """摘要/压缩构建本身的成本(single-summary 模型摘要时由调用方填入)。"""

    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0


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
    #: 底层构建结果(冻结喂入用;不进入机器可读工件)
    build_result: ContextBuildResult | None = None

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
                {"role": message.role, "content": message.content}
                for message in self.compiled_messages
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
            "warnings": list(self.warnings),
            "required_retained": self.required_retained,
            "budget_fit": self.budget_fit,
            "tokenizer_version": self.tokenizer_version,
            "scores": [_score_payload(row) for row in self.scores],
            "scoring_version": self.scoring_version,
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

    @classmethod
    def from_env(cls, *, llm_summary: bool = False) -> "SessionCompiler":
        """按环境变量装配:BUDGETED_SCORING(v2 评分)、LLM_SUMMARY(LLM 摘要)。

        未设置的开关保持既有基准行为(v1 排序、抽取式摘要),
        保证 v1/v2、抽取式/LLM 摘要可做受控对照。
        LLM 摘要默认启用「生成一次后冻结」缓存(engine/var/cache/),
        ``LLM_SUMMARY_FREEZE=0`` 关闭。
        """

        from bdlh_runtime.context import scorer_from_env

        summarizer = None
        if llm_summary:
            from .llm_summary import LLMSummarizer

            summarizer = LLMSummarizer(
                cache_path=(Path(__file__).resolve().parents[3] / "var" / "cache" / "llm-summary.json")
            )
        return cls(scorer=scorer_from_env(), summarizer=summarizer)

    def compile(
        self,
        session: SessionCase,
        variant: dict[str, Any],
        *,
        common_rules: str,
        build_metrics: BuildMetrics | None = None,
    ) -> CompiledContext:
        strategy = STRATEGY_BY_NAME.get(str(variant.get("strategy") or ""))
        if strategy is None:
            raise ValueError(f"未知上下文策略: {variant.get('strategy')!r}")
        variant_id = str(variant["variant_id"])
        token_budget = int(variant["token_budget"])

        serialized: tuple[SerializedItem, ...] = serialize_session(session)
        question_sequence = session.events[-1].seq + 1
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
        started = time.perf_counter()
        built = self._builder.build(
            ContextBuildRequest(
                items=tuple(items),
                token_budget=token_budget,
                strategy=strategy,
                owner_id=None,
                # recent-window 由预算主导,条数上限取全部条目(说明 §3.2)
                recent_n=len(items),
                summary_recent_tokens=int(
                    reserved.get("recent_session_events")
                    or reserved.get("recent_session_events_max")
                    or 1024
                ),
                summary_max_tokens=int(reserved.get("history_summary_max") or 2560),
            )
        )
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
        payload_messages = [
            {"role": message.role, "content": message.content} for message in built.messages
        ]
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
        warnings.extend(f"summary: {row}" for row in usage_warnings)
        warnings.append(f"algo_version={STRUCTURED_TEXT_ALGO_VERSION}")
        if self.tokenizer_version == TIKTOKEN_TOKENIZER_VERSION:
            warnings.append(
                "tokenizer=cl100k_base 为 OpenAI 词表近似口径(非 Qwen 词表),跨口径数据不可直接比较"
            )
        elif self.tokenizer_version == QWEN_TIKTOKEN_VERSION:
            warnings.append(
                "tokenizer=qwen 官方词表精确口径(与模型实际切分高度一致;若模型带扩展词表略有偏差),跨口径数据不可直接比较"
            )
        return CompiledContext(
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
            warnings=tuple(warnings),
            strategy=strategy.value,
            required_retained=built.report.required_retained,
            budget_fit=built.report.budget_fit,
            tokenizer_version=self.tokenizer_version,
            scores=tuple(built.report.scores),
            scoring_version=built.report.scoring_version,
            build_result=built,
        )

    @staticmethod
    def _collect_metrics(
        build_metrics: BuildMetrics | None, take_usage: Any
    ) -> tuple[BuildMetrics, list[str]]:
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
            ),
            list(getattr(usage, "warnings", []) or []),
        )
