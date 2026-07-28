"""Soft-404 detection and HTML->markdown conversion, against real captured pages."""

from __future__ import annotations

from qualify_docs_harvester.htmlmd import extract_content_html, html_to_markdown
from qualify_docs_harvester.soft404 import is_soft_404, visible_text


class TestSoftFourOhFour:
    def test_detects_metas_real_soft_404(self, soft404_html: str) -> None:
        """`/documentation/graph-api/overview` -- HTTP 200, 136KB, 40 characters
        of visible text reading 'Page Not Found'. Captured 2026-07-24."""
        assert is_soft_404(soft404_html)
        assert len(visible_text(soft404_html)) < 200

    def test_real_page_is_not_flagged(self, graphapi_html: str) -> None:
        assert not is_soft_404(graphapi_html)

    def test_markdown_page_is_not_flagged(self, ig_overview_markdown: str) -> None:
        assert not is_soft_404(ig_overview_markdown)

    def test_long_page_mentioning_not_found_is_not_flagged(self) -> None:
        """The Graph API error-codes reference discusses 404 handling at length.
        Requiring both signals -- marker *and* implausibly short body -- keeps it
        out of the false-positive bucket."""
        body = (
            "<html><body><h1>Error codes</h1><p>"
            + ("A page not found error is returned when the node does not exist. " * 40)
            + "</p></body></html>"
        )
        assert not is_soft_404(body)

    def test_spanish_locale_soft_404(self) -> None:
        """The host geo-localizes; without Accept-Language it answers in Spanish."""
        body = "<html><head></head><body>No se pudo encontrar la página</body></html>"
        assert is_soft_404(body)

    def test_visible_text_strips_scripts_and_styles(self) -> None:
        body = "<style>.a{color:red}</style><script>var x=1;</script><p>Hello</p>"
        assert visible_text(body) == "Hello"


class TestHtmlToMarkdown:
    def test_isolates_metas_content_container(self, graphapi_html: str) -> None:
        """~1MB in, and almost all of it is chrome. Converting the whole document
        would bury the prose."""
        content = extract_content_html(graphapi_html)
        assert len(content) < len(graphapi_html) / 2
        assert "Graph API overview" in content

    def test_converts_real_graph_api_page(self, graphapi_html: str) -> None:
        markdown = html_to_markdown(graphapi_html)
        assert markdown.startswith("# Graph API overview")
        assert "The Graph API is the primary way to get data" in markdown
        # The conversion must actually shrink the payload to its prose.
        assert len(markdown) < 60_000
        assert "<script" not in markdown
        assert "_4-u2" not in markdown  # Facebook's CSS class soup is gone

    def test_falls_back_to_whole_body_when_container_missing(self) -> None:
        """A layout change on Meta's side should degrade the conversion, not drop
        the page. The manifest records which path ran, so a spike is visible."""
        markdown = html_to_markdown("<html><body><h1>Title</h1><p>Body</p></body></html>")
        assert "Title" in markdown
        assert "Body" in markdown

    def test_collapses_blank_line_runs(self) -> None:
        body = (
            "<div id='documentation_body_pagelet'><p>a</p>" + "<div></div>" * 30 + "<p>b</p></div>"
        )
        markdown = html_to_markdown(body)
        assert "\n\n\n\n" not in markdown
