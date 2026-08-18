"""Unit tests for the Clarity Data Export client: parameter mapping, the error family,
and the response-shape guard. `httpx.MockTransport` keeps everything offline."""

from __future__ import annotations

import httpx
import pytest

from qualify_api.clarity.client import (
    ClarityAPIError,
    ClarityBadRequest,
    ClarityQuotaExceeded,
    ClarityUnauthorized,
    HttpClarityClient,
)

PAYLOAD = [{"metricName": "Traffic", "information": [{"totalSessionCount": "42"}]}]


class _Recorder:
    def __init__(self, response: httpx.Response) -> None:
        self.request: httpx.Request | None = None
        self._response = response

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.request = request
        return self._response


def make_client(monkeypatch: pytest.MonkeyPatch, response: httpx.Response) -> _Recorder:
    recorder = _Recorder(response)
    transport = httpx.MockTransport(recorder)
    original_get = httpx.get

    def patched_get(url: str, **kwargs: object) -> httpx.Response:
        with httpx.Client(transport=transport) as client:
            kwargs.pop("timeout", None)
            return client.get(url, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "get", patched_get)
    assert httpx.get is not original_get
    return recorder


def test_params_and_auth_header(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = make_client(monkeypatch, httpx.Response(200, json=PAYLOAD))
    result = HttpClarityClient().live_insights(
        token="tok-123", num_of_days=3, dimensions=["URL", "Device"]
    )
    assert result == PAYLOAD
    assert recorder.request is not None
    assert recorder.request.headers["Authorization"] == "Bearer tok-123"
    params = dict(httpx.QueryParams(recorder.request.url.query))
    assert params == {"numOfDays": "3", "dimension1": "URL", "dimension2": "Device"}


@pytest.mark.parametrize(
    ("status", "exception"),
    [
        (401, ClarityUnauthorized),
        (403, ClarityUnauthorized),
        (429, ClarityQuotaExceeded),
        (400, ClarityBadRequest),
        (500, ClarityAPIError),
    ],
)
def test_error_statuses_map_to_typed_exceptions(
    monkeypatch: pytest.MonkeyPatch, status: int, exception: type[ClarityAPIError]
) -> None:
    make_client(monkeypatch, httpx.Response(status))
    with pytest.raises(exception) as excinfo:
        HttpClarityClient().live_insights(token="t", num_of_days=1, dimensions=[])
    assert excinfo.value.status == status


def test_non_list_body_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    make_client(monkeypatch, httpx.Response(200, json={"unexpected": "shape"}))
    with pytest.raises(ClarityAPIError):
        HttpClarityClient().live_insights(token="t", num_of_days=1, dimensions=[])


def test_transport_errors_never_leak_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    def exploding_get(url: str, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx, "get", exploding_get)
    with pytest.raises(ClarityAPIError) as excinfo:
        HttpClarityClient().live_insights(token="secret-token", num_of_days=1, dimensions=[])
    assert "secret-token" not in str(excinfo.value)
