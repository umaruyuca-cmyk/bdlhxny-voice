"""Tests-only Skill catalog used by GoalActionSelector wiring."""

from __future__ import annotations

from bdlh_runtime.cognitive.plugin_gates import SkillCatalog, SkillToolSpec

DEMO_SKILL_CATALOG = SkillCatalog(
    (
        SkillToolSpec(skill_id="stock-research", domain="finance", hint="quotes and research"),
        SkillToolSpec(skill_id="portfolio-health", domain="finance", hint="portfolio"),
        SkillToolSpec(skill_id="suitability-evaluation", domain="finance", hint="suitability"),
        SkillToolSpec(skill_id="forecast", domain="weather", hint="forecast"),
    )
)
