"""生产上下文工作台的构建契约与来源适配器。

P0 第一阶段先接入冻结 Session 只读来源，用同一套状态、轮次和工件协议
验证工作台闭环；生产数据库来源通过相同接口接入，不与固定实验编译职责混合。
历史轮 Segment 复用(``segments``)在同一编排下接入:legacy 不启用,
shadow 只观察,incremental 生成并保存。
"""

from .agent_run import AgentRunResult, LLMAgentRunner, ToolLoopAgentRunner
from .analysis import (
    AnalysisConfigError,
    AnalysisSettings,
    LLMSegmentJudge,
    SegmentJudgeVerdict,
    run_analysis,
)
from .data_store import DataServiceContextBuildStore
from .segments import (
    GENERATION_MODE_EXTRACTIVE,
    GENERATION_MODE_LLM,
    DataServiceMemorySegmentRepository,
    HistoryTurn,
    MemorySegment,
    MemorySegmentManager,
    MemorySegmentRepository,
    MemorySegmentStoreError,
    SegmentConfigError,
    SegmentPreparation,
    SegmentSettings,
    load_turn_summary_system_prompt,
    segment_source_hash,
    split_history_turns,
    split_turns_for_segments,
)
from .service import ContextWorkbenchService
from .sources import DatabaseSessionSource, FrozenSessionSource, SessionSource, ShadowSessionSource, source_for_mode
from .store import (
    ActiveBuildConflict,
    BuildIdempotencyConflict,
    BuildNotFound,
    ContextBuildStore,
    ForbiddenBuild,
)
from .turns import events_with_turns

__all__ = [
    "ActiveBuildConflict",
    "AgentRunResult",
    "AnalysisConfigError",
    "AnalysisSettings",
    "BuildIdempotencyConflict",
    "BuildNotFound",
    "ContextBuildStore",
    "ContextWorkbenchService",
    "DataServiceContextBuildStore",
    "DataServiceMemorySegmentRepository",
    "DatabaseSessionSource",
    "ForbiddenBuild",
    "FrozenSessionSource",
    "GENERATION_MODE_EXTRACTIVE",
    "GENERATION_MODE_LLM",
    "HistoryTurn",
    "LLMAgentRunner",
    "LLMSegmentJudge",
    "MemorySegment",
    "MemorySegmentManager",
    "MemorySegmentRepository",
    "MemorySegmentStoreError",
    "SegmentConfigError",
    "SegmentJudgeVerdict",
    "SegmentPreparation",
    "SegmentSettings",
    "SessionSource",
    "ShadowSessionSource",
    "ToolLoopAgentRunner",
    "events_with_turns",
    "load_turn_summary_system_prompt",
    "run_analysis",
    "segment_source_hash",
    "source_for_mode",
    "split_history_turns",
    "split_turns_for_segments",
]
