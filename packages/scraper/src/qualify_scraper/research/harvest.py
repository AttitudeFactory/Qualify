"""Download a research corpus of short videos with their engagement metrics.

Built for the hook-pattern spike: the extractor in `qualify_models.hooks` needs the
mp4 on disk, and `hooks.analysis.PostObservation` needs `source_id`, `account_id`,
`posted_at` and an engagement outcome. This module produces exactly that and stops.

**Why this is not the production scraper.** Measured 2026-08-06: TikTok's `playAddr`
(what `parsers/tiktok.py` puts in `MediaItem.url`) returns HTTP 403 to a plain GET and
to a GET carrying a real browser `User-Agent` + `Referer`. The CDN sits behind a JS
anti-bot challenge whose solution becomes a cookie. Solving it is a moving target
maintained upstream by `yt-dlp`, not something to reimplement here — so the corpus
runner shells out to `yt-dlp` and the production path keeps its own concerns.

Output layout, all plain files (no R2, no envelope, no `brand_id` — that machinery is
the production path and would drag Parte 3 scope into a research script)::

    <out_dir>/
        metrics.csv                     one row per successfully harvested post
        accounts.csv                    one row per account (carries follower_count)
        failures.csv                    one row per failed attempt, with the reason
        <handle>/<post_id>.mp4          the bytes the extractor needs
        <handle>/<post_id>.info.json    the raw fetcher payload, kept so the corpus can
                                        be re-derived without re-fetching

Re-running is safe and resumes: a post whose mp4 exists and whose row is already in
`metrics.csv` is skipped without a network call. That is mandatory rather than tidy —
per-video fetches were measured at roughly a 60-70% success rate, and the failures are
transient, so a full run is expected to be partial and to be repeated.

Running it
----------
`yt-dlp` is invoked as a **binary via subprocess**, never imported. So it does not need
to be in the workspace venv, and running a corpus needs **no sync at all**::

    uv run --no-sync python -c "from qualify_scraper.research import ..."

**Do not run `uv sync --group corpus` in this repo.** CLAUDE.md records a measured trap:
alternating `uv sync` between dependency groups corrupts the shared workspace `.venv`
editable installs — observed twice in one day with a single agent running, recoverable
only by `rm -rf .venv && uv sync --group ml`. Adding a third group to that rotation is
the same hazard and would break the venv for every other agent in the repo. The
`corpus` group in `pyproject.toml` declares intent and pins a version floor; it is not
an install step. If the binary is missing, install it isolated from the workspace with
`uv tool install yt-dlp`.

Reading this corpus, and the one thing that must not be misread
---------------------------------------------------------------
**A null result from the pilot may mean "we could not see it", not "it is not there".**
Two independent reasons, both measured rather than hypothetical:

1. **Three accounts, zero margin.** The analysis requires a hook type to appear in >=3
   accounts before it counts as a pattern rather than one advertiser's house style. This
   niche yields exactly three usable TikTok accounts, so a type must appear in *all
   three*; one account not using it erases it from the study outright.
2. **Achieved span can be far narrower than requested.** Measured: a run asking for 365
   days came back covering 98, because the picks at both ends failed and only interior
   backups survived. `HarvestReport.span_coverage` reports this. Low coverage is
   **asymmetric** — a *positive* finding survives it (variety observed is variety that
   exists), a *negative* one does not, because a hook type used only in the unsampled
   months is simply absent and reads as "this account does not vary".

Since the pilot exists to falsify "this niche never varies", an uninterpretable negative
is its worst possible outcome: it looks decisive and is not. Check `span_coverage` and
the account count before reading any null as a verdict.

A note for the next person adding a guard — or a CSV writer — here
------------------------------------------------------------------
`accounts.csv` originally appended blindly, so every resumed run added a duplicate row
for the same account — enough to fan out any consumer joining on `account_id`. **The
suite was 13/13 green the whole time it was broken; only running it against real
accounts revealed it.** A fixture-backed suite that never re-runs against a populated
directory cannot see an append bug, because the bug lives in the *second* run over
state the first one left behind. If you add a writer, add the re-run test with it —
`test_rerunning_does_not_duplicate_account_rows` is the shape to copy.

That was one instance of a pattern worth naming, because **four of them landed in a
single day (2026-08-06) across this package and `packages/models`, every one under a
green suite**:

* `int(view_count or 0)` here — a metric-missing guard that made the blank it was
  protecting against impossible to emit in the first place.
* recency sampling here — a corpus sampler aimed at measuring within-account variety,
  positioned so it could only ever see one ~3-month window.
* a `separation > 0.5` threshold in `packages/models` — where 0.5 is the *maximum* a
  balanced two-type account can produce, so it could never fire for the case it was
  built to catch.
* a Spearman residual check in `packages/models` — which reads ~0 against a symmetric U
  and so would have passed exactly the non-monotone drift it was meant to detect.

**The shared shape: a guard aimed at the right hazard, positioned where it can never
fire.** Tests that merely pass with the guard present cannot detect this — all four did.
**The countermeasure is to write a test that makes the guard actually fire**, with the
input that should trip it, and assert it tripped. If you cannot construct that input,
that is the finding.
"""

from __future__ import annotations

import csv
import json
import logging
import subprocess
import time
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

METRICS_FILENAME = "metrics.csv"
ACCOUNTS_FILENAME = "accounts.csv"
FAILURES_FILENAME = "failures.csv"

METRICS_COLUMNS = (
    "source_id",
    "account_id",
    "posted_at",
    "likes",
    "comments",
    "views",
    "duration_seconds",
    "fetched_at",
    "video_path",
)
ACCOUNTS_COLUMNS = ("account_id", "handle", "follower_count", "video_count", "fetched_at")
FAILURES_COLUMNS = ("source_id", "account_id", "stage", "reason", "attempted_at")


class HarvestError(RuntimeError):
    """A single post could not be harvested. Carries the stage so a failure row can
    distinguish "the account would not enumerate" from "this one video would not fetch"
    — the first invalidates a handle, the second is expected background noise."""

    def __init__(self, stage: str, reason: str) -> None:
        super().__init__(f"{stage}: {reason}")
        self.stage = stage
        self.reason = reason


class PostRef(BaseModel):
    """A post identified but not yet fetched. What enumeration returns.

    `posted_at` is best-effort and may be `None`: it is filled only when the platform's
    id encodes a timestamp (TikTok's does), which lets the runner apply an age window
    at *selection* time — before spending a request per post. A fetcher that cannot
    supply it leaves it `None` and age filtering degrades to a no-op rather than to a
    wrong answer."""

    account_id: str
    post_id: str
    post_url: str
    posted_at: datetime | None = None


class HarvestedPost(BaseModel):
    """One post on disk, with the metrics captured in the same pass as its bytes.

    Metrics and bytes are captured together deliberately: `views`/`likes` drift
    continuously, so a download-now/metrics-later design would silently pair a hook
    with an outcome measured at a different time."""

    source_id: str
    account_id: str
    posted_at: datetime
    # `None` means the platform did not report the metric, and is written to CSV as an
    # empty cell — never as 0. A consumer must be able to tell "no views reported" from
    # "zero views", because the first is a missing measurement and the second is data.
    likes: int | None = None
    comments: int | None = None
    views: int | None = None
    duration_seconds: float | None = None
    fetched_at: datetime
    video_path: Path
    caption: str = ""

    def metrics_row(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "account_id": self.account_id,
            "posted_at": self.posted_at.isoformat(),
            "likes": "" if self.likes is None else str(self.likes),
            "comments": "" if self.comments is None else str(self.comments),
            "views": "" if self.views is None else str(self.views),
            "duration_seconds": (
                "" if self.duration_seconds is None else str(self.duration_seconds)
            ),
            "fetched_at": self.fetched_at.isoformat(),
            "video_path": str(self.video_path),
        }


class AccountProfile(BaseModel):
    """Account-level facts. `follower_count` lives here rather than on every post row
    because it is one value per account, not per post — and because it is absent from
    the per-video payload entirely (measured: `channel_follower_count` came back None),
    so it costs its own request."""

    account_id: str
    handle: str
    follower_count: int | None = None
    video_count: int | None = None
    fetched_at: datetime

    def accounts_row(self) -> dict[str, str]:
        return {
            "account_id": self.account_id,
            "handle": self.handle,
            "follower_count": "" if self.follower_count is None else str(self.follower_count),
            "video_count": "" if self.video_count is None else str(self.video_count),
            "fetched_at": self.fetched_at.isoformat(),
        }


class FetchFailure(BaseModel):
    """A recorded miss. Written as it happens so a partial run is legible: a corpus
    that quietly ends with 43 of 50 files, with no record of which 7 failed or why,
    is the failure mode this runner exists to prevent."""

    source_id: str
    account_id: str
    stage: str
    reason: str
    attempted_at: datetime

    def failures_row(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "account_id": self.account_id,
            "stage": self.stage,
            "reason": self.reason,
            "attempted_at": self.attempted_at.isoformat(),
        }


class HarvestReport(BaseModel):
    """What one run actually achieved, per account. Reported rather than logged so a
    caller can assert on it."""

    requested_per_account: int
    harvested: int
    skipped_existing: int
    failed: int
    accounts: list[AccountProfile] = Field(default_factory=list)
    failures: list[FetchFailure] = Field(default_factory=list)
    # The span actually achieved, which is NOT the span requested. Measured: a run
    # asking for a 365-day spread returned posts covering 2026-01-13 to 2026-04-21 —
    # 98 days — because the picks at both ends of the window failed and only interior
    # backups survived. Anything reasoning about time-confounding must read the span the
    # corpus *has*, not the one the run asked for.
    earliest_posted_at: datetime | None = None
    latest_posted_at: datetime | None = None
    # The span the run was *asking* for, which the analysis needs in order to tell a
    # 98-day corpus that was designed as 98 days from one that was designed as 365.
    # When `max_age_days` is set this is that value. When the run is unbounded there is
    # still a requested span — the age range of the candidates actually available to
    # sample — and without it a coverage check would be undefined for exactly the
    # unbounded pilot it matters most for.
    requested_span_days: float | None = None

    @property
    def attempted(self) -> int:
        return self.harvested + self.failed

    @property
    def success_rate(self) -> float | None:
        """Share of *network attempts* that yielded a video. `None` when nothing was
        attempted (a fully resumed run), which is not the same as a 0% rate."""
        if self.attempted == 0:
            return None
        return self.harvested / self.attempted

    @property
    def achieved_span_days(self) -> float | None:
        """Days between the oldest and newest harvested post, or `None` if fewer than
        two carried a date. Compare against the requested `max_age_days`: a large gap
        means the corpus is temporally narrower than designed."""
        if self.earliest_posted_at is None or self.latest_posted_at is None:
            return None
        return (self.latest_posted_at - self.earliest_posted_at).total_seconds() / 86400

    @property
    def span_coverage(self) -> float | None:
        """Achieved span as a fraction of requested span, or `None` if either is unknown.

        Low coverage is **asymmetric in what it invalidates**: a positive finding still
        holds (variety observed is variety that exists), but a negative one does not — a
        hook type used only in the unsampled months is simply absent and reads as "this
        account does not vary". Since the pilot exists to falsify the pessimistic
        hypothesis, an uninterpretable negative is its worst outcome."""
        achieved = self.achieved_span_days
        if achieved is None or not self.requested_span_days:
            return None
        return min(achieved / self.requested_span_days, 1.0)


SampleStrategy = Literal["spread", "recent"]


def _tiktok_posted_at(post_id: str) -> datetime | None:
    """Decode a TikTok post id into its creation time.

    TikTok ids are snowflake-style: the high 32 bits are a unix timestamp in seconds.
    That makes the age of every post in a catalogue knowable **from enumeration alone**,
    with no per-post request — which is what lets `max_age_days` filter before spending
    a fetch rather than after.

    **Approximate, and deliberately used only for the age window.** Measured against a
    real post: the id decodes to 21:24:31 while the payload's own `timestamp` says
    21:24:23 — an 8 s difference, presumably id-minting time vs publish time. Irrelevant
    against a 365-day bound; not acceptable as an analysis timestamp. `PostRef.posted_at`
    is therefore only ever a filter input, and `HarvestedPost.posted_at` — the value that
    reaches `metrics.csv` — is always the exact `timestamp` from the fetched payload.

    Returns `None` for anything that does not decode to a plausible date, so a format
    change degrades to "age unknown" rather than to a confident wrong answer."""
    try:
        seconds = int(post_id) >> 32
    except ValueError:
        return None
    # TikTok launched in 2016; anything outside a sane band is a decode failure.
    if not 1_400_000_000 < seconds < 4_000_000_000:
        return None
    return datetime.fromtimestamp(seconds, UTC)


def _within_age(refs: Sequence[PostRef], max_age_days: int | None) -> list[PostRef]:
    """Drop posts older than the window. Posts of unknown age are **kept**.

    Keeping unknowns is the conservative choice: dropping them would silently shrink a
    corpus on any platform whose ids do not encode a timestamp, which looks identical to
    "this account has few recent posts"."""
    if max_age_days is None:
        return list(refs)
    cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
    return [ref for ref in refs if ref.posted_at is None or ref.posted_at >= cutoff]


def _evenly_spaced(population: int, count: int) -> list[int]:
    """`count` indices spread across `range(population)`, endpoints included."""
    if count >= population:
        return list(range(population))
    if count == 1:
        return [0]
    step = (population - 1) / (count - 1)
    return sorted({round(i * step) for i in range(count)})


def _select(
    refs: Sequence[PostRef], target: int, candidates: int, strategy: SampleStrategy
) -> list[PostRef]:
    """Choose which enumerated posts to actually fetch.

    Enumeration returns newest-first, so taking the first `count` is a **recency
    sample**, and on a long-lived account that is a severe bias. Measured on
    `@inmobiliarialunaroman`: 365 posts spanning 2022-04-29 to 2026-07-26 (1,549 days),
    where the 34 most recent cover **67 days — 4.3% of the catalogue's time span**.

    That matters because the study's binding question is whether a single account's
    *openings vary*. One 67-day window is likely to catch a single campaign or template
    era, which biases the variety measurement in an unknown direction: it can report no
    variety where the account has changed style over time, or report variety that is
    really two adjacent campaigns. `spread` samples evenly across the whole catalogue
    instead, so an account's range has a chance to show up.

    `recent` remains available for "what is this account doing now", which is a
    different question and the right one for trend work.

    Ordering is load-bearing under `spread`. The runner over-enumerates (`candidates` >
    `target`) to absorb the ~30-40% fetch failure rate, and stops as soon as `target` is
    met. So the **first `target` entries must already span the whole catalogue**;
    spreading all `candidates` evenly instead would leave the run stopping halfway and
    covering only the newest half. The extras are therefore appended *after* the primary
    picks as backups, consumed only when a primary fetch fails.
    """
    if strategy == "recent":
        return list(refs[:candidates])
    if target >= len(refs):
        return list(refs)
    primary = _evenly_spaced(len(refs), target)
    remaining = [i for i in range(len(refs)) if i not in set(primary)]
    backups = [remaining[i] for i in _evenly_spaced(len(remaining), max(candidates - target, 0))]
    return [refs[i] for i in [*primary, *backups]]


class VideoFetcher(Protocol):
    """The network seam, mirroring `client.ScrapingClient`: the only place a live
    request happens, so the suite can inject a fixture-backed double and never touch
    the network. Keeps the vendor swappable — a Zyte or Data365 implementation drops in
    here without the runner changing.

    `limit=None` means "the whole catalogue", which `spread` sampling needs."""

    def enumerate_account(self, handle: str, limit: int | None) -> list[PostRef]: ...

    def fetch_account(self, handle: str) -> AccountProfile: ...

    def fetch_post(self, ref: PostRef, dest_dir: Path) -> HarvestedPost: ...


def _run_yt_dlp(args: Sequence[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed executable, no shell
        ["yt-dlp", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


class YtDlpFetcher:
    """Live fetcher backed by the `yt-dlp` CLI. Never exercised by the test suite.

    Shells out rather than importing the package: `yt-dlp`'s Python API is explicitly
    not a stable interface, while its CLI contract (`-J`, `--flat-playlist`,
    `--write-info-json`) is. Keeping it behind a subprocess boundary also means a
    crash in the tool is an exit code here, not a dead worker."""

    def __init__(
        self,
        platform_url_template: str = "https://www.tiktok.com/@{handle}",
        post_url_template: str = "https://www.tiktok.com/@{handle}/video/{post_id}",
        timeout: float = 180.0,
        sleep_between: float = 2.0,
    ) -> None:
        self._account_url = platform_url_template
        self._post_url = post_url_template
        self._timeout = timeout
        self._sleep_between = sleep_between
        # Cached limit is `None` when the whole catalogue was fetched, which satisfies
        # any subsequent ask.
        self._payload_cache: dict[str, tuple[int | None, dict[str, Any]]] = {}

    def _account_payload(self, handle: str, limit: int | None) -> dict[str, Any]:
        """One enumeration request per account, memoised and reused for any smaller ask.

        `fetch_account` and `enumerate_account` both need this payload and the runner
        calls them back to back. Without the cache that is two requests per account
        against a host that rate-limits — for data that cannot have changed in between."""
        cached = self._payload_cache.get(handle)
        if cached is not None and (cached[0] is None or (limit is not None and cached[0] >= limit)):
            return cached[1]
        limit_args = [] if limit is None else ["--playlist-end", str(limit)]
        result = _run_yt_dlp(
            [
                "--flat-playlist",
                "-J",
                *limit_args,
                "--no-warnings",
                self._account_url.format(handle=handle),
            ],
            timeout=self._timeout,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise HarvestError("enumerate", (result.stderr or "empty response").strip()[:300])
        payload: dict[str, Any] = json.loads(result.stdout)
        self._payload_cache[handle] = (limit, payload)
        return payload

    def enumerate_account(self, handle: str, limit: int | None) -> list[PostRef]:
        payload = self._account_payload(handle, limit)
        account_id = str(payload.get("id") or handle)
        refs: list[PostRef] = []
        for entry in payload.get("entries") or []:
            post_id = str(entry.get("id") or "")
            if not post_id:
                continue
            refs.append(
                PostRef(
                    account_id=account_id,
                    post_id=post_id,
                    post_url=self._post_url.format(handle=handle, post_id=post_id),
                    posted_at=_tiktok_posted_at(post_id),
                )
            )
        return refs

    def fetch_account(self, handle: str, limit: int = 1) -> AccountProfile:
        """Account-level facts, as far as this fetcher can supply them.

        **`follower_count` is always None on TikTok via yt-dlp, and that is not a bug
        here.** Verified 2026-08-06 against a live account: `channel_follower_count` is
        absent from the flat-playlist payload *and* from every per-video payload (no key
        matching `follow*` exists in either). `playlist_count` is likewise null. So the
        column exists in `accounts.csv` and must be filled by hand — roughly 30 s per
        account in a browser, three accounts for the pilot. It is deliberately left
        empty rather than defaulted to 0, which would be a fabricated measurement."""
        payload = self._account_payload(handle, limit)
        return AccountProfile(
            account_id=str(payload.get("id") or handle),
            handle=handle,
            follower_count=payload.get("channel_follower_count"),
            # `playlist_count` only, never `len(entries)`: entries is capped by the
            # caller's `--playlist-end`, so counting it would report our own request
            # size as if it were the account's catalogue size. An unmeasured number
            # stays None rather than becoming a plausible-looking wrong one.
            video_count=payload.get("playlist_count"),
            fetched_at=datetime.now(UTC),
        )

    def fetch_post(self, ref: PostRef, dest_dir: Path) -> HarvestedPost:
        """Download bytes and metadata in a single invocation.

        One call rather than a metadata call plus a download call: it halves the
        requests against a rate-limiting host, and it guarantees the metrics describe
        the same fetch that produced the file."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        output_template = str(dest_dir / f"{ref.post_id}.%(ext)s")
        result = _run_yt_dlp(
            [
                "--no-warnings",
                "--write-info-json",
                "--no-playlist",
                "-o",
                output_template,
                ref.post_url,
            ],
            timeout=self._timeout,
        )
        if self._sleep_between:
            time.sleep(self._sleep_between)
        info_path = dest_dir / f"{ref.post_id}.info.json"
        if result.returncode != 0 or not info_path.exists():
            raise HarvestError("fetch", (result.stderr or "no info json written").strip()[:300])
        return _post_from_info(ref, json.loads(info_path.read_text()), dest_dir)


def _optional_int(value: Any) -> int | None:
    """Absent stays absent; a real zero stays zero.

    Deliberately not `int(value or 0)`. That idiom collapses "the platform did not
    report this metric" into "this post got none", which is a fabricated measurement —
    and a damaging one now that `views` is the analysis's primary outcome *and* the
    denominator of `engagement_rate`: an imputed 0 would rank an unmeasured post as the
    worst in its library, and a 0 denominator is not a 0 rate."""
    if value is None:
        return None
    return int(value)


def _post_from_info(ref: PostRef, info: dict[str, Any], dest_dir: Path) -> HarvestedPost:
    """Map a fetcher payload onto the corpus row.

    `posted_at` comes from `timestamp` (epoch seconds, UTC) and never from
    `upload_date`, which is date-only and throws away time of day — the analysis
    detrends on posting time, so that resolution matters."""
    timestamp = info.get("timestamp")
    if timestamp is None:
        raise HarvestError("parse", "payload carried no timestamp; cannot derive posted_at")
    video_path = _locate_video(dest_dir, ref.post_id)
    if video_path is None:
        raise HarvestError("fetch", "metadata written but no video file on disk")
    return HarvestedPost(
        source_id=ref.post_id,
        account_id=ref.account_id,
        posted_at=datetime.fromtimestamp(int(timestamp), UTC),
        likes=_optional_int(info.get("like_count")),
        comments=_optional_int(info.get("comment_count")),
        views=_optional_int(info.get("view_count")),
        duration_seconds=(None if info.get("duration") is None else float(info["duration"])),
        fetched_at=datetime.now(UTC),
        video_path=video_path,
        caption=str(info.get("description") or ""),
    )


_VIDEO_SUFFIXES = (".mp4", ".webm", ".mkv", ".mov")


def _locate_video(dest_dir: Path, post_id: str) -> Path | None:
    for suffix in _VIDEO_SUFFIXES:
        candidate = dest_dir / f"{post_id}{suffix}"
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate
    return None


def _append_row(path: Path, columns: Sequence[str], row: dict[str, str]) -> None:
    """Append one row, writing the header if the file is new, and flush immediately.

    Row-at-a-time rather than a batch write at the end: a run that dies partway
    through must leave behind everything it had already achieved."""
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        if is_new:
            writer.writeheader()
        writer.writerow(row)
        handle.flush()


def _upsert_row(path: Path, columns: Sequence[str], row: dict[str, str], key: str) -> None:
    """Write one row, replacing any existing row with the same `key`.

    `accounts.csv` holds one row per account, not one per observation, so a re-run must
    refresh its row rather than append a second one — otherwise a resumed corpus grows a
    duplicate account row per run and any consumer joining on `account_id` fans out.
    Rewrites the whole file, which is safe here: it is one row per account."""
    existing: list[dict[str, str]] = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as handle:
            existing = [r for r in csv.DictReader(handle) if r.get(key) != row[key]]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        writer.writerows([*existing, row])
        handle.flush()


def _existing_source_ids(metrics_path: Path) -> set[str]:
    if not metrics_path.exists():
        return set()
    with metrics_path.open(newline="", encoding="utf-8") as handle:
        return {row["source_id"] for row in csv.DictReader(handle) if row.get("source_id")}


README_FILENAME = "README.md"


def _write_corpus_readme(out_dir: Path, report: HarvestReport) -> None:
    """Write the interpretation caveats *into the corpus directory*, with this run's own
    measured numbers substituted in.

    The caveats also live in this module's docstring and the package README, but those
    protect readers of the *code*. The person most likely to misread a null result is
    whoever opens this directory weeks from now, possibly outside this repo and without
    having read either. A caveat carrying the run's actual coverage figure is also much
    harder to wave through than a paragraph of generic prose."""
    accounts = len(report.accounts)
    coverage = report.span_coverage
    coverage_line = (
        "not measurable (too few dated posts)"
        if coverage is None
        else f"**{coverage:.0%}** of the span this run asked for"
    )
    span = report.achieved_span_days
    span_line = "unknown" if span is None else f"{span:.0f} days"
    margin = "ZERO — a hook type must appear in ALL of them" if accounts <= 3 else "some"

    out_dir.joinpath(README_FILENAME).write_text(
        f"""# Research corpus — read this before interpreting a null result

Generated by `qualify_scraper.research.harvest`. **A null result from this corpus may
mean "we could not see it", not "it is not there."**

This run: **{report.harvested} videos harvested**, {report.failed} failed,
{report.skipped_existing} already present, across **{accounts} account(s)**.
Temporal span actually covered: **{span_line}** — {coverage_line}.

1. **Account margin: {margin}.** A hook type must appear in at least 3 accounts before
   it counts as a pattern rather than one advertiser's house style. With {accounts}
   account(s) here, a single account not using a type erases that type from the study.
2. **Achieved span is not requested span.** Fetches fail (~30-50%), and failures at the
   ends of the range collapse coverage inward. This run covered {span_line}.
3. **Low coverage is asymmetric.** A **positive** finding survives it — variety observed
   is variety that exists. A **negative** finding does not: a hook type used only in the
   unsampled months is absent here and reads as "this account does not vary".

Because the study exists to falsify "this niche never varies", an uninterpretable
negative is the worst outcome available: it looks decisive and is not. Check the
coverage and account numbers above before treating any null as a verdict.

`failures.csv` lists every attempt that did not land, with its reason.
""",
        encoding="utf-8",
    )


def _record_requested_span(
    report: HarvestReport, candidates: Sequence[PostRef], max_age_days: int | None
) -> None:
    """Set the span this run is asking for, widening across accounts.

    Bounded runs requested exactly `max_age_days`. Unbounded runs requested whatever was
    on offer, so the honest figure is the age range of the candidate population — which
    is knowable for free, because enumeration already decoded every post's date."""
    if max_age_days is not None:
        requested = float(max_age_days)
    else:
        dated = [ref.posted_at for ref in candidates if ref.posted_at is not None]
        if len(dated) < 2:
            return
        requested = (max(dated) - min(dated)).total_seconds() / 86400
    if report.requested_span_days is None or requested > report.requested_span_days:
        report.requested_span_days = requested


def harvest_corpus(
    fetcher: VideoFetcher,
    handles: Iterable[str],
    out_dir: Path,
    *,
    target_per_account: int = 20,
    attempt_multiplier: float = 3.0,
    strategy: SampleStrategy = "spread",
    max_age_days: int | None = None,
) -> HarvestReport:
    """Harvest up to `target_per_account` videos from each handle into `out_dir`.

    `attempt_multiplier` defaults to 3.0. It picks `target * multiplier` candidates and
    stops each account once the target is met, so a healthy success rate simply means
    fewer requests rather than an overshoot. 3.0 rather than 2.0 because success is
    **not uniform across a catalogue**: measured on a real account, recency-sampled
    fetches ran 0.56-0.80 while a spread sample reaching back to 2022 ran **0.40** —
    old posts fail materially more often. At 2.0 a `spread` run exhausts its candidates
    and misses the target (measured: 4 harvested of 10 attempts against a target of 5).

    `strategy` defaults to `"spread"` — evenly across the account's catalogue rather
    than the most recent posts. On a long-lived account a head sample is too narrow to
    answer the question the corpus exists for (measured: the 34 newest of 365 posts
    cover 4.3% of a 4.2-year span), so it cannot falsify "this account never varies".
    Pass `"recent"` when the question is what an account is doing *now* instead.

    `max_age_days` defaults to `None` — **the whole catalogue** — and the reasoning is
    worth keeping, because a 12-month bound was proposed, implemented, and then reversed.

    The risk a bound addresses is real: sampling multiple years maximises observed
    variety *and* the chance that variety is unusable, because if an account favoured one
    opening in 2022 and another in 2026 then hook type is a **proxy for date**, and
    regressing out the time trend removes the hook effect with it. But the pilot's job is
    to *falsify* "this niche never varies", and full-catalogue spread is the most generous
    test of that — a negative from the most generous test is the most informative
    negative. A bound weakens exactly the test that most needs power: "no variety" inside
    a narrow window cannot distinguish *no repertoire* from *window too short*.

    The confound is handled by measuring it instead of pre-empting it: the analysis
    computes how far apart in time the hook types sit, so variety + low separation reads
    as repertoire and variety + high separation reads as drift — and that number then
    tells the corpus phase how tight its window must be, rather than it being guessed
    up front. So: **pilot unbounded, corpus bounded by measurement.** Pass a value here
    for the corpus phase.

    Posts of unknown age are kept, so on a platform whose ids do not encode a timestamp
    this degrades to no filtering rather than to an empty corpus.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = out_dir / METRICS_FILENAME
    accounts_path = out_dir / ACCOUNTS_FILENAME
    failures_path = out_dir / FAILURES_FILENAME

    already_have = _existing_source_ids(metrics_path)
    report = HarvestReport(
        requested_per_account=target_per_account, harvested=0, skipped_existing=0, failed=0
    )

    for handle in handles:
        account_dir = out_dir / handle
        candidate_limit = max(target_per_account, int(target_per_account * attempt_multiplier))
        # Enumerate before profiling: a fetcher may serve both from one response, and
        # this ordering lets it. An account that will not enumerate is also a dead
        # handle, so there is nothing to gain by profiling it first.
        # `spread` needs the whole catalogue to sample across it; `recent` only needs
        # the head, so it asks for the head and costs less.
        enumerate_limit = None if strategy == "spread" else candidate_limit
        try:
            all_refs = fetcher.enumerate_account(handle, enumerate_limit)
            profile = fetcher.fetch_account(handle)
        except HarvestError as exc:
            failure = FetchFailure(
                source_id="",
                account_id=handle,
                stage=exc.stage,
                reason=exc.reason,
                attempted_at=datetime.now(UTC),
            )
            report.failures.append(failure)
            report.failed += 1
            _append_row(failures_path, FAILURES_COLUMNS, failure.failures_row())
            logger.warning("account %s unavailable: %s", handle, exc.reason)
            continue

        report.accounts.append(profile)
        _upsert_row(accounts_path, ACCOUNTS_COLUMNS, profile.accounts_row(), key="handle")

        in_window = _within_age(all_refs, max_age_days)
        _record_requested_span(report, in_window, max_age_days)
        refs = _select(in_window, target_per_account, candidate_limit, strategy)
        harvested_here = 0
        for ref in refs:
            if harvested_here >= target_per_account:
                break
            if ref.post_id in already_have and _locate_video(account_dir, ref.post_id) is not None:
                report.skipped_existing += 1
                harvested_here += 1
                continue
            try:
                post = fetcher.fetch_post(ref, account_dir)
            except HarvestError as exc:
                failure = FetchFailure(
                    source_id=ref.post_id,
                    account_id=ref.account_id,
                    stage=exc.stage,
                    reason=exc.reason,
                    attempted_at=datetime.now(UTC),
                )
                report.failures.append(failure)
                report.failed += 1
                _append_row(failures_path, FAILURES_COLUMNS, failure.failures_row())
                continue
            _append_row(metrics_path, METRICS_COLUMNS, post.metrics_row())
            already_have.add(post.source_id)
            report.harvested += 1
            harvested_here += 1
            if report.earliest_posted_at is None or post.posted_at < report.earliest_posted_at:
                report.earliest_posted_at = post.posted_at
            if report.latest_posted_at is None or post.posted_at > report.latest_posted_at:
                report.latest_posted_at = post.posted_at

    # Rewritten every run so the caveats always carry the corpus's current numbers.
    _write_corpus_readme(out_dir, report)
    return report
