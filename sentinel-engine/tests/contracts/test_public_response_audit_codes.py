"""PublicResponse.audit_codes 是对外可观测审计码的契约槽位。"""

from bdlh_runtime.cognitive.contracts import PublicResponse


def test_public_response_audit_codes_hold_observability_codes() -> None:
    response = PublicResponse(
        response_kind="ANSWER",
        message="已完成回答。",
        audit_codes=["RESPOND", "GOAL_COVERAGE_ASSUMED", "UNDERSTAND_CAPABILITY_SMUGGLED"],
    )
    assert "GOAL_COVERAGE_ASSUMED" in response.audit_codes
    assert "UNDERSTAND_CAPABILITY_SMUGGLED" in response.audit_codes
