"""The harvest journal: an append-only JSONL record, flushed once per page.

Shape is chosen for crash safety. This project's outcome ledger records repeated
agent and session deaths mid-task, so mid-harvest death is engineered for rather
than treated as an anomaly: one line is written and fsynced as each page
completes, so a crash loses at most the page in flight, and the journal *is* the
resume frontier -- no separate state file to fall out of sync.

`manifest.json` (the aggregate task P2 asks for) is regenerated from the journal
rather than maintained alongside it, so the two cannot disagree.

Provenance is per CLAUDE.md's hard rule, applied to a harvested corpus: every row
carries where it came from, when, what Meta served, **which code path produced the
markdown** (native vs converted), and the `harvester_version` that produced it.
Meta's docs move -- that is the whole reason to harvest them -- so when a page
changes we need to know which converter wrote the copy we have.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Literal

from pydantic import BaseModel

HARVESTER_VERSION = "0.1.0"

Outcome = Literal[
    "harvested",
    "skipped_out_of_scope",
    "soft_404",
    "http_error",
    "fetch_error",
    "duplicate",
]
Conversion = Literal["native_markdown", "html_to_markdown"]


def sha256_hex(data: str) -> str:
    return "sha256:" + hashlib.sha256(data.encode("utf-8")).hexdigest()


class ManifestEntry(BaseModel):
    """One decision about one URL. Every URL the crawl considers gets a row --
    including ones it declined to fetch -- so the harvest boundary is auditable
    and nothing is silently dropped."""

    requested_url: str
    final_url: str
    outcome: Outcome
    depth: int
    fetched_at: datetime
    harvester_version: str = HARVESTER_VERSION

    status_code: int | None = None
    content_type: str | None = None
    local_path: str | None = None
    conversion: Conversion | None = None
    source_sha256: str | None = None
    content_sha256: str | None = None
    reason: str | None = None

    @property
    def redirected(self) -> bool:
        return self.requested_url != self.final_url


class ManifestJournal:
    """Append-only writer over `manifest.jsonl`, flushed and fsynced per entry."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle: IO[str] | None = None

    def __enter__(self) -> ManifestJournal:
        self._handle = self.path.open("a", encoding="utf-8")
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def append(self, entry: ManifestEntry) -> None:
        if self._handle is None:
            raise RuntimeError("journal is not open")
        self._handle.write(entry.model_dump_json() + "\n")
        # flush + fsync per page: the point of the journal is that a hard kill
        # between two pages costs one page, not the run.
        self._handle.flush()
        os.fsync(self._handle.fileno())

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None


def read_journal(path: Path) -> Iterator[ManifestEntry]:
    """Replay the journal, tolerating a torn final line from a hard kill."""
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                # Only ever the last line, and only after an ungraceful exit.
                continue
            yield ManifestEntry.model_validate(payload)


def visited_urls(path: Path) -> set[str]:
    """Every URL already decided, in either spelling -- the resume frontier.

    Includes `requested_url` as well as `final_url` so that after a resume we do
    not re-fetch a `/docs/` alias whose `/documentation/` target we already have.
    """
    seen: set[str] = set()
    for entry in read_journal(path):
        seen.add(entry.requested_url)
        seen.add(entry.final_url)
    return seen


def write_aggregate(journal_path: Path, out_path: Path) -> dict[str, object]:
    """Regenerate `manifest.json` from the journal. Returns the summary block."""
    entries = list(read_journal(journal_path))
    by_outcome: dict[str, int] = {}
    for entry in entries:
        by_outcome[entry.outcome] = by_outcome.get(entry.outcome, 0) + 1

    aggregate = {
        "harvester_version": HARVESTER_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "total_entries": len(entries),
        "by_outcome": by_outcome,
        "pages": [entry.model_dump(mode="json") for entry in entries],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(aggregate, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"total_entries": len(entries), "by_outcome": by_outcome}


def new_entry(
    *,
    requested_url: str,
    final_url: str,
    outcome: Outcome,
    depth: int,
    **rest: object,
) -> ManifestEntry:
    """Construct an entry stamped with the current time and harvester version."""
    return ManifestEntry(
        requested_url=requested_url,
        final_url=final_url,
        outcome=outcome,
        depth=depth,
        fetched_at=datetime.now(UTC),
        **rest,  # type: ignore[arg-type]
    )
