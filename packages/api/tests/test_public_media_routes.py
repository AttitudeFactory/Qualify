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


def test_the_object_is_opened_off_the_event_loop(
    harness: tuple[TestClient, MediaTokenStore, MemoryStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Opening (and, for HEAD, reading) the object is blocking network I/O against R2:
    it runs in a worker thread so a slow object never stalls every other request."""
    client, token_store, store = harness
    offloaded: list[str] = []
    real = public_media_routes.asyncio.to_thread

    async def recording(fn, *args, **kwargs):
        offloaded.append(getattr(fn, "__name__", "?"))
        return await real(fn, *args, **kwargs)

    monkeypatch.setattr(public_media_routes.asyncio, "to_thread", recording)
    token = _issue_valid_token(token_store, store)
    assert client.get(f"/public/media/{token}").status_code == 200
    assert offloaded == ["_open_unpurged"]
    offloaded.clear()
    assert client.head(f"/public/media/{token}").status_code == 200
    assert offloaded == ["_open_unpurged"]


# -- m-24820842: length, ranges and ranged reads (BytePlus fetching reference videos) -------


class RangeStore(MemoryStore):
    """`R2ObjectStore`'s ranged API: `size` is a HEAD, `open_range` reads only the bytes
    asked. Every call is recorded — a whole-object `open` must never happen here."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple] = []

    def open(self, key: str) -> io.BytesIO:
        self.calls.append(("open", key))
        return super().open(key)

    def size(self, key: str) -> int:
        self.calls.append(("size", key))
        if key not in self.objects:
            raise ObjectNotFound(key)
        return len(self.objects[key][0])

    def open_range(self, key: str, start: int, end: int) -> io.BytesIO:
        self.calls.append(("range", start, end))
        return io.BytesIO(self.objects[key][0][start : end + 1])


VIDEO = bytes(range(256)) * 10_000  # 2.56 MB
JPEG = bytes.fromhex("ffd8ffe0") + b"fake-jpeg-bytes"


@pytest.fixture
def ranged() -> tuple[TestClient, MediaTokenStore, RangeStore, str]:
    store = RangeStore()
    token_store = MediaTokenStore(FakeRedis())
    app = create_app(configure_production=False)
    app.dependency_overrides[public_media_routes.get_media_token_store] = lambda: token_store
    app.dependency_overrides[public_media_routes.get_public_media_gate] = lambda: ObjectGate(store)
    key = f"t/{TENANT}/generated/d/r1/ref.mp4"
    store.objects[key] = (VIDEO, "video/mp4")
    token = token_store.issue(tenant_id=TENANT, object_key=key, content_type="video/mp4")
    return TestClient(app), token_store, store, token


def test_get_sends_its_length_and_streams_by_ranged_reads(ranged) -> None:  # noqa: ANN001
    client, _, store, token = ranged
    response = client.get(f"/public/media/{token}")
    assert response.status_code == 200
    assert response.headers["content-length"] == str(len(VIDEO))
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-type"] == "video/mp4"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.content == VIDEO
    reads = [c for c in store.calls if c[0] == "range"]
    assert reads[0] == ("range", 0, 1024 * 1024 - 1)  # the first byte after 1 MB, not 2.56
    assert len(reads) == 3 and ("open", f"t/{TENANT}/generated/d/r1/ref.mp4") not in store.calls


def test_head_reads_no_body(ranged) -> None:  # noqa: ANN001
    client, _, store, token = ranged
    response = client.head(f"/public/media/{token}")
    assert response.status_code == 200 and response.content == b""
    assert response.headers["content-length"] == str(len(VIDEO))
    assert response.headers["accept-ranges"] == "bytes"
    assert [c[0] for c in store.calls] == ["size"]


@pytest.mark.parametrize(
    ("header", "start", "end"),
    [("bytes=0-99", 0, 99), ("bytes=100-", 100, len(VIDEO) - 1), ("bytes=-50", len(VIDEO) - 50,
     len(VIDEO) - 1), ("bytes=10-99999999", 10, len(VIDEO) - 1)],
)  # fmt: skip
def test_a_single_range_is_a_206(ranged, header: str, start: int, end: int) -> None:  # noqa: ANN001
    client, _, _, token = ranged
    response = client.get(f"/public/media/{token}", headers={"Range": header})
    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes {start}-{end}/{len(VIDEO)}"
    assert response.headers["content-length"] == str(end - start + 1)
    assert response.content == VIDEO[start : end + 1]


def test_an_unsatisfiable_range_is_a_416_and_several_ranges_get_it_all(ranged) -> None:  # noqa: ANN001
    client, _, _, token = ranged
    response = client.get(f"/public/media/{token}", headers={"Range": f"bytes={len(VIDEO)}-"})
    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{len(VIDEO)}"
    several = client.get(f"/public/media/{token}", headers={"Range": "bytes=0-1,5-9"})
    assert several.status_code == 200 and several.content == VIDEO


@pytest.mark.parametrize("header", ["bytes=5-2", f"bytes={len(VIDEO) + 9}-{len(VIDEO) + 1}"])
def test_an_invalid_range_is_ignored_and_the_whole_object_sent(ranged, header: str) -> None:  # noqa: ANN001
    """Review N2: a last byte before the first is an invalid range-spec, not an
    unsatisfiable one; RFC 9110 §14.2 says to ignore the header (200, the whole body)."""
    client, _, _, token = ranged
    response = client.get(f"/public/media/{token}", headers={"Range": header})
    assert response.status_code == 200 and response.content == VIDEO
    assert "content-range" not in response.headers


def test_a_valid_range_past_the_end_is_still_a_416() -> None:
    from qualify_api.http.public_media_routes import parse_range

    assert parse_range("bytes=100-200", 100) is False
    assert parse_range("bytes=150-", 100) is False
    assert parse_range("bytes=5-2", 100) is None
    assert parse_range("bytes=5-5", 100) == (5, 5)


def test_a_store_without_ranges_still_sends_length_and_ranges(
    harness: tuple[TestClient, MediaTokenStore, MemoryStore],
) -> None:
    client, token_store, store = harness
    token = _issue_valid_token(token_store, store)
    whole = client.get(f"/public/media/{token}")
    assert whole.headers["content-length"] == str(len(JPEG))
    part = client.get(f"/public/media/{token}", headers={"Range": "bytes=0-3"})
    assert part.status_code == 206 and part.content == JPEG[:4]


def test_the_ranged_route_keeps_every_not_found_identical(ranged) -> None:  # noqa: ANN001
    client, token_store, store, _ = ranged
    foreign = token_store.issue(
        tenant_id=TENANT, object_key=f"t/{OTHER_TENANT}/x.mp4", content_type="video/mp4"
    )
    missing = token_store.issue(
        tenant_id=TENANT, object_key=f"t/{TENANT}/gone.mp4", content_type="video/mp4"
    )
    bodies = {
        (r.status_code, r.content)
        for r in (
            client.get("/public/media/nope", headers={"Range": "bytes=0-9"}),
            client.get(f"/public/media/{foreign}", headers={"Range": "bytes=0-9"}),
            client.get(f"/public/media/{missing}"),
        )
    }
    assert bodies == {(404, b'{"detail":"not found"}')}
    assert ("size", f"t/{OTHER_TENANT}/x.mp4") not in store.calls  # refused before the store


# -- m-24973446: a purged piece's objects may stay in R2 (bucket lock on `t/`) -------------

PURGED_DRAFT = UUID("77777777-7777-4777-8777-777777777777")
LIVE_DRAFT = UUID("88888888-8888-4888-8888-888888888888")


@pytest.fixture
def purged_lookup(monkeypatch: pytest.MonkeyPatch) -> list[tuple[UUID, UUID]]:
    from qualify_api.creative import purged_media

    asked: list[tuple[UUID, UUID]] = []

    def lookup(tenant_id: UUID, draft_id: UUID) -> bool:
        asked.append((tenant_id, draft_id))
        return draft_id == PURGED_DRAFT

    purged_media.clear_cache()
    monkeypatch.setattr(purged_media, "lookup", lookup)
    yield asked
    purged_media.clear_cache()


def test_an_object_of_a_purged_piece_answers_the_same_404_although_r2_holds_it(
    ranged, purged_lookup: list[tuple[UUID, UUID]]
) -> None:  # noqa: ANN001
    client, token_store, store, _ = ranged
    unknown = client.get("/public/media/never-issued")
    tokens = {}
    for draft in (PURGED_DRAFT, LIVE_DRAFT):
        key = f"t/{TENANT}/generated/{draft}/r1/video.mp4"
        store.objects[key] = (VIDEO, "video/mp4")
        tokens[draft] = token_store.issue(
            tenant_id=TENANT, object_key=key, content_type="video/mp4"
        )
    store.calls.clear()
    purged = f"/public/media/{tokens[PURGED_DRAFT]}"
    for response in (client.get(purged), client.get(purged, headers={"Range": "bytes=0-3"})):
        assert (response.status_code, response.content) == (404, unknown.content)
    assert client.head(purged).status_code == 404  # a HEAD carries no body
    assert store.calls == []  # refused before the store: not even a size probe
    assert client.get(f"/public/media/{tokens[LIVE_DRAFT]}").content == VIDEO
    assert (TENANT, PURGED_DRAFT) in purged_lookup


def test_keys_outside_a_piece_folder_never_ask_about_purges(
    harness: tuple[TestClient, MediaTokenStore, MemoryStore],
    purged_lookup: list[tuple[UUID, UUID]],
) -> None:
    client, token_store, store = harness
    token = _issue_valid_token(token_store, store)
    assert client.get(f"/public/media/{token}").status_code == 200
    assert purged_lookup == []
