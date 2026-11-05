"""«Ideas para tus reels» shows each idea's cover from R2 (ADR 42 R12, m-24854859), offline:
the run's copy (`qualify_api.referentes.reel_covers`) lands in an in-memory R2 behind the
real public door, the networks' CDN is an `httpx.MockTransport`, and the cover route is
`avatar_proxy.avatar_api` driven through `httpx.ASGITransport`.

Pins: a 6-day-old idea whose CDN link died is still shown, from the copy; the card's path
is the copy's, else the live signed path while the link is fresh, else nothing (the
placeholder); the route without a query serves the copy for a week or a `no-store` 404,
and with the signed query passes the live picture through for an hour — keeping nothing
on disk, following no redirect, and still refusing a path it did not sign."""

from __future__ import annotations

import io
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from PIL import Image
from qualify_api.referentes import reel_covers
from qualify_api.referentes.reel_covers import MemoryCoverStore, copy_idea_covers
from qualify_api.referentes.reel_runs import IdeaSource
from qualify_api.referentes.reel_store import Idea, MemoryReelRunStore, PublicReel, StoredVerdict
from qualify_api.vendors.cdn_media import signature_expired
from qualify_shared.objects.gate import ObjectNotFound, StoredObject
from qualify_shared.objects.public import PublicObjectGate, reel_cover_key

from . import avatar_proxy as ap
from . import reels_ideas_vm as vm

TENANT = UUID("a0000000-0000-4000-8000-000000000001")
COPIED = datetime(2026, 11, 2, 11, 0, tzinfo=UTC)  # the Monday run
SIX_DAYS_LATER = COPIED + timedelta(days=6)
CDN_HOST = "scontent-bog1-1.cdninstagram.com"


def _url(reel_id: str, *, expires: datetime) -> str:
    return (
        f"https://{CDN_HOST}/v/t51.2885-15/{reel_id}.jpg?oe={int(expires.timestamp()):X}&_nc_sid=1"
    )


def _jpeg(size: tuple[int, int] = (1080, 1920)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (250, 200, 120)).save(out, "JPEG")
    return out.getvalue()


class R2:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, fileobj: Any, content_type: str) -> None:
        self.objects[key] = fileobj.read()

    def open(self, key: str) -> io.BytesIO:
        if key not in self.objects:
            raise ObjectNotFound(key)
        return io.BytesIO(self.objects[key])

    def list_prefix(self, prefix: str) -> Iterator[StoredObject]:
        for key, data in sorted(self.objects.items()):
            if key.startswith(prefix):
                yield StoredObject(key, len(data))

    def delete_keys(self, keys: list[str]) -> None:
        for key in keys:
            self.objects.pop(key, None)


class Cdn:
    """The network's CDN; `answers` overrides what a path answers."""

    def __init__(self) -> None:
        self.asked: list[str] = []
        self.answers: dict[str, httpx.Response] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request.url.path)
        name = request.url.path.rsplit("/", 1)[-1]
        if name in self.answers:
            return self.answers[name]
        return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=_jpeg())

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def r2(monkeypatch: pytest.MonkeyPatch) -> R2:
    """The bucket the route reads, behind the real public door."""
    store = R2()
    monkeypatch.setattr(reel_covers, "_default_gate", lambda: PublicObjectGate(store))
    return store


@pytest.fixture
def cdn(monkeypatch: pytest.MonkeyPatch) -> Cdn:
    """The live pass-through's CDN; a disk write during it fails the test."""
    fake = Cdn()
    monkeypatch.setattr(ap, "_cover_client", fake.client)
    monkeypatch.setattr(ap, "_reel_misses", {})

    def no_disk(self: Path, data: bytes) -> int:
        raise AssertionError(f"the cover route wrote to disk: {self}")

    monkeypatch.setattr(Path, "write_bytes", no_disk)
    return fake


def _reel(
    reel_id: str, *, read_at: datetime, url: str | None, key: str | None = None
) -> PublicReel:
    return PublicReel(
        network="instagram",
        reel_id=reel_id,
        handle="heladosdonde",
        taken_at=read_at - timedelta(days=3),
        metrics_at=read_at,
        parser_version=2,
        caption="Helado de yogur con frutos rojos",
        views=12_000,
        cover_url=url,
        cover_url_at=read_at if url else None,
        cover_r2_key=key,
    )


def _idea(reel: PublicReel) -> Idea:
    verdict = StoredVerdict(
        network=reel.network,
        reel_id=reel.reel_id,
        brief_hash="b",
        input_hash="i",
        fits=True,
        model_id="claude",
        prompt_version="p",
        affinity="producto",
    )
    return Idea(rank=1, window_days=7, reel=reel, verdict=verdict)


async def _get(path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=ap.avatar_api)
    async with httpx.AsyncClient(transport=transport, base_url="http://qualify") as client:
        return await client.get(path)


# --------------------------------------------------------------------------------------
# the acceptance test: a 6-day-old idea
# --------------------------------------------------------------------------------------


async def test_a_six_day_old_idea_whose_link_died_shows_its_cover_from_r2(r2: R2) -> None:
    """ADR 42 R12's criterion: Monday's run copied the cover while its Instagram link
    lived (~4 days); on Sunday the link is dead and the card still shows the cover."""
    url = _url("DecE2c8x7c_", expires=COPIED + timedelta(days=4))
    runs = MemoryReelRunStore()
    runs.upsert_reels(TENANT, [_reel("DecE2c8x7c_", read_at=COPIED, url=url)])
    cdn = Cdn()
    with cdn.client() as client:
        report = copy_idea_covers(
            TENANT,
            uuid4(),
            [
                IdeaSource(
                    "instagram",
                    "DecE2c8x7c_",
                    "https://www.instagram.com/reel/x/",
                    "",
                    cover_url=url,
                )
            ],
            gate=PublicObjectGate(r2),
            store=MemoryCoverStore(runs),
            client=client,
            clock=COPIED.timestamp,
        )
    assert report.copied == 1 and len(cdn.asked) == 1

    stored = runs.reels[("instagram", "DecE2c8x7c_")]
    assert signature_expired(url, now=SIX_DAYS_LATER.timestamp())  # the CDN link is dead
    card = vm.idea_card(_idea(stored), now=SIX_DAYS_LATER)
    assert card["cover"] == "/avatar/reel/instagram/DecE2c8x7c_"  # no query: the copy

    response = await _get(card["cover"])
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "public, max-age=604800"
    assert response.content == r2.objects[reel_cover_key("instagram", "DecE2c8x7c_")]
    with Image.open(io.BytesIO(response.content)) as picture:
        assert picture.format == "JPEG" and max(picture.size) == 720
    assert len(cdn.asked) == 1  # Sunday never asked the dead link

    gone = vm.idea_card(
        _idea(_reel("B2", read_at=COPIED, url=_url("B2", expires=COPIED + timedelta(days=1)))),
        now=SIX_DAYS_LATER,
    )
    assert gone["cover"] == ""  # no copy and a dead link: the card's placeholder


# --------------------------------------------------------------------------------------
# the card's path
# --------------------------------------------------------------------------------------


def test_the_card_prefers_the_copy_then_a_fresh_link_then_nothing() -> None:
    now = SIX_DAYS_LATER
    live = _url("A1", expires=now + timedelta(days=2))
    copied = _reel(
        "A1", read_at=now - timedelta(days=1), url=live, key=reel_cover_key("instagram", "A1")
    )
    assert vm.cover_path(copied, now=now) == "/avatar/reel/instagram/A1"

    fresh = _reel("A1", read_at=now - timedelta(days=1), url=live)
    signed = vm.cover_path(fresh, now=now)
    assert signed == ap.reel_cover_path("instagram", "A1", live)
    assert signed.startswith("/avatar/reel/instagram/A1?u=https%3A%2F%2F") and "&s=" in signed

    expired = _reel("A1", read_at=now - timedelta(days=1), url=_url("A1", expires=now))
    stale = _reel("A1", read_at=now - timedelta(days=5), url="https://p16.tiktokcdn.com/c.jpeg")
    foreign = _reel("A1", read_at=now, url="https://evil.example/c.jpg")
    for reel in (expired, stale, foreign, _reel("A1", read_at=now, url=None)):
        assert vm.cover_path(reel, now=now) == ""


# --------------------------------------------------------------------------------------
# the route, with and without a query
# --------------------------------------------------------------------------------------


async def test_without_a_query_the_route_serves_the_copy_or_a_no_store_404(r2: R2) -> None:
    r2.objects[reel_cover_key("tiktok", "7301")] = b"\xff\xd8copy"
    found = await _get("/avatar/reel/tiktok/7301")
    assert (found.status_code, found.content) == (200, b"\xff\xd8copy")
    assert found.headers["cache-control"] == "public, max-age=604800"

    for path in ("/avatar/reel/tiktok/7302", "/avatar/reel/tiktok/a.b", "/avatar/reel/facebook/1"):
        missing = await _get(path)
        assert missing.status_code == 404 and missing.headers["cache-control"] == "no-store"


async def test_with_the_signed_query_the_live_cover_passes_through_without_a_disk_copy(
    r2: R2, cdn: Cdn
) -> None:
    live = _url("C9", expires=datetime.now(UTC) + timedelta(days=2))
    path = ap.reel_cover_path("instagram", "C9", live)
    first, again = await _get(path), await _get(path)
    for response in (first, again):
        assert response.status_code == 200 and response.content[:3] == b"\xff\xd8\xff"
        assert response.headers["cache-control"] == "public, max-age=3600"
    assert len(cdn.asked) == 2  # a pass-through: nothing kept between two requests
    assert r2.objects == {}  # and nothing written to R2 either: only the run copies


async def test_the_signed_query_still_refuses_what_it_did_not_sign_and_follows_no_redirect(
    r2: R2, cdn: Cdn
) -> None:
    live = _url("C9", expires=datetime.now(UTC) + timedelta(days=2))
    path = ap.reel_cover_path("instagram", "C9", live)
    forged = path.replace("C9.jpg", "C8.jpg")
    unsigned = path.split("&s=")[0]
    for bad in (forged, unsigned, unsigned + "&s=%C3%B1"):
        response = await _get(bad)
        assert response.status_code == 404 and response.headers["cache-control"] == "no-store"
    assert cdn.asked == []

    other = _url("C7", expires=datetime.now(UTC) + timedelta(days=2))
    cdn.answers["C7.jpg"] = httpx.Response(302, headers={"location": live})
    moved = await _get(ap.reel_cover_path("instagram", "C7", other))
    assert moved.status_code == 404 and len(cdn.asked) == 1  # the 302 was not followed

    dead = _url("C6", expires=datetime.now(UTC) - timedelta(minutes=1))
    expired = await _get(ap.reel_cover_path("instagram", "C6", dead))
    assert expired.status_code == 404 and len(cdn.asked) == 1  # never even asked


async def test_heic_passes_through_as_jpeg(cdn: Cdn) -> None:
    pillow_heif = pytest.importorskip("pillow_heif")
    pillow_heif.register_heif_opener()
    heic = io.BytesIO()
    try:
        Image.new("RGB", (64, 64), (9, 9, 9)).save(heic, format="HEIF")
    except Exception:  # noqa: BLE001 - an install without an HEIF encoder
        pytest.skip("pillow-heif has no encoder here")
    soon = int(datetime.now(UTC).timestamp()) + 3600
    url = f"https://p16-sign.tiktokcdn.com/obj/cover.heic?x-expires={soon}"
    cdn.answers["cover.heic"] = httpx.Response(
        200, headers={"content-type": "image/heic"}, content=heic.getvalue()
    )
    response = await _get(ap.reel_cover_path("tiktok", "7301", url))
    assert response.status_code == 200 and response.headers["content-type"] == "image/jpeg"
    assert response.content[:3] == b"\xff\xd8\xff"
