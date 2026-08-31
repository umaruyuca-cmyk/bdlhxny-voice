"""版本化运行配置快照(RunConfig,混合路线阶段 A1)。

一次 Agent 运行的全部可变条件的不可变快照:

- ``execution_engine`` 固定 ``native-tool-calling``(统一 AgentLoop 底座);
- ``tool_delivery`` 支持 ``all/search``(正式工具提供方式实验);
- 请求值(``*_requested``)来自模板与允许的高级设置;生效值(``*_effective``)
  由模型适配器确认后回填——模型不支持某参数时 ``effective`` 写 ``None``
  并在 ``unsupported_reasons`` 记录普通语言原因,不能静默忽略后冒充生效;
- ``repeat_count`` 属于批次计划,不进入本配置,也不与 ``max_agent_steps`` 混用;
- 规范化序列化(键排序 + 稳定数组规则 + 紧凑 JSON)计算 SHA-256 得到
  ``config_hash``;工具排除项按稳定工具名排序后进入哈希,
  工具实际 Schema 另经 ``catalog_schema_hash`` 计算目录哈希。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

RUN_CONFIG_VERSION = 2

#: 统一循环实现(原生 Tool Calling AgentLoop)。
EXECUTION_ENGINE_NATIVE_TOOL_CALLING = "native-tool-calling"

EXECUTION_ENGINE_VALUES = (EXECUTION_ENGINE_NATIVE_TOOL_CALLING,)

TOOL_DELIVERY_ALL = "all"
TOOL_DELIVERY_SEARCH = "search"
TOOL_DELIVERY_VALUES = (TOOL_DELIVERY_ALL, TOOL_DELIVERY_SEARCH)

GOVERNANCE_OFF = "off"
GOVERNANCE_STANDARD = "standard"
GOVERNANCE_VALUES = (GOVERNANCE_OFF, GOVERNANCE_STANDARD)

#: 标准工具选择实验的固定 tool_choice(不允许点名强制调用)。
TOOL_CHOICE_AUTO = "auto"


class RunConfigError(ValueError):
    """运行配置本身不合法(枚举值、非法组合等)。"""


class FixedConditionViolation(RuntimeError):
    """同一正式批次中非自变量字段不一致;执行前失败,不生成结果后警告。"""


@dataclass(frozen=True)
class ModelParams:
    """模型参数的请求值/生效值对;生效值由适配器确认(阶段 A2)。"""

    provider: str = "configured-provider"
    model_id: str = "configured-model"
    temperature_requested: float | None = 0.1
    temperature_effective: float | None = None
    top_p_requested: float | None = None
    top_p_effective: float | None = None
    reasoning_effort_requested: str | None = None
    reasoning_effort_effective: str | None = None
    seed_requested: int | None = None
    seed_effective: int | None = None
    max_output_tokens: int = 1200
    tool_choice: str = TOOL_CHOICE_AUTO
    parallel_tool_calls: bool = False
    unsupported_reasons: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model_id": self.model_id,
            "temperature_requested": self.temperature_requested,
            "temperature_effective": self.temperature_effective,
            "top_p_requested": self.top_p_requested,
            "top_p_effective": self.top_p_effective,
            "reasoning_effort_requested": self.reasoning_effort_requested,
            "reasoning_effort_effective": self.reasoning_effort_effective,
            "seed_requested": self.seed_requested,
            "seed_effective": self.seed_effective,
            "max_output_tokens": self.max_output_tokens,
            "tool_choice": self.tool_choice,
            "parallel_tool_calls": self.parallel_tool_calls,
            # 语义上是集合:稳定排序后进哈希
            "unsupported_reasons": sorted(self.unsupported_reasons),
        }


@dataclass(frozen=True)
class LimitsConfig:
    """单次 Agent 运行的硬限制(与批次重复次数无关)。"""

    max_agent_steps: int = 4
    max_tool_calls: int = 6
    max_calls_per_tool: int = 2
    agent_timeout_seconds: int = 60
    tool_timeout_seconds: int = 10
    llm_retry_count: int = 1
    tool_retry_count: int = 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "max_agent_steps": self.max_agent_steps,
            "max_tool_calls": self.max_tool_calls,
            "max_calls_per_tool": self.max_calls_per_tool,
            "agent_timeout_seconds": self.agent_timeout_seconds,
            "tool_timeout_seconds": self.tool_timeout_seconds,
            "llm_retry_count": self.llm_retry_count,
            "tool_retry_count": self.tool_retry_count,
        }


@dataclass(frozen=True)
class ToolsConfig:
    """工具提供方式相关条件;目录 Schema 哈希单独计算,不进 config_hash。"""

    catalog_version: str = "mock-tools-v1"
    excluded_tools: tuple[str, ...] = ()
    search_top_k: int | None = None
    search_threshold: float | None = None
    schema_detail: str = "full"

    def to_payload(self) -> dict[str, Any]:
        # 排除项按稳定工具名排序后进入哈希(集合语义)
        return {
            "catalog_version": self.catalog_version,
            "excluded_tools": sorted(self.excluded_tools),
            "search_top_k": self.search_top_k,
            "search_threshold": self.search_threshold,
            "schema_detail": self.schema_detail,
        }


@dataclass(frozen=True)
class ContextParams:
    """上下文构建参数(策略值在 RunConfig.context_strategy 顶层字段)。"""

    token_budget: int = 8192
    recent_turn_count: int | None = None
    compression_target_tokens: int | None = None
    current_turn_reserved_tokens: int = 1024
    tokenizer_version: str = "configured-tokenizer"

    def to_payload(self) -> dict[str, Any]:
        return {
            "token_budget": self.token_budget,
            "recent_turn_count": self.recent_turn_count,
            "compression_target_tokens": self.compression_target_tokens,
            "current_turn_reserved_tokens": self.current_turn_reserved_tokens,
            "tokenizer_version": self.tokenizer_version,
        }


@dataclass(frozen=True)
class RunConfig:
    """一次运行的完整配置快照;不可变,序列化即哈希输入。"""

    execution_engine: str = EXECUTION_ENGINE_NATIVE_TOOL_CALLING
    tool_delivery: str = TOOL_DELIVERY_ALL
    governance_profile: str = GOVERNANCE_STANDARD
    context_strategy: str = "full"
    model: ModelParams = field(default_factory=ModelParams)
    limits: LimitsConfig = field(default_factory=LimitsConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    context: ContextParams = field(default_factory=ContextParams)
    fixture_version: str = "fixture-v1"
    prompt_version: str = "agent-prompt-v1"
    judge_version: str = "judge-v1"
    config_version: int = RUN_CONFIG_VERSION

    def to_payload(self) -> dict[str, Any]:
        return {
            "config_version": self.config_version,
            "execution_engine": self.execution_engine,
            "tool_delivery": self.tool_delivery,
            "governance_profile": self.governance_profile,
            "context_strategy": self.context_strategy,
            "model": self.model.to_payload(),
            "limits": self.limits.to_payload(),
            "tools": self.tools.to_payload(),
            "context": self.context.to_payload(),
            "fixture_version": self.fixture_version,
            "prompt_version": self.prompt_version,
            "judge_version": self.judge_version,
        }

    def canonical_json(self) -> str:
        """键排序 + 紧凑分隔;数组稳定性由各 to_payload 的排序规则保证。"""
        return json.dumps(self.to_payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @property
    def config_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def validate(self) -> None:
        """枚举与组合合法性(与模板无关的结构校验)。"""
        if self.execution_engine not in EXECUTION_ENGINE_VALUES:
            raise RunConfigError(
                f"execution_engine 只能是 {list(EXECUTION_ENGINE_VALUES)},收到 {self.execution_engine!r}"
            )
        if self.tool_delivery not in TOOL_DELIVERY_VALUES:
            raise RunConfigError(f"tool_delivery 只能是 {list(TOOL_DELIVERY_VALUES)},收到 {self.tool_delivery!r}")
        if self.governance_profile not in GOVERNANCE_VALUES:
            raise RunConfigError(
                f"governance_profile 只能是 {list(GOVERNANCE_VALUES)},收到 {self.governance_profile!r}"
            )
        if self.limits.max_agent_steps <= 0 or self.limits.max_tool_calls < 0:
            raise RunConfigError("limits.max_agent_steps 必须 > 0 且 max_tool_calls >= 0")
        if self.model.tool_choice != TOOL_CHOICE_AUTO:
            raise RunConfigError(f"工具选择实验 tool_choice 固定为 {TOOL_CHOICE_AUTO!r}")

    def validate_for_formal_template(self) -> None:
        """新正式单变量模板的额外边界。"""
        self.validate()

    def with_overrides(self, overrides: Mapping[str, Any]) -> RunConfig:
        """按点分路径覆盖字段(模板变体生成用);未知路径拒绝。"""
        flat = self.to_payload_flat()
        for path, value in overrides.items():
            if path not in flat:
                raise RunConfigError(f"覆盖路径 {path!r} 不存在于 RunConfig")
            flat[path] = value
        return self.from_flat(flat)

    # ---- 扁平化读/建(模板变体与一致性校验共用同一真源) ----

    def to_payload_flat(self) -> dict[str, Any]:
        """点分路径扁平化(payload 键与嵌套结构一致)。"""
        flat: dict[str, Any] = {}

        def walk(prefix: str, node: Any) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    walk(f"{prefix}.{key}" if prefix else str(key), value)
            else:
                flat[prefix] = node

        walk("", self.to_payload())
        return flat

    @classmethod
    def from_flat(cls, flat: Mapping[str, Any]) -> RunConfig:
        """从扁平字典重建(路径必须与 to_payload_flat 完全一致)。"""
        nested: dict[str, Any] = {}

        def insert(path: str, value: Any) -> None:
            parts = path.split(".")
            node = nested
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = value

        for path, value in flat.items():
            insert(str(path), value)
        if set(nested) != set(cls().to_payload()):
            raise RunConfigError(f"扁平字段重建失败:未知或缺失的顶层段 {sorted(set(nested))}")
        return cls(
            execution_engine=str(nested["execution_engine"]),
            tool_delivery=str(nested["tool_delivery"]),
            governance_profile=str(nested["governance_profile"]),
            context_strategy=str(nested["context_strategy"]),
            model=ModelParams(
                provider=str(nested["model"]["provider"]),
                model_id=str(nested["model"]["model_id"]),
                temperature_requested=nested["model"]["temperature_requested"],
                temperature_effective=nested["model"]["temperature_effective"],
                top_p_requested=nested["model"]["top_p_requested"],
                top_p_effective=nested["model"]["top_p_effective"],
                reasoning_effort_requested=nested["model"]["reasoning_effort_requested"],
                reasoning_effort_effective=nested["model"]["reasoning_effort_effective"],
                seed_requested=nested["model"]["seed_requested"],
                seed_effective=nested["model"]["seed_effective"],
                max_output_tokens=int(nested["model"]["max_output_tokens"]),
                tool_choice=str(nested["model"]["tool_choice"]),
                parallel_tool_calls=bool(nested["model"]["parallel_tool_calls"]),
                unsupported_reasons=tuple(nested["model"]["unsupported_reasons"]),
            ),
            limits=LimitsConfig(**{k: int(v) for k, v in nested["limits"].items()}),
            tools=ToolsConfig(
                catalog_version=str(nested["tools"]["catalog_version"]),
                excluded_tools=tuple(nested["tools"]["excluded_tools"]),
                search_top_k=nested["tools"]["search_top_k"],
                search_threshold=nested["tools"]["search_threshold"],
                schema_detail=str(nested["tools"]["schema_detail"]),
            ),
            context=ContextParams(
                token_budget=int(nested["context"]["token_budget"]),
                recent_turn_count=nested["context"]["recent_turn_count"],
                compression_target_tokens=nested["context"]["compression_target_tokens"],
                current_turn_reserved_tokens=int(nested["context"]["current_turn_reserved_tokens"]),
                tokenizer_version=str(nested["context"]["tokenizer_version"]),
            ),
            fixture_version=str(nested["fixture_version"]),
            prompt_version=str(nested["prompt_version"]),
            judge_version=str(nested["judge_version"]),
            config_version=int(nested["config_version"]),
        )

    def config_payload_with_hash(self) -> dict[str, Any]:
        """公开/工件形态:配置体 + config_hash。"""
        return {**self.to_payload(), "config_hash": self.config_hash}


# ── 模型能力确认(阶段 A2 的配置侧;能力描述本体在 infra.llm) ────────────────


def confirm_model_params(requested: ModelParams, capability: Any) -> ModelParams:
    """按适配器能力确认生效值:不支持的参数 effective=None 并记录原因。

    仅仅从环境变量复制到 effective 不算生效确认;只有适配器声明
    「支持该参数且实际传给 SDK」时,请求值才被确认为生效值。
    """
    reasons: list[str] = []

    def confirm(name: str, value: Any, supported: bool, adapter_note: str) -> Any:
        if value is None:
            return None
        if not supported:
            reasons.append(f"{name}: {adapter_note}")
            return None
        return value

    temperature = confirm(
        "temperature",
        requested.temperature_requested,
        capability.supports_temperature,
        capability.temperature_note,
    )
    top_p = confirm(
        "top_p",
        requested.top_p_requested,
        capability.supports_top_p,
        capability.top_p_note,
    )
    reasoning_effort = confirm(
        "reasoning_effort",
        requested.reasoning_effort_requested,
        capability.supports_reasoning_effort,
        capability.reasoning_effort_note,
    )
    seed = confirm(
        "seed",
        requested.seed_requested,
        capability.supports_seed,
        capability.seed_note,
    )
    parallel = bool(requested.parallel_tool_calls) and capability.supports_parallel_tool_calls
    if requested.parallel_tool_calls and not capability.supports_parallel_tool_calls:
        reasons.append(f"parallel_tool_calls: {capability.parallel_tool_calls_note}")
    return replace(
        requested,
        temperature_effective=temperature,
        top_p_effective=top_p,
        reasoning_effort_effective=reasoning_effort,
        seed_effective=seed,
        parallel_tool_calls=parallel,
        unsupported_reasons=tuple(reasons),
    )


# ── 批次一致性(阶段 A3:非自变量字段不一致 → 执行前失败) ─────────────────────


def assert_single_variable(
    configs: Sequence[RunConfig],
    *,
    variable_paths: Sequence[str],
    label: str = "批次",
) -> None:
    """同一正式批次中,各 RunConfig 只允许在 ``variable_paths`` 上不同。

    比较基于规范化序列化(与 config_hash 同一真源),键顺序不影响结果。
    违规抛 :class:`FixedConditionViolation`,运行计划在执行前失败。
    """
    if not configs:
        return
    paths = tuple(variable_paths)
    baselines: list[str] = []
    for config in configs:
        flat = config.to_payload_flat()
        for path in paths:
            flat.pop(path, None)
        baselines.append(json.dumps(flat, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    first = baselines[0]
    for position, payload in enumerate(baselines[1:], start=1):
        if payload != first:
            differing = _differing_paths(configs[0], configs[position], skip=paths)
            raise FixedConditionViolation(
                f"{label}存在非自变量字段不一致({differing});"
                f"本批次唯一自变量是 {list(paths)},固定条件被变体覆盖,执行前失败"
            )


def _differing_paths(left: RunConfig, right: RunConfig, *, skip: Sequence[str]) -> list[str]:
    flat_left = left.to_payload_flat()
    flat_right = right.to_payload_flat()
    skip_set = set(skip)
    return sorted(key for key in flat_left if key not in skip_set and flat_left.get(key) != flat_right.get(key))


def assert_temperature_top_p_isolation(variable_paths: Sequence[str]) -> None:
    """温度与 top_p 不能在同一个正式实验中同时变化。"""
    varies_temperature = any("model.temperature" in path for path in variable_paths)
    varies_top_p = any("model.top_p" in path for path in variable_paths)
    if varies_temperature and varies_top_p:
        raise RunConfigError("温度与 top_p 不能在同一个正式实验中同时变化;固定其一")


# ── 工具目录 Schema 哈希(与 config_hash 分开计算) ────────────────────────────


def catalog_schema_hash(manifests: Iterable[Mapping[str, Any]]) -> str:
    """对实际工具 Schema 计算目录哈希:按工具名排序 + 紧凑 JSON + SHA-256。"""
    rows = sorted((dict(row) for row in manifests), key=lambda row: str(row.get("name") or ""))
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def canonical_json_of(payload: Mapping[str, Any]) -> str:
    """fixed_conditions 等批次字段的规范化序列化(与 config_hash 同一规则)。"""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def hash_of(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_of(payload).encode("utf-8")).hexdigest()


__all__ = [
    "EXECUTION_ENGINE_NATIVE_TOOL_CALLING",
    "FixedConditionViolation",
    "GOVERNANCE_OFF",
    "GOVERNANCE_STANDARD",
    "GOVERNANCE_VALUES",
    "LimitsConfig",
    "ModelParams",
    "RunConfig",
    "RunConfigError",
    "RUN_CONFIG_VERSION",
    "TOOL_CHOICE_AUTO",
    "TOOL_DELIVERY_ALL",
    "TOOL_DELIVERY_SEARCH",
    "TOOL_DELIVERY_VALUES",
    "ToolsConfig",
    "assert_single_variable",
    "assert_temperature_top_p_isolation",
    "catalog_schema_hash",
    "canonical_json_of",
    "confirm_model_params",
    "hash_of",
]
