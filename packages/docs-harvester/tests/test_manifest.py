"""Journal round-trip, crash tolerance, and the aggregate manifest."""

from __future__ import annotations

import json
from pathlib import Path

from qualify_docs_harvester.manifest import (
    HARVESTER_VERSION,
    ManifestJournal,
    new_entry,
    read_journal,
    sha256_hex,
    visited_urls,
    write_aggregate,
)

URL = "https://developers.facebook.com/documentation/instagram-platform/overview"


def _harvested(url: str = URL, depth: int = 1) -> object:
    return new_entry(
        requested_url=url.replace("/documentation/", "/docs/"),
        final_url=url,
        outcome="harvested",
        depth=depth,
        status_code=200,
        content_type="text/markdown; charset=utf-8",
        local_path="documentation/instagram-platform/overview.md",
        conversion="native_markdown",
        source_sha256=sha256_hex("raw"),
        content_sha256=sha256_hex("raw"),
    )


class TestJournal:
    def test_round_trip(self, tmp_path: Path) -> None:
        journal = tmp_path / "manifest.jsonl"
        with ManifestJournal(journal) as jrnl:
            jrnl.append(_harvested())  # type: ignore[arg-type]

        entries = list(read_journal(journal))
        assert len(entries) == 1
        entry = entries[0]
        assert entry.final_url == URL
        assert entry.outcome == "harvested"
        assert entry.conversion == "native_markdown"
        assert entry.harvester_version == HARVESTER_VERSION
        assert entry.redirected  # requested /docs/, landed on /documentation/

    def test_appends_across_sessions(self, tmp_path: Path) -> None:
        """Two separate opens, as a resumed run does."""
        journal = tmp_path / "manifest.jsonl"
        with ManifestJournal(journal) as jrnl:
            jrnl.append(_harvested(URL))  # type: ignore[arg-type]
        with ManifestJournal(journal) as jrnl:
            jrnl.append(_harvested(URL + "/insights"))  # type: ignore[arg-type]
        assert len(list(read_journal(journal))) == 2

    def test_tolerates_torn_final_line(self, tmp_path: Path) -> None:
        """A hard kill mid-write leaves a partial line. It must cost that one
        page, not the whole journal."""
        journal = tmp_path / "manifest.jsonl"
        with ManifestJournal(journal) as jrnl:
            jrnl.append(_harvested())  # type: ignore[arg-type]
        with journal.open("a", encoding="utf-8") as handle:
            handle.write('{"requested_url": "https://developers.faceb')

        entries = list(read_journal(journal))
        assert len(entries) == 1
        assert entries[0].final_url == URL

    def test_missing_journal_reads_empty(self, tmp_path: Path) -> None:
        assert list(read_journal(tmp_path / "absent.jsonl")) == []


class TestVisitedUrls:
    def test_includes_both_spellings(self, tmp_path: Path) -> None:
        """After a resume, a `/docs/` alias whose `/documentation/` target is
        already harvested must not be re-fetched -- scraping costs Meta bandwidth
        and us wall-clock time."""
        journal = tmp_path / "manifest.jsonl"
        with ManifestJournal(journal) as jrnl:
            jrnl.append(_harvested())  # type: ignore[arg-type]
        seen = visited_urls(journal)
        assert URL in seen
        assert URL.replace("/documentation/", "/docs/") in seen


class TestAggregate:
    def test_regenerated_from_journal(self, tmp_path: Path) -> None:
        journal = tmp_path / "manifest.jsonl"
        with ManifestJournal(journal) as jrnl:
            jrnl.append(_harvested(URL))  # type: ignore[arg-type]
            jrnl.append(  # type: ignore[arg-type]
                new_entry(
                    requested_url="https://developers.facebook.com/docs/marketing-api",
                    final_url="https://developers.facebook.com/docs/marketing-api",
                    outcome="skipped_out_of_scope",
                    depth=2,
                    reason="outside the approved allowlist",
                )
            )

        summary = write_aggregate(journal, tmp_path / "manifest.json")
        assert summary["total_entries"] == 2
        assert summary["by_outcome"] == {"harvested": 1, "skipped_out_of_scope": 1}

        payload = json.loads((tmp_path / "manifest.json").read_text())
        assert payload["harvester_version"] == HARVESTER_VERSION
        assert len(payload["pages"]) == 2
        # Declined URLs carry their reason: the harvest boundary is auditable.
        skipped = [p for p in payload["pages"] if p["outcome"] == "skipped_out_of_scope"][0]
        assert "allowlist" in skipped["reason"]
