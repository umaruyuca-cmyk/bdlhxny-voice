"""实验数据统计模块(P0-7):纯代码、不调 LLM、快照可重建。

职责边界(方案 13.6):
- 只读取已经完成的运行和工件;
- 过滤无效、失败或证据不完整的运行并给出原因;
- 按变体累计描述性统计,输出样本量分级;
- 生成版本化统计快照(snapshot_hash 可校验);
- 不调用 LLM,不生成新的 Agent 运行,不修改原始运行结果。
"""

from bdlh_runtime.statistics.aggregators import build_series_statistics
from bdlh_runtime.statistics.models import (
    EXCLUDE_CONFIG_MISMATCH,
    EXCLUDE_DUPLICATE_RUN_ID,
    EXCLUDE_EMPTY_CONFIG_HASH,
    EXCLUDE_INVALID,
    EXCLUDE_LLM_UNAVAILABLE,
    EXCLUDE_MISSING_FIELDS,
    EXCLUDE_NO_AGENT_LOOP,
    EXCLUDE_UNKNOWN_VARIANT,
    SAMPLE_LEVEL_EXTENDED,
    SAMPLE_LEVEL_FORMAL,
    SAMPLE_LEVEL_LABELS,
    SAMPLE_LEVEL_NONE,
    SAMPLE_LEVEL_RANK,
    SAMPLE_LEVEL_SINGLE,
    SAMPLE_LEVEL_TREND,
    STATISTICS_VERSION,
    StatisticsSnapshot,
    VariantStatistics,
    canonical_hash,
    sample_level_for,
)
from bdlh_runtime.statistics.service import (
    build_snapshot,
    load_snapshot,
    persist_snapshot,
    snapshot_path,
)

__all__ = [
    "STATISTICS_VERSION",
    "SAMPLE_LEVEL_NONE",
    "SAMPLE_LEVEL_SINGLE",
    "SAMPLE_LEVEL_TREND",
    "SAMPLE_LEVEL_FORMAL",
    "SAMPLE_LEVEL_EXTENDED",
    "SAMPLE_LEVEL_LABELS",
    "SAMPLE_LEVEL_RANK",
    "EXCLUDE_MISSING_FIELDS",
    "EXCLUDE_DUPLICATE_RUN_ID",
    "EXCLUDE_INVALID",
    "EXCLUDE_LLM_UNAVAILABLE",
    "EXCLUDE_NO_AGENT_LOOP",
    "EXCLUDE_UNKNOWN_VARIANT",
    "EXCLUDE_EMPTY_CONFIG_HASH",
    "EXCLUDE_CONFIG_MISMATCH",
    "StatisticsSnapshot",
    "VariantStatistics",
    "canonical_hash",
    "sample_level_for",
    "build_series_statistics",
    "build_snapshot",
    "persist_snapshot",
    "load_snapshot",
    "snapshot_path",
]
