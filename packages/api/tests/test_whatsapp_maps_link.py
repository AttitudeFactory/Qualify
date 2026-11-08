"""m-24945889 — `resolve_maps_link`, the one parser of a pasted Google Maps link. Offline:
a fake hop fetcher, and `default_hop` with a fake resolver and an httpx MockTransport."""

from __future__ import annotations

import functools

import httpx
import pytest

from qualify_api.whatsapp.maps_link import (
    MAX_HOPS,
    REASON_NO_POINT,
    REASON_NOT_MAPS,
    REASON_UNREACHABLE,
    REASON_UNSAFE,
    Hop,
    MapsPoint,
    UnsafeHop,
    default_hop,
    parse_maps_url,
    resolve_maps_link,
)

LONG = (
    "https://www.google.com/maps/place/Bianki+Shawarma/@7.8939,-72.5078,17z/"
    "data=!3m1!4b1!4m6!3m5!1s0x0:0x0!8m2!3d7.894123!4d-72.503456"
)
SHORT = "https://maps.app.goo.gl/AbCdEf123"


class Script:
    """A hop fetcher answering from a dict url → Hop; records the calls."""

    def __init__(self, answers: dict[str, Hop | Exception]) -> None:
        self.answers = answers
        self.calls: list[str] = []

    def __call__(self, url: str, timeout: float) -> Hop:
        self.calls.append(url)
        answer = self.answers[url]
        if isinstance(answer, Exception):
            raise answer
        return answer


def test_a_short_link_is_followed_to_its_point() -> None:
    hop = Script({SHORT: Hop(302, LONG)})
    result = resolve_maps_link(SHORT, hop=hop)
    assert result.point == MapsPoint(7.894123, -72.503456, "Bianki Shawarma")
    assert hop.calls == [SHORT]


def test_a_long_link_needs_no_network() -> None:
    hop = Script({})
    assert resolve_maps_link(LONG, hop=hop).point.latitude == 7.894123
    assert hop.calls == []


def test_a_redirect_to_another_host_is_refused() -> None:
    hop = Script({SHORT: Hop(301, "https://evil.example/maps/@1,2")})
    assert resolve_maps_link(SHORT, hop=hop).reason == REASON_UNSAFE
    http_hop = Script({SHORT: Hop(301, "http://www.google.com/maps/@1,2")})
    assert resolve_maps_link(SHORT, hop=http_hop).reason == REASON_UNSAFE


def test_more_than_three_hops_is_refused() -> None:
    chain = {
        f"https://maps.app.goo.gl/{i}": Hop(302, f"https://maps.app.goo.gl/{i + 1}")
        for i in range(10)
    }
    hop = Script(chain)
    result = resolve_maps_link("https://maps.app.goo.gl/0", hop=hop)
    assert result.reason == REASON_UNSAFE and len(hop.calls) == MAX_HOPS


def test_a_private_address_is_refused_before_connecting() -> None:
    def private(host: str, port: int) -> list[str]:
        return ["10.0.0.7"]

    with pytest.raises(UnsafeHop):
        default_hop(SHORT, 4.0, resolve=private)
    hop = functools.partial(default_hop, resolve=private)
    assert resolve_maps_link(SHORT, hop=hop).reason == REASON_UNSAFE


def test_the_default_hop_reads_the_redirect_pinned_and_without_cookies() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(302, headers={"location": LONG})

    hop = functools.partial(
        default_hop,
        resolve=lambda host, port: ["142.250.78.110"],
        transport=httpx.MockTransport(handler),
    )
    result = resolve_maps_link(SHORT, hop=hop)
    assert result.point is not None and result.point.longitude == -72.503456
    (request,) = seen
    assert request.method == "HEAD" and request.url.host == "142.250.78.110"
    assert request.headers["host"] == "maps.app.goo.gl" and "cookie" not in request.headers


def test_a_link_that_does_not_answer_is_reported() -> None:
    assert resolve_maps_link(SHORT, hop=Script({SHORT: TimeoutError()})).reason == (
        REASON_UNREACHABLE
    )
    assert resolve_maps_link(SHORT, hop=Script({SHORT: Hop(200)})).reason == REASON_UNREACHABLE


@pytest.mark.parametrize(
    ("url", "point"),
    [
        ("https://www.google.com/maps/@7.89,-72.5,15z", (7.89, -72.5)),
        ("https://maps.google.com/?q=7.89,-72.5", (7.89, -72.5)),
        ("https://www.google.com/maps/search/?api=1&query=7.89%2C-72.5", (7.89, -72.5)),
        ("https://maps.google.com.co/?ll=7.89,-72.5&z=15", (7.89, -72.5)),
        (
            "https://www.google.com.ve/maps/place/X/@7.8,-72.4,17z/data=!3d7.89!4d-72.5",
            (7.89, -72.5),
        ),
        ("https://google.com/maps/dir/?api=1&destination=7.89,-72.5", (7.89, -72.5)),
    ],
)
def test_every_long_form(url: str, point: tuple[float, float]) -> None:
    found = parse_maps_url(url)
    assert found is not None and (found.latitude, found.longitude) == point


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("", REASON_NOT_MAPS),
        ("hola", REASON_NOT_MAPS),
        ("https://example.com/maps/@1,2", REASON_NOT_MAPS),
        ("http://www.google.com/maps/@1,2", REASON_NOT_MAPS),
        ("https://goo.gl/abc", REASON_NOT_MAPS),
        ("https://www.google.com/search?q=bianki", REASON_NOT_MAPS),
        ("https://www.google.com/maps/place/Bianki", REASON_NO_POINT),
        ("https://www.google.com/maps/@95,-72.5,15z", REASON_NO_POINT),
    ],
)
def test_junk_is_refused_with_its_reason(url: str, reason: str) -> None:
    result = resolve_maps_link(url, hop=Script({}))
    assert result.point is None and result.reason == reason


# --- security review: pinned refusals --------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://maps.app.goo.gl@evil.example/x",  # credentials / userinfo
        "https://user:pw@maps.app.goo.gl/x",
        "https://maps.app.goo.gl.evil.com/x",  # look-alike hosts
        "https://google.com.evil.tld/maps/@1,2",
        "https://www.google.evil/maps/@1,2",
        "https://maps.app.goo.gl:8443/x",  # an explicit port
        "https://www.google.com:8080/maps/@1,2",
        "https://maps.app.goo.gl./x",  # a trailing dot
        "https://www.google.com./maps/@1,2",
    ],
)
def test_crafted_links_are_refused_without_a_request(url: str) -> None:
    hop = Script({})
    result = resolve_maps_link(url, hop=hop)
    assert result.point is None and result.reason == REASON_NOT_MAPS and hop.calls == []


@pytest.mark.parametrize(
    "location",
    [
        "http://www.google.com/maps/@1,2",
        "http://maps.app.goo.gl/next",
        "https://maps.app.goo.gl.evil.com/next",
        "https://www.google.com:8443/maps/@1,2",
        "https://user@www.google.com/maps/@1,2",
    ],
)
def test_a_redirect_off_the_safe_hosts_is_refused(location: str) -> None:
    hop = Script({SHORT: Hop(302, location)})
    assert resolve_maps_link(SHORT, hop=hop).reason == REASON_UNSAFE


def test_port_443_is_accepted() -> None:
    assert resolve_maps_link("https://www.google.com:443/maps/@7.89,-72.5,15z").point is not None


def test_the_budget_is_total_across_the_read() -> None:
    import time as real_time

    def slow(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(405)

        def body():
            while True:
                real_time.sleep(0.05)
                yield b"x" * 10

        return httpx.Response(200, content=body())

    hop = functools.partial(
        default_hop,
        resolve=lambda host, port: ["142.250.78.110"],
        transport=httpx.MockTransport(slow),
    )
    started = real_time.monotonic()
    with pytest.raises(TimeoutError):
        hop(SHORT, 0.2)
    assert real_time.monotonic() - started < 1.0
