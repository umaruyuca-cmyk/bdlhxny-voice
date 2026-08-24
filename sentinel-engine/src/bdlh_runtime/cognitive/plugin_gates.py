"""会话工具门禁（内核侧）。

Skill 与其他 tools 同等：清单由装配期注入的 ``SkillCatalog`` 提供。
要不要调用，由 Understand LLM 选择 ``use_skill``，内核不做领域归因。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class SkillToolSpec:
    """一条可调用 Skill 的调度记录；``domain`` 用于 handler 查找。"""

    skill_id: str
    domain: str
    hint: str = ""


class SkillCatalog:
    """Skill 清单与 ``{domain}.{skill}`` 前缀约定。"""

    def __init__(self, tools: Iterable[SkillToolSpec] = ()) -> None:
        self._tools = tuple(tools)
        index: dict[str, SkillToolSpec] = {}
        for tool in self._tools:
            index[tool.skill_id] = tool
            if "." in tool.skill_id:
                index[tool.skill_id.split(".", 1)[1]] = tool
            else:
                index[f"{tool.domain}.{tool.skill_id}"] = tool
        self._index = index

    def __bool__(self) -> bool:
        return bool(self._tools)

    def domain_for(self, skill_id: str | None) -> str | None:
        spec = self._lookup(skill_id)
        return spec.domain if spec is not None else None

    def tool_prompt(self, enabled_skills: frozenset[str] | None) -> str:
        allowed = enabled_skill_ids(enabled_skills)
        if not allowed:
            return "本轮没有可用工具。use_skill 必须为 null。"
        lines = ["本轮可用工具（与其他 tools 相同；不调用则 use_skill 必须为 null）："]
        for skill_id in allowed:
            spec = self._lookup(skill_id)
            hint = spec.hint if spec is not None else "已启用的会话工具"
            lines.append(f"- {skill_id}：{hint}")
        lines.append("根据用户问题选择其中一个 id，或不选。不要按领域或关键词做意图分类。")
        return "\n".join(lines)

    def resolve_use_skill(
        self,
        use_skill: str | None,
        enabled_skills: frozenset[str] | None,
    ) -> str | None:
        text = str(use_skill or "").strip()
        if not text or text.lower() in {"null", "none"}:
            return None
        allowed = enabled_skill_ids(enabled_skills)
        if not allowed:
            return None
        if text in allowed:
            return text
        spec = self._lookup(text)
        if spec is None:
            return None
        for item in allowed:
            if self._lookup(item) is spec:
                return item
        return None

    def _lookup(self, skill_id: str | None) -> SkillToolSpec | None:
        text = str(skill_id or "").strip()
        if not text:
            return None
        found = self._index.get(text)
        if found is not None:
            return found
        if "." in text:
            return self._index.get(text.split(".", 1)[1])
        return None


def enabled_skill_ids(enabled_skills: frozenset[str] | None) -> tuple[str, ...]:
    """本轮允许作为工具调用的 Skill id（保持会话里的写法）。"""
    if not enabled_skills:
        return ()
    return tuple(item.strip() for item in sorted(enabled_skills) if item.strip())


def catalog_from_records(records: Iterable[Mapping[str, str]]) -> SkillCatalog:
    """从注册表投影构建目录；记录需含 skill_id / domain，可选 hint。"""
    tools: list[SkillToolSpec] = []
    for row in records:
        skill_id = str(row.get("skill_id") or "").strip()
        domain = str(row.get("domain") or "").strip()
        if not skill_id or not domain:
            continue
        tools.append(
            SkillToolSpec(
                skill_id=skill_id,
                domain=domain,
                hint=str(row.get("hint") or skill_id),
            )
        )
    return SkillCatalog(tools)
