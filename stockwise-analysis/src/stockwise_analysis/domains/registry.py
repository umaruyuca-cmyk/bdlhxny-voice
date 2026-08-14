"""领域运行时注册表（31 号统一开发实施 Prompt §7.1）。

M1 已将 ``FinanceRuntime`` 注册为 ``finance`` 领域；现有 Root Graph 仍是默认
执行入口，后续认知层可通过本注册表显式路由到领域运行时。

注册表只保存领域到运行时的稳定映射，不保存业务策略。
"""

from __future__ import annotations

from typing import Any


class DomainRegistry:
    """领域名称 → 领域运行时 的单一真源映射。

    实现保持最小：不依赖 LangGraph / MCP / Mem0，任何领域运行时
    （Protocol）都可以注册。
    """

    def __init__(self) -> None:
        self._runtimes: dict[str, Any] = {}

    def register(self, domain: str, runtime: Any) -> None:
        """注册领域运行时；重复注册同一领域直接报错，防止静默覆盖。"""
        if not domain or not domain.strip():
            raise ValueError("domain must be a non-empty string")
        if domain in self._runtimes:
            raise ValueError(f"Domain already registered: {domain}")
        self._runtimes[domain] = runtime

    def get(self, domain: str) -> Any:
        try:
            return self._runtimes[domain]
        except KeyError as exc:
            raise KeyError(f"Domain is not registered: {domain}") from exc

    def contains(self, domain: str) -> bool:
        return domain in self._runtimes

    def list_domains(self) -> list[str]:
        return sorted(self._runtimes)
