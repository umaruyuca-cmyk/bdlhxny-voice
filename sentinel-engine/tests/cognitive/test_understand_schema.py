"""理解输出契约：禁止 route / skill_id / plan_steps 及任意额外字段。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bdlh_runtime.cognitive.goal_schema import (
    FORBIDDEN_UNDERSTAND_FIELDS,
    GoalSpec,
    SuccessCriterion,
    UnderstandOutput,
)


def _minimal_payload(**extra) -> dict:
    payload = {
        "goals": [
            {
                "goal_id": "g1",
                "objective": "查一下报价",
                "success_criteria": [
                    {"criterion_id": "c1", "description": "拿到最新价"},
                ],
            }
        ],
        "needs_external": True,
    }
    payload.update(extra)
    return payload


@pytest.mark.parametrize("field", FORBIDDEN_UNDERSTAND_FIELDS)
def test_understand_output_rejects_forbidden_fields(field: str) -> None:
    """输出含 route / skill_id / plan_steps 必须校验失败。"""
    with pytest.raises(ValidationError):
        UnderstandOutput.model_validate(_minimal_payload(**{field: "forbidden"}))


def test_understand_output_accepts_minimal_goals() -> None:
    out = UnderstandOutput.model_validate(_minimal_payload())
    assert len(out.goals) == 1
    assert out.goals[0].status == "PENDING"


def test_goal_spec_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        GoalSpec.model_validate(
            {
                "goal_id": "g1",
                "objective": "x",
                "success_criteria": [SuccessCriterion(criterion_id="c1", description="d").model_dump()],
                "legacy_route_type": "comprehensive",
            }
        )


def test_nested_forbidden_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="forbidden field"):
        UnderstandOutput.model_validate(
            {
                "goals": [
                    {
                        "goal_id": "g1",
                        "objective": "查报价",
                        "success_criteria": [
                            {"criterion_id": "c1", "description": "拿到最新价", "route": "research"}
                        ],
                    }
                ]
            }
        )
    with pytest.raises(ValidationError, match="forbidden field"):
        GoalSpec.model_validate(
            {
                "goal_id": "g1",
                "objective": "x",
                "skill_id": "stock-research",
                "success_criteria": [{"criterion_id": "c1", "description": "d"}],
            }
        )

