"""The host rule a picture URL must meet (`qualify_api.vendors.cdn_media.url_on_hosts`,
m-24957331): https on port 443, no credentials, printable ASCII, a host equal to or under
a listed suffix, or exactly a listed name. Offline, no request is made.

A file of its own (not `test_cdn_media.py`): that one comes with #470 (R12), with the rest
of the module."""

from __future__ import annotations

import pytest

from qualify_api.vendors import cdn_media as cm

EXACT = {"unavatar.io"}


@pytest.mark.parametrize(
    "url",
    [
        "https://scontent-bog1-1.cdninstagram.com/v/C1.jpg",
        "https://instagram.fbog2-1.fna.fbcdn.net/v/C1.jpg",
        "https://p16-sign-va.tiktokcdn.com/obj/cover.jpeg",
        "https://p19-sign.tiktokcdn-us.com/obj/cover.heic",
        "https://p16.tiktokcdn-eu.com:443/obj/cover.webp",
        "https://cdninstagram.com/C1.jpg",
        "https://unavatar.io/tiktok/sof_lol?fallback=false",
    ],
)
def test_the_networks_cdns_and_unavatar_itself_are_allowed(url: str) -> None:
    assert cm.url_on_hosts(url, cm.CDN_HOST_SUFFIXES, exact=EXACT)


@pytest.mark.parametrize(
    "url",
    [
        "http://scontent.cdninstagram.com/C1.jpg",  # not https
        "https://scontent.cdninstagram.com:8443/C1.jpg",  # not 443
        "https://scontent.cdninstagram.com:99999/C1.jpg",  # an invalid port
        "https://user:pw@scontent.cdninstagram.com/C1.jpg",  # credentials
        "https://user@scontent.cdninstagram.com/C1.jpg",
        "https://evil.example/cdninstagram.com/C1.jpg",
        "https://cdninstagram.com.evil.example/C1.jpg",
        "https://evilcdninstagram.com/C1.jpg",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/C1.jpg",
        "https://evil.com\t.cdninstagram.com/",  # urlsplit drops the tab, httpx does not
        "https://evil.com\n.cdninstagram.com/",
        "https://evil.com .cdninstagram.com/",
        "https://scontent.cdninstagram.com/C1.jpg\x00",
        "https://scöntent.cdninstagram.com/C1.jpg",
        "https://[",
        "not a url",
        "",
        "https://cdn.unavatar.io/tiktok/x",  # unavatar: the name itself, never a subdomain
        "https://localhost.unavatar.io/tiktok/x",
        "https://unavatar.io.evil.example/tiktok/x",
    ],
)
def test_anything_else_is_refused(url: str) -> None:
    assert not cm.url_on_hosts(url, cm.CDN_HOST_SUFFIXES, exact=EXACT)


def test_an_exact_name_matches_only_itself_and_suffixes_their_subdomains() -> None:
    assert cm.url_on_hosts("https://unavatar.io/x", (), exact=EXACT)
    assert not cm.url_on_hosts("https://unavatar.io/x", cm.CDN_HOST_SUFFIXES)  # not a CDN
    assert cm.url_on_hosts("https://a.b.cdninstagram.com/x", cm.CDN_HOST_SUFFIXES)
    # pinned whole (an addition is a reviewed change): the networks' CDNs, never unavatar
    assert cm.CDN_HOST_SUFFIXES == (
        "tiktokcdn.com",
        "tiktokcdn-us.com",
        "tiktokcdn-eu.com",
        "cdninstagram.com",
        "fbcdn.net",
    )
