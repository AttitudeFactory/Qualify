"""m-24976895 — previews of seasonal media: tokens only for THIS business's exact
seasonal keys, in their own namespace, served only through `open_seasonal_media`."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_api.publishing.media_token import MediaTokenStore
from qualify_shared.objects.gate import ObjectGate
from qualify_shared.objects.keys import TenantPrefixViolation
from qualify_shared.objects.memory import MemoryObjectStore

from .seasonal_media import (
    issue_seasonal_view_path,
    require_seasonal_key,
    seasonal_token_store,
    serve,
)

TENANT = UUID("a0000000-0000-4000-8000-000000976895")
BRAND = UUID("c0000000-0000-4000-8000-000000976895")
OTHER = UUID("a1000000-0000-4000-8000-000000976895")
MEDIA = "1b2c3d4e-0000-4000-8000-000000000001"
#: The gate's validation reads no store: an in-memory one stands in for R2.
GATE = ObjectGate(MemoryObjectStore(locked=False))


def _key(tenant: UUID = TENANT, brand: UUID = BRAND, ext: str = "webp", attempt: str = "1") -> str:
    """The gate's shape since 927d9726: `{media_id}-{attempt}.{ext}` (attempt 1–3)."""
    return f"seasonal/{tenant}/{brand}/navidad-2026/{MEDIA}-{attempt}.{ext}"


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def set(self, name: str, value: str, *, ex: int | None = None) -> bool:
        self.data[name] = value
        return True

    def get(self, name: str) -> str | None:
        return self.data.get(name)


def test_only_this_business_exact_keys_get_a_token() -> None:
    redis = FakeRedis()
    store = seasonal_token_store(redis)
    good = issue_seasonal_view_path(TENANT, BRAND, _key(), store=store, gate=GATE)
    assert good.startswith("/r2seasonal/")
    assert require_seasonal_key(TENANT, BRAND, _key(ext="mp4"), gate=GATE) == "video/mp4"
    assert require_seasonal_key(TENANT, BRAND, _key(), gate=GATE) == "image/webp"
    assert require_seasonal_key(TENANT, BRAND, _key(attempt="3"), gate=GATE) == "image/webp"
    # m-25016851: «Pedir otro» has no cap of three — a later attempt still gets a preview
    assert require_seasonal_key(TENANT, BRAND, _key(attempt="12"), gate=GATE) == "image/webp"
    refused = (
        _key(tenant=OTHER),  # another tenant
        _key(brand=uuid4()),  # another business of the same tenant
        f"t/{TENANT}/pieces/{MEDIA}.webp",  # a piece, not seasonal
        f"gallery/{TENANT}/{MEDIA}/a.webp",
        _key(ext="png"),  # not webp|mp4
        f"seasonal/{TENANT}/{BRAND}/navidad-2026/../x/{MEDIA}-1.webp",
        f"seasonal/{TENANT}/{BRAND}//navidad-2026/{MEDIA}-1.webp",
        f"seasonal/{TENANT}/{BRAND}/navidad-2026/sub/{MEDIA}-1.webp",
        f"seasonal/{TENANT}/{BRAND}/navidad-2026/not-a-uuid.webp",
        f"seasonal/{TENANT}/{BRAND}/{MEDIA}-1.webp",  # no season folder
        _key(attempt="100"),  # past the technical ceiling (99)
        _key(attempt="0"),
        f"seasonal/{TENANT}/{BRAND}/navidad-2026/{MEDIA}.webp",  # no attempt
        "",
    )
    for key in refused:
        assert issue_seasonal_view_path(TENANT, BRAND, key, store=store, gate=GATE) == "", key
        if key:
            with pytest.raises(TenantPrefixViolation):
                require_seasonal_key(TENANT, BRAND, key, gate=GATE)
    assert len(redis.data) == 1 and all(k.startswith("seasonal:") for k in redis.data)


def test_the_two_token_namespaces_never_resolve_each_other() -> None:
    redis = FakeRedis()
    seasonal = seasonal_token_store(redis)
    generic = MediaTokenStore(redis)
    path = issue_seasonal_view_path(TENANT, BRAND, _key(), store=seasonal, gate=GATE)
    token = path.rsplit("/", 1)[-1]
    assert seasonal.resolve(token) is not None
    assert generic.resolve(token) is None  # /r2media cannot serve it
    other = generic.issue(tenant_id=TENANT, object_key=_key(), content_type="image/webp")
    assert seasonal.resolve(other) is None  # /r2seasonal cannot serve a generic token


def _request(method: str = "GET", range_header: str = "") -> Any:
    headers = {"range": range_header} if range_header else {}
    return SimpleNamespace(method=method, headers=headers)


def test_the_route_serves_through_the_gate_only() -> None:
    redis, objects = FakeRedis(), MemoryObjectStore(locked=False)
    store, gate = seasonal_token_store(redis), ObjectGate(objects)
    objects.objects[_key(ext="mp4")] = b"0123456789"
    token = issue_seasonal_view_path(TENANT, BRAND, _key(ext="mp4"), store=store, gate=GATE).rsplit(
        "/"
    )[-1]

    whole = asyncio.run(serve(token, _request(), store, gate))
    assert whole.status_code == 200 and whole.body == b"0123456789"
    assert whole.media_type == "video/mp4" and "private" in whole.headers["cache-control"]
    part = asyncio.run(serve(token, _request(range_header="bytes=2-4"), store, gate))
    assert part.status_code == 206 and part.body == b"234"
    assert part.headers["content-range"] == "bytes 2-4/10"
    head = asyncio.run(serve(token, _request("HEAD"), store, gate))
    assert head.status_code == 200 and head.headers["content-length"] == "10"
    assert asyncio.run(serve("no-such-token", _request(), store, gate)).status_code == 404

    # a token whose key the gate refuses (minted around the issuer) is the same 404
    bad = store.issue(
        tenant_id=TENANT, object_key=f"t/{TENANT}/x/{MEDIA}.mp4", content_type="video/mp4"
    )
    assert asyncio.run(serve(bad, _request(), store, gate)).status_code == 404
    other_tenant = store.issue(tenant_id=OTHER, object_key=_key(ext="mp4"), content_type="x")
    assert asyncio.run(serve(other_tenant, _request(), store, gate)).status_code == 404


def test_a_refresh_reuses_the_token_of_a_key() -> None:
    store = seasonal_token_store(FakeRedis())
    first = issue_seasonal_view_path(TENANT, BRAND, _key(attempt="2"), store=store, gate=GATE)
    again = issue_seasonal_view_path(TENANT, BRAND, _key(attempt="2"), store=store, gate=GATE)
    assert first and first == again  # the browser keeps its cached preview
    other = issue_seasonal_view_path(TENANT, BRAND, _key(attempt="3"), store=store, gate=GATE)
    assert other != first


def test_the_token_cache_is_pruned_on_insert(monkeypatch: pytest.MonkeyPatch) -> None:
    from . import seasonal_media

    store = seasonal_token_store(FakeRedis())
    clock = [1000.0]
    monkeypatch.setattr(seasonal_media.time, "monotonic", lambda: clock[0])
    seasonal_media._issued.clear()
    issue_seasonal_view_path(TENANT, BRAND, _key(attempt="1"), store=store, gate=GATE)
    assert len(seasonal_media._issued) == 1
    clock[0] += seasonal_media.VIEW_TTL_SECONDS  # the first token is past its margin
    issue_seasonal_view_path(TENANT, BRAND, _key(attempt="2"), store=store, gate=GATE)
    assert len(seasonal_media._issued) == 1  # the stale entry went on that insert
