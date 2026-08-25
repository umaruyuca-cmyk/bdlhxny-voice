"""演示注入端点契约测试（WO-T1-8）：demo 档开/关路由注册、source 全链路透传。

设计文档 §4.8、§6.1、C-4：``POST /internal/demo/events`` 仅在 ``BDLH_DEMO_MODE=true``
时注册；注入事件 ``source=demo_inject`` 必须贯穿至事件记录。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from bdlh_runtime.api.routes import create_api_app
from bdlh_runtime.config import Settings
from bdlh_runtime.watch.events import WatchEvent
from bdlh_runtime.watch.sources import DedupeKeyConflict
from tests.helpers_application import build_isolated_application


class _CapturingEventStore:
    """记录写入的事件，供断言 source 透传。"""

    def __init__(self) -> None:
        self.events: list[WatchEvent] = []
        self._keys: set[str] = set()

    def dedupe_key_exists(self, key: str) -> bool:
        return key in self._keys

    def append(self, event: WatchEvent) -> WatchEvent:
        if event.dedupe_key in self._keys:
            raise DedupeKeyConflict(event.dedupe_key)
        self._keys.add(event.dedupe_key)
        stored = event.model_copy(update={"id": len(self.events) + 1})
        self.events.append(stored)
        return stored


def _build_app(*, demo_mode: bool, event_store: _CapturingEventStore | None = None):
    settings = Settings(environment="production", auth_required=False, memory_mode="remote", demo_mode=demo_mode)
    app = build_isolated_application(settings=settings)
    if event_store is not None:
        app.watch_event_store = event_store
    return create_api_app(app, api_prefix="/api/v1")


_DEMO_PATH = "/api/v1/internal/demo/events"


def test_demo_route_not_registered_when_demo_mode_off():
    """非 demo 档：路由不注册，POST 返回 404（不依赖隐藏）。"""
    app = _build_app(demo_mode=False)
    client = TestClient(app)
    resp = client.post(_DEMO_PATH, json={"type": "price_threshold", "symbol": "300750", "pct": -5.2})
    assert resp.status_code == 404


def test_demo_route_registered_when_demo_mode_on():
    """demo 档：路由注册，注入成功并返回 event_id。"""
    store = _CapturingEventStore()
    app = _build_app(demo_mode=True, event_store=store)
    client = TestClient(app)
    resp = client.post(_DEMO_PATH, json={"type": "price_threshold", "symbol": "300750", "pct": -5.2})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "demo_inject"  # C-4：source 透传
    assert body["event_id"]
    # 事件落库且 source 贯穿
    assert len(store.events) == 1
    assert store.events[0].source == "demo_inject"
    assert store.events[0].payload["demo"] is True
    assert store.events[0].payload["symbol"] == "300750"
    assert store.events[0].payload["direction"] == "down"  # pct 负 → down


def test_demo_inject_cron_event():
    store = _CapturingEventStore()
    app = _build_app(demo_mode=True, event_store=store)
    client = TestClient(app)
    resp = client.post(_DEMO_PATH, json={"type": "daily_briefing"})
    assert resp.status_code == 200, resp.text
    assert store.events[0].type == "daily_briefing"
    assert store.events[0].source == "demo_inject"
    assert "trading_day" in store.events[0].payload


def test_demo_inject_rejects_invalid_type():
    app = _build_app(demo_mode=True, event_store=_CapturingEventStore())
    client = TestClient(app)
    resp = client.post(_DEMO_PATH, json={"type": "unknown_type"})
    assert resp.status_code == 400


def test_demo_inject_price_threshold_requires_pct_or_abs_price():
    app = _build_app(demo_mode=True, event_store=_CapturingEventStore())
    client = TestClient(app)
    resp = client.post(_DEMO_PATH, json={"type": "price_threshold", "symbol": "300750"})
    assert resp.status_code == 400


def test_demo_route_503_when_event_store_not_wired():
    """demo 档但 watch_event_store 未装配：503（不静默，§4.9）。"""
    app = _build_app(demo_mode=True, event_store=None)
    client = TestClient(app)
    resp = client.post(_DEMO_PATH, json={"type": "price_threshold", "symbol": "300750", "pct": -5.2})
    assert resp.status_code == 503
