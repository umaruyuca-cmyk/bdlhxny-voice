"""P2 分析的单元测试:跨构建趋势与摘要质量抽检。

全部使用内存 Store 与假 Segment 仓库,不调用真实 LLM、不触网。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bdlh_runtime.memory.segments import MemorySegment
from bdlh_runtime.memory.service import ContextWorkbenchService
from bdlh_runtime.memory.store import ContextBuildStore
from bdlh_runtime.session import SessionCompiler
from bdlh_runtime.session.loader import SessionCase, SessionEvent

OWNER = "10000000-0000-0000-0000-000000000001"
OTHER_OWNER = "10000000-0000-0000-0000-000000000002"


class _Source:
    source_type = "FROZEN_FILE"

    def list_sessions(self) -> list[dict]:
        return []

    def get_session(self, session_id: str):
        events = (
            SessionEvent(1, "u1", "", "user_message", "历史问题一", "user"),
            SessionEvent(2, "a1", "", "assistant_message", "历史回答一", "assistant"),
            SessionEvent(3, "u2", "", "user_message", "历史问题二", "user"),
            SessionEvent(4, "u-current", "", "user_message", "当前请求", "user"),
        )
        case = SessionCase(
            session_id=session_id,
            session_version=1,
            title="",
            owner_id=OWNER,
            fixture_set_id=None,
            tool_catalog_version=None,
            current_question="当前请求",
            visible_tools=(),
            context_target_tokens=8192,
            events=events,
            source_hash="sha256:case",
            source_path="",
        )
        variants = {
            "context_variants": [
                {
                    "variant_id": "budgeted-session",
                    "strategy": "budgeted",
                    "strategy_version": "budgeted-hybrid-v1",
                    "token_budget": 8192,
                }
            ]
        }
        return case, variants


class _FakeSegmentRepo:
    """内存 Segment 仓库:按传入列表返回。"""

    owner_id = OWNER

    def __init__(self, segments: list[MemorySegment]) -> None:
        self.segments = segments

    def list_segments(self, owner_id: str, session_id: str) -> list[MemorySegment]:  # noqa: ARG002
        return list(self.segments)

    def save_segment(self, segment: MemorySegment) -> None:  # noqa: ARG002
        return None


def _segment(
    segment_id: str,
    *,
    summary: str = "摘要正文",
    summary_tokens: int = 40,
    source_tokens: int = 400,
    status: str = "FROZEN",
    source_event_ids: tuple[str, ...] = ("u1", "a1"),
    source_hash: str = "sha256:seg",
) -> MemorySegment:
    return MemorySegment(
        segment_id=segment_id,
        session_id="s1",
        start_event_id=source_event_ids[0] if source_event_ids else "",
        end_event_id=source_event_ids[-1] if source_event_ids else "",
        source_event_ids=source_event_ids,
        source_hash=source_hash,
        source_tokens=source_tokens,
        summary_content=summary,
        summary_tokens=summary_tokens,
        status=status,
        summary_model="fake-model",
        prompt_version="turn-summary-v1",
        algorithm_version="segment-v1",
        generation_mode="LLM",
        fallback_reason=None,
    )


def _service(tmp_path: Path, segment_repo: Any | None = None) -> ContextWorkbenchService:
    SessionCompiler.from_env = classmethod(lambda cls, **_: SessionCompiler())
    return ContextWorkbenchService(ContextBuildStore(tmp_path), source=_Source(), segment_repository=segment_repo)


def _create_build(service: ContextWorkbenchService, owner: str, key: str) -> str:
    build, _replay = service.store.create(
        owner_id=owner,
        session_id="s1",
        current_request_event_id="u-current",
        algorithm="budgeted-hybrid-v1",
        idempotency_key=key,
        source_type="FROZEN_FILE",
    )
    service.execute_build(build["build_id"], owner)
    return str(build["build_id"])


def test_build_trends_reports_metric_evolution(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = _create_build(service, OWNER, "trend-0001")
    second = _create_build(service, OWNER, "trend-0002")

    trends = service.build_trends("s1", OWNER)

    assert trends["session_id"] == "s1"
    assert trends["build_count"] == 2
    assert trends["returned"] == 2
    ids = [row["build_id"] for row in trends["trends"]]
    assert second in ids and first in ids
    latest = trends["trends"][0]
    # 压缩率来自真实计数:0 ≤ rate ≤ 1 或为 None,不估算
    assert latest["compression_rate"] is None or 0 <= latest["compression_rate"] <= 1
    assert latest["raw_tokens"] >= 0 and latest["final_tokens"] >= 0
    assert latest["summary_calls"] >= 0 and latest["cache_hits"] >= 0


def test_build_trends_scopes_owner_and_session(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _create_build(service, OWNER, "trend-own-0001")
    _create_build(service, OTHER_OWNER, "trend-other-0001")

    own = service.build_trends("s1", OWNER)
    other = service.build_trends("s1", OTHER_OWNER)

    assert own["build_count"] == 1
    assert other["build_count"] == 1
    assert own["trends"][0]["build_id"] != other["trends"][0]["build_id"]
    empty = service.build_trends("missing-session", OWNER)
    assert empty["build_count"] == 0 and empty["trends"] == []


def test_segment_quality_checks_are_deterministic(tmp_path: Path) -> None:
    repo = _FakeSegmentRepo(
        [
            _segment("seg-good"),
            _segment("seg-empty-summary", summary="", summary_tokens=0),
            _segment("seg-over-budget", summary_tokens=600),
            _segment("seg-invalidated", status="INVALIDATED"),
            _segment("seg-no-sources", source_event_ids=()),
        ]
    )
    service = _service(tmp_path, segment_repo=repo)

    report = service.segment_quality("s1")

    assert report["enabled"] is True
    assert report["checked"] == 5
    assert report["passed"] == 1
    problems = {issue["segment_id"]: issue["problems"] for issue in report["issues"]}
    assert (
        problems["seg-empty-summary"] == ["EMPTY_SUMMARY", "MISSING_SOURCE_HASH"]
        or "EMPTY_SUMMARY" in problems["seg-empty-summary"]
    )
    assert "SUMMARY_OVER_BUDGET" in problems["seg-over-budget"]
    assert "STATUS_INVALIDATED" in problems["seg-invalidated"]
    assert "MISSING_SOURCE_EVENTS" in problems["seg-no-sources"]
    good = next(row for row in report["rows"] if row["segment_id"] == "seg-good")
    assert good["problems"] == []
    assert good["token_ratio"] == round(40 / 400, 4)


def test_segment_quality_legacy_disabled(tmp_path: Path) -> None:
    service = _service(tmp_path)

    report = service.segment_quality("s1")

    assert report["enabled"] is False
    assert report["checked"] == 0 and report["rows"] == []
