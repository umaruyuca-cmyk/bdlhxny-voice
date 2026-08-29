"""统计快照数据模型(P0-7):版本化、可重建、可哈希校验。

原始运行记录是事实真源;统计快照是纯派生数据——同一批输入记录永远
得到同一 ``snapshot_hash``(``generated_at`` 不参与哈希),删除快照后
可从原始 Run 完全重建。本模块保持纯代码:不 import 任何 LLM 相关设施。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

STATISTICS_VERSION = "experiment-stats-v1"

#: ── 样本量结果等级(方案 13.9):按每变体有效样本数诚实分级, ──────────────
#: 不把单次观察的成功率 0%/100% 描述为稳定结论
SAMPLE_LEVEL_NONE = "no-data"  # 0:无数据,不计算结论
SAMPLE_LEVEL_SINGLE = "single-observation"  # 1:单次观察,只展示原始结果
SAMPLE_LEVEL_TREND = "preliminary-trend"  # 2:初步趋势,明确样本不足
SAMPLE_LEVEL_FORMAL = "formal-minimum"  # 3~4:最小正式样本,区间较宽
SAMPLE_LEVEL_EXTENDED = "extended"  # ≥5:扩展样本

SAMPLE_LEVEL_LABELS: dict[str, str] = {
    SAMPLE_LEVEL_NONE: "无数据",
    SAMPLE_LEVEL_SINGLE: "单次观察",
    SAMPLE_LEVEL_TREND: "初步趋势",
    SAMPLE_LEVEL_FORMAL: "最小正式样本",
    SAMPLE_LEVEL_EXTENDED: "扩展样本",
}

#: 等级序(用于overall取各变体最低等级);值越大表示证据越强
SAMPLE_LEVEL_RANK: dict[str, int] = {
    SAMPLE_LEVEL_NONE: 0,
    SAMPLE_LEVEL_SINGLE: 1,
    SAMPLE_LEVEL_TREND: 2,
    SAMPLE_LEVEL_FORMAL: 3,
    SAMPLE_LEVEL_EXTENDED: 4,
}


def sample_level_for(valid_samples: int) -> dict[str, str]:
    """有效样本数 → 结果等级;分级规则固定,不引入任何模型判断。"""
    if valid_samples <= 0:
        level = SAMPLE_LEVEL_NONE
    elif valid_samples == 1:
        level = SAMPLE_LEVEL_SINGLE
    elif valid_samples == 2:
        level = SAMPLE_LEVEL_TREND
    elif valid_samples <= 4:
        level = SAMPLE_LEVEL_FORMAL
    else:
        level = SAMPLE_LEVEL_EXTENDED
    return {"level": level, "label": SAMPLE_LEVEL_LABELS[level]}


#: ── 排除原因(进入 excluded_runs,与方案 13.7 示例对齐) ───────────────────
EXCLUDE_MISSING_FIELDS = "MISSING_FIELDS"  # 缺 run_id / variant_label,无法归位
EXCLUDE_DUPLICATE_RUN_ID = "DUPLICATE_RUN_ID"  # 同一 run_id 只统计一次
EXCLUDE_INVALID = "INVALID"  # validity 判定为无效
EXCLUDE_LLM_UNAVAILABLE = "LLM_UNAVAILABLE"  # 无效且错误文本指向模型不可用
EXCLUDE_NO_AGENT_LOOP = "NO_AGENT_LOOP"  # actual_agent_steps=0,未进入模型循环
EXCLUDE_CONFIG_MISMATCH = "CONFIG_HASH_MISMATCH"  # 同变体内冻结配置与主导值不一致


@dataclass
class VariantStatistics:
    """单个变体的累计描述性统计(只基于纳入统计的有效运行)。"""

    variant_id: str
    included_run_ids: list[str] = field(default_factory=list)
    excluded_count: int = 0
    config_hashes: list[str] = field(default_factory=list)
    actual_agent_steps: dict[str, Any] = field(default_factory=dict)
    duration_ms: dict[str, Any] = field(default_factory=dict)
    tool_calls_per_run: dict[str, Any] = field(default_factory=dict)
    #: 以下三项在运行记录未持久化相应字段时如实缺席(None),不以 0 冒充
    input_tokens: dict[str, Any] | None = None
    output_tokens: dict[str, Any] | None = None
    success_rate: float | None = None
    stop_reasons: dict[str, int] = field(default_factory=dict)
    errors: dict[str, int] = field(default_factory=dict)
    sample_level: dict[str, str] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class StatisticsSnapshot:
    """一次统计重算的版本化快照(方案 13.7 结构)。"""

    series_id: str
    statistics_version: str = STATISTICS_VERSION
    template_id: str = ""
    template_version: int | None = None
    definition_hash: str = ""
    generated_at: str = ""
    included_run_ids: list[str] = field(default_factory=list)
    excluded_runs: list[dict[str, Any]] = field(default_factory=list)
    by_variant: dict[str, dict[str, Any]] = field(default_factory=dict)
    comparison: dict[str, Any] = field(default_factory=dict)
    sample_sufficiency: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    snapshot_hash: str = ""

    def to_payload(self) -> dict[str, Any]:
        return dict(self.__dict__)


def canonical_hash(payload: dict[str, Any]) -> str:
    """对任意 payload 的规范化 JSON 计算 sha256;同一内容永远同一哈希。"""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
