"""HTML -> markdown conversion for the legacy `/docs/graph-api/**` tree.

Most of the approved scope (`instagram-platform`, app-review, business
verification, access tokens) is served as clean `text/markdown` and needs none of
this. The Graph API tree is the exception: it comes back as ~1MB of `text/html`.

That HTML is genuinely server-rendered -- `/docs/graph-api/overview` carries
~10.7KB of real prose -- so no browser is needed. But ~99% of the bytes are
navigation, chrome and inline script. Converting the whole document produces
mostly noise, so we isolate Meta's content container first.
"""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag
from markdownify import markdownify

# Meta wraps documentation body content in this pagelet. Verified present on
# /docs/graph-api/overview and /docs/permissions (2026-07-24).
CONTENT_CONTAINER_ID = "documentation_body_pagelet"


def extract_content_html(body: str) -> str:
    """Return the documentation content subtree, or the whole body as fallback.

    Falling back rather than raising is deliberate: a layout change on Meta's side
    should degrade the conversion to noisy-but-present, not drop the page. The
    manifest records which path produced each file, so a spike in fallbacks is
    visible after the fact.
    """
    soup = BeautifulSoup(body, "html.parser")
    container = soup.find(id=CONTENT_CONTAINER_ID)
    if isinstance(container, Tag):
        return str(container)
    return body


def html_to_markdown(body: str) -> str:
    """Convert a Meta docs HTML page to markdown."""
    content = extract_content_html(body)
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    markdown = markdownify(str(soup), heading_style="ATX")
    # markdownify leaves long runs of blank lines where chrome was removed.
    lines = [line.rstrip() for line in markdown.splitlines()]
    out: list[str] = []
    blanks = 0
    for line in lines:
        if line:
            blanks = 0
            out.append(line)
        else:
            blanks += 1
            if blanks <= 2:
                out.append(line)
    return "\n".join(out).strip() + "\n"
