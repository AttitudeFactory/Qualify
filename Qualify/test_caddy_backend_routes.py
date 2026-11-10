"""m-24986798 — every route the Reflex backend app serves must be routed to it by the
production Caddy, and a seasonal medium goes the whole way: signed → `/r2seasonal/…` →
served by the mounted route with the type of its extension.

The incident: the seasonal previews (`/r2seasonal/<token>`, m-24976895) were mounted on
the backend app but `deploy/Caddyfile` only sent `/r2media/*` and `/avatar/*` there, so
every preview fell through to the SPA's 404 page (an HTML body, not the medium). «Descargar»
(`/piece-download/<token>`) had the same gap.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from qualify_shared.objects.gate import ObjectGate
from qualify_shared.objects.memory import MemoryObjectStore

from . import piece_download, r2_media, seasonal_media
from .avatar_proxy import avatar_api

ROOT = Path(__file__).resolve().parent.parent
CADDYFILE = ROOT / "deploy" / "Caddyfile"
APP_MODULE = Path(__file__).resolve().parent / "Qualify.py"

TENANT = UUID("a0000000-0000-4000-8000-000000986798")
BRAND = UUID("c0000000-0000-4000-8000-000000986798")
OTHER_TENANT = UUID("a1000000-0000-4000-8000-000000986798")
OTHER_BRAND = UUID("c1000000-0000-4000-8000-000000986798")
MEDIA = "5e7a1b2c-0000-4000-8000-000000986798"


def _key(tenant: UUID = TENANT, brand: UUID = BRAND, ext: str = "webp") -> str:
    """The exact key `ObjectGate.put_seasonal_media` writes (attempt 1)."""
    return f"seasonal/{tenant}/{brand}/navidad/{MEDIA}-1.{ext}"


def _reflex_backend_matcher() -> set[str]:
    match = re.search(r"^\s*@reflex_backend path (.+)$", CADDYFILE.read_text(), re.M)
    assert match, "deploy/Caddyfile lost its @reflex_backend matcher"
    return set(match[1].split())


def _first_segment(path: str) -> str:
    return "/" + path.lstrip("/").split("/", 1)[0]


def test_the_app_mounts_exactly_the_routers_this_test_knows() -> None:
    """A new router on the backend app must be added here AND to the Caddyfile."""
    mounted = re.findall(r"avatar_api\.include_router\((\w+)\)", APP_MODULE.read_text())
    assert sorted(mounted) == sorted(
        ["r2_media_router", "seasonal_media_router", "piece_download_router"]
    )
    # ...and the backend app is still `avatar_api` (plus the upload fallback) only.
    assert re.search(r"api_transformer=\[avatar_api, upload_fallback\]", APP_MODULE.read_text())


@pytest.mark.parametrize(
    "routes",
    [
        avatar_api.routes,
        r2_media.router.routes,
        seasonal_media.router.routes,
        piece_download.router.routes,
    ],
    ids=["avatar_api", "r2_media", "seasonal_media", "piece_download"],
)
def test_every_backend_route_is_proxied_by_caddy(routes: list) -> None:
    matcher = _reflex_backend_matcher()
    for route in routes:
        path = getattr(route, "path", "")
        if not path or path.startswith(("/docs", "/openapi", "/redoc")):
            continue  # FastAPI's own pages, never linked by the app
        segment = _first_segment(path)
        assert f"{segment}/*" in matcher, f"{path} is not routed to reflex:8000"


def test_the_upstream_smoke_probes_the_seasonal_and_download_routes() -> None:
    probes = (ROOT / "deploy" / "check-static-http.mjs").read_text()
    assert "'/r2seasonal/probe.webp'" in probes and "'/piece-download/probe.zip'" in probes


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def set(self, name: str, value: str, *, ex: int | None = None) -> bool:
        self.data[name] = value
        return True

    def get(self, name: str) -> str | None:
        return self.data.get(name)


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, MemoryObjectStore]]:
    """The production route on a FastAPI app, over an in-memory token store and an
    `ObjectGate` on an in-memory object store (no Redis, no R2)."""
    objects = MemoryObjectStore(locked=False)
    store = seasonal_media.seasonal_token_store(_FakeRedis())
    gate = ObjectGate(objects)
    monkeypatch.setattr(seasonal_media, "_token_store", lambda: store)
    monkeypatch.setattr(seasonal_media, "_gate", lambda: gate)
    seasonal_media._issued.clear()
    app = FastAPI()
    app.include_router(seasonal_media.router)
    yield TestClient(app), objects
    seasonal_media._issued.clear()


@pytest.mark.parametrize(("ext", "content_type"), [("webp", "image/webp"), ("mp4", "video/mp4")])
def test_a_seasonal_medium_is_signed_and_served_with_its_type(
    served: tuple[TestClient, MemoryObjectStore], ext: str, content_type: str
) -> None:
    client, objects = served
    objects.objects[_key(ext=ext)] = b"RIFF-or-ftyp-bytes"
    path = seasonal_media.issue_seasonal_view_path(TENANT, BRAND, _key(ext=ext))
    assert path.startswith(seasonal_media.SEASONAL_MEDIA_ROUTE + "/")
    assert _first_segment(path) + "/*" in _reflex_backend_matcher()

    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"] == content_type
    assert response.content == b"RIFF-or-ftyp-bytes"
    ranged = client.get(path, headers={"Range": "bytes=0-3"})
    assert ranged.status_code == 206 and ranged.content == b"RIFF"
    assert ranged.headers["content-type"] == content_type


def test_another_tenants_or_businesss_medium_is_never_signed_nor_served(
    served: tuple[TestClient, MemoryObjectStore],
) -> None:
    client, objects = served
    foreign = [_key(tenant=OTHER_TENANT), _key(brand=OTHER_BRAND)]
    for key in foreign:
        objects.objects[key] = b"not yours"
        assert seasonal_media.issue_seasonal_view_path(TENANT, BRAND, key) == ""

    # A token minted around the issuer for ANOTHER TENANT's key is the same 404: the route
    # re-checks the key against the token's tenant. (The business is bound at issuance —
    # only `issue_seasonal_view_path` with the session's business mints these tokens.)
    store = seasonal_media._token_store()
    token = store.issue(tenant_id=TENANT, object_key=foreign[0], content_type="image/webp")
    assert client.get(f"{seasonal_media.SEASONAL_MEDIA_ROUTE}/{token}").status_code == 404


def test_the_generic_r2media_signer_never_signs_a_seasonal_key() -> None:
    """Seasonal media stay behind their business-bound door: the generic signer is bound
    to the tenant only, so it must not name them (m-24976895)."""
    assert r2_media.issue_view_path(TENANT, _key(), "image", store=object()) == ""
