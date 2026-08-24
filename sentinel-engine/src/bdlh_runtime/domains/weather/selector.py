"""天气域 handler：LLM 选中 weather.forecast 后派发固定预报。"""

from __future__ import annotations

from bdlh_runtime.cognitive.contracts import CognitiveAction, CognitiveActionType, InputEvent
from bdlh_runtime.cognitive.goal_schema import UnderstandOutput
from bdlh_runtime.domains.contracts import DomainBudget, DomainOperation, DomainRequest


class WeatherCognitiveSelector:
    async def select(
        self,
        event: InputEvent,
        *,
        understood: UnderstandOutput | None = None,
    ) -> CognitiveAction:
        del understood
        request = DomainRequest(
            request_id=f"{event.event_id}:forecast",
            domain="weather",
            authenticated_user_id=event.user_id,
            objective="返回固定演示天气预报",
            success_criteria=["给出一条可核对的预报事实"],
            authorized_operations={DomainOperation.READ_PUBLIC_RESEARCH},
            budget=DomainBudget(tool_call_limit=1, runtime_seconds=5, model_call_limit=0),
        )
        return CognitiveAction(
            action_type=CognitiveActionType.INVOKE_DOMAIN,
            reason_code="WEATHER_FORECAST",
            reason="调用演示天气预报工具",
            domain_request=request,
        )
