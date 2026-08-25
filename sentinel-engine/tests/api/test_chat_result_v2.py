"""ChatResult v2：五类 Block 由 Observation 直接投影，数字不篡改（WO-T3-2）。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from bdlh_runtime.api.projections import chat_final_payload, project_blocks
from bdlh_runtime.api.routes import create_api_app
from bdlh_runtime.api.schemas import SUITABILITY_DISCLOSURE
from bdlh_runtime.cognitive.contracts import CognitiveExecution, CognitiveState, InputEvent, PublicResponse
from bdlh_runtime.config import Settings
from bdlh_runtime.contracts.observation import Observation, ProvenanceRecord
from bdlh_runtime.engine.loop import AgentLoop
from bdlh_runtime.engine.runtime import EngineRuntime
from bdlh_runtime.tools.catalog import catalog_from_snapshot
from tests.engine.test_loop import FakeChatModel
from tests.helpers_application import build_isolated_application

SECRET = "test-jwt-secret-with-at-least-thirty-two-bytes"

_SCORE_PAYLOAD = {
    "symbol": "300750",
    "name": "宁德时代",
    "overall": 72,
    "scale": 100,
    "rating": "中性偏强",
    "dimensions": [
        {"name": "技术面", "score": 78, "trend": "up"},
        {"name": "基本面", "score": 74, "trend": "flat"},
        {"name": "估值", "score": 52, "trend": "down"},
        {"name": "资金流", "score": 65, "trend": "up"},
        {"name": "情绪面", "score": 71, "trend": "flat"},
    ],
}
_REPORT_PAYLOAD = {
    "dimensions": [
        {
            "name": "基本面",
            "findings": ["营收同比 +12%"],
            "metrics": {"pe": 18.4, "roe": 0.21},
            "evidence_refs": ["fin:2026q2"],
        }
    ]
}
_SUITABILITY_PAYLOAD = {
    "matches": ["风险等级 R3 ↔ 画像稳健型", "持仓集中度在容忍带内"],
    "risks": ["单日波动超画像容忍带 1.8σ", "该标的占仓 18%，高于单标的建议区间"],
    "concentration_pct": 18,
    "sigma": 1.8,
    "conclusion": "适合买入",
}
_PORTFOLIO_PAYLOAD = {
    "hhi": 0.18,
    "top3_weight": 0.62,
    "sectors": [{"name": "新能源", "weight": 0.41}],
    "risks": ["单标的占仓 18%"],
}
_QUOTE_PAYLOAD = {
    "columns": ["symbol", "last", "change_pct"],
    "rows": [{"symbol": "300750", "last": 412.5, "change_pct": 2.1}],
}


def _obs(result_type: str, payload: dict[str, Any], *, observation_id: str = "obs-1") -> dict[str, Any]:
    return {
        "observation_id": observation_id,
        "capability": "analysis.run_analysis",
        "status": "SUCCESS",
        "result_type": result_type,
        "payload": payload,
        "provenance": [
            {"source": "java-api", "tool": "analysis.run_analysis", "retrieved_at": "2026-08-19T00:00:00Z"}
        ],
    }


def _token(user_id: int) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": now + timedelta(hours=1)},
        SECRET,
        algorithm="HS256",
    )


def _events(response) -> list[dict]:
    return [json.loads(line.removeprefix("data: ")) for line in response.text.splitlines() if line.startswith("data: ")]


def test_five_block_types_project_payload_numbers_unchanged() -> None:
    cases = [
        ("ScoreCard", _SCORE_PAYLOAD, ("overall", 72), ("dimensions", 0, "score", 78)),
        ("AnalysisReport", _REPORT_PAYLOAD, ("dimensions", 0, "metrics", "pe", 18.4), None),
        ("PortfolioHealth", _PORTFOLIO_PAYLOAD, ("hhi", 0.18), ("top3_weight", 0.62)),
        ("QuoteTable", _QUOTE_PAYLOAD, ("rows", 0, "last", 412.5), ("rows", 0, "change_pct", 2.1)),
    ]
    for result_type, payload, first, second in cases:
        blocks = project_blocks([_obs(result_type, payload, observation_id=result_type)])
        assert len(blocks) == 1
        assert blocks[0].type == result_type
        assert blocks[0].payload == payload
        _assert_path(blocks[0].payload, first)
        if second is not None:
            _assert_path(blocks[0].payload, second)


def test_suitability_draft_enforces_c2_without_changing_numbers() -> None:
    blocks = project_blocks([_obs("SuitabilityDraft", _SUITABILITY_PAYLOAD)])
    assert len(blocks) == 1
    payload = blocks[0].payload
    assert payload["matches"] == _SUITABILITY_PAYLOAD["matches"]
    assert payload["risks"] == _SUITABILITY_PAYLOAD["risks"]
    assert payload["concentration_pct"] == 18
    assert payload["sigma"] == 1.8
    assert payload["disclosure"] == SUITABILITY_DISCLOSURE
    assert "conclusion" not in payload
    assert "适合买入" not in json.dumps(payload, ensure_ascii=False)
    assert "matches" in payload and "risks" in payload


def test_unknown_result_type_is_not_projected() -> None:
    assert project_blocks([_obs("UnknownChart", {"value": 1})]) == []


def test_nested_data_result_type_is_lifted() -> None:
    observation = Observation(
        observation_id="obs-nested",
        capability="analysis.run_analysis",
        status="SUCCESS",
        data={"result_type": "QuoteTable", "payload": _QUOTE_PAYLOAD},
        provenance=[
            ProvenanceRecord(source="mcp", tool="market.get_realtime_quote", retrieved_at="2026-08-19T08:00:00Z")
        ],
    )
    blocks = project_blocks([observation])
    assert blocks[0].type == "QuoteTable"
    assert blocks[0].payload["rows"][0]["last"] == 412.5
    assert blocks[0].source == "mcp"
    assert blocks[0].data_time == "2026-08-19T08:00:00Z"


def test_chat_final_payload_is_chat_result_v2() -> None:
    response = PublicResponse(
        response_kind="ANSWER",
        message="宁德时代综合评分中性偏强。",
        evidence_refs=["score:300750"],
        audit_codes=["TEST"],
        risk_disclosures=["示例风险披露"],
    )
    payload = chat_final_payload(
        response,
        observations=[_obs("ScoreCard", _SCORE_PAYLOAD)],
        tool_trace=[{"tool": "analysis.run_analysis", "status": "SUCCESS", "elapsedMs": 12}],
    )
    assert payload["type"] == "response.final"
    assert payload["answer"] == "宁德时代综合评分中性偏强。"
    assert payload["blocks"][0]["type"] == "ScoreCard"
    assert payload["blocks"][0]["payload"]["overall"] == 72
    assert payload["tool_trace"][0]["tool"] == "analysis.run_analysis"
    assert payload["evidence_refs"] == ["score:300750"]
    assert payload["audit_codes"] == ["TEST"]
    assert payload["disclosures"] == ["示例风险披露"]


class _TypedCognitive:
    async def run(self, event: InputEvent, *, observer: Any = None, checkpoint: Any = None) -> CognitiveExecution:
        del observer, checkpoint
        return CognitiveExecution(
            state=CognitiveState(event=event),
            response=PublicResponse(
                response_kind="ANSWER",
                response_structure="RESEARCH",
                message="数字以评分卡为准。",
                evidence_refs=["score:300750"],
                audit_codes=["TYPED"],
            ),
            observations=[_obs("ScoreCard", _SCORE_PAYLOAD)],
            tool_trace=[{"tool": "analysis.run_analysis", "status": "SUCCESS", "elapsedMs": 8}],
        )


def test_sse_response_final_carries_blocks() -> None:
    application = build_isolated_application(
        settings=Settings(auth_required=True, jwt_secret=SECRET),
        cognitive_application=_TypedCognitive(),
    )
    client = TestClient(create_api_app(application))
    events = _events(
        client.post(
            "/api/v1/chat/stream",
            headers={"Authorization": f"Bearer {_token(7)}"},
            json={"message": "宁德时代怎么样"},
        )
    )
    final = events[-2]
    assert final["type"] == "response.final"
    assert final["answer"] == "数字以评分卡为准。"
    assert final["blocks"][0]["payload"]["overall"] == 72
    assert final["tool_trace"][0]["tool"] == "analysis.run_analysis"


@pytest.mark.asyncio
async def test_engine_lifts_tool_typed_result_into_execution(registry_snapshot) -> None:
    async def executor(name: str, arguments: dict) -> dict:
        del name, arguments
        return {"result_type": "ScoreCard", "payload": _SCORE_PAYLOAD}

    runtime = EngineRuntime(
        AgentLoop(
            llm=FakeChatModel(
                [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "analysis.run_analysis",
                                "args": {},
                                "id": "call-1",
                                "type": "tool_call",
                            }
                        ],
                    ),
                    AIMessage(content="解读文本，分数见评分卡。"),
                ]
            ),
            catalog=catalog_from_snapshot(registry_snapshot),
            executor=executor,
        )
    )
    execution = await runtime.run(
        InputEvent(
            event_id="e1",
            user_id="user-1",
            session_id="s1",
            run_id="r-score",
            message="宁德时代综合评分",
        )
    )
    assert execution.observations[0]["result_type"] == "ScoreCard"
    assert execution.observations[0]["payload"]["overall"] == 72
    assert execution.tool_trace[0]["tool"] == "analysis.run_analysis"
    blocks = project_blocks(execution.observations)
    assert blocks[0].payload["dimensions"][2]["score"] == 52


def _assert_path(payload: dict[str, Any], path: tuple) -> None:
    cursor: Any = payload
    expected = path[-1]
    for key in path[:-1]:
        cursor = cursor[key]
    assert cursor == expected
