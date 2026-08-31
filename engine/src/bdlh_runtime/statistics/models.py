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

STATISTICS_VERSION = "experiment-stats-v2"

#: ── 样本量结果等级(方案 13.9):按每变体有效样本数诚实分级, ──────────────
#: 不把单次观察的成功率 0%/100% 描述为稳定结论
SAMPLE_LEVEL_NONE = "no-data"  # 0:无数据,不计算结论
SAMPLE_LEVEL_SINGLE = "single-observation"  # 1:单次观察,只展示原始结果
SAMPLE_LEVEL_TREND = "preliminary-trend"  # 2:初步趋势,明确样本不足
SAMPLE_LEVEL_OBSERVATION = "observed-compat"  # 兼容口径:样本量达标但未冻结预期配置哈希
SAMPLE_LEVEL_FORMAL = "formal-minimum"  # ≥ formal_min_repeat_count:最小正式样本
SAMPLE_LEVEL_EXTENDED = "extended"  # ≥ extended_threshold:扩展样本

SAMPLE_LEVEL_LABELS: dict[str, str] = {
    SAMPLE_LEVEL_NONE: "无数据",
    SAMPLE_LEVEL_SINGLE: "单次观察",
    SAMPLE_LEVEL_TREND: "初步趋势",
    SAMPLE_LEVEL_OBSERVATION: "观察结果(兼容口径)",
    SAMPLE_LEVEL_FORMAL: "最小正式样本",
    SAMPLE_LEVEL_EXTENDED: "扩展样本",
}

#: 等级序(用于overall取各变体最低等级);值越大表示证据越强
SAMPLE_LEVEL_RANK: dict[str, int] = {
    SAMPLE_LEVEL_NONE: 0,
    SAMPLE_LEVEL_SINGLE: 1,
    SAMPLE_LEVEL_TREND: 2,
    SAMPLE_LEVEL_OBSERVATION: 3,
    SAMPLE_LEVEL_FORMAL: 4,
    SAMPLE_LEVEL_EXTENDED: 5,
}


def extended_threshold_for(formal_min_repeat_count: int) -> int:
    """扩展样本门槛:max(formal_min + 2, 5);模板可显式冻结,统计模块不写死。"""
    return max(int(formal_min_repeat_count) + 2, 5)


def sample_level_for(valid_samples: int, formal_min_repeat_count: int = 3) -> dict[str, str]:
    """有效样本数 → 结果等级;分级尊重模板冻结的正式最小样本门槛。

    0 → no-data;1 且 formal_min>1 → single-observation;
    ≥ extended_threshold → extended;≥ formal_min → formal-minimum;
    2..formal_min-1 → preliminary-trend。formal_min=1 时 1 个样本即正式。
    """
    formal_min = max(int(formal_min_repeat_count or 1), 1)
    if valid_samples <= 0:
        level = SAMPLE_LEVEL_NONE
    elif valid_samples == 1 and formal_min > 1:
        level = SAMPLE_LEVEL_SINGLE
    elif valid_samples >= extended_threshold_for(formal_min):
        level = SAMPLE_LEVEL_EXTENDED
    elif valid_samples >= formal_min:
        level = SAMPLE_LEVEL_FORMAL
    else:
        level = SAMPLE_LEVEL_TREND
    return {"level": level, "label": SAMPLE_LEVEL_LABELS[level]}


#: ── 排除原因(进入 excluded_runs,与方案 13.7 示例对齐) ───────────────────
EXCLUDE_MISSING_FIELDS = "MISSING_FIELDS"  # 缺 run_id / variant_label,无法归位
EXCLUDE_DUPLICATE_RUN_ID = "DUPLICATE_RUN_ID"  # 同一 run_id 只统计一次
EXCLUDE_INVALID = "INVALID"  # validity 判定为无效
EXCLUDE_LLM_UNAVAILABLE = "LLM_UNAVAILABLE"  # 无效且错误文本指向模型不可用
EXCLUDE_NO_AGENT_LOOP = "NO_AGENT_LOOP"  # actual_agent_steps=0,未进入模型循环
EXCLUDE_UNKNOWN_VARIANT = "UNKNOWN_VARIANT"  # 运行不属于实验组计划变体
EXCLUDE_EMPTY_CONFIG_HASH = "EMPTY_CONFIG_HASH"  # 正式样本缺少配置哈希
EXCLUDE_CONFIG_MISMATCH = "CONFIG_HASH_MISMATCH"  # 同变体内冻结配置与预期/主导值不一致


@dataclass
class VariantStatistics:
    """单个变体的累计描述性统计(只基于纳入统计的有效运行)。"""

    variant_id: str
    included_run_ids: list[str] = field(default_factory=list)
    included_count: int = 0
    #: 完成登记的物理运行数(done;含执行完成但被判无效的运行)
    completed_count: int = 0
    #: 失败物理运行数(执行未完成;是 excluded_count 的子集)
    failed_count: int = 0
    excluded_count: int = 0
    exclusion_reasons: dict[str, int] = field(default_factory=dict)
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
    #: 本快照使用的正式最小样本门槛(实验组冻结定义;批次口径缺省 3)
    formal_min_repeat_count: int | None = None
    #: 参与本次统计的预期配置哈希(实验组冻结;兼容模式下为空)
    expected_config_hashes: dict[str, str] = field(default_factory=dict)
    #: 配置一致性口径:"expected"(与冻结哈希直接比较) / "observed-dominant"(历史兼容)
    config_hash_mode: str = ""
    generated_at: str = ""
    input_run_count: int = 0
    included_run_count: int = 0
    excluded_run_count: int = 0
    included_run_ids: list[str] = field(default_factory=list)
    excluded_runs: list[dict[str, Any]] = field(default_factory=list)
    #: 输入数据质量提示(如 DUPLICATE_RUN_IDS_DETECTED);进入快照哈希
    data_quality_warnings: list[dict[str, Any]] = field(default_factory=list)
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
