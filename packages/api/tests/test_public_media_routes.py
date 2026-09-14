"""`GET/HEAD /public/media/{token}` (QUA-68), exercised end-to-end with zero network — the
route, a REAL `ObjectGate` (tenant-prefix revalidation exercised for real, not mocked), and
a `MediaTokenStore` over a fake Redis. Only the object STORE underneath the gate is faked,
same convention `test_publishing_routes.py` already uses for `ObjectGate`.

The four "not found" cases (unknown token, expired token, object outside the tenant prefix,
object missing entirely) are tested for BYTE-FOR-BYTE identical responses — that
indistinguishability is the actual security property this route exists to have, not an
incidental detail worth a looser assertion.
"""

from __future__ import annotations

import io
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from qualify_shared.objects.gate import ObjectGate, ObjectNotFound

from qualify_api.http import public_media_routes
from qualify_api.http.app import create_app
from qualify_api.publishing.media_token import MediaTokenStore

TENANT = UUID("55555555-5555-4555-8555-555555555555")
OTHER_TENANT = UUID("66666666-6666-4666-8666-666666666666")


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, name: str, value: str, *, ex: int | None = None) -> bool | None:
        self.store[name] = value
        return True

    def get(self, name: str) -> str | None:
        return self.store.get(name)


class MemoryStore:
    """Mirrors `R2ObjectStore`'s exception contract exactly (QUA-68 addition): a missing
    key raises `ObjectNotFound`, never a bare `KeyError` — this is what makes the offline
    test exercise the SAME branch `public_media_routes.py` catches for the real store."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, fileobj: io.IOBase, content_type: str) -> None:
        self.objects[key] = (fileobj.read(), content_type)

    def open(self, key: str) -> io.BytesIO:
        if key not in self.objects:
            raise ObjectNotFound(key)
        return io.BytesIO(self.objects[key][0])


@pytest.fixture
def harness() -> tuple[TestClient, MediaTokenStore, MemoryStore]:
    store = MemoryStore()
    gate = ObjectGate(store)
    token_store = MediaTokenStore(FakeRedis())

    app = create_app(configure_production=False)
    app.dependency_overrides[public_media_routes.get_media_token_store] = lambda: token_store
    app.dependency_overrides[public_media_routes.get_public_media_gate] = lambda: gate
    return TestClient(app), token_store, store


def _issue_valid_token(
    token_store: MediaTokenStore, store: MemoryStore, *, tenant_id: UUID = TENANT
) -> str:
    key = f"t/{tenant_id}/media/conn-1/img-1"
    store.objects[key] = (b"\xff\xd8\xff\xe0fake-jpeg-bytes", "image/jpeg")
    return token_store.issue(tenant_id=tenant_id, object_key=key, content_type="image/jpeg")


def test_valid_token_serves_the_bytes_with_the_right_content_type(
    harness: tuple[TestClient, MediaTokenStore, MemoryStore],
) -> None:
    client, token_store, store = harness
    token = _issue_valid_token(token_store, store)

    response = client.get(f"/public/media/{token}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == b"\xff\xd8\xff\xe0fake-jpeg-bytes"


def test_head_returns_no_body_but_the_right_headers(
    harness: tuple[TestClient, MediaTokenStore, MemoryStore],
) -> None:
    client, token_store, store = harness
    token = _issue_valid_token(token_store, store)

    response = client.head(f"/public/media/{token}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == b""


def test_unknown_token_is_404(harness: tuple[TestClient, MediaTokenStore, MemoryStore]) -> None:
    client, _, _ = harness

    response = client.get("/public/media/this-token-was-never-issued")

    assert response.status_code == 404


def test_expired_token_is_404(harness: tuple[TestClient, MediaTokenStore, MemoryStore]) -> None:
    client, token_store, store = harness
    token = _issue_valid_token(token_store, store)
    # Simulate TTL eviction the same way test_media_token.py does — deleting the entry
    # is indistinguishable from Redis expiring it, from resolve()'s point of view.
    for key in list(token_store._redis.store):  # noqa: SLF001 — test-only introspection
        del token_store._redis.store[key]  # noqa: SLF001

    response = client.get(f"/public/media/{token}")

    assert response.status_code == 404


def test_object_missing_despite_a_valid_token_is_404(
    harness: tuple[TestClient, MediaTokenStore, MemoryStore],
) -> None:
    client, token_store, store = harness
    key = f"t/{TENANT}/media/conn-1/img-gone"
    token = token_store.issue(tenant_id=TENANT, object_key=key, content_type="image/jpeg")
    # Deliberately never written to `store.objects` — the token is real, the object is not.

    response = client.get(f"/public/media/{token}")

    assert response.status_code == 404


def test_object_outside_the_tenant_prefix_is_404_never_the_object(
    harness: tuple[TestClient, MediaTokenStore, MemoryStore],
) -> None:
    """A token mapping whose `object_key` does not carry ITS OWN `tenant_id`'s prefix —
    structurally unreachable through `MediaTokenStore.issue()` as this codebase calls it,
    but `ObjectGate.open_object` re-checks on every read regardless (`require_tenant_
    prefix`), because a key read back from a store is still input. This proves that
    re-check actually fires for this route, not just for the video path."""
    client, token_store, store = harness
    mismatched_key = f"t/{OTHER_TENANT}/media/conn-1/img-1"
    store.objects[mismatched_key] = (b"leaked-bytes", "image/jpeg")
    token = token_store.issue(
        tenant_id=TENANT, object_key=mismatched_key, content_type="image/jpeg"
    )

    response = client.get(f"/public/media/{token}")

    assert response.status_code == 404


def test_every_not_found_case_is_byte_for_byte_identical(
    harness: tuple[TestClient, MediaTokenStore, MemoryStore],
) -> None:
    """The actual security property: none of these four failure modes may be
    distinguishable from any other by body, status, or Content-Type."""
    client, token_store, store = harness

    unknown = client.get("/public/media/never-issued")

    expired_token = _issue_valid_token(token_store, store, tenant_id=OTHER_TENANT)
    for key in list(token_store._redis.store):  # noqa: SLF001
        del token_store._redis.store[key]  # noqa: SLF001
    expired = client.get(f"/public/media/{expired_token}")

    missing_key = f"t/{TENANT}/media/conn-1/img-missing"
    missing_token = token_store.issue(
        tenant_id=TENANT, object_key=missing_key, content_type="image/jpeg"
    )
    missing_object = client.get(f"/public/media/{missing_token}")

    mismatched_key = f"t/{OTHER_TENANT}/media/conn-1/img-x"
    store.objects[mismatched_key] = (b"x", "image/jpeg")
    cross_tenant_token = token_store.issue(
        tenant_id=TENANT, object_key=mismatched_key, content_type="image/jpeg"
    )
    cross_tenant = client.get(f"/public/media/{cross_tenant_token}")

    responses = [unknown, expired, missing_object, cross_tenant]
    for response in responses:
        assert response.status_code == 404
        assert response.content == responses[0].content
        assert response.headers["content-type"] == responses[0].headers["content-type"]


def test_post_is_405(harness: tuple[TestClient, MediaTokenStore, MemoryStore]) -> None:
    client, token_store, store = harness
    token = _issue_valid_token(token_store, store)

    response = client.post(f"/public/media/{token}")

    assert response.status_code == 405


def test_response_never_carries_a_cacheable_header(
    harness: tuple[TestClient, MediaTokenStore, MemoryStore],
) -> None:
    """A live, working link must not be cached by an intermediary past its own TTL."""
    client, token_store, store = harness
    token = _issue_valid_token(token_store, store)

    response = client.get(f"/public/media/{token}")

    assert response.headers["cache-control"] == "private, no-store"
