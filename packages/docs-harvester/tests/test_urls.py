"""URL handling. The regression guards here encode findings that cost real
discovery time -- see `urls.py`'s module docstring for the measurements."""

from __future__ import annotations

from pathlib import Path

import pytest

from qualify_docs_harvester.urls import (
    canonicalize,
    extract_links,
    is_in_scope,
    url_to_local_path,
)

BASE = "https://developers.facebook.com/documentation/instagram-platform"


class TestCanonicalize:
    def test_strips_fragment(self) -> None:
        # Per-permission URLs are fragments on one page; keeping them would fetch
        # the same 1.1MB document once per permission.
        assert (
            canonicalize(
                "https://developers.facebook.com/docs/permissions#instagram_business_basic"
            )
            == "https://developers.facebook.com/docs/permissions"
        )

    def test_strips_query_and_trailing_slash(self) -> None:
        assert (
            canonicalize("https://developers.facebook.com/docs/permissions/?locale=en_US")
            == "https://developers.facebook.com/docs/permissions"
        )

    def test_upgrades_scheme_and_lowercases_host(self) -> None:
        assert (
            canonicalize("http://DEVELOPERS.facebook.com/docs/instagram-platform")
            == "https://developers.facebook.com/docs/instagram-platform"
        )

    def test_resolves_relative_against_base(self) -> None:
        assert (
            canonicalize("/docs/graph-api/overview", base=BASE)
            == "https://developers.facebook.com/docs/graph-api/overview"
        )

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.facebook.com/business/m/one-sheeters/page-publishing-authorization",
            "https://business.instagram.com/",
            "mailto:someone@example.com",
            "",
        ],
    )
    def test_rejects_non_docs_urls(self, url: str) -> None:
        assert canonicalize(url) is None

    def test_does_not_rewrite_docs_to_documentation(self) -> None:
        """The load-bearing guard. Rewriting these into each other maps the whole
        Graph API tree onto a soft-404 in one direction and breaks the Instagram
        tree in the other. The relation is resolved by following redirects, never
        by string surgery -- `/docs/app-review` reaches
        `/documentation/resp-plat-initiatives/individual-processes/app-review`
        in three hops, which no rewrite rule could produce."""
        docs = canonicalize("https://developers.facebook.com/docs/graph-api/overview")
        documentation = canonicalize(
            "https://developers.facebook.com/documentation/graph-api/overview"
        )
        assert docs != documentation
        assert docs is not None and "/docs/" in docs
        assert documentation is not None and "/documentation/" in documentation


class TestScope:
    @pytest.mark.parametrize(
        "url",
        [
            "https://developers.facebook.com/docs/instagram-platform",
            "https://developers.facebook.com/documentation/instagram-platform/overview",
            "https://developers.facebook.com/documentation/instagram-platform/"
            "instagram-graph-api/reference/ig-comment/replies",
            "https://developers.facebook.com/docs/graph-api/overview/access-levels",
            "https://developers.facebook.com/docs/permissions",
            "https://developers.facebook.com/docs/facebook-login/guides/access-tokens",
            "https://developers.facebook.com/documentation/resp-plat-initiatives/"
            "individual-processes/app-review",
            "https://developers.facebook.com/docs/development/release/business-verification",
            "https://developers.facebook.com/documentation/business-messaging/instagram-messaging",
        ],
    )
    def test_in_scope(self, url: str) -> None:
        assert is_in_scope(url)

    @pytest.mark.parametrize(
        "url",
        [
            # The long tail two hops out from the seeds. This is what the
            # allowlist exists to stop.
            "https://developers.facebook.com/docs/marketing-api",
            "https://developers.facebook.com/docs/devpolicy",
            "https://developers.facebook.com/docs/javascript",
            "https://developers.facebook.com/terms",
            "https://developers.facebook.com/docs/instagram/embedding",
            "https://www.facebook.com/business/help",
        ],
    )
    def test_out_of_scope(self, url: str) -> None:
        assert not is_in_scope(url)

    def test_prefix_match_respects_path_boundary(self) -> None:
        """`/docs/permissions-elsewhere` must not match the `/docs/permissions`
        prefix -- otherwise the allowlist leaks on any sibling path sharing a
        textual prefix."""
        assert not is_in_scope("https://developers.facebook.com/docs/permissions-elsewhere")


class TestLocalPath:
    def test_mirrors_url_path(self, tmp_path: Path) -> None:
        assert (
            url_to_local_path(
                "https://developers.facebook.com/documentation/instagram-platform/overview",
                tmp_path,
            )
            == tmp_path / "documentation/instagram-platform/overview.md"
        )

    def test_page_that_is_also_a_parent_does_not_collide(self, tmp_path: Path) -> None:
        """`.../instagram-platform` is both a page and the parent of its children.
        The file is `instagram-platform.md`, the children live in
        `instagram-platform/` -- different names, so both can exist."""
        parent = url_to_local_path(
            "https://developers.facebook.com/documentation/instagram-platform", tmp_path
        )
        child = url_to_local_path(
            "https://developers.facebook.com/documentation/instagram-platform/overview",
            tmp_path,
        )
        assert parent == tmp_path / "documentation/instagram-platform.md"
        assert child.parent == tmp_path / "documentation/instagram-platform"
        assert parent != child
        parent.parent.mkdir(parents=True, exist_ok=True)
        parent.write_text("page")
        child.parent.mkdir(parents=True, exist_ok=True)
        child.write_text("child")
        assert parent.read_text() == "page"

    def test_rejects_foreign_url(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            url_to_local_path("https://example.com/x", tmp_path)


class TestExtractLinks:
    def test_extracts_from_real_meta_markdown(self, ig_root_markdown: str) -> None:
        links = extract_links(ig_root_markdown, base=BASE)
        assert (
            "https://developers.facebook.com/documentation/instagram-platform/"
            "instagram-api-with-instagram-login" in links
        )
        assert (
            "https://developers.facebook.com/documentation/instagram-platform/sharing-to-stories"
            in links
        )
        # Off-host links in the same document are dropped, not returned as junk.
        assert all(link.startswith("https://developers.facebook.com/") for link in links)

    def test_deduplicates_and_preserves_order(self) -> None:
        body = (
            "[a](https://developers.facebook.com/docs/one) "
            "[b](https://developers.facebook.com/docs/two) "
            "[a again](https://developers.facebook.com/docs/one#frag)"
        )
        assert extract_links(body, base=BASE) == [
            "https://developers.facebook.com/docs/one",
            "https://developers.facebook.com/docs/two",
        ]

    def test_extracts_root_relative_hrefs_from_html(self) -> None:
        body = '<a href="/docs/graph-api/reference" class="_3cx9">Reference</a>'
        assert extract_links(body, base=BASE) == [
            "https://developers.facebook.com/docs/graph-api/reference"
        ]

    def test_finds_the_permissions_reference_from_content_publishing(
        self, ig_overview_markdown: str
    ) -> None:
        """The permissions page gates the A5 ruling, so its discoverability from
        the Instagram tree is worth pinning rather than assuming."""
        links = extract_links(ig_overview_markdown, base=BASE)
        assert any("/docs/graph-api/overview/access-levels" in link for link in links)
