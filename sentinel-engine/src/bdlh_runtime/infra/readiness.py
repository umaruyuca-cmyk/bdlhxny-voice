"""Orchestrator readiness 评估（与 liveness 分离）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .dependency_probes import probe_java_data_plane, probe_memory_service


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class ReadinessReport:
    ready: bool
    checks: tuple[ReadinessCheck, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "READY" if self.ready else "NOT_READY",
            "service": "bdlh-runtime-orchestrator",
            "checks": [{"name": item.name, "ok": item.ok, "detail": item.detail} for item in self.checks],
        }


def evaluate_readiness(application: Any) -> ReadinessReport:
    """评估应用是否可接收流量。

    必需：配置完整、Registry 已装配、Java Data Plane 可达。
    条件：``memory_mode=remote`` 时 Memory Service 必须可达。
    """

    settings = application.settings
    checks: list[ReadinessCheck] = []

    java_url = (settings.java_api_base_url or "").strip()
    if java_url:
        checks.append(ReadinessCheck("config.java_api_base_url", True, java_url))
    else:
        checks.append(
            ReadinessCheck(
                "config.java_api_base_url",
                False,
                "缺少 JAVA_API_BASE_URL",
            )
        )

    if settings.auth_required:
        if settings.jwt_secret:
            checks.append(ReadinessCheck("config.jwt_secret", True, "已配置"))
        else:
            checks.append(ReadinessCheck("config.jwt_secret", False, "auth_required 但缺少 JWT_SECRET"))
    else:
        checks.append(ReadinessCheck("config.jwt_secret", True, "auth_required=false，跳过"))

    if settings.java_data_internal_token:
        checks.append(ReadinessCheck("config.java_data_internal_token", True, "已配置"))
    else:
        checks.append(
            ReadinessCheck(
                "config.java_data_internal_token",
                False,
                "缺少 JAVA_DATA_INTERNAL_TOKEN（产品路径不允许无凭证）",
            )
        )

    if application.capability_registry is not None and application.engine_runtime is not None:
        checks.append(ReadinessCheck("registry.loaded", True, "capability_registry 与 engine_runtime 已装配"))
    else:
        checks.append(
            ReadinessCheck(
                "registry.loaded",
                False,
                "capability_registry 或 engine_runtime 未装配",
            )
        )

    if java_url:
        probe = probe_java_data_plane(java_url)
        checks.append(ReadinessCheck(probe.name, probe.ok, probe.detail))
    else:
        checks.append(ReadinessCheck("java_data_plane", False, "未配置基址，跳过探测失败"))

    if settings.memory_mode == "remote":
        memory_url = (settings.memory_service_base_url or "").strip()
        if not memory_url or not settings.memory_service_internal_token:
            checks.append(
                ReadinessCheck(
                    "memory_service",
                    False,
                    "memory_mode=remote 但缺少 MEMORY_SERVICE_BASE_URL 或 TOKEN",
                )
            )
        else:
            probe = probe_memory_service(memory_url)
            checks.append(ReadinessCheck(probe.name, probe.ok, probe.detail))
    else:
        checks.append(
            ReadinessCheck(
                "memory_service",
                True,
                f"memory_mode={settings.memory_mode}，不探测",
            )
        )

    # G6：Flag 打开时必须具备原子搜索凭证，禁止用 Flag 掩盖缺基础设施
    if settings.deep_research_enabled:
        key = (settings.bailian_web_search_api_key or "").strip()
        if key:
            checks.append(ReadinessCheck("deep_research.bailian", True, "已配置百炼 Key"))
        else:
            checks.append(
                ReadinessCheck(
                    "deep_research.bailian",
                    False,
                    "BDLH_DEEP_RESEARCH_ENABLED=true 但缺少 BDLH_BAILIAN_WEB_SEARCH_API_KEY",
                )
            )
    else:
        checks.append(ReadinessCheck("deep_research.bailian", True, "Deep Research Flag 关闭，跳过"))

    ready = all(item.ok for item in checks)
    return ReadinessReport(ready=ready, checks=tuple(checks))
