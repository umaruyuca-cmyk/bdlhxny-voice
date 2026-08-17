"""M5 新旧路径确定性灰度、发布门禁和回退边界。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from threading import RLock
from typing import Literal

from bdlh_runtime.config import Settings

from .errors import ConfigurationError


class RuntimePath(StrEnum):
    LEGACY = "legacy_root_graph"
    COGNITIVE = "cognitive_finance"


class RolloutMode(StrEnum):
    OFF = "off"
    INTERNAL = "internal"
    PERCENTAGE = "percentage"
    ALL = "all"


@dataclass(frozen=True)
class RolloutGate:
    """经过审批的 M5 代码门禁证明；不代表系统自动完成了人工验收。"""

    approval_ref: str | None = None
    rollout_owner: str | None = None
    rollback_owner: str | None = None
    m0_to_m4_accepted: bool = False
    identity_isolation_passed: bool = False
    guardrails_passed: bool = False
    mock_isolation_passed: bool = False
    comparison_passed: bool = False
    persistence_faults_passed: bool = False
    observability_ready: bool = False
    rollback_drill_passed: bool = False

    def missing_requirements(self) -> tuple[str, ...]:
        missing: list[str] = []
        for name in (
            "m0_to_m4_accepted",
            "identity_isolation_passed",
            "guardrails_passed",
            "mock_isolation_passed",
            "comparison_passed",
            "persistence_faults_passed",
            "observability_ready",
            "rollback_drill_passed",
        ):
            if not getattr(self, name):
                missing.append(name)
        for name in ("approval_ref", "rollout_owner", "rollback_owner"):
            if not str(getattr(self, name) or "").strip():
                missing.append(name)
        return tuple(missing)


@dataclass(frozen=True)
class RolloutConfig:
    mode: RolloutMode = RolloutMode.OFF
    percentage: int = 0
    internal_user_ids: frozenset[str] = frozenset()
    gate: RolloutGate = field(default_factory=RolloutGate)

    def __post_init__(self) -> None:
        if not 0 <= self.percentage <= 100:
            raise ValueError("rollout percentage must be between 0 and 100")
        if self.mode == RolloutMode.PERCENTAGE and self.percentage <= 0:
            raise ValueError("percentage rollout requires percentage > 0")
        if self.mode == RolloutMode.INTERNAL and not self.internal_user_ids:
            raise ValueError("internal rollout requires at least one internal user")


@dataclass(frozen=True)
class RoutingDecision:
    path: RuntimePath
    reason_code: str
    bucket: int | None = None


class CognitiveTrafficRouter:
    """以用户+会话稳定分桶；配置无效或门禁未通过时 fail-closed 到旧路径。"""

    def __init__(self, config: RolloutConfig) -> None:
        self.config = config

    def decide(self, *, user_id: str | None, session_id: str) -> RoutingDecision:
        if self.config.mode == RolloutMode.OFF:
            return RoutingDecision(RuntimePath.LEGACY, "ROLLOUT_OFF")
        if user_id is None:
            return RoutingDecision(RuntimePath.LEGACY, "AUTHENTICATED_USER_REQUIRED")
        missing = self.config.gate.missing_requirements()
        if missing:
            return RoutingDecision(RuntimePath.LEGACY, "ROLLOUT_GATE_BLOCKED")
        normalized_user = str(user_id or "__anonymous__")
        if self.config.mode == RolloutMode.INTERNAL:
            selected = normalized_user in self.config.internal_user_ids
            return RoutingDecision(
                RuntimePath.COGNITIVE if selected else RuntimePath.LEGACY,
                "INTERNAL_USER_SELECTED" if selected else "NOT_INTERNAL_USER",
            )
        if self.config.mode == RolloutMode.ALL:
            return RoutingDecision(RuntimePath.COGNITIVE, "ROLLOUT_ALL")
        bucket = _stable_bucket(normalized_user, session_id)
        selected = bucket < self.config.percentage
        return RoutingDecision(
            RuntimePath.COGNITIVE if selected else RuntimePath.LEGACY,
            "PERCENTAGE_SELECTED" if selected else "PERCENTAGE_NOT_SELECTED",
            bucket=bucket,
        )


@dataclass
class CognitiveExecutionProgress:
    """新路径副作用边界；Domain Request 发出后禁止自动旧路径重跑。"""

    domain_request_started: bool = False
    external_capability_started: bool = False
    persistence_write_started: bool = False

    @property
    def automatic_fallback_allowed(self) -> bool:
        return not (
            self.domain_request_started
            or self.external_capability_started
            or self.persistence_write_started
        )


class RolloutMetrics:
    """进程内计数器只用于开发与指标适配；不作为生产审计存储。"""

    def __init__(self) -> None:
        self._counts: Counter[tuple[str, str]] = Counter()
        self._lock = RLock()

    def increment(self, metric: str, *, path: RuntimePath) -> None:
        with self._lock:
            self._counts[(metric, path.value)] += 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                f"{metric}:{path}": count
                for (metric, path), count in sorted(self._counts.items())
            }


@dataclass(frozen=True)
class RollbackDecision:
    rollback_required: bool
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RolloutHealthPolicy:
    """M5 自动回滚告警阈值；实际切换仍由配置控制面执行。"""

    minimum_cognitive_runs: int = 20
    maximum_error_rate: float = 0.05
    maximum_fallback_rate: float = 0.10

    def __post_init__(self) -> None:
        if self.minimum_cognitive_runs < 1:
            raise ValueError("minimum_cognitive_runs must be positive")
        for name in ("maximum_error_rate", "maximum_fallback_rate"):
            value = getattr(self, name)
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")

    def evaluate(self, metrics: dict[str, int]) -> RollbackDecision:
        suffix = RuntimePath.COGNITIVE.value
        completed = metrics.get(f"completed:{suffix}", 0)
        errors = metrics.get(f"cognitive_error:{suffix}", 0)
        fallbacks = metrics.get(f"automatic_fallback:{suffix}", 0)
        total = completed + errors
        if total < self.minimum_cognitive_runs:
            return RollbackDecision(False, ("INSUFFICIENT_OBSERVATION_WINDOW",))
        reasons: list[str] = []
        if errors / total > self.maximum_error_rate:
            reasons.append("COGNITIVE_ERROR_RATE_EXCEEDED")
        if fallbacks / total > self.maximum_fallback_rate:
            reasons.append("AUTOMATIC_FALLBACK_RATE_EXCEEDED")
        return RollbackDecision(bool(reasons), tuple(reasons))


def build_rollout_router(
    settings: Settings,
    *,
    production_storage_ready: bool,
) -> CognitiveTrafficRouter:
    """从部署配置构建路由；生产环境未满足持久化门禁时拒绝启动灰度。"""

    try:
        mode = RolloutMode(settings.cognitive_rollout_mode.lower())
    except ValueError as exc:
        raise ConfigurationError(
            f"未知的 Cognitive 灰度模式: {settings.cognitive_rollout_mode}"
        ) from exc
    gate = RolloutGate(
        approval_ref=settings.cognitive_rollout_approval_ref,
        rollout_owner=settings.cognitive_rollout_owner,
        rollback_owner=settings.cognitive_rollback_owner,
        # 这些验证项不能由一个环境变量伪造；当前仓库完成对应自动化/运维接线后
        # 应由发布控制面注入强类型 Gate。默认工厂只允许 OFF。
    )
    config = RolloutConfig(
        mode=mode,
        percentage=settings.cognitive_rollout_percentage,
        internal_user_ids=settings.cognitive_rollout_internal_user_ids,
        gate=gate,
    )
    if settings.environment == "production" and mode != RolloutMode.OFF:
        if not production_storage_ready:
            raise ConfigurationError(
                "M5 灰度被阻断：Run Registry、Chat Store 或 Cognitive Checkpoint 尚未全部持久化"
            )
        missing = gate.missing_requirements()
        if missing:
            raise ConfigurationError(
                "M5 灰度门禁未通过: " + ", ".join(missing)
            )
    return CognitiveTrafficRouter(config)


def approved_test_gate() -> RolloutGate:
    """仅供测试/离线演练显式构造完整门禁，生产装配不得调用。"""

    return RolloutGate(
        approval_ref="test-approval",
        rollout_owner="test-owner",
        rollback_owner="test-rollback-owner",
        m0_to_m4_accepted=True,
        identity_isolation_passed=True,
        guardrails_passed=True,
        mock_isolation_passed=True,
        comparison_passed=True,
        persistence_faults_passed=True,
        observability_ready=True,
        rollback_drill_passed=True,
    )


def _stable_bucket(user_id: str, session_id: str) -> int:
    digest = sha256(f"{user_id}\x1f{session_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % 100
