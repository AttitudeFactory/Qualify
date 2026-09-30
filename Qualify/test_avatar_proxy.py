"""The discovery cards' picture proxy (`avatar_proxy.py`, request 2026-09-14): disk
first, the vendor's signed URL once, unavatar as the by-handle fallback, 404 last —
and never a fetch from a host that is not a vendor CDN."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from . import avatar_proxy as ap
from . import creator_discovery as cd

_JPEG = b"\xff\xd8\xff\xe0fake-jpeg-bytes"
_VENDOR = "https://p16-common-sign.tiktokcdn-us.com/tos/abc~c5_100x100.jpeg?x-expires=9999999999"


def _transport(routes: dict[str, tuple[int, bytes, str]]) -> httpx.MockTransport:
    """`url prefix → (status, body, content-type)`; anything else is a 404."""

    def handler(request: httpx.Request) -> httpx.Response:
        for prefix, (status, body, ctype) in routes.items():
            if str(request.url).startswith(prefix):
                return httpx.Response(status, content=body, headers={"content-type": ctype})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def _reset_module_state() -> None:
    ap._misses.clear()
    ap._background_tasks.clear()
    ap._account_locks.clear()
    ap._refreshed.clear()
    ap._refresh_log.clear()


def test_only_vendor_cdns_and_unavatar_are_fetchable() -> None:
    assert ap.source_allowed(_VENDOR)
    assert ap.source_allowed("https://scontent-mad1-1.cdninstagram.com/v/t51/pic.jpg")
    assert ap.source_allowed("https://instagram.fbcdn.net/pic.jpg")
    assert ap.source_allowed("https://unavatar.io/tiktok/x?fallback=false")
    assert not ap.source_allowed("http://p16-common-sign.tiktokcdn-us.com/insecure.jpg")
    assert not ap.source_allowed("https://evil.example/tiktokcdn.com/pic.jpg")
    assert not ap.source_allowed("https://tiktokcdn.com.evil.example/pic.jpg")
    assert not ap.source_allowed("https://169.254.169.254/latest/meta-data")
    assert not ap.source_allowed("not a url")


def test_target_validation() -> None:
    assert ap.valid_target("tiktok", "sof_lol")
    assert ap.valid_target("instagram", "midu.dev")
    assert not ap.valid_target("youtube", "x")
    assert not ap.valid_target("tiktok", "../etc/passwd")
    assert not ap.valid_target("tiktok", "")


async def test_vendor_url_is_fetched_once_and_served_from_disk_after(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, content=_JPEG, headers={"content-type": "image/jpeg"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = await ap.resolve_avatar(
            "tiktok", "Sof_Lol", _VENDOR, client=client, directory=tmp_path
        )
        assert first == (_JPEG, "image/jpeg")
        assert (tmp_path / "tiktok_sof_lol.jpg").read_bytes() == _JPEG
        assert calls == [_VENDOR]

        # the signature has died since — nobody asks the vendor again
        again = await ap.resolve_avatar(
            "tiktok", "sof_lol", _VENDOR + "&dead=1", client=client, directory=tmp_path
        )
        assert again == (_JPEG, "image/jpeg") and calls == [_VENDOR]


async def test_unavatar_is_the_fallback_when_the_vendor_url_is_dead_or_absent(
    tmp_path: Path,
) -> None:
    transport = _transport(
        {
            _VENDOR: (403, b"expired", "text/plain"),
            "https://unavatar.io/tiktok/sof_lol": (200, _JPEG, "image/png"),
        }
    )
    async with httpx.AsyncClient(transport=transport) as client:
        found = await ap.resolve_avatar(
            "tiktok", "sof_lol", _VENDOR, client=client, directory=tmp_path
        )
        assert found == (_JPEG, "image/png")
        assert (tmp_path / "tiktok_sof_lol.png").exists()
        # a card from a cache written before pictures existed: no vendor URL at all
        found = await ap.resolve_avatar("tiktok", "sof_lol", "", client=client, directory=tmp_path)
        assert found == (_JPEG, "image/png")


async def test_a_miss_is_a_none_and_is_not_retried_for_a_while(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert (
            await ap.resolve_avatar(
                "tiktok", "nobody", "", client=client, directory=tmp_path, now=1000.0
            )
            is None
        )
        assert len(calls) == 1  # unavatar only: no vendor URL
        assert (
            await ap.resolve_avatar(
                "tiktok", "nobody", "", client=client, directory=tmp_path, now=1500.0
            )
            is None
        )
        assert len(calls) == 1  # remembered
        assert (
            await ap.resolve_avatar(
                "tiktok", "nobody", "", client=client, directory=tmp_path, now=1000.0 + 16 * 60
            )
            is None
        )
        assert len(calls) == 2  # forgotten after `_MISS_TTL_SECONDS`
        assert not list(tmp_path.iterdir())


async def test_non_images_and_oversized_bodies_are_refused(tmp_path: Path) -> None:
    transport = _transport(
        {
            _VENDOR: (200, b"<html>login</html>", "text/html; charset=utf-8"),
            "https://unavatar.io/": (200, b"x" * (ap._MAX_BYTES + 1), "image/jpeg"),
        }
    )
    async with httpx.AsyncClient(transport=transport) as client:
        assert (
            await ap.resolve_avatar("tiktok", "big", _VENDOR, client=client, directory=tmp_path)
            is None
        )


def test_the_route_serves_the_picture_or_a_404(monkeypatch: pytest.MonkeyPatch) -> None:
    """The HTTP shape only — the lookup itself is covered above. The route lowercases
    the network (the cards say "TikTok") and passes `u` through as the vendor URL."""
    asked: list[tuple[str, str, str]] = []

    async def fake_resolve(
        network: str, handle: str, vendor_url: str = "", *, refresh: object = None
    ) -> tuple[bytes, str] | None:
        # the browser's request is the one allowed the paid last resort
        assert refresh is ap.fresh_vendor_url
        asked.append((network, handle, vendor_url))
        return (_JPEG, "image/webp") if handle == "sof_lol" else None

    monkeypatch.setattr(ap, "resolve_avatar", fake_resolve)
    client = TestClient(ap.avatar_api)

    ok = client.get(f"{cd.AVATAR_ROUTE}/TikTok/sof_lol", params={"u": _VENDOR})
    assert ok.status_code == 200
    assert ok.headers["content-type"] == "image/webp"
    assert ok.headers["cache-control"] == "public, max-age=86400"
    assert ok.content == _JPEG
    assert asked == [("tiktok", "sof_lol", _VENDOR)]

    missing = client.get(f"{cd.AVATAR_ROUTE}/tiktok/nobody")
    assert missing.status_code == 404
    assert missing.headers["cache-control"] == "no-store"
    assert asked[-1] == ("tiktok", "nobody", "")


def test_the_card_path_the_frontend_asks_for_matches_the_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`creator_discovery.avatar_path` (what the card's `<img>` asks for) and the
    route agree: the handle survives as a path segment and the vendor URL arrives
    decoded, query string and all."""
    asked: list[tuple[str, str, str]] = []

    async def fake_resolve(
        network: str, handle: str, vendor_url: str = "", *, refresh: object = None
    ) -> None:
        asked.append((network, handle, vendor_url))
        return None

    monkeypatch.setattr(ap, "resolve_avatar", fake_resolve)
    card = {"handle": "@Sof_Lol", "network": "TikTok", "avatar": _VENDOR}
    path = cd.avatar_path(card)
    assert path.startswith(f"{cd.AVATAR_ROUTE}/tiktok/Sof_Lol?u=")
    TestClient(ap.avatar_api).get(path)
    assert asked == [("tiktok", "Sof_Lol", _VENDOR)]


async def test_the_shared_client_is_reused_across_calls() -> None:
    """§ request 2026-09-14 ("más rápido cargar las imágenes"): one pooled client,
    not a fresh TLS handshake per avatar. Reset before AND after regardless of test
    order/prior failures, so nothing leaks a client bound to a closed event loop
    into another test."""
    ap._shared_client = None
    try:
        first = ap._shared()
        second = ap._shared()
        assert first is second
        assert not first.is_closed
    finally:
        if ap._shared_client is not None:
            await ap._shared_client.aclose()
        ap._shared_client = None


async def test_warm_avatars_prefetches_every_card_and_tolerates_bad_ones(
    tmp_path: Path,
) -> None:
    good_a = "https://p16.tiktokcdn.com/a.jpg"
    good_b = "https://p16.tiktokcdn.com/b.jpg"
    transport = _transport({good_a: (200, _JPEG, "image/jpeg"), good_b: (200, _JPEG, "image/jpeg")})
    cards = [
        {"network": "tiktok", "handle": "a", "avatar": good_a},
        {"network": "tiktok", "handle": "b", "avatar": good_b},
        {"network": "youtube", "handle": "c", "avatar": "https://nope"},  # bad network
        {"network": "tiktok", "handle": "", "avatar": "https://nope"},  # no handle
    ]
    async with httpx.AsyncClient(transport=transport) as client:
        await ap.warm_avatars(cards, client=client, directory=tmp_path)
    assert {p.name for p in tmp_path.iterdir()} == {"tiktok_a.jpg", "tiktok_b.jpg"}


def test_warm_avatars_in_background_is_a_noop_outside_a_running_loop() -> None:
    """`_apply_phase` is called directly and synchronously by existing tests — the
    prefetch must never explode when there is no event loop to schedule it on."""
    ap.warm_avatars_in_background([{"network": "tiktok", "handle": "x", "avatar": "https://x"}])
    assert ap._background_tasks == set()


async def test_warm_avatars_in_background_schedules_and_tracks_the_task(
    tmp_path: Path,
) -> None:
    transport = _transport({_VENDOR: (200, _JPEG, "image/jpeg")})
    async with httpx.AsyncClient(transport=transport) as client:
        ap.warm_avatars_in_background(
            [{"network": "tiktok", "handle": "sof_lol", "avatar": _VENDOR}],
            client=client,
            directory=tmp_path,
        )
        assert len(ap._background_tasks) == 1
        await next(iter(ap._background_tasks))
    assert ap._background_tasks == set()
    assert (tmp_path / "tiktok_sof_lol.jpg").exists()


def _heic_bytes() -> bytes:
    pillow_heif = pytest.importorskip("pillow_heif")
    from io import BytesIO

    from PIL import Image

    pillow_heif.register_heif_opener()
    out = BytesIO()
    try:
        Image.new("RGB", (16, 16), (200, 30, 30)).save(out, format="HEIF")
    except Exception:  # noqa: BLE001 - an install without an HEIF encoder
        pytest.skip("pillow-heif has no encoder here")
    return out.getvalue()


async def test_heic_from_the_cdn_is_served_as_jpeg(tmp_path: Path) -> None:
    """TikTok's CDN answers `image/heic` for avatar URLs already saved in a discovery
    cache, and the `.jpeg` sibling of a signed URL is a 403 — so the proxy converts."""
    heic = _heic_bytes()
    transport = _transport({_VENDOR: (200, heic, "image/heic")})
    async with httpx.AsyncClient(transport=transport) as client:
        found = await ap.resolve_avatar(
            "tiktok", "jona_9998", _VENDOR, client=client, directory=tmp_path
        )
    assert found is not None and found[1] == "image/jpeg"
    assert found[0][:3] == b"\xff\xd8\xff"
    assert (tmp_path / "tiktok_jona_9998.jpg").exists()


async def test_an_unavatar_429_pauses_it_for_everyone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ap, "_unavatar_blocked_until", 0.0)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(429, content=b"{}", headers={"content-type": "application/json"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert (
            await ap.resolve_avatar("tiktok", "a", client=client, directory=tmp_path, now=1.0)
            is None
        )
        assert (
            await ap.resolve_avatar("tiktok", "b", client=client, directory=tmp_path, now=2.0)
            is None
        )
        assert len(calls) == 1  # `b` never reached unavatar: it is paused
        later = 2.0 + ap._UNAVATAR_COOLDOWN_SECONDS
        assert (
            await ap.resolve_avatar("tiktok", "c", client=client, directory=tmp_path, now=later)
            is None
        )
        assert len(calls) == 2  # the pause is over


# -- the paid last resort (§ request 2026-09-29) -----------------------------------------

_EXPIRED_IG = "https://scontent-mia5-2.cdninstagram.com/v/t51/old.jpg?oe=68D2B9A5"
_FRESH_IG = "https://scontent-mia5-2.cdninstagram.com/v/t51/new.jpg?oe=7FFFFFFF"


async def test_an_expired_url_is_replaced_by_a_fresh_one_when_allowed(tmp_path: Path) -> None:
    """The vendor URL answers 403 (its signature expired) and unavatar has nothing: the
    refresh hands a fresh URL, whose picture is served and kept on disk."""
    transport = _transport(
        {_EXPIRED_IG: (403, b"", "text/plain"), _FRESH_IG: (200, _JPEG, "image/jpeg")}
    )
    asked: list[tuple[str, str]] = []

    def refresh(network: str, handle: str) -> str:
        asked.append((network, handle))
        return _FRESH_IG

    async with httpx.AsyncClient(transport=transport) as client:
        found = await ap.resolve_avatar(
            "instagram",
            "mouredev",
            _EXPIRED_IG,
            client=client,
            directory=tmp_path,
            refresh=refresh,
        )
    assert found == (_JPEG, "image/jpeg")
    assert asked == [("instagram", "mouredev")]
    assert (tmp_path / "instagram_mouredev.jpg").read_bytes() == _JPEG


async def test_without_refresh_a_dead_url_stays_a_miss(tmp_path: Path) -> None:
    """The prefetch and every other caller pass no `refresh`: nothing is ever spent."""
    transport = _transport({_EXPIRED_IG: (403, b"", "text/plain")})
    async with httpx.AsyncClient(transport=transport) as client:
        found = await ap.resolve_avatar(
            "instagram", "mouredev", _EXPIRED_IG, client=client, directory=tmp_path
        )
    assert found is None


def test_the_profile_read_runs_once_per_account_and_within_the_hourly_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from . import scrapecreators_client as sc

    reads: list[tuple[str, str]] = []

    def fetch_profile(network: str, handle: str) -> dict[str, str]:
        reads.append((network, handle))
        return {"profilePicUrl": _FRESH_IG}

    monkeypatch.setattr(sc, "fetch_profile", fetch_profile)
    monkeypatch.setattr(ap, "_REFRESH_PER_HOUR", 2)
    t0 = 1_000_000.0

    assert ap.fresh_vendor_url("instagram", "MoureDev", now=t0) == _FRESH_IG
    assert ap.fresh_vendor_url("instagram", "mouredev", now=t0 + 1) == ""  # same account
    assert ap.fresh_vendor_url("instagram", "otra", now=t0 + 2) == _FRESH_IG
    assert ap.fresh_vendor_url("instagram", "tercera", now=t0 + 3) == ""  # hour spent
    # an hour later the budget is back; the same account waits its day
    assert ap.fresh_vendor_url("instagram", "tercera", now=t0 + 3601) == _FRESH_IG
    assert ap.fresh_vendor_url("instagram", "mouredev", now=t0 + 3602) == ""
    assert ap.fresh_vendor_url("instagram", "mouredev", now=t0 + 24 * 3600 + 5) == _FRESH_IG
    assert reads == [
        ("instagram", "MoureDev"),
        ("instagram", "otra"),
        ("instagram", "tercera"),
        ("instagram", "mouredev"),
    ]


def test_a_zero_budget_turns_the_refresh_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from . import scrapecreators_client as sc

    monkeypatch.setattr(sc, "fetch_profile", lambda *_a: pytest.fail("must not spend"))
    monkeypatch.setattr(ap, "_REFRESH_PER_HOUR", 0)
    assert ap.fresh_vendor_url("instagram", "mouredev") == ""


def test_a_signature_says_when_a_url_is_dead() -> None:
    now = 1_790_000_000.0
    assert ap.signature_expired(f"https://x.cdninstagram.com/p.jpg?oe={int(now) - 1:X}", now=now)
    assert not ap.signature_expired(
        f"https://x.cdninstagram.com/p.jpg?oe={int(now) + 3600:X}", now=now
    )
    assert ap.signature_expired(f"https://t.tiktokcdn.com/p.jpeg?x-expires={int(now)}", now=now)
    assert not ap.signature_expired("https://t.tiktokcdn.com/p.jpeg?x-expires=9999999999", now=now)
    assert not ap.signature_expired("https://t.tiktokcdn.com/p.jpeg", now=now)  # unknown: alive
    assert not ap.signature_expired("https://x.cdninstagram.com/p.jpg?oe=zz", now=now)


async def test_a_dead_url_and_instagram_unavatar_are_never_asked(tmp_path: Path) -> None:
    """Both are known failures (measured 2026-09-29): no request goes out for them."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        found = await ap.resolve_avatar(
            "instagram", "mouredev", _EXPIRED_IG, client=client, directory=tmp_path
        )
    assert found is None
    assert calls == []


async def test_the_prefetch_uses_the_paid_refresh_and_pays_once_per_account(
    tmp_path: Path,
) -> None:
    """The prefetch is where a dead picture is replaced (§ 2026-09-29); two cards of the
    same account — or the prefetch and the browser at once — cost one read."""
    transport = _transport({_FRESH_IG: (200, _JPEG, "image/jpeg")})
    asked: list[tuple[str, str]] = []

    def refresh(network: str, handle: str) -> str:
        asked.append((network, handle))
        return _FRESH_IG

    card = {"network": "Instagram", "handle": "@mouredev", "avatar": _EXPIRED_IG}
    async with httpx.AsyncClient(transport=transport) as client:
        await ap.warm_avatars(
            [card, dict(card)], client=client, directory=tmp_path, refresh=refresh
        )
    assert asked == [("instagram", "mouredev")]
    assert (tmp_path / "instagram_mouredev.jpg").read_bytes() == _JPEG


async def test_a_miss_left_by_the_prefetch_does_not_block_the_paid_refresh(
    tmp_path: Path,
) -> None:
    """The prefetch (no `refresh`) records the miss first; the browser's request right
    after must still get the refreshed picture instead of the remembered 404."""
    transport = _transport(
        {_EXPIRED_IG: (403, b"", "text/plain"), _FRESH_IG: (200, _JPEG, "image/jpeg")}
    )
    async with httpx.AsyncClient(transport=transport) as client:
        warm = await ap.resolve_avatar(
            "instagram", "leomarisreyes.dev", _EXPIRED_IG, client=client, directory=tmp_path
        )
        assert warm is None  # the miss is now remembered
        found = await ap.resolve_avatar(
            "instagram",
            "leomarisreyes.dev",
            _EXPIRED_IG,
            client=client,
            directory=tmp_path,
            refresh=lambda _n, _h: _FRESH_IG,
        )
    assert found == (_JPEG, "image/jpeg")
