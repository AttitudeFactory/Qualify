"""End-to-end crawl, driven entirely by `FixtureFetcher`.

Every test here runs the real `crawl()` with no network. The no-network property
is structural: `crawl` reaches the outside world only through the `Fetcher`
Protocol, and these tests inject a fixture-backed implementation.
"""

from __future__ import annotations

import json
from pathlib import Path

from qualify_docs_harvester.crawl import crawl
from qualify_docs_harvester.fetch import FetchResult, FixtureFetcher
from qualify_docs_harvester.manifest import read_journal

MD = "text/markdown; charset=utf-8"
HTML = 'text/html; charset="utf-8"'
IG = "https://developers.facebook.com/documentation/instagram-platform"
IG_DOCS = "https://developers.facebook.com/docs/instagram-platform"


def md_result(url: str, body: str, *, final: str | None = None) -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=final or url,
        status_code=200,
        content_type=MD,
        body=body,
    )


class TestCrawl:
    def test_harvests_and_mirrors_url_structure(self, tmp_path: Path) -> None:
        fetcher = FixtureFetcher(
            responses={
                IG: md_result(IG, f"# Root\n\n[Overview]({IG}/overview)"),
                f"{IG}/overview": md_result(f"{IG}/overview", "# Overview\n\nBody."),
            }
        )
        stats = crawl(fetcher=fetcher, output_root=tmp_path, seeds=(IG,))

        assert stats.harvested == 2
        assert (tmp_path / "documentation/instagram-platform.md").read_text().startswith("# Root")
        assert (
            (tmp_path / "documentation/instagram-platform/overview.md")
            .read_text()
            .startswith("# Overview")
        )

    def test_follows_redirect_and_keys_on_effective_url(self, tmp_path: Path) -> None:
        """`/docs/X` 301s to `/documentation/X`. The file must land under the
        effective URL, and the journal must record the alias."""
        fetcher = FixtureFetcher(
            responses={IG: md_result(IG, "# Root", final=IG)},
            redirects={IG_DOCS: IG},
        )
        crawl(fetcher=fetcher, output_root=tmp_path, seeds=(IG_DOCS,))

        assert (tmp_path / "documentation/instagram-platform.md").exists()
        assert not (tmp_path / "docs/instagram-platform.md").exists()

        entry = next(iter(read_journal(tmp_path / "manifest.jsonl")))
        assert entry.requested_url == IG_DOCS
        assert entry.final_url == IG
        assert entry.redirected

    def test_both_spellings_collapse_to_one_fetch(self, tmp_path: Path) -> None:
        """A page linked as `/docs/X` and `/documentation/X` is one page. Without
        alias handling it would be fetched twice and written twice."""
        fetcher = FixtureFetcher(
            responses={
                IG: md_result(IG, f"# Root\n\n[same page]({IG_DOCS})"),
            },
            redirects={IG_DOCS: IG},
        )
        stats = crawl(fetcher=fetcher, output_root=tmp_path, seeds=(IG,))

        assert stats.harvested == 1
        assert stats.duplicate == 1
        outcomes = [e.outcome for e in read_journal(tmp_path / "manifest.jsonl")]
        assert outcomes.count("harvested") == 1

    def test_soft_404_is_not_written_to_the_corpus(self, tmp_path: Path) -> None:
        """The defect this whole guard exists for: HTTP 200 with a not-found body
        must not become a corpus file recorded as a success."""
        url = "https://developers.facebook.com/documentation/graph-api/overview"
        fetcher = FixtureFetcher(
            responses={
                url: FetchResult(
                    requested_url=url,
                    final_url=url,
                    status_code=200,
                    content_type=HTML,
                    body="<html><body>Page Not Found - Meta for Developers</body></html>",
                )
            }
        )
        stats = crawl(fetcher=fetcher, output_root=tmp_path, seeds=(url,))

        assert stats.harvested == 0
        assert stats.soft_404 == 1
        assert not (tmp_path / "documentation/graph-api/overview.md").exists()
        assert any("soft-404" in f for f in stats.failures)

    def test_out_of_scope_links_are_recorded_not_dropped(self, tmp_path: Path) -> None:
        body = (
            "# Root\n\n"
            "[marketing](https://developers.facebook.com/docs/marketing-api)\n"
            "[terms](https://developers.facebook.com/terms)\n"
        )
        fetcher = FixtureFetcher(responses={IG: md_result(IG, body)})
        stats = crawl(fetcher=fetcher, output_root=tmp_path, seeds=(IG,))

        assert stats.harvested == 1
        assert stats.skipped_out_of_scope == 2
        skipped = [
            e
            for e in read_journal(tmp_path / "manifest.jsonl")
            if e.outcome == "skipped_out_of_scope"
        ]
        assert {e.final_url for e in skipped} == {
            "https://developers.facebook.com/docs/marketing-api",
            "https://developers.facebook.com/terms",
        }
        assert all(e.reason and "allowlist" in e.reason for e in skipped)
        # Recorded, never fetched.
        assert "https://developers.facebook.com/docs/marketing-api" not in fetcher.requested

    def test_html_pages_are_converted_and_labelled(self, tmp_path: Path) -> None:
        url = "https://developers.facebook.com/docs/graph-api/overview"
        fetcher = FixtureFetcher(
            responses={
                url: FetchResult(
                    requested_url=url,
                    final_url=url,
                    status_code=200,
                    content_type=HTML,
                    body=(
                        "<html><body><div id='documentation_body_pagelet'>"
                        "<h1>Graph API overview</h1><p>" + "Real prose. " * 30 + "</p>"
                        "</div></body></html>"
                    ),
                )
            }
        )
        crawl(fetcher=fetcher, output_root=tmp_path, seeds=(url,))

        written = (tmp_path / "docs/graph-api/overview.md").read_text()
        assert written.startswith("# Graph API overview")
        entry = next(iter(read_journal(tmp_path / "manifest.jsonl")))
        assert entry.conversion == "html_to_markdown"

    def test_native_markdown_is_labelled_as_such(self, tmp_path: Path) -> None:
        fetcher = FixtureFetcher(responses={IG: md_result(IG, "# Root")})
        crawl(fetcher=fetcher, output_root=tmp_path, seeds=(IG,))
        entry = next(iter(read_journal(tmp_path / "manifest.jsonl")))
        assert entry.conversion == "native_markdown"
        assert entry.source_sha256 and entry.source_sha256.startswith("sha256:")

    def test_respects_max_depth(self, tmp_path: Path) -> None:
        fetcher = FixtureFetcher(
            responses={
                IG: md_result(IG, f"[a]({IG}/a)"),
                f"{IG}/a": md_result(f"{IG}/a", f"[b]({IG}/a/b)"),
                f"{IG}/a/b": md_result(f"{IG}/a/b", "leaf"),
            }
        )
        stats = crawl(fetcher=fetcher, output_root=tmp_path, seeds=(IG,), max_depth=1)
        assert stats.harvested == 2
        assert not (tmp_path / "documentation/instagram-platform/a/b.md").exists()

    def test_respects_max_pages(self, tmp_path: Path) -> None:
        responses = {IG: md_result(IG, " ".join(f"[{i}]({IG}/p{i})" for i in range(10)))}
        for i in range(10):
            responses[f"{IG}/p{i}"] = md_result(f"{IG}/p{i}", f"page {i}")
        stats = crawl(
            fetcher=FixtureFetcher(responses=responses),
            output_root=tmp_path,
            seeds=(IG,),
            max_pages=4,
        )
        assert stats.harvested == 4

    def test_fetch_failures_are_recorded_and_do_not_abort(self, tmp_path: Path) -> None:
        bad = f"{IG}/broken"
        fetcher = FixtureFetcher(
            responses={
                IG: md_result(IG, f"[ok]({IG}/ok) [bad]({bad})"),
                f"{IG}/ok": md_result(f"{IG}/ok", "fine"),
                bad: FetchResult(
                    requested_url=bad,
                    final_url=bad,
                    status_code=0,
                    content_type="",
                    body="",
                    error="ConnectTimeout: timed out after 3 attempts",
                ),
            }
        )
        stats = crawl(fetcher=fetcher, output_root=tmp_path, seeds=(IG,))

        assert stats.harvested == 2  # the crawl continued past the failure
        assert stats.fetch_error == 1
        assert any("broken" in f for f in stats.failures)


class TestResume:
    def test_resumed_run_does_not_refetch(self, tmp_path: Path) -> None:
        """The core crash-recovery property. Scraping costs money and time, so a
        resumed harvest must re-fetch nothing it already decided."""
        responses = {
            IG: md_result(IG, f"[a]({IG}/a) [b]({IG}/b)"),
            f"{IG}/a": md_result(f"{IG}/a", "page a"),
            f"{IG}/b": md_result(f"{IG}/b", "page b"),
        }

        first = FixtureFetcher(responses=responses)
        crawl(fetcher=first, output_root=tmp_path, seeds=(IG,), max_pages=2)
        assert len(first.requested) == 2

        second = FixtureFetcher(responses=responses)
        stats = crawl(fetcher=second, output_root=tmp_path, seeds=(IG,))

        assert stats.resumed_from > 0
        # Only the page the first run never reached.
        assert second.requested == [f"{IG}/b"]
        assert (tmp_path / "documentation/instagram-platform/a.md").exists()
        assert (tmp_path / "documentation/instagram-platform/b.md").exists()

    def test_resume_survives_a_torn_journal(self, tmp_path: Path) -> None:
        responses = {
            IG: md_result(IG, f"[a]({IG}/a)"),
            f"{IG}/a": md_result(f"{IG}/a", "page a"),
        }
        crawl(fetcher=FixtureFetcher(responses=responses), output_root=tmp_path, seeds=(IG,))

        journal = tmp_path / "manifest.jsonl"
        with journal.open("a", encoding="utf-8") as handle:
            handle.write('{"requested_url": "https://developers.fac')

        second = FixtureFetcher(responses=responses)
        crawl(fetcher=second, output_root=tmp_path, seeds=(IG,))
        assert second.requested == []

    def test_aggregate_manifest_is_rewritten_each_run(self, tmp_path: Path) -> None:
        responses = {
            IG: md_result(IG, f"[a]({IG}/a)"),
            f"{IG}/a": md_result(f"{IG}/a", "page a"),
        }
        crawl(
            fetcher=FixtureFetcher(responses=responses),
            output_root=tmp_path,
            seeds=(IG,),
            max_pages=1,
        )
        after_first = json.loads((tmp_path / "manifest.json").read_text())
        assert after_first["total_entries"] == 1

        crawl(fetcher=FixtureFetcher(responses=responses), output_root=tmp_path, seeds=(IG,))
        after_second = json.loads((tmp_path / "manifest.json").read_text())
        assert after_second["total_entries"] == 2
        assert after_second["by_outcome"]["harvested"] == 2


class TestOutputPathIsAParameter:
    def test_two_independent_roots(self, tmp_path: Path) -> None:
        """`reference/` must never be baked in: nothing under `packages/` may
        depend on the corpus landing in one particular place."""
        responses = {IG: md_result(IG, "# Root")}
        one, two = tmp_path / "one", tmp_path / "two"
        crawl(fetcher=FixtureFetcher(responses=responses), output_root=one, seeds=(IG,))
        crawl(fetcher=FixtureFetcher(responses=responses), output_root=two, seeds=(IG,))
        assert (one / "documentation/instagram-platform.md").exists()
        assert (two / "documentation/instagram-platform.md").exists()
