"""The picture proxy's safety (m-24957331, CodeQL py/full-ssrf and py/path-injection),
offline: a recording `httpx.MockTransport` stands for the networks, `tmp_path` for the
disk cache.

Pins: the profile route serves only paths the server signed — anything else is a
`no-store` 404 before any read of the disk or the network; a redirect is followed by hand,
only onto the allowed hosts (the networks' CDNs and their subdomains, `unavatar.io` itself)
and at most 3 hops — a hop anywhere else, or a `Location` that cannot be read, is never
even requested, and its host (never its URL) is logged; a body is streamed and capped at
3 MB, a compressed one refused unread; a URL httpx refuses
(`https://evil.com\\t.cdninstagram.com/`) or cannot parse is a `no-store` 404 on every
avatar path, never a 500; and a handle or reel id with `..`, a slash or any odd character
never reads or writes a file, inside the cache folder or out of it."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from . import avatar_proxy as ap
from . import creator_discovery as cd

_JPEG = b"\xff\xd8\xff\xe0fake-jpeg-bytes"
#: Instagram has no unavatar fallback: a refused picture asks nobody else.
IG = "https://scontent-bog1-1.cdninstagram.com/v/t51/pic.jpg?oe=7FFFFFFF"
TT = "https://p16-sign-va.tiktokcdn.com/obj/pic.jpeg?x-expires=9999999999"
TAB_TRICK = "https://evil.com\t.cdninstagram.com/"


class Net:
    """The networks: exact URL → answer; anything else a 404. Every request recorded."""

    def __init__(self, routes: dict[str, Callable[[], httpx.Response]]) -> None:
        self.routes = routes
        self.asked: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.asked.append(url)
        answer = self.routes.get(url)
        return answer() if answer is not None else httpx.Response(404)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


def moved(location: str, status: int = 302) -> Callable[[], httpx.Response]:
    return lambda: httpx.Response(status, headers={"location": location})


def picture() -> Callable[[], httpx.Response]:
    return lambda: httpx.Response(200, content=_JPEG, headers={"content-type": "image/jpeg"})


@pytest.fixture(autouse=True)
def _fresh_state() -> None:
    ap._misses.clear()
    ap._account_locks.clear()
    ap._unavatar_blocked_until = 0.0


def _files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def _signed(network: str, handle: str, vendor_url: str = "") -> str:
    """The path a card asks for — the builder's own, signature included."""
    return cd.avatar_path({"network": network, "handle": handle, "avatar": vendor_url})


# --------------------------------------------------------------------------------------
# redirects, followed by hand (py/full-ssrf)
# --------------------------------------------------------------------------------------


async def test_a_redirect_onto_the_cdn_is_followed(tmp_path: Path) -> None:
    """Measured 2026-11-06, unavatar answers the picture itself (200, image/jpeg); were it
    to send it on to the network's CDN, that hop is followed."""
    unavatar = ap.unavatar_url("tiktok", "sof_lol")
    net = Net({unavatar: moved(TT), TT: picture()})
    async with net.client() as client:
        found = await ap.resolve_avatar("tiktok", "sof_lol", "", client=client, directory=tmp_path)
    assert found == (_JPEG, "image/jpeg")
    assert net.asked == [unavatar, TT]
    assert _files(tmp_path) == [tmp_path / "tiktok_sof_lol.jpg"]


async def test_a_relative_redirect_on_the_same_cdn_is_followed(tmp_path: Path) -> None:
    other = "https://scontent-bog1-1.cdninstagram.com/v/t51/other.jpg"
    net = Net({IG: moved("/v/t51/other.jpg", 301), other: picture()})
    async with net.client() as client:
        found = await ap.resolve_avatar(
            "instagram", "midu.dev", IG, client=client, directory=tmp_path
        )
    assert found == (_JPEG, "image/jpeg") and net.asked == [IG, other]


@pytest.mark.parametrize(
    "location",
    [
        "http://169.254.169.254/latest/meta-data/",  # the cloud's metadata service
        "http://scontent-bog1-1.cdninstagram.com/v/pic.jpg",  # not https
        "https://evil.example/pic.jpg",
        "https://cdninstagram.com.evil.example/pic.jpg",
        "//evil.example/pic.jpg",  # scheme-relative: resolves to another host
        "https://user:pw@scontent-bog1-1.cdninstagram.com/pic.jpg",
        "https://scontent-bog1-1.cdninstagram.com:8443/pic.jpg",
        "https://127.0.0.1/pic.jpg",
        TAB_TRICK,
        "ftp://scontent-bog1-1.cdninstagram.com/pic.jpg",
    ],
)
async def test_a_redirect_off_the_allowed_hosts_is_never_requested(
    location: str, tmp_path: Path
) -> None:
    net = Net({IG: moved(location)})
    async with net.client() as client:
        found = await ap.resolve_avatar(
            "instagram", "midu.dev", IG, client=client, directory=tmp_path
        )
    assert found is None
    assert net.asked == [IG]  # the off-list hop never left
    assert _files(tmp_path) == []


async def test_three_hops_are_followed_and_a_fourth_is_not(tmp_path: Path) -> None:
    hop = [f"https://scontent-bog1-1.cdninstagram.com/v/hop{n}.jpg" for n in range(5)]
    three = Net(
        {IG: moved(hop[1]), hop[1]: moved(hop[2]), hop[2]: moved(hop[3]), hop[3]: picture()}
    )
    async with three.client() as client:
        found = await ap.resolve_avatar("instagram", "a", IG, client=client, directory=tmp_path)
    assert found == (_JPEG, "image/jpeg") and three.asked == [IG, hop[1], hop[2], hop[3]]

    four = Net(
        {
            IG: moved(hop[1]),
            hop[1]: moved(hop[2]),
            hop[2]: moved(hop[3]),
            hop[3]: moved(hop[4]),
            hop[4]: picture(),
        }
    )
    async with four.client() as client:
        refused = await ap.resolve_avatar("instagram", "b", IG, client=client, directory=tmp_path)
    assert refused is None
    assert four.asked == [IG, hop[1], hop[2], hop[3]]  # the fourth hop never left


def test_the_route_answers_an_off_list_redirect_with_a_no_store_404(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    net = Net({IG: moved("http://169.254.169.254/latest/meta-data/")})
    _route_on(monkeypatch, net, tmp_path)
    response = TestClient(ap.avatar_api).get(_signed("instagram", "midu.dev", IG))
    assert response.status_code == 404 and response.headers["cache-control"] == "no-store"
    assert net.asked == [IG]


# --------------------------------------------------------------------------------------
# a URL httpx refuses or cannot read: a no-store 404, never a 500
# --------------------------------------------------------------------------------------


def _route_on(monkeypatch: pytest.MonkeyPatch, net: Net, cache: Path) -> None:
    """The profile route over `net` and a disk cache in `cache` (never the real one)."""
    real = ap.resolve_avatar

    async def resolve(network: str, handle: str, vendor_url: str = "", **kw: Any) -> Any:
        async with net.client() as client:
            return await real(network, handle, vendor_url, client=client, directory=cache, **kw)

    monkeypatch.setattr(ap, "resolve_avatar", resolve)


@pytest.mark.parametrize(
    "vendor_url",
    [
        TAB_TRICK,
        "https://evil.com\n.cdninstagram.com/",
        "https://scontent-bog1-1.cdninstagram.com/pic.jpg\x00",
        "https://[",  # not even parseable
        "https://scontent-bog1-1.cdninstagram.com:99999/pic.jpg",
    ],
)
def test_a_url_httpx_refuses_is_a_no_store_404_never_a_500(
    vendor_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    net = Net({})
    _route_on(monkeypatch, net, tmp_path)
    path = _signed("instagram", "midu.dev", vendor_url)  # signed: the URL logic is reached
    response = TestClient(ap.avatar_api, raise_server_exceptions=False).get(path)
    assert response.status_code == 404 and response.headers["cache-control"] == "no-store"
    assert net.asked == [] and _files(tmp_path) == []


def test_every_avatar_path_answers_odd_input_with_a_no_store_404(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The profile picture, the live reel cover (signed by its URL) and the stored one
    (signed by its reel), each fed what httpx or the cache cannot take — the live cover
    also a URL `urlsplit` cannot read, which its expiry check must not choke on."""
    net = Net({})
    _route_on(monkeypatch, net, tmp_path)
    monkeypatch.setattr(
        ap, "_cover_client", lambda: httpx.Client(transport=httpx.MockTransport(net.handler))
    )
    monkeypatch.setattr(ap, "_reel_misses", {})
    client = TestClient(ap.avatar_api, raise_server_exceptions=False)

    def sig(handle: str, u: str = "") -> dict[str, str]:
        return {**({"u": u} if u else {}), "s": cd.avatar_signature("instagram", handle, u)}

    paths = [
        (f"{cd.AVATAR_ROUTE}/instagram/midu.dev", sig("midu.dev", TAB_TRICK)),
        (f"{cd.AVATAR_ROUTE}/instagram/a%0Ab", sig("a\nb")),  # a newline in the handle
        (f"{cd.AVATAR_ROUTE}/instagram/a%00b", sig("a\x00b")),
        (f"{cd.AVATAR_ROUTE}/instagram/a%20b", sig("a b")),
        (
            ap.REEL_COVER_ROUTE + "/instagram/C1",
            {"u": TAB_TRICK, "s": ap.reel_cover_signature("instagram", "C1", TAB_TRICK)},
        ),
        (  # its own reel: C1's miss, remembered just above, would answer before the check
            ap.REEL_COVER_ROUTE + "/instagram/C2",
            {"u": "https://[", "s": ap.reel_cover_signature("instagram", "C2", "https://[")},
        ),
        (
            ap.REEL_COVER_ROUTE + "/instagram/C1%0A",
            {"s": ap.stored_cover_signature("instagram", "C1\n")},
        ),
    ]
    for path, params in paths:
        response = client.get(path, params=params)
        assert response.status_code == 404, path
        assert response.headers.get("cache-control") == "no-store", path
    assert net.asked == [] and _files(tmp_path) == []


# --------------------------------------------------------------------------------------
# the profile route fetches only what the server signed (review of m-24957331)
# --------------------------------------------------------------------------------------


def test_an_unsigned_or_forged_profile_path_is_refused_before_any_io(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`u` is anonymous: without the server's signature of this network, this handle and
    this very URL, the route reads neither the disk nor the network."""
    looked: list[tuple[str, str, str]] = []

    async def resolve(network: str, handle: str, vendor_url: str = "", **_: Any) -> Any:
        looked.append((network, handle, vendor_url))
        return (_JPEG, "image/jpeg")

    monkeypatch.setattr(ap, "resolve_avatar", resolve)
    client = TestClient(ap.avatar_api)
    video = "https://scontent-bog1-1.cdninstagram.com/o1/v/t16/reel.mp4"
    good = _signed("instagram", "midu.dev", IG)
    forged = [
        f"{cd.AVATAR_ROUTE}/instagram/midu.dev?u={IG}",  # unsigned
        good.replace("midu.dev", "another"),  # another account's path, same signature
        good.split("&s=")[0] + "&s=" + good.split("&s=")[1][::-1],
        good.split("?")[0] + "?u=" + video + "&s=" + good.split("&s=")[1],  # another URL
        f"{cd.AVATAR_ROUTE}/instagram/midu.dev?s=%C3%B1",
        f"{cd.AVATAR_ROUTE}/instagram/midu.dev",
    ]
    for path in forged:
        refused = client.get(path)
        assert refused.status_code == 404 and refused.headers["cache-control"] == "no-store"
    assert looked == []

    served = client.get(good)
    assert (served.status_code, served.headers["cache-control"]) == (200, "public, max-age=86400")
    assert looked == [("instagram", "midu.dev", IG)]
    assert _signed("instagram", "midu.dev", IG) == good  # the same path: cacheable


# --------------------------------------------------------------------------------------
# a body is streamed and capped (review of m-24957331)
# --------------------------------------------------------------------------------------


class _Body:
    """A body that says whether anyone read it."""

    def __init__(self, size: int, chunk: int = 1_000_000) -> None:
        self.size, self.chunk, self.read = size, chunk, 0

    def __iter__(self) -> Iterator[bytes]:
        while self.read < self.size:
            piece = min(self.chunk, self.size - self.read)
            self.read += piece
            yield b"x" * piece


@pytest.mark.parametrize(
    ("headers", "size", "unread"),
    [
        ({"content-type": "image/jpeg", "content-length": "3000001"}, 3_000_001, True),
        ({"content-type": "image/jpeg"}, 4_000_000, False),  # no length: cut off at 3 MB
        ({"content-type": "image/jpeg", "content-encoding": "gzip"}, 1_000, True),
        ({"content-type": "video/mp4"}, 50_000_000, True),  # a reel's video: never read
    ],
)
async def test_a_body_over_three_mb_or_not_an_image_is_refused_without_holding_it(
    headers: dict[str, str], size: int, unread: bool, tmp_path: Path
) -> None:
    body = _Body(size)
    seen: list[httpx.Request] = []

    async def stream() -> AsyncIterator[bytes]:
        for piece in body:
            yield piece

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers=headers, content=stream())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        found = await ap.resolve_avatar(
            "instagram", "midu.dev", IG, client=client, directory=tmp_path
        )
    assert found is None and _files(tmp_path) == []
    assert seen[0].headers["accept-encoding"] == "identity"
    if unread:
        assert body.read == 0
    else:
        assert body.read <= 3_000_000 + body.chunk  # stopped at the cap, not at 4 MB


# --------------------------------------------------------------------------------------
# a Location that cannot be read; the refused host in the log (review of m-24957331)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("location", ["https://[", "//[x", "https://a[b.cdninstagram.com/"])
def test_a_location_urljoin_cannot_read_is_an_off_list_hop(
    location: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    net = Net({IG: moved(location)})
    _route_on(monkeypatch, net, tmp_path)
    response = TestClient(ap.avatar_api, raise_server_exceptions=False).get(
        _signed("instagram", "midu.dev", IG)
    )
    assert response.status_code == 404 and response.headers["cache-control"] == "no-store"
    assert net.asked == [IG]


async def test_the_refused_hop_logs_its_host_never_its_url(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    net = Net({IG: moved("https://evil.example/steal?token=sekrit")})
    caplog.set_level(logging.INFO, logger=ap.logger.name)
    async with net.client() as client:
        assert (
            await ap.resolve_avatar("instagram", "a", IG, client=client, directory=tmp_path) is None
        )
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "evil.example" in text and "sekrit" not in text and "/steal" not in text


def test_unavatar_is_matched_exactly_and_the_cdns_by_suffix() -> None:
    assert ap.source_allowed("https://unavatar.io/tiktok/sof_lol?fallback=false")
    for host in ("localhost.unavatar.io", "cdn.unavatar.io", "unavatar.io.evil.example"):
        assert not ap.source_allowed(f"https://{host}/tiktok/sof_lol")
    assert ap.source_allowed("https://scontent-bog1-1.cdninstagram.com/v/pic.jpg")
    assert ap.source_allowed("https://p16-sign-va.tiktokcdn.com/obj/pic.jpeg")


# --------------------------------------------------------------------------------------
# the disk cache never leaves its folder (py/path-injection)
# --------------------------------------------------------------------------------------

ODD = [
    "../secret",
    "..\\secret",
    "a/b",
    "/etc/passwd",
    "a\nb",
    "abc\n",  # `re.match` with `$` let a trailing newline through
    "a\x00b",
    "a b",
    "ñandú",
    "%2e%2e",
    "",
    "x" * 41,
]


@pytest.mark.parametrize("handle", ODD)
def test_an_odd_handle_never_names_a_file(handle: str, tmp_path: Path) -> None:
    assert ap._cache_path(tmp_path, "instagram", handle, ".jpg") is None
    assert ap.cache_file("instagram", handle, directory=tmp_path) is None
    assert ap.valid_target("instagram", handle) is False


def test_a_handle_names_one_file_inside_the_folder_and_nothing_else(tmp_path: Path) -> None:
    for handle in ("midu.dev", "..", "a..b", "Sof_Lol"):
        path = ap._cache_path(tmp_path, "instagram", handle, ".jpg")
        assert path is not None and path.parent == tmp_path.resolve()
        assert path.name == f"instagram_{handle.lower()}.jpg"
    assert ap._cache_path(tmp_path, "facebook", "midu.dev", ".jpg") is None  # closed set
    assert ap._cache_path(tmp_path, "instagram", "midu.dev", ".exe") is None


@pytest.mark.parametrize("handle", ODD)
async def test_an_odd_handle_reads_and_writes_nothing_anywhere(handle: str, tmp_path: Path) -> None:
    """A file planted next to the cache is never read, and nothing is written."""
    cache = tmp_path / "cache"
    (tmp_path / "secret.jpg").write_bytes(b"not yours")
    net = Net({IG: picture()})
    async with net.client() as client:
        found = await ap.resolve_avatar("instagram", handle, IG, client=client, directory=cache)
    assert found is None and net.asked == []
    assert ap._keep("instagram", handle, (_JPEG, "image/jpeg"), cache) == (_JPEG, "image/jpeg")
    assert _files(tmp_path) == [tmp_path / "secret.jpg"]  # nothing read, nothing written


@pytest.mark.parametrize("reel_id", ["../x", "a/b", "C1\n", "C1\x00", "a b", ""])
async def test_an_odd_reel_id_asks_nobody_and_touches_no_file(
    reel_id: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(200, content=_JPEG, headers={"content-type": "image/jpeg"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert await ap.resolve_reel_cover("instagram", reel_id, IG, client=client) is None
    assert asked == [] and _files(tmp_path) == []
