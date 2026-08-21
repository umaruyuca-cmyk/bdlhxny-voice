"""领域运行时注册表（ADR-010）。

产品默认注册 ``FinanceRuntime``（``finance``）；后续 Domain 通过本注册表挂载。
注册表同时携带 ``DomainDescriptor``；Capability/Toolset 一致性由
``runtime/manifest_validation.py`` 在启动期 fail-fast 校验。
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

    def is_skill_enabled(self, domain: str, skill_id: str) -> bool:
        """查询某 domain 是否投影出且启用了某 Skill（Registry Skill.enabled）。"""
        descriptor = self._descriptors.get(domain)
        if descriptor is None:
            return False
        return any(skill.skill_id == skill_id and skill.enabled for skill in descriptor.skills)
