"""The Canva Connect client against a mock transport. The shapes are the documented
ones (canva.dev, 2026-09-28) — no live call has been made yet, so these tests pin what
the code sends and how it reads the documented answers, not Canva's real behaviour."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from qualify_creative.adapters.canva_connect import (
    AUTHORIZE_URL,
    SCOPES,
    CanvaAPIError,
    CanvaConnectClient,
    CanvaError,
    CanvaJobFailed,
    CanvaJobTimeout,
    authorize_url,
    decode_correlation_jwt,
    mp4_quality_for,
    new_correlation_state,
    new_pkce,
    with_correlation_state,
)

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def client_for(
    handler: Any, *, poll_timeout: float = 10.0, sleeps: list[float] | None = None
) -> CanvaConnectClient:
    clock = [0.0]

    def sleep(seconds: float) -> None:
        clock[0] += seconds
        if sleeps is not None:
            sleeps.append(seconds)

    return CanvaConnectClient(
        client_id="cid",
        client_secret="secret",
        transport=httpx.MockTransport(handler),
        poll_interval_seconds=1.0,
        poll_timeout_seconds=poll_timeout,
        sleep=sleep,
        monotonic=lambda: clock[0],
        now=lambda: NOW,
    )


def ok(body: dict[str, Any], status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body)


# -- OAuth helpers ------------------------------------------------------------------------


def test_pkce_challenge_is_the_s256_of_the_verifier() -> None:
    pair = new_pkce()
    assert 43 <= len(pair.verifier) <= 128
    digest = hashlib.sha256(pair.verifier.encode()).digest()
    assert pair.challenge == base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def test_authorize_url_carries_pkce_state_and_scopes() -> None:
    url = authorize_url(
        client_id="cid",
        redirect_uri="http://127.0.0.1:3000/canva/callback",
        state="st",
        code_challenge="ch",
    )
    assert url.startswith(AUTHORIZE_URL + "?")
    query = parse_qs(urlsplit(url).query)
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == ["ch"] and query["state"] == ["st"]
    assert query["scope"] == [" ".join(SCOPES)]


def test_correlation_state_is_short_and_url_safe_and_appended_to_the_edit_url() -> None:
    state = new_correlation_state()
    assert len(state) <= 50 and state.replace("-", "").replace("_", "").isalnum()
    url = with_correlation_state("https://www.canva.com/design/D1/edit?ui=x", state)
    assert parse_qs(urlsplit(url).query) == {"ui": ["x"], "correlation_state": [state]}
    assert with_correlation_state("https://c/d", "abc").endswith("?correlation_state=abc")
    with pytest.raises(ValueError):
        with_correlation_state("https://c/d", "x" * 51)


def test_correlation_jwt_claims_are_decoded_without_trusting_them() -> None:
    claims = {"design_id": "D1", "correlation_state": "abc", "aud": "cid"}
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    assert decode_correlation_jwt(f"e30.{payload}.sig") == claims
    with pytest.raises(CanvaError):
        decode_correlation_jwt("not-a-jwt")


def test_mp4_quality_follows_the_shape() -> None:
    assert mp4_quality_for(1080, 1350) == "vertical_1080p"
    assert mp4_quality_for(1920, 1080) == "horizontal_1080p"


# -- tokens ------------------------------------------------------------------------------


def test_code_exchange_uses_basic_auth_and_the_verifier() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return ok({"access_token": "at", "refresh_token": "rt", "expires_in": 14400, "scope": "s"})

    tokens = client_for(handler).exchange_code(
        code="c0de", code_verifier="ver", redirect_uri="http://127.0.0.1:3000/canva/callback"
    )
    assert (tokens.access_token, tokens.refresh_token, tokens.scope) == ("at", "rt", "s")
    assert tokens.expires_at == NOW.replace(hour=16)
    request = seen[0]
    assert request.url.path == "/rest/v1/oauth/token"
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"cid:secret").decode()
    form = parse_qs(request.content.decode())
    assert form["grant_type"] == ["authorization_code"] and form["code_verifier"] == ["ver"]


def test_refresh_returns_the_new_refresh_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert parse_qs(request.content.decode())["refresh_token"] == ["old"]
        return ok({"access_token": "at2", "refresh_token": "new", "expires_in": 60})

    assert client_for(handler).refresh(refresh_token="old").refresh_token == "new"


def test_a_token_error_surfaces_canvas_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return ok({"error": "invalid_grant", "error_description": "used"}, status=400)

    with pytest.raises(CanvaAPIError) as excinfo:
        client_for(handler).refresh(refresh_token="spent")
    assert excinfo.value.code == "invalid_grant"


# -- assets, designs, exports ------------------------------------------------------------


def test_asset_upload_sends_raw_bytes_and_waits_for_the_asset() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "POST":
            return ok({"job": {"id": "J1", "status": "in_progress"}})
        return ok({"job": {"id": "J1", "status": "success", "asset": {"id": "A1"}}})

    sleeps: list[float] = []
    asset_id = client_for(handler, sleeps=sleeps).upload_asset(
        access_token="at", data=b"png-bytes", name="anuncio.png", is_video=False
    )
    assert asset_id == "A1" and sleeps == [1.0]
    post = seen[0]
    assert post.url.path == "/rest/v1/asset-uploads"
    assert post.headers["Authorization"] == "Bearer at"
    assert post.headers["Content-Type"] == "application/octet-stream"
    metadata = json.loads(post.headers["Asset-Upload-Metadata"])
    assert base64.b64decode(metadata["name_base64"]) == b"anuncio.png"
    assert post.content == b"png-bytes"
    assert seen[1].url.path == "/rest/v1/asset-uploads/J1"


def test_an_oversized_image_is_refused_before_any_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    with pytest.raises(ValueError, match="at most"):
        client_for(handler).upload_asset(
            access_token="at", data=b"x" * (50 * 1024 * 1024 + 1), name="a.png", is_video=False
        )


def test_a_failed_job_raises_with_canvas_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return ok({"job": {"id": "J1", "status": "failed", "error": {"code": "file_too_big"}}})

    with pytest.raises(CanvaJobFailed) as excinfo:
        client_for(handler).upload_asset(access_token="at", data=b"v", name="v.mp4", is_video=True)
    assert excinfo.value.code == "file_too_big"


def test_a_job_that_never_ends_times_out() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return ok({"job": {"id": "J1", "status": "in_progress"}})

    with pytest.raises(CanvaJobTimeout):
        client_for(handler, poll_timeout=3.0).export_design(
            access_token="at", design_id="D1", file_type="png"
        )


def test_create_design_is_custom_sized_and_places_the_image() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return ok(
            {
                "design": {
                    "id": "D1",
                    "urls": {"edit_url": "https://canva/e", "view_url": "https://canva/v"},
                    "updated_at": 1790000000,
                }
            }
        )

    design = client_for(handler).create_design(
        access_token="at", width=1080, height=1350, title="Anuncio", asset_id="A1"
    )
    assert (design.id, design.edit_url, design.updated_at) == ("D1", "https://canva/e", 1790000000)
    assert seen[0] == {
        "design_type": {"type": "custom", "width": 1080, "height": 1350},
        "title": "Anuncio",
        "asset_id": "A1",
    }
    with pytest.raises(ValueError):
        client_for(handler).create_design(access_token="at", width=20, height=1350, title="x")


def test_mp4_export_asks_the_quality_and_returns_the_urls() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen.append(json.loads(request.content))
            return ok({"job": {"id": "E1", "status": "in_progress"}})
        return ok({"job": {"id": "E1", "status": "success", "urls": ["https://dl/1.mp4"]}})

    urls = client_for(handler).export_design(
        access_token="at", design_id="D1", file_type="mp4", mp4_quality="vertical_1080p"
    )
    assert urls == ["https://dl/1.mp4"]
    assert seen[0] == {"design_id": "D1", "format": {"type": "mp4", "quality": "vertical_1080p"}}
    with pytest.raises(ValueError):
        client_for(handler).export_design(access_token="at", design_id="D1", file_type="gif")


def test_download_follows_the_presigned_url_without_auth() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "Authorization" not in request.headers
        return httpx.Response(200, content=b"bytes")

    assert client_for(handler).download("https://dl/1.png") == b"bytes"


def test_the_client_refuses_missing_credentials() -> None:
    with pytest.raises(ValueError):
        CanvaConnectClient(client_id="", client_secret="s")
