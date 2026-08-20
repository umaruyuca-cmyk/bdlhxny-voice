"""依赖可达性探测（P0 readiness / 启动门禁）。

只探测生产必需依赖：Java Data Plane Actuator、可选 Memory Service live。
MCP / LLM / Web Search 不在此探测——失败应降级表达，不应导致进程反复重启。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProbeResult:
    """单次依赖探测结果。"""

    name: str
    ok: bool
    detail: str


def probe_http_get(url: str, *, timeout_seconds: float = 2.0) -> tuple[bool, str]:
    """对 URL 发 GET；2xx 视为成功。返回 (ok, detail)。"""

    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - 运行时应由依赖保证
        return False, f"缺少 httpx：{exc}"

    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.get(url)
        if 200 <= response.status_code < 300:
            return True, f"HTTP {response.status_code}"
        return False, f"HTTP {response.status_code}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def probe_java_data_plane(base_url: str, *, timeout_seconds: float = 2.0) -> ProbeResult:
    """探测 Java Data Plane：``GET {base}/actuator/health``。"""

    root = base_url.rstrip("/")
    ok, detail = probe_http_get(f"{root}/actuator/health", timeout_seconds=timeout_seconds)
    return ProbeResult(name="java_data_plane", ok=ok, detail=detail)


def probe_memory_service(base_url: str, *, timeout_seconds: float = 2.0) -> ProbeResult:
    """探测 Memory Service：``GET {base}/health/live``。"""

    root = base_url.rstrip("/")
    ok, detail = probe_http_get(f"{root}/health/live", timeout_seconds=timeout_seconds)
    return ProbeResult(name="memory_service", ok=ok, detail=detail)


def assert_java_reachable_for_startup(
    settings: Any,
    *,
    registry_snapshot: Any | None,
) -> None:
    """非测试启动路径下，Java 不可达则 fail-closed。

    - ``test``：跳过（单测注入 snapshot / 假 URL）
    - ``production``：只要配置了 JAVA_API_BASE_URL 就必须可达
    - ``development``：仅在从 Java 拉取 Registry（未注入 snapshot）时探测
    """

    from .errors import ConfigurationError

    base_url = getattr(settings, "java_api_base_url", None)
    if not base_url:
        return
    environment = getattr(settings, "environment", "development")
    if environment == "test":
        return
    if environment != "production" and registry_snapshot is not None:
        return

    result = probe_java_data_plane(base_url)
    if not result.ok:
        raise ConfigurationError(
            "Java Data Plane 不可达，拒绝启动: "
            f"{base_url}/actuator/health ({result.detail})"
        )
