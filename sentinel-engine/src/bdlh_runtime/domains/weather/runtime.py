"""天气玩具 Runtime：固定预报，不接真实天气 API。"""

from __future__ import annotations

from bdlh_runtime.domains.contracts import (
    ConfidenceAssessment,
    DomainFact,
    DomainOutcome,
    DomainRequest,
)


class WeatherRuntime:
    async def run(self, request: DomainRequest) -> DomainOutcome:
        return DomainOutcome(
            request_id=request.request_id,
            domain="weather",
            status="COMPLETE",
            established_facts=[
                DomainFact(
                    fact_id="wx-toy-1",
                    statement="演示预报：明日晴，最高 26℃。",
                    source_refs=["weather:toy-forecast"],
                    directness="DIRECT",
                )
            ],
            confidence=ConfidenceAssessment(
                level="HIGH",
                reasons=["toy-fixture"],
                coverage_status="COMPLETE",
            ),
        )
