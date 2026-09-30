"""R2-only media on the draft screen and the Planificador (`r2_media.py`).

No R2, no Redis: an in-memory object store behind the REAL `ObjectGate` (so the tenant-
prefix check is the production one) and a dict behind the REAL `MediaTokenStore` (so
tokens are hashed and resolved exactly as in production). The route under test is the
real `r2_media.router`, served by FastAPI's TestClient.
"""

from __future__ import annotations

import io
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from qualify_api.publishing.media_token import MediaTokenStore
from qualify_shared.objects.gate import ObjectGate, ObjectNotFound

from . import creative_provider, planner_provider, r2_media
from .creative_vm import MediaVM, build_media_vms

TENANT_A = UUID("a0000000-0000-4000-8000-00000000000a")
TENANT_B = UUID("b0000000-0000-4000-8000-00000000000b")
KEY_A = f"t/{TENANT_A}/media/c1/video-a"
KEY_B = f"t/{TENANT_B}/media/c2/video-b"
VIDEO = b"\x00\x00\x00\x18ftypmp42-fake-video-bytes"
KEY_BIG = f"t/{TENANT_A}/media/c1/big-video"
BIG = bytes(range(256)) * (3 * 1024 * 1024 // 256)  # 3 MiB, above MAX_RANGE_BYTES


class _Redis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def set(self, name: str, value: str, *, ex: int | None = None) -> bool:
        self.data[name] = value
        return True

    def get(self, name: str) -> str | None:
        return self.data.get(name)


class _Store:
    """The raw object sink the gate wraps: knows nothing about tenants, like R2."""

    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.full_reads: list[str] = []
        self.range_reads: list[tuple[str, int, int]] = []

    def put(self, key: str, fileobj, content_type: str) -> None:  # pragma: no cover
        self.objects[key] = fileobj.read()

    def open(self, key: str):
        if key not in self.objects:
            raise ObjectNotFound(key)
        self.full_reads.append(key)
        return io.BytesIO(self.objects[key])

    def size(self, key: str) -> int:
        if key not in self.objects:
            raise ObjectNotFound(key)
        return len(self.objects[key])

    def open_range(self, key: str, start: int, end: int):
        if key not in self.objects:
            raise ObjectNotFound(key)
        self.range_reads.append((key, start, end))
        return io.BytesIO(self.objects[key][start : end + 1])


@pytest.fixture
def backend(monkeypatch):
    tokens = MediaTokenStore(_Redis(), ttl_seconds=r2_media.VIEW_TTL_SECONDS)
    store = _Store({KEY_A: VIDEO, KEY_B: b"tenant-b-secret", KEY_BIG: BIG})
    gate = ObjectGate(store)
    monkeypatch.setattr(r2_media, "_token_store", lambda: tokens)
    monkeypatch.setattr(r2_media, "_issued", {})  # no path minted by another test
    monkeypatch.setattr(r2_media, "_gate", lambda: gate)
    app = FastAPI()
    app.include_router(r2_media.router)
    client = TestClient(app)
    client.store = store  # type: ignore[attr-defined]
    return client, tokens


# --- minting: only the viewer's own R2 objects ------------------------------------------


def test_a_valid_r2_video_is_served_with_its_type(backend) -> None:
    client, _ = backend
    path = r2_media.issue_view_path(TENANT_A, KEY_A, "video")
    assert path.startswith("/r2media/") and KEY_A not in path  # opaque, not the key
    response = client.get(path)
    assert response.status_code == 200
    assert response.content == VIDEO
    assert response.headers["content-type"] == "video/mp4"
    assert response.headers["cache-control"] == "private, no-store"
    assert "content-disposition" not in response.headers


def test_download_asks_the_browser_to_save_the_file(backend) -> None:
    client, _ = backend
    path = r2_media.issue_view_path(TENANT_A, KEY_A, "video")
    response = client.get(path + "?download=1")
    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="qualify-media.mp4"'


def test_a_head_request_answers_without_reading_the_object(backend) -> None:
    client, _ = backend
    response = client.head(r2_media.issue_view_path(TENANT_A, KEY_A, "video"))
    assert response.status_code == 200 and response.content == b""
    assert response.headers["content-length"] == str(len(VIDEO))
    assert response.headers["accept-ranges"] == "bytes"
    assert client.store.full_reads == [] and client.store.range_reads == []


# --- HTTP Range: what a <video> actually asks for ------------------------------------------


def test_a_byte_range_returns_exactly_those_bytes(backend) -> None:
    client, _ = backend
    path = r2_media.issue_view_path(TENANT_A, KEY_A, "video")
    response = client.get(path, headers={"Range": "bytes=4-7"})
    assert response.status_code == 206
    assert response.content == VIDEO[4:8]
    assert response.headers["content-range"] == f"bytes 4-7/{len(VIDEO)}"
    assert response.headers["content-type"] == "video/mp4"
    assert client.store.full_reads == []  # only the range was read from the store


def test_an_open_ended_range_is_capped_so_a_card_never_pulls_a_whole_reel(backend) -> None:
    client, _ = backend
    path = r2_media.issue_view_path(TENANT_A, KEY_BIG, "video")
    response = client.get(path, headers={"Range": "bytes=0-"})
    cap = r2_media.MAX_RANGE_BYTES
    assert response.status_code == 206
    assert len(response.content) == cap
    assert response.headers["content-range"] == f"bytes 0-{cap - 1}/{len(BIG)}"
    assert client.store.range_reads == [(KEY_BIG, 0, cap - 1)]


def test_a_suffix_range_returns_the_last_bytes(backend) -> None:
    client, _ = backend
    path = r2_media.issue_view_path(TENANT_A, KEY_A, "video")
    response = client.get(path, headers={"Range": "bytes=-5"})
    assert response.status_code == 206 and response.content == VIDEO[-5:]


def test_an_unsatisfiable_range_is_a_416(backend) -> None:
    client, _ = backend
    path = r2_media.issue_view_path(TENANT_A, KEY_A, "video")
    response = client.get(path, headers={"Range": f"bytes={len(VIDEO) + 10}-"})
    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{len(VIDEO)}"


def test_a_range_header_this_route_does_not_understand_serves_the_whole_object(backend) -> None:
    client, _ = backend
    path = r2_media.issue_view_path(TENANT_A, KEY_A, "video")
    response = client.get(path, headers={"Range": "bytes=0-1,4-5"})
    assert response.status_code == 200 and response.content == VIDEO


def test_a_ranged_request_for_another_tenants_object_is_still_a_404(backend) -> None:
    client, tokens = backend
    forged = tokens.issue(tenant_id=TENANT_A, object_key=KEY_B, content_type="video/mp4")
    response = client.get(f"{r2_media.R2_MEDIA_ROUTE}/{forged}", headers={"Range": "bytes=0-"})
    assert response.status_code == 404
    assert b"tenant-b-secret" not in response.content


def test_a_ranged_request_for_a_missing_object_is_the_same_404(backend) -> None:
    client, _ = backend
    path = r2_media.issue_view_path(TENANT_A, f"t/{TENANT_A}/media/c1/gone", "video")
    response = client.get(path, headers={"Range": "bytes=0-"})
    assert response.status_code == 404
    assert response.content == b'{"detail":"not found"}'


@pytest.mark.parametrize(
    ("header", "size", "expected"),
    [
        ("bytes=0-99", 1000, (0, 99)),
        ("bytes=900-", 1000, (900, 999)),
        ("bytes=-100", 1000, (900, 999)),
        ("bytes=0-5000", 1000, (0, 999)),
        ("bytes=1000-", 1000, None),
        ("bytes=10-5", 1000, None),
    ],
)
def test_parse_range(header: str, size: int, expected) -> None:
    assert r2_media.parse_range(header, size) == expected


@pytest.mark.parametrize("header", ["bytes=0-1,3-4", "items=0-1", "bytes=-", "garbage"])
def test_parse_range_refuses_what_it_does_not_understand(header: str) -> None:
    with pytest.raises(ValueError):
        r2_media.parse_range(header, 1000)


def test_no_url_is_minted_for_another_tenants_object(backend) -> None:
    _, tokens = backend
    assert r2_media.issue_view_path(TENANT_A, KEY_B, "video") == ""


def test_a_token_naming_another_tenants_object_is_refused_on_the_way_out(backend) -> None:
    """Defence in depth: even a token whose mapping pairs tenant A with tenant B's key
    (never minted by `issue_view_path`) gets the gate's prefix refusal → 404."""
    client, tokens = backend
    forged = tokens.issue(tenant_id=TENANT_A, object_key=KEY_B, content_type="video/mp4")
    response = client.get(f"{r2_media.R2_MEDIA_ROUTE}/{forged}")
    assert response.status_code == 404
    assert b"tenant-b-secret" not in response.content


@pytest.mark.parametrize("key", ["generated/a0/d1/video.mp4", "uploads/x.png", "", "https://x"])
def test_keys_outside_r2_keep_the_local_path(key: str, backend) -> None:
    assert r2_media.issue_view_path(TENANT_A, key, "video") == ""


# --- the single 404 -----------------------------------------------------------------------


def test_an_unknown_token_is_a_404(backend) -> None:
    client, _ = backend
    response = client.get(f"{r2_media.R2_MEDIA_ROUTE}/not-a-real-token")
    assert response.status_code == 404
    assert response.content == b'{"detail":"not found"}'


def test_a_missing_object_is_the_same_404(backend) -> None:
    client, _ = backend
    gone = f"t/{TENANT_A}/media/c1/deleted"
    path = r2_media.issue_view_path(TENANT_A, gone, "video")
    response = client.get(path)
    assert response.status_code == 404
    assert response.content == b'{"detail":"not found"}'


# --- the draft screen and the Planificador dialog ----------------------------------------


def test_the_draft_screen_gets_urls_only_for_r2_media(backend) -> None:
    media = build_media_vms(
        [
            (KEY_A, "video", 0, None),
            ("generated/a/d/image.jpg", "image", 1, None),
        ]
    )
    out = creative_provider._with_r2_urls(TENANT_A, media)
    assert out[0].url.startswith("/r2media/")
    assert out[1].url == ""  # local upload store, resolved by the page as before


def test_no_media_means_no_urls_and_no_tokens(backend) -> None:
    _, tokens = backend
    assert creative_provider._with_r2_urls(TENANT_A, ()) == ()
    assert planner_provider._video_url(TENANT_A, None) == ""
    assert tokens._redis.data == {}


def test_a_token_that_cannot_be_minted_only_costs_the_preview(monkeypatch) -> None:
    def _down():
        raise ConnectionError("redis down")

    monkeypatch.setattr(r2_media, "_token_store", _down)
    (item,) = creative_provider._with_r2_urls(TENANT_A, (MediaVM(KEY_A, "video", 0, "Video"),))
    assert item.url == ""
    assert planner_provider._video_url(TENANT_A, KEY_A) == ""


def test_the_planner_dialog_gets_a_playable_url(backend) -> None:
    client, _ = backend
    path = planner_provider._video_url(TENANT_A, KEY_A)
    assert client.get(path).content == VIDEO


# --- the Planificador cards (list + calendar) ------------------------------------------------


def test_the_week_mints_one_url_per_post_with_an_r2_video(backend) -> None:
    from types import SimpleNamespace
    from uuid import uuid4

    _, tokens = backend
    reel, image = uuid4(), uuid4()

    def planned(post_id, key):
        return SimpleNamespace(post=SimpleNamespace(post_id=post_id, video_object_key=key))

    urls = planner_provider._week_video_urls(
        TENANT_A,
        [
            planned(reel, KEY_A),
            planned(reel, KEY_A),
            planned(image, None),
            SimpleNamespace(post=None),
        ],
    )
    assert list(urls) == [str(reel)]  # the same POST scheduled twice → one token
    assert urls[str(reel)].startswith("/r2media/")
    assert len(tokens._redis.data) == 1


def test_a_card_carries_the_video_url_it_was_given() -> None:
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    from .planner_vm import CardInput, build_card

    card = build_card(
        CardInput(
            event_id="e1",
            post_id="p1",
            scheduled_at=datetime(2026, 9, 29, 21, 20, tzinfo=UTC),
            status="published",
            overdue=False,
            connection_id="c1",
            post_title="Reel",
            video_url="/r2media/tok",
        ),
        zone=ZoneInfo("America/Caracas"),
        connections={"c1": ("instagram", "@qualifymkt.co")},
    )
    assert card.video_url == "/r2media/tok"


# --- one browser cache entry per video (2026-09-30 measurement) ------------------------------


def test_the_same_video_gets_the_same_url_so_cards_and_dialog_share_the_cache(backend) -> None:
    _, tokens = backend
    first = r2_media.issue_view_path(TENANT_A, KEY_A, "video")
    again = r2_media.issue_view_path(TENANT_A, KEY_A, "video")
    other_video = r2_media.issue_view_path(TENANT_A, KEY_BIG, "video")
    assert first == again and first != other_video
    assert len(tokens._redis.data) == 2  # one token per video, not per card
    # Another tenant never gets that URL (it gets no URL at all for A's key).
    assert r2_media.issue_view_path(TENANT_B, KEY_A, "video") == ""


def test_a_path_close_to_expiry_is_not_reused(backend, monkeypatch) -> None:
    first = r2_media.issue_view_path(TENANT_A, KEY_A, "video")
    real = r2_media.time.monotonic
    later = real() + r2_media.VIEW_TTL_SECONDS - r2_media._REUSE_MARGIN_SECONDS + 1
    monkeypatch.setattr(r2_media.time, "monotonic", lambda: later)
    assert r2_media.issue_view_path(TENANT_A, KEY_A, "video") != first


def test_ranged_responses_are_privately_cacheable(backend) -> None:
    client, _ = backend
    path = r2_media.issue_view_path(TENANT_A, KEY_A, "video")
    response = client.get(path, headers={"Range": "bytes=0-3"})
    assert response.status_code == 206
    cache = response.headers["cache-control"]
    assert cache.startswith("private, max-age=") and "no-store" not in cache
