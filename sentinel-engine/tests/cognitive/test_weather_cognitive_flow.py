"""第二 Skill（weather.forecast）经 Registry 装配跑通认知主链路。"""

from __future__ import annotations

import pytest

from bdlh_runtime.cognitive.contracts import CognitiveActionType, InputEvent
from bdlh_runtime.cognitive.goal_action_selector import GoalActionSelector
from bdlh_runtime.cognitive.goal_schema import ActionSpec, GoalSpec, SuccessCriterion, UnderstandOutput
from bdlh_runtime.cognitive.orchestrator import CognitiveOrchestrator
from bdlh_runtime.cognitive.plugin_gates import catalog_from_records
from bdlh_runtime.domains.assembly import AssemblyContext, assemble_domains
from bdlh_runtime.domains.contracts import DomainOperation
from bdlh_runtime.domains.dispatcher import DomainDispatcher
from bdlh_runtime.tools.analysis_capability import create_analysis_capability
from bdlh_runtime.tools.capabilities import load_capability_registry
from bdlh_runtime.tools.java_data_adapter import create_java_adapter
from tests.helpers_registry import seeded_snapshot


class _Respond:
    def answer(self, message: str) -> str:
        return f"chat:{message}"


class _WeatherUnderstand:
    async def understand(self, message: str, *, enabled_skills=None) -> UnderstandOutput:
        del enabled_skills
        return UnderstandOutput(
            goals=[
                GoalSpec(
                    goal_id="g1",
                    objective=message,
                    success_criteria=[SuccessCriterion(criterion_id="c1", description="拿到一条预报事实")],
                )
            ],
            needs_external=True,
            action=ActionSpec(tool="weather.forecast", parameters={"city": "beijing"}),
        )


@pytest.mark.asyncio
async def test_weather_forecast_goes_through_cognitive_flow() -> None:
    snapshot = seeded_snapshot()
    assembly = assemble_domains(
        AssemblyContext(
            snapshot=snapshot,
            capability_registry=load_capability_registry(snapshot),
            analysis_capability=create_analysis_capability(),
            java_adapter=create_java_adapter(base_url=None, token=None),
            knowledge_responder=_Respond(),
            execution_environment="production",
        )
    )
    assert "weather" in assembly.enabled_domains
    assert "finance" in assembly.handlers
    catalog = catalog_from_records(
        {"skill_id": skill.skill_id, "domain": skill.domain, "hint": skill.skill_id}
        for skill in snapshot.skills
        if skill.enabled
    )
    result = await CognitiveOrchestrator(
        selector=GoalActionSelector(
            handlers=assembly.handlers,
            catalog=catalog,
            respond=_Respond(),
        ),
        dispatcher=DomainDispatcher(assembly.registry),
        continuation=assembly.continuation,
        plan_guardrail=assembly.plan_guardrail,
        enabled_domains=assembly.enabled_domains,
        authorized_operations=frozenset({DomainOperation.READ_PUBLIC_RESEARCH.value}),
        understand=_WeatherUnderstand(),
    ).run(
        InputEvent(
            event_id="wx-1",
            user_id="user-1",
            session_id="session-1",
            message="明天天气怎么样",
            enabled_skills=frozenset({"weather.forecast"}),
        )
    )

    assert [item.action_type for item in result.state.action_history] == [CognitiveActionType.INVOKE_DOMAIN]
    assert result.response.response_kind == "DOMAIN_RESULT"
    assert result.response.evidence_refs == ["weather:toy-forecast"]
    assert result.response.audit_codes[0] == "WEATHER_FORECAST"
    assert "演示预报" in result.response.message
