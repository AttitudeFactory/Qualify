"""`GET/HEAD /public/catalog-media/{tenant_id}/{media_id}/{sig}.jpg` (ADR 48 §8), end to end
with zero network: the route, a REAL `ObjectGate` (tenant-prefix check for real) over an
in-memory store, and a fake lookup in place of Postgres. Every failure must answer the
same 404 byte for byte, and a bad signature must never reach the lookup."""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from qualify_shared.objects.gate import ObjectGate
from qualify_shared.objects.memory import MemoryObjectStore

from qualify_api.http import public_catalog_media_routes as routes
from qualify_api.http.app import create_app
from qualify_api.whatsapp.catalog_sync import media_url

TENANT = UUID("55555555-5555-4555-8555-555555555555")
OTHER = UUID("66666666-6666-4666-8666-666666666666")
MEDIA = UUID("77777777-7777-4777-8777-777777777777")
DELETED_ITEM_MEDIA = UUID("88888888-8888-4888-8888-888888888888")
MISSING_OBJECT_MEDIA = UUID("99999999-9999-4999-8999-999999999999")
FOREIGN_KEY_MEDIA = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
BYTES = b"\xff\xd8\xff\xe0" + b"j" * 100


class _Lookup:
    """What `lookup_catalog_media` would answer: a row only for a media of THIS tenant
    whose product has a live item."""

    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID]] = []
        self.rows = {
            (TENANT, MEDIA): routes.CatalogMediaTarget(f"t/{TENANT}/catalog/a.jpg", "image/jpeg"),
            (TENANT, MISSING_OBJECT_MEDIA): routes.CatalogMediaTarget(
                f"t/{TENANT}/catalog/gone.jpg", "image/jpeg"
            ),
            # A key outside the tenant's roots (a corrupted row): the gate refuses it.
            (TENANT, FOREIGN_KEY_MEDIA): routes.CatalogMediaTarget(
                f"t/{OTHER}/catalog/a.jpg", "image/jpeg"
            ),
        }

    def __call__(self, tenant_id: UUID, media_id: UUID) -> routes.CatalogMediaTarget | None:
        self.calls.append((tenant_id, media_id))
        return self.rows.get((tenant_id, media_id))


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, _Lookup]:
    monkeypatch.setenv(media_url.SECRET_ENV, "k" * 40)
    monkeypatch.setenv(media_url.BASE_URL_ENV, "https://qualify.example")
    store = MemoryObjectStore()
    store.objects[f"t/{TENANT}/catalog/a.jpg"] = BYTES
    store.objects[f"t/{OTHER}/catalog/a.jpg"] = BYTES
    lookup = _Lookup()
    app = create_app(configure_production=False)
    app.dependency_overrides[routes.get_catalog_media_lookup] = lambda: lookup
    app.dependency_overrides[routes.get_catalog_media_gate] = lambda: ObjectGate(store)
    return TestClient(app), lookup


def _path(tenant: UUID, media: UUID, sig: str | None = None) -> str:
    return f"/public/catalog-media/{tenant}/{media}/{sig or media_url.sign(tenant, media)}.jpg"


def test_the_built_url_is_the_route(harness: tuple[TestClient, _Lookup]) -> None:
    client, _ = harness
    url = media_url.catalog_media_url(TENANT, MEDIA)
    assert url == "https://qualify.example" + _path(TENANT, MEDIA)
    assert client.get(url.removeprefix("https://qualify.example")).status_code == 200


def test_a_good_signature_serves_the_photo(harness: tuple[TestClient, _Lookup]) -> None:
    client, _ = harness
    response = client.get(_path(TENANT, MEDIA))
    assert response.status_code == 200
    assert response.content == BYTES
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["content-length"] == str(len(BYTES))
    assert response.headers["cache-control"] == "public, max-age=86400"


def test_head_and_ranges(harness: tuple[TestClient, _Lookup]) -> None:
    client, _ = harness
    head = client.head(_path(TENANT, MEDIA))
    assert head.status_code == 200 and head.content == b""
    assert head.headers["content-length"] == str(len(BYTES))
    ranged = client.get(_path(TENANT, MEDIA), headers={"Range": "bytes=0-3"})
    assert ranged.status_code == 206
    assert ranged.content == BYTES[:4]
    assert ranged.headers["content-range"] == f"bytes 0-3/{len(BYTES)}"


def _not_found(client: TestClient, path: str) -> bytes:
    response = client.get(path)
    assert response.status_code == 404
    return response.content


def test_every_failure_is_the_same_404(harness: tuple[TestClient, _Lookup]) -> None:
    client, lookup = harness
    good_sig = media_url.sign(TENANT, MEDIA)
    bad_sig = ("A" if good_sig[0] != "A" else "B") + good_sig[1:]
    bodies = {
        "bad signature": _not_found(client, _path(TENANT, MEDIA, bad_sig)),
        "signature of another media": _not_found(
            client, f"/public/catalog-media/{TENANT}/{MEDIA}/{media_url.sign(TENANT, OTHER)}.jpg"
        ),
        "another tenant's media": _not_found(client, _path(OTHER, MEDIA)),
        "unknown media": _not_found(client, _path(TENANT, UUID(int=5))),
        "deleted item": _not_found(client, _path(TENANT, DELETED_ITEM_MEDIA)),
        "missing object": _not_found(client, _path(TENANT, MISSING_OBJECT_MEDIA)),
        "key outside the tenant": _not_found(client, _path(TENANT, FOREIGN_KEY_MEDIA)),
        "not a uuid": _not_found(client, f"/public/catalog-media/nope/{MEDIA}/{good_sig}.jpg"),
        "uuid without hyphens": _not_found(
            client, f"/public/catalog-media/{TENANT.hex}/{MEDIA}/{good_sig}.jpg"
        ),
        "no .jpg": _not_found(client, f"/public/catalog-media/{TENANT}/{MEDIA}/{good_sig}"),
    }
    assert set(bodies.values()) == {b'{"detail":"not found"}'}
    # Signature failures never reach the database.
    assert (TENANT, MEDIA) not in lookup.calls


def test_bad_signature_never_reads_the_database(harness: tuple[TestClient, _Lookup]) -> None:
    client, lookup = harness
    _not_found(client, _path(TENANT, MEDIA, "x" * 43))
    assert lookup.calls == []


@pytest.mark.parametrize("secret", ["", "dev-only-state-secret-not-for-production", "short"])
def test_an_unusable_secret_answers_404(
    harness: tuple[TestClient, _Lookup], monkeypatch: pytest.MonkeyPatch, secret: str
) -> None:
    client, lookup = harness
    path = _path(TENANT, MEDIA)  # signed with the good secret
    monkeypatch.setenv(media_url.SECRET_ENV, secret)
    assert _not_found(client, path) == b'{"detail":"not found"}'
    assert lookup.calls == []
