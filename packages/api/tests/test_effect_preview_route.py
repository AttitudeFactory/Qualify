"""m-25120474 — `/r2effects/<id>/v<n>` serves only `platform/effects/<id>/v<n>/preview.mp4`.

Offline: an in-memory object store wrapped so every call is recorded, never R2. A bad
path must answer 404 without a single store call.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import IO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from qualify_creative.schemas import EFFECT_ID_PATTERN
from qualify_shared.objects import platform_effects
from qualify_shared.objects.memory import MemoryObjectStore
from qualify_shared.objects.platform_effects import PlatformEffectsReader

from qualify_api.http import effect_preview_routes as routes

ROOT = Path(__file__).resolve().parents[3]
KEY = "platform/effects/humo_denso/v1/preview.mp4"
VIDEO = b"\x00\x00\x00\x18ftypmp42" + bytes(range(200))


class _CountingStore(MemoryObjectStore):
    """`MemoryObjectStore` that records every read it is asked for."""

    def __init__(self) -> None:
        super().__init__(locked=False)
        self.calls: list[tuple[str, str]] = []

    def open(self, key: str) -> IO[bytes]:
        self.calls.append(("open", key))
        return super().open(key)

    def size(self, key: str) -> int:
        self.calls.append(("size", key))
        return super().size(key)

    def open_range(self, key: str, start: int, end: int) -> IO[bytes]:
        self.calls.append(("open_range", key))
        return super().open_range(key, start, end)


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, _CountingStore]:
    store = _CountingStore()
    store.objects[KEY] = VIDEO
    # A tenant's object and another platform object: never reachable through the route.
    store.objects["t/a0000000-0000-4000-8000-000000000001/x/preview.mp4"] = b"tenant"
    store.objects["platform/effects/humo_denso/v1/other.mp4"] = b"other"
    reader = PlatformEffectsReader(store)
    monkeypatch.setattr(routes, "_reader", lambda: reader)
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app), store


def test_a_valid_effect_version_is_served_as_mp4_with_a_long_cache(
    served: tuple[TestClient, _CountingStore],
) -> None:
    client, store = served
    response = client.get("/r2effects/humo_denso/v1")
    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
    assert response.headers["cache-control"] == "public, max-age=86400"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.content == VIDEO
    assert store.calls == [("size", KEY), ("open", KEY)]


def test_head_and_ranges_read_only_the_preview_key(
    served: tuple[TestClient, _CountingStore],
) -> None:
    client, store = served
    head = client.head("/r2effects/humo_denso/v1")
    assert head.status_code == 200
    assert head.headers["content-length"] == str(len(VIDEO))
    assert head.headers["content-type"] == "video/mp4"

    ranged = client.get("/r2effects/humo_denso/v1", headers={"Range": "bytes=0-3"})
    assert ranged.status_code == 206
    assert ranged.content == VIDEO[:4]
    assert ranged.headers["content-range"] == f"bytes 0-3/{len(VIDEO)}"
    assert ranged.headers["content-type"] == "video/mp4"

    past = client.get("/r2effects/humo_denso/v1", headers={"Range": f"bytes={len(VIDEO)}-"})
    assert past.status_code == 416
    assert past.headers["cache-control"] == "no-store"
    assert past.headers["content-range"] == f"bytes */{len(VIDEO)}"
    assert {key for _op, key in store.calls} == {KEY}


def test_a_big_object_without_range_is_never_loaded_whole(
    served: tuple[TestClient, _CountingStore],
) -> None:
    """A public GET with no `Range` on an object over 8 MiB: the first MiB as a 206."""
    client, store = served
    big = bytes(range(256)) * (routes.MAX_WHOLE_BYTES // 256 + 1)
    key = "platform/effects/brasas/v2/preview.mp4"
    store.objects[key] = big
    response = client.get("/r2effects/brasas/v2")
    assert response.status_code == 206
    assert response.content == big[: routes.MAX_RANGE_BYTES]
    assert response.headers["content-range"] == (f"bytes 0-{routes.MAX_RANGE_BYTES - 1}/{len(big)}")
    assert response.headers["content-type"] == "video/mp4"
    assert response.headers["cache-control"] == "public, max-age=86400"
    assert store.calls == [("size", key), ("open_range", key)]
    # exactly at the limit it is still served whole
    store.calls.clear()
    store.objects[key] = big[: routes.MAX_WHOLE_BYTES]
    whole = client.get("/r2effects/brasas/v2")
    assert whole.status_code == 200 and len(whole.content) == routes.MAX_WHOLE_BYTES
    assert store.calls == [("size", key), ("open", key)]


def test_a_missing_version_is_a_404(served: tuple[TestClient, _CountingStore]) -> None:
    client, store = served
    response = client.get("/r2effects/humo_denso/v2")
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    assert store.calls == [("size", "platform/effects/humo_denso/v2/preview.mp4")]


@pytest.mark.parametrize(
    "path",
    [
        # outside platform/effects/ or naming a file
        "/r2effects/humo_denso/v1/preview.mp4",
        "/r2effects/humo_denso/v1/other.mp4",
        "/r2effects/humo_denso/v1/",
        "/r2effects/humo_denso",
        "/r2effects/",
        "/r2effects",
        "/r2effects/t/a0000000-0000-4000-8000-000000000001/x/preview.mp4",
        # traversal and odd encodings
        "/r2effects/humo_denso/v1/..",
        "/r2effects/humo_denso/..%2Fv1",
        "/r2effects/humo_denso%2Fv1/v1",
        "/r2effects/%2e%2e/v1",
        "/r2effects/humo_denso/v1%00",
        "/r2effects/humo_denso/v1%2Fpreview.mp4",
        "/r2effects//humo_denso/v1",
        "/r2effects/humo_denso//v1",
        "/r2effects/humo%5Cdenso/v1",
        # malformed ids
        "/r2effects/Humo_denso/v1",
        "/r2effects/1humo/v1",
        "/r2effects/humo-denso/v1",
        "/r2effects/humo.denso/v1",
        "/r2effects/" + "a" * 41 + "/v1",
        # malformed versions
        "/r2effects/humo_denso/1",
        "/r2effects/humo_denso/v0",
        "/r2effects/humo_denso/v01",
        "/r2effects/humo_denso/v-1",
        "/r2effects/humo_denso/v1.mp4",
        "/r2effects/humo_denso/V1",
        "/r2effects/humo_denso/v10000",
        "/r2effects/humo_denso/v",
        "/r2effects/humo_denso/v%31",
    ],
)
def test_anything_else_is_a_404_without_calling_r2(
    served: tuple[TestClient, _CountingStore], path: str
) -> None:
    client, store = served
    for method in ("GET", "HEAD"):
        response = client.request(method, path)
        assert response.status_code == 404, (method, path)
    assert store.calls == []


def test_a_raw_dot_dot_path_never_reaches_r2(served: tuple[TestClient, _CountingStore]) -> None:
    """Straight into the ASGI app with a raw `..` (an HTTP client would normalise it)."""
    client, store = served
    app = client.app
    for raw in (
        "/r2effects/../t/x/v1",
        "/r2effects/humo_denso/../v1",
        "/r2effects/../v1",
        "/r2effects/./v1",
        "/r2effects/humo_denso/./v1",
    ):
        assert asyncio.run(_asgi_status(app, raw)) == 404, raw
    assert store.calls == []


async def _asgi_status(app: object, path: str) -> int:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 1),
        "server": ("testserver", 80),
    }
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    await app(scope, receive, send)  # type: ignore[operator]
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


def test_writes_are_not_allowed(served: tuple[TestClient, _CountingStore]) -> None:
    client, store = served
    for method in ("POST", "PUT", "DELETE", "PATCH"):
        assert client.request(method, "/r2effects/humo_denso/v1").status_code == 405
    assert store.calls == []


def test_the_door_builds_only_the_preview_key() -> None:
    assert platform_effects.preview_key("humo_denso", 1) == KEY
    assert platform_effects.preview_key("humo_denso", "1") == KEY
    for effect_id, version in [
        ("humo_denso", True),
        ("humo_denso", 0),
        ("humo_denso", "v1"),
        ("../t", 1),
        ("humo/denso", 1),
        (None, 1),
    ]:
        with pytest.raises(platform_effects.NotAnEffectPreview):
            platform_effects.preview_key(effect_id, version)


def test_the_route_for_a_key_and_back() -> None:
    assert routes.path_for_key(KEY) == "/r2effects/humo_denso/v1"
    assert routes.effect_preview_path("humo_denso", 3) == "/r2effects/humo_denso/v3"
    for key in [
        "platform/effects/humo_denso/v1/other.mp4",
        "platform/effects/humo_denso/v1/../preview.mp4",
        "platform/effects/humo_denso/v01/preview.mp4",
        "platform/effects/humo_denso/preview.mp4",
        "effects/humo_capa/v1/preview.webm",
        "t/a0000000-0000-4000-8000-000000000001/platform/effects/x/v1/preview.mp4",
        "",
        None,
    ]:
        assert routes.path_for_key(key) == "", key


def test_the_id_rule_is_the_librarys() -> None:
    assert f"^{platform_effects.EFFECT_ID_RE.pattern}$" == EFFECT_ID_PATTERN


def test_production_caddy_sends_r2effects_to_the_reflex_backend() -> None:
    caddyfile = (ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")
    match = re.search(r"^\s*@reflex_backend path (.+)$", caddyfile, re.M)
    assert match
    assert "/r2effects/*" in match[1].split()
    probes = (ROOT / "deploy" / "check-static-http.mjs").read_text(encoding="utf-8")
    assert "'/r2effects/probe/v1'" in probes
