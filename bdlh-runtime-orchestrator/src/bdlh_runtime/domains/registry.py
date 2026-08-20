"""领域运行时注册表（31 号统一开发实施 Prompt §7.1；ADR-010 §5/§6）。

M1 已将 ``FinanceRuntime`` 注册为 ``finance`` 领域；现有 Root Graph 仍是默认
执行入口，后续认知层可通过本注册表显式路由到领域运行时。

ADR-010 升级后，注册表同时携带每个域的 ``DomainDescriptor``（声明支持哪些意图、
当前启用哪些、挂载哪些 Skill）。注册表本身**不做跨层校验**——descriptor 的
Capability/Toolset 一致性校验由 ``runtime/manifest_validation.py`` 在启动时
对 Capability Registry 逐项执行（ADR-010 §3.1.2 fail-fast）。这样注册表保持
「只存只查」的纯净，不依赖 ``tools`` 或任何领域实现（ADR-009 §3.3）。
"""

from __future__ import annotations

from typing import Any

from bdlh_runtime.domains.manifests import DomainDescriptor


class DomainRegistry:
    """领域名称 → 领域运行时 的单一真源映射（ADR-010：同时携带 descriptor）。

    实现保持最小：不依赖 LangGraph / MCP / Mem0，任何领域运行时
    （Protocol）都可以注册。descriptor 注册是可选的——没有 descriptor 的域
    仍可被 ``get`` / ``contains`` 查询，只是无法回答 intent 启用状态。
    """

    def __init__(self) -> None:
        self._runtimes: dict[str, Any] = {}
        self._descriptors: dict[str, DomainDescriptor] = {}

    def register(self, domain: str, runtime: Any) -> None:
        """注册领域运行时；重复注册同一领域直接报错，防止静默覆盖。"""
        if not domain or not domain.strip():
            raise ValueError("domain must be a non-empty string")
        if domain in self._runtimes:
            raise ValueError(f"Domain already registered: {domain}")
        self._runtimes[domain] = runtime

    def register_descriptor(self, domain: str, descriptor: DomainDescriptor) -> None:
        """注册域描述符（ADR-010 §4）。

        ``descriptor.domain`` 必须与 ``domain`` 一致，且该 domain 必须已注册
        runtime（runtime 先于 descriptor 注册，对齐 bootstrap 顺序）。重复
        注册同一 domain 的 descriptor 直接报错，禁止静默覆盖。

        本方法只做结构存储与一致性检查，**不做** Capability/Toolset 校验——
        那是 ``runtime/manifest_validation.py`` 的启动职责（保持本模块纯净）。
        """
        if not self.contains(domain):
            raise ValueError(f"Cannot register descriptor for unregistered domain: {domain}")
        if descriptor.domain != domain:
            raise ValueError(
                f"Descriptor domain mismatch: descriptor.domain={descriptor.domain!r} but registered under {domain!r}"
            )
        if domain in self._descriptors:
            raise ValueError(f"Descriptor already registered for domain: {domain}")
        self._descriptors[domain] = descriptor

    def get(self, domain: str) -> Any:
        try:
            return self._runtimes[domain]
        except KeyError as exc:
            raise KeyError(f"Domain is not registered: {domain}") from exc

    def contains(self, domain: str) -> bool:
        return domain in self._runtimes

    def list_domains(self) -> list[str]:
        return sorted(self._runtimes)

    def descriptor(self, domain: str) -> DomainDescriptor | None:
        """返回该 domain 的描述符；未注册 descriptor 时返回 ``None``。"""
        return self._descriptors.get(domain)

    def is_intent_enabled(self, domain: str, intent: str) -> bool:
        """查询某 domain 是否启用了某 intent（ADR-010 §5 路由判定）。

        无 descriptor 的域视为「不启用任何 intent」，调用方应返回
        ``ACTION_NOT_ENABLED``。有 descriptor 的域以 ``enabled_intents`` 为准。
        """
        descriptor = self._descriptors.get(domain)
        if descriptor is None:
            return False
        return intent in descriptor.enabled_intents
