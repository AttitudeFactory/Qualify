"""What the reels-worker and the picture proxy share about the networks' CDN media
(`qualify_api.vendors.cdn_media`, ADR 42 R12, m-24854859), offline: an
`httpx.MockTransport` CDN and real Pillow pictures.

Pins the cover download (the CDN's hosts only, https on 443, no credentials, no redirects,
at most 3 MB declared or streamed, an image type, the URL never in an error) and the
re-encode (JPEG / PNG / WebP / HEIC up to 4096 px per side in; a JPEG of at most 720 px,
quality 80, upright, without any metadata out)."""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from PIL import Image

from qualify_api.vendors import cdn_media as cm

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
URL = "https://scontent-bog1-1.cdninstagram.com/v/t51/C1.jpg?oe=6A000000&_nc_sid=1"


def _picture(fmt: str, size: tuple[int, int] = (1080, 1920), **save: object) -> bytes:
    out = io.BytesIO()
    mode = "RGBA" if fmt in ("PNG", "WEBP") else "RGB"
    Image.new(mode, size, (200, 120, 40, 255) if mode == "RGBA" else (200, 120, 40)).save(
        out, fmt, **save
    )
    return out.getvalue()


def _client(*responses: httpx.Response, seen: list[httpx.Request] | None = None) -> httpx.Client:
    answers = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return answers.pop(0)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _jpeg_response(body: bytes | None = None, **headers: str) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "image/jpeg", **headers},
        content=body if body is not None else _picture("JPEG"),
    )


# --------------------------------------------------------------------------------------
# where a cover may come from
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://scontent-bog1-1.cdninstagram.com/v/C1.jpg",
        "https://instagram.fbog2-1.fna.fbcdn.net/v/C1.jpg",
        "https://p16-sign-va.tiktokcdn.com/obj/cover.jpeg",
        "https://p19-sign.tiktokcdn-us.com/obj/cover.heic",
        "https://p16.tiktokcdn-eu.com:443/obj/cover.webp",
    ],
)
def test_the_networks_cdns_are_allowed(url: str) -> None:
    assert cm.cdn_host_allowed(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://scontent.cdninstagram.com/C1.jpg",  # not https
        "https://scontent.cdninstagram.com:8443/C1.jpg",  # not 443
        "https://user:pw@scontent.cdninstagram.com/C1.jpg",  # credentials
        "https://user@scontent.cdninstagram.com/C1.jpg",
        "https://unavatar.io/instagram/x",  # the proxy's own extra, never a cover's
        "https://evil.example/cdninstagram.com/C1.jpg",
        "https://cdninstagram.com.evil.example/C1.jpg",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/C1.jpg",
        "https://scontent.cdninstagram.com:99999/C1.jpg",  # an invalid port
        "not a url",
        "",
    ],
)
def test_anything_else_is_refused_before_any_request(url: str) -> None:
    seen: list[httpx.Request] = []
    assert not cm.cdn_host_allowed(url)
    with pytest.raises(cm.CoverUnavailable) as caught, _client(seen=seen) as client:
        cm.fetch_cover(url, client=client)
    assert caught.value.reason == "refused" and seen == []


#: The review's exact case: `urlsplit` drops the tab (host `evil.com.cdninstagram.com`), httpx
#: refuses the URL with `InvalidURL`, which is not an `HTTPError`.
TAB_TRICK = "https://evil.com\t.cdninstagram.com/"


@pytest.mark.parametrize(
    "url",
    [
        TAB_TRICK,
        "https://evil.com\n.cdninstagram.com/",
        "https://evil.com\r.cdninstagram.com/",
        "https://evil.com .cdninstagram.com/",
        "https://scontent.cdninstagram.com/C1.jpg\x00",
        "https://scontent.cdninstagram.com\u3002evil.com/C1.jpg",  # an ideographic full stop
        "https://scöntent.cdninstagram.com/C1.jpg",
    ],
)
def test_a_url_with_a_control_character_or_outside_ascii_is_refused(url: str) -> None:
    seen: list[httpx.Request] = []
    assert not cm.cdn_host_allowed(url)
    with pytest.raises(cm.CoverUnavailable) as caught, _client(seen=seen) as client:
        cm.fetch_cover(url, client=client)
    assert caught.value.reason == "refused" and seen == []


def test_a_url_httpx_will_not_send_is_refused_even_past_the_host_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cm, "cdn_host_allowed", lambda url: True)  # as if the check missed it
    with pytest.raises(cm.CoverUnavailable) as caught, _client() as client:
        cm.fetch_cover(TAB_TRICK, client=client)
    assert caught.value.reason == "refused"


def test_the_cdn_hosts_are_the_networks_own_and_nothing_else() -> None:
    """Exactly the networks' CDNs: unavatar.io stays the avatar proxy's own extra source,
    never a cover's (pinned as the whole tuple, so an addition is a reviewed change)."""
    assert cm.CDN_HOST_SUFFIXES == (
        "tiktokcdn.com",
        "tiktokcdn-us.com",
        "tiktokcdn-eu.com",
        "cdninstagram.com",
        "fbcdn.net",
    )


# --------------------------------------------------------------------------------------
# the download
# --------------------------------------------------------------------------------------


def test_a_cover_is_fetched_with_a_browser_agent_and_no_redirect_followed() -> None:
    seen: list[httpx.Request] = []
    with _client(_jpeg_response(), seen=seen) as client:
        body, kind = cm.fetch_cover(URL, client=client)
    assert kind == "image/jpeg" and body[:3] == b"\xff\xd8\xff"
    assert seen[0].headers["user-agent"].startswith("Mozilla/5.0")


def test_a_redirect_is_refused_even_to_another_cdn_host() -> None:
    other = "https://scontent-mia3-1.cdninstagram.com/v/C1.jpg"
    seen: list[httpx.Request] = []
    moved = httpx.Response(302, headers={"location": other})
    with pytest.raises(cm.CoverUnavailable) as caught, _client(moved, seen=seen) as client:
        cm.fetch_cover(URL, client=client)
    assert caught.value.reason == "redirect" and len(seen) == 1


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (httpx.Response(403, content=b"URL signature expired"), "http_403"),
        (httpx.Response(500), "http_500"),
        (
            httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>"),
            "not_an_image",
        ),
        (
            httpx.Response(200, headers={"content-type": "image/gif"}, content=b"GIF89a"),
            "not_an_image",
        ),
        (httpx.Response(200, headers={"content-type": "image/jpeg"}, content=b""), "not_an_image"),
        (
            httpx.Response(
                200,
                headers={"content-type": "image/jpeg", "content-length": "3000001"},
                content=b"x",
            ),
            "too_large",
        ),
    ],
)
def test_what_is_not_a_small_picture_is_refused(response: httpx.Response, reason: str) -> None:
    with pytest.raises(cm.CoverUnavailable) as caught, _client(response) as client:
        cm.fetch_cover(URL, client=client)
    assert caught.value.reason == reason
    assert URL not in str(caught.value) and "cdninstagram" not in str(caught.value)


def test_a_body_over_three_megabytes_is_cut_off_while_streaming() -> None:
    def chunks():
        for _ in range(4):
            yield b"x" * 1_000_000

    big = httpx.Response(200, headers={"content-type": "image/jpeg"}, content=chunks())
    with pytest.raises(cm.CoverUnavailable) as caught, _client(big) as client:
        cm.fetch_cover(URL, client=client)
    assert caught.value.reason == "too_large"


def test_a_cover_is_asked_for_as_stored_and_a_compressed_answer_is_refused_unread() -> None:
    """Review item 6: the 3 MB cap counts the bytes on the wire — the body is asked for
    with `Accept-Encoding: identity` and read raw, and an answer compressed anyway is
    refused before a byte of it is read (48 KB of gzip once inflated to ~125 MiB)."""
    import gzip

    seen: list[httpx.Request] = []
    with _client(_jpeg_response(), seen=seen) as client:
        cm.fetch_cover(URL, client=client)
    assert seen[0].headers["accept-encoding"] == "identity"

    read: list[int] = []

    def bomb():
        read.append(1)
        yield gzip.compress(b"\0" * 10_000_000)

    zipped = httpx.Response(
        200, headers={"content-type": "image/jpeg", "content-encoding": "gzip"}, content=bomb()
    )
    with pytest.raises(cm.CoverUnavailable) as caught, _client(zipped) as client:
        cm.fetch_cover(URL, client=client)
    assert caught.value.reason == "encoded" and read == []


def test_a_download_that_trickles_past_the_deadline_is_cut_off() -> None:
    """Each read within its 8 s, the whole past `COVER_DEADLINE_SECONDS`: the clock is the
    test's, moving 5 s per look."""
    moments = iter(range(0, 1000, 5))

    def chunks():
        for _ in range(5):
            yield b"x" * 1000

    slow = httpx.Response(200, headers={"content-type": "image/jpeg"}, content=chunks())
    with pytest.raises(cm.CoverUnavailable) as caught, _client(slow) as client:
        cm.fetch_cover(URL, client=client, clock=lambda: float(next(moments)))
    assert caught.value.reason == "too_slow"


def test_a_network_failure_is_a_reason_not_the_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout(f"timed out reaching {request.url}")

    with (
        pytest.raises(cm.CoverUnavailable) as caught,
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
    ):
        cm.fetch_cover(URL, client=client)
    assert caught.value.reason == "network" and "cdninstagram" not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


# --------------------------------------------------------------------------------------
# the re-encode
# --------------------------------------------------------------------------------------


def test_the_copy_is_a_small_jpeg_without_any_metadata_and_upright() -> None:
    pixels = Image.new("RGB", (1080, 1920), (10, 200, 30))
    pixels.paste((255, 0, 0), (0, 0, 1080, 100))  # a red band along the stored top
    exif = Image.Exif()
    exif[0x0112] = 6  # «rotate 90° clockwise to show»
    exif[0x010F] = "Canon"
    exif[0x013B] = "Ana Pérez"  # the artist: a person's name
    source = io.BytesIO()
    pixels.save(source, "JPEG", exif=exif.tobytes(), icc_profile=b"\0" * 128, comment=b"x")
    with Image.open(io.BytesIO(cm.reencode_cover(source.getvalue()))) as copy:
        assert copy.format == "JPEG" and copy.size == (720, 405)  # upright, then ≤ 720
        assert not {"exif", "icc_profile", "comment"} & set(copy.info)
        assert dict(copy.getexif()) == {}
        assert copy.getpixel((715, 200))[0] > 200  # the band now runs down the right side


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_jpeg_png_and_webp_are_accepted(fmt: str) -> None:
    with Image.open(io.BytesIO(cm.reencode_cover(_picture(fmt)))) as copy:
        assert copy.format == "JPEG" and max(copy.size) == cm.COVER_MAX_SIDE


def test_heic_is_accepted() -> None:
    pillow_heif = pytest.importorskip("pillow_heif")
    pillow_heif.register_heif_opener()
    out = io.BytesIO()
    try:
        Image.new("RGB", (800, 600), (1, 2, 3)).save(out, format="HEIF")
    except Exception:  # noqa: BLE001 - an install without an HEIF encoder
        pytest.skip("pillow-heif has no encoder here")
    with Image.open(io.BytesIO(cm.reencode_cover(out.getvalue()))) as copy:
        assert (copy.format, copy.size) == ("JPEG", (720, 540))


def test_a_small_picture_is_not_enlarged_and_transparency_turns_white() -> None:
    with Image.open(io.BytesIO(cm.reencode_cover(_picture("PNG", (300, 200))))) as copy:
        assert copy.size == (300, 200)
    clear = io.BytesIO()
    Image.new("RGBA", (40, 40), (0, 0, 0, 0)).save(clear, "PNG")
    with Image.open(io.BytesIO(cm.reencode_cover(clear.getvalue()))) as copy:
        assert copy.getpixel((5, 5)) == (255, 255, 255)


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (_picture("GIF", (10, 10)), "not_an_image"),
        (_picture("BMP", (10, 10)), "not_an_image"),
        (b"<html>not a picture</html>", "undecodable"),
        (_picture("JPEG")[:400], "undecodable"),
        (_picture("PNG", (4097, 8)), "too_big"),
        (_picture("PNG", (8, 4097)), "too_big"),
    ],
)
def test_anything_else_is_refused(data: bytes, reason: str) -> None:
    with pytest.raises(cm.CoverUnavailable) as caught:
        cm.reencode_cover(data)
    assert caught.value.reason == reason


def test_the_largest_accepted_side_is_4096() -> None:
    with Image.open(io.BytesIO(cm.reencode_cover(_picture("PNG", (4096, 64))))) as copy:
        assert copy.size == (720, 11)


def test_a_2048_square_webp_is_accepted_and_anything_over_4_mp_is_not() -> None:
    """The reels-worker's memory (review of R12): decoding is what costs, so at most
    2048×2048 pixels in all — a real cover is 1080×1920 — besides the 4096 px per side."""
    with Image.open(io.BytesIO(cm.reencode_cover(_picture("WEBP", (2048, 2048))))) as copy:
        assert copy.size == (720, 720)
    with Image.open(io.BytesIO(cm.reencode_cover(_picture("PNG", (4096, 1024))))) as copy:
        assert copy.size == (720, 180)  # exactly 4 MP, the widest side allowed
    for size in ((2049, 2048), (2048, 2049), (4096, 1025)):
        with pytest.raises(cm.CoverUnavailable) as caught:
            cm.reencode_cover(_picture("WEBP", size))
        assert caught.value.reason == "too_big", size


def test_an_oversized_picture_is_refused_from_its_header_before_any_decoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Were the pixels decoded first, the patched `load` would make it `undecodable`."""
    big = _picture("PNG", (2049, 2048))

    def no_decoding(self: Image.Image) -> None:
        raise AssertionError("the picture was decoded before its size was checked")

    monkeypatch.setattr(Image.Image, "load", no_decoding)
    with pytest.raises(cm.CoverUnavailable) as caught:
        cm.reencode_cover(big)
    assert caught.value.reason == "too_big"


# --------------------------------------------------------------------------------------
# when a link is dead
# --------------------------------------------------------------------------------------


def test_signature_expired_reads_instagram_and_tiktok_stamps() -> None:
    moment = NOW.timestamp()
    assert cm.signature_expired(
        f"https://x.cdninstagram.com/p.jpg?oe={int(moment) - 1:X}", now=moment
    )
    assert not cm.signature_expired(
        f"https://x.cdninstagram.com/p.jpg?oe={int(moment) + 60:X}", now=moment
    )
    assert cm.signature_expired(
        f"https://t.tiktokcdn.com/p.jpeg?x-expires={int(moment)}", now=moment
    )
    assert not cm.signature_expired("https://t.tiktokcdn.com/p.jpeg", now=moment)  # unknown: alive


def test_a_cover_url_is_fresh_while_signed_alive_and_younger_than_four_days() -> None:
    alive = f"https://x.cdninstagram.com/p.jpg?oe={int((NOW + timedelta(days=1)).timestamp()):X}"
    dead = f"https://x.cdninstagram.com/p.jpg?oe={int((NOW - timedelta(hours=1)).timestamp()):X}"
    unsigned = "https://p16-sign.tiktokcdn.com/obj/cover.jpeg"
    assert cm.cover_url_fresh(alive, NOW - timedelta(days=3), NOW)
    assert not cm.cover_url_fresh(dead, NOW - timedelta(hours=2), NOW)
    assert cm.cover_url_fresh(unsigned, NOW - timedelta(days=3), NOW)
    assert not cm.cover_url_fresh(unsigned, NOW - timedelta(days=4, minutes=1), NOW)
    assert not cm.cover_url_fresh("https://evil.example/p.jpg", NOW, NOW)
    assert not cm.cover_url_fresh(None, NOW, NOW) and not cm.cover_url_fresh("", NOW, NOW)
