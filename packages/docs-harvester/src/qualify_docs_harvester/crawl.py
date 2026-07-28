"""Resumable, scope-bounded BFS over Meta's developer docs.

Ordering is breadth-first from the seeds so the highest-value pages land first
and a truncated run still yields a useful corpus.

Two invariants worth stating, because both were defects waiting to happen:

1. **Everything keys on the final effective URL.** `/docs/X` and `/documentation/X`
   are frequently the same page reached two ways (Meta 301s the former to the
   latter). Keying on the requested URL writes the same content to two files;
   keying on a rewritten prefix breaks half the scope outright (see `urls.py`).
   The alias table maps requested -> effective so a second spelling costs nothing
   after the first fetch.
2. **Every considered URL gets a manifest row**, including ones we decline. An
   out-of-scope link is recorded with a reason rather than dropped, so the harvest
   boundary can be audited instead of taken on trust.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from qualify_docs_harvester.fetch import Fetcher, FetchResult
from qualify_docs_harvester.htmlmd import html_to_markdown
from qualify_docs_harvester.manifest import (
    ManifestJournal,
    new_entry,
    read_journal,
    sha256_hex,
    write_aggregate,
)
from qualify_docs_harvester.soft404 import is_soft_404
from qualify_docs_harvester.urls import canonicalize, extract_links, is_in_scope, url_to_local_path

# Priority order set by the lead: a teammate is blocked on each tier. The
# permissions reference gates the A5 ruling, so it is fetched first.
DEFAULT_SEEDS: tuple[str, ...] = (
    "https://developers.facebook.com/docs/permissions",
    "https://developers.facebook.com/docs/graph-api/overview/access-levels",
    "https://developers.facebook.com/docs/instagram-platform",
    "https://developers.facebook.com/docs/instagram-platform/overview",
    "https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login",
    "https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login",
    "https://developers.facebook.com/docs/facebook-login/guides/access-tokens",
    "https://developers.facebook.com/docs/app-review",
    "https://developers.facebook.com/docs/development/release/business-verification",
    "https://developers.facebook.com/docs/instagram-platform/content-publishing",
    "https://developers.facebook.com/docs/business-messaging/instagram-messaging",
    "https://developers.facebook.com/docs/graph-api/overview",
)


@dataclass
class CrawlStats:
    harvested: int = 0
    skipped_out_of_scope: int = 0
    soft_404: int = 0
    http_error: int = 0
    fetch_error: int = 0
    duplicate: int = 0
    resumed_from: int = 0
    failures: list[str] = field(default_factory=list)

    def record(self, outcome: str) -> None:
        setattr(self, outcome, getattr(self, outcome) + 1)


def _markdown_for(result: FetchResult) -> tuple[str, str]:
    """Return `(markdown, conversion)` for a successful fetch."""
    if result.is_markdown:
        return result.body, "native_markdown"
    return html_to_markdown(result.body), "html_to_markdown"


def crawl(
    *,
    fetcher: Fetcher,
    output_root: Path,
    seeds: tuple[str, ...] = DEFAULT_SEEDS,
    max_depth: int = 6,
    max_pages: int = 1200,
    journal_path: Path | None = None,
) -> CrawlStats:
    """Harvest the docs corpus into `output_root`, resuming from its journal.

    `output_root` is a parameter, never a module constant: nothing under
    `packages/` may depend on `reference/` being the destination, and the tests
    write to tmp dirs.
    """
    output_root = Path(output_root)
    journal = journal_path or output_root / "manifest.jsonl"
    aggregate_path = output_root / "manifest.json"

    # Resume: replay the journal. Both spellings of an already-decided URL count
    # as visited, so a redirect alias is not re-fetched after a crash.
    visited: set[str] = set()
    alias: dict[str, str] = {}
    harvested: list[tuple[str, str, int]] = []
    for entry in read_journal(journal):
        visited.add(entry.requested_url)
        visited.add(entry.final_url)
        alias[entry.requested_url] = entry.final_url
        if entry.outcome == "harvested" and entry.local_path is not None:
            harvested.append((entry.final_url, entry.local_path, entry.depth))

    stats = CrawlStats(resumed_from=len(visited))
    queue: deque[tuple[str, int]] = deque()
    queued: set[str] = set()

    def enqueue(url: str, depth: int) -> None:
        if url not in visited and url not in queued:
            queue.append((url, depth))
            queued.add(url)

    for seed in seeds:
        canonical = canonicalize(seed)
        if canonical is not None:
            enqueue(canonical, 0)

    # Rebuild the pending frontier from the corpus already on disk. A run cut
    # short by `max_pages` or by a crash leaves URLs discovered but never
    # fetched, and those appear in no journal row -- without this, a resumed
    # harvest walks only the seeds, finds every one already visited, and stops
    # early while silently reporting success. Re-reading the harvested files
    # costs no network and keeps the corpus self-describing, for the same reason
    # `manifest.json` is regenerated from the journal rather than maintained
    # beside it: one source of truth cannot disagree with itself.
    for final_url, local_path, depth in harvested:
        if depth >= max_depth:
            continue
        page = output_root / local_path
        if not page.exists():
            continue
        for link in extract_links(page.read_text(encoding="utf-8"), base=final_url):
            if is_in_scope(link):
                enqueue(link, depth + 1)

    pages_fetched = 0

    with ManifestJournal(journal) as jrnl:
        while queue and pages_fetched < max_pages:
            url, depth = queue.popleft()
            queued.discard(url)
            if url in visited:
                continue

            if not is_in_scope(url):
                visited.add(url)
                stats.record("skipped_out_of_scope")
                jrnl.append(
                    new_entry(
                        requested_url=url,
                        final_url=url,
                        outcome="skipped_out_of_scope",
                        depth=depth,
                        reason="outside the approved harvest allowlist",
                    )
                )
                continue

            result = fetcher.fetch(url)
            pages_fetched += 1
            visited.add(url)

            final = canonicalize(result.final_url) or url
            alias[url] = final

            if not result.ok:
                outcome = "fetch_error" if result.error else "http_error"
                stats.record(outcome)
                stats.failures.append(f"{url} -> {result.error or result.status_code}")
                jrnl.append(
                    new_entry(
                        requested_url=url,
                        final_url=final,
                        outcome=outcome,  # type: ignore[arg-type]
                        depth=depth,
                        status_code=result.status_code or None,
                        content_type=result.content_type or None,
                        reason=result.error or f"HTTP {result.status_code}",
                    )
                )
                continue

            # A redirect may land on a page already harvested under its canonical
            # spelling. Record the alias, do not write the file twice.
            if final != url and final in visited:
                stats.record("duplicate")
                jrnl.append(
                    new_entry(
                        requested_url=url,
                        final_url=final,
                        outcome="duplicate",
                        depth=depth,
                        status_code=result.status_code,
                        content_type=result.content_type,
                        reason="redirected onto an already-harvested page",
                    )
                )
                continue
            visited.add(final)

            if is_soft_404(result.body):
                stats.record("soft_404")
                stats.failures.append(f"{url} -> soft-404 (HTTP {result.status_code})")
                jrnl.append(
                    new_entry(
                        requested_url=url,
                        final_url=final,
                        outcome="soft_404",
                        depth=depth,
                        status_code=result.status_code,
                        content_type=result.content_type,
                        reason="HTTP 200 with a not-found body",
                    )
                )
                continue

            markdown, conversion = _markdown_for(result)
            local_path = url_to_local_path(final, output_root)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_text(markdown, encoding="utf-8")

            stats.record("harvested")
            jrnl.append(
                new_entry(
                    requested_url=url,
                    final_url=final,
                    outcome="harvested",
                    depth=depth,
                    status_code=result.status_code,
                    content_type=result.content_type,
                    local_path=str(local_path.relative_to(output_root)),
                    conversion=conversion,
                    source_sha256=sha256_hex(result.body),
                    content_sha256=sha256_hex(markdown),
                )
            )

            if depth >= max_depth:
                continue
            for link in extract_links(result.body, base=final):
                if link in visited or link in queued:
                    continue
                if not is_in_scope(link):
                    # Recorded once, at discovery, so the boundary is auditable
                    # without re-deciding it on every inbound reference.
                    visited.add(link)
                    stats.record("skipped_out_of_scope")
                    jrnl.append(
                        new_entry(
                            requested_url=link,
                            final_url=link,
                            outcome="skipped_out_of_scope",
                            depth=depth + 1,
                            reason=f"outside the approved allowlist; linked from {final}",
                        )
                    )
                    continue
                enqueue(link, depth + 1)

    write_aggregate(journal, aggregate_path)
    return stats
