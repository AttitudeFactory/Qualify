"""URL handling for the Meta developer-docs crawl. Pure functions, no I/O.

**Do not add a `/docs/` <-> `/documentation/` rewrite here.** It is the obvious
thing to try and it is wrong. `developers.facebook.com` serves two distinct
documentation systems:

  - a *new* system, canonically under `/documentation/`, which `/docs/` 301s to;
  - a *legacy* system that exists only under `/docs/` and is never redirected.

Measured, 2026-07-24:

    /docs/instagram-platform  -> 301 -> /documentation/instagram-platform  (markdown)
    /docs/app-review          -> 301 x3 -> /documentation/resp-plat-initiatives/
                                           individual-processes/app-review
    /docs/graph-api/overview  -> 200, no redirect, text/html

Rewriting toward `/documentation/` maps the whole Graph API tree onto a soft-404
(see `soft404.py`); rewriting toward `/docs/` breaks the new system instead. The
`app-review` case shows the mapping is not even expressible as a string rule --
three hops and a completely different path.

So: canonicalization here is *syntactic only* (scheme/host/fragment/trailing
slash). The `/docs/` -> `/documentation/` relation is resolved at fetch time by
following redirects, and every downstream key -- manifest, dedupe, local path --
is derived from the **final effective URL**. `crawl.py` keeps the requested ->
effective alias table so the two spellings of one page collapse to one fetch.
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

DOCS_HOST = "developers.facebook.com"

# Founder-approved scope: the full instagram-platform tree plus the Meta graph-api
# base set (Graph API core, App Review, Business Verification, access tokens).
# Both prefix spellings are listed where both systems serve the tree, because we
# classify *before* knowing which one a redirect will land on.
IN_SCOPE_PREFIXES: tuple[str, ...] = (
    "/documentation/instagram-platform",
    "/docs/instagram-platform",
    # Graph API core lives only under /docs/ (legacy system, HTML-rendered).
    "/docs/graph-api",
    "/documentation/graph-api",
    # Per-permission reference: one page, fragments per permission.
    "/docs/permissions",
    "/documentation/permissions",
    # App Review.
    "/docs/resp-plat-initiatives",
    "/documentation/resp-plat-initiatives",
    # Business Verification.
    "/docs/development/release/business-verification",
    "/documentation/development/release/business-verification",
    # Access tokens / Facebook Login for Business (the client-onboarding model).
    "/docs/facebook-login",
    "/documentation/facebook-login",
    # Instagram Messaging API.
    "/docs/business-messaging/instagram-messaging",
    "/documentation/business-messaging/instagram-messaging",
)

_ABSOLUTE_LINK_RE = re.compile(r"https://developers\.facebook\.com/[^\s)\"'<>\]]+")


def canonicalize(url: str, *, base: str | None = None) -> str | None:
    """Normalize a URL syntactically, or return None if it is not a docs URL.

    Strips the fragment (`#instagram_business_content_publish` is a location on a
    page, not a page) and the query string, drops a trailing slash, and lowercases
    the host. Relative URLs resolve against `base` when given.

    Returns None for anything off-host or non-HTTP -- the caller treats that as
    out of scope rather than as an error.
    """
    raw = url.strip()
    if not raw:
        return None
    if base is not None:
        raw = urljoin(base, raw)

    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https"):
        return None
    if parts.hostname is None or parts.hostname.lower() != DOCS_HOST:
        return None

    path = posixpath.normpath(parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    # normpath collapses "" to "."; guard so we never emit a relative path.
    if not path.startswith("/"):
        path = "/" + path.lstrip("./")

    return urlunsplit(("https", DOCS_HOST, path, "", ""))


def is_in_scope(url: str) -> bool:
    """True if `url` falls inside the founder-approved harvest scope.

    Deliberately an allowlist. BFS from these seeds otherwise reaches all of
    developers.facebook.com -- the discovered link set already includes
    marketing-api, devpolicy, terms and javascript after two hops.
    """
    canonical = canonicalize(url)
    if canonical is None:
        return False
    path = urlsplit(canonical).path
    return any(path == prefix or path.startswith(prefix + "/") for prefix in IN_SCOPE_PREFIXES)


def url_to_local_path(url: str, root: Path) -> Path:
    """Map a canonical URL to its file in the corpus, mirroring the URL path.

    `/documentation/instagram-platform/overview` -> `<root>/documentation/
    instagram-platform/overview.md`.

    A page that is also a parent (`.../instagram-platform` has children) is safe:
    the file is `instagram-platform.md` while the children live in the sibling
    directory `instagram-platform/`, so the two names never collide.
    """
    canonical = canonicalize(url)
    if canonical is None:
        raise ValueError(f"not a docs URL: {url!r}")
    path = urlsplit(canonical).path.strip("/")
    if not path:
        return root / "index.md"
    return root / (path + ".md")


def extract_links(body: str, *, base: str) -> list[str]:
    """Pull outbound docs links from a page body, canonicalized and deduped.

    Handles both response shapes this host serves: markdown (where Meta emits
    absolute `https://developers.facebook.com/...` URLs, including inside
    `[text](url)`) and HTML (where `href` may be root-relative). Order is
    preserved so the crawl frontier is deterministic and the tests can assert it.
    """
    found: list[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> None:
        canonical = canonicalize(candidate, base=base)
        if canonical is not None and canonical not in seen:
            seen.add(canonical)
            found.append(canonical)

    for match in _ABSOLUTE_LINK_RE.finditer(body):
        add(match.group(0))

    # HTML hrefs, including root-relative ones the regex above cannot see.
    for match in re.finditer(r"""href=["']([^"']+)["']""", body):
        add(match.group(1))

    return found
