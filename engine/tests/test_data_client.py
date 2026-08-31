from __future__ import annotations

import httpx
import pytest

from bdlh_runtime.data_client import DataClient, DataServiceError


def test_context_session_request_passes_owner_as_query_parameter(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_request(method: str, url: str, **kwargs):  # noqa: ANN202, ANN003
        captured.update({"method": method, "url": url, **kwargs})
        return httpx.Response(
            200,
            request=httpx.Request(method, url),
            json={"sessions": [{"sessionId": "session-1"}]},
        )

    monkeypatch.setattr(httpx, "request", fake_request)
    client = DataClient("http://data.test/internal/v1", "internal-token")

    sessions = client.list_context_sessions("owner-1")

    assert sessions == [{"sessionId": "session-1"}]
    assert captured["params"] == {"accountId": "owner-1"}
    assert captured["headers"]["X-Internal-Token"] == "internal-token"


def test_data_client_converts_http_status_to_stable_service_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request(method: str, url: str, **kwargs):  # noqa: ANN202, ANN003
        return httpx.Response(
            404,
            request=httpx.Request(method, url),
            json={"errorCode": "SESSION_NOT_FOUND"},
        )

    monkeypatch.setattr(httpx, "request", fake_request)
    client = DataClient("http://data.test/internal/v1", "internal-token")

    with pytest.raises(DataServiceError) as error:
        client.get_context_session("owner-1", "missing")

    assert error.value.status_code == 404
    assert str(error.value) == "SESSION_NOT_FOUND"
