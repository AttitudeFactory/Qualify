"""Offline tests for the research corpus runner.

No network, ever: every test drives `harvest_corpus` through a `FixtureFetcher` that
serves canned payloads and writes placeholder video files. The point of the
`VideoFetcher` Protocol is that this double is interchangeable with `YtDlpFetcher`,
so the runner's resume/failure/reporting behaviour is testable without yt-dlp
installed and without touching TikTok.
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from qualify_scraper.research.harvest import (
    ACCOUNTS_COLUMNS,
    METRICS_COLUMNS,
    AccountProfile,
    HarvestedPost,
    HarvestError,
    HarvestReport,
    PostRef,
    _post_from_info,
    _tiktok_posted_at,
    _within_age,
    harvest_corpus,
)

HANDLE = "inmobiliarialunaroman"
ACCOUNT_ID = "MS4wLjABAAAAtest"


def _info(post_id: str, *, timestamp: int = 1785101063, **overrides: object) -> dict[str, object]:
    """A yt-dlp `-J` payload trimmed to the keys the runner reads. Field names and
    shapes copied from a real TikTok response captured 2026-08-06."""
    payload: dict[str, object] = {
        "id": post_id,
        "timestamp": timestamp,
        "upload_date": "20260726",
        "duration": 59,
        "view_count": 750,
        "like_count": 8,
        "comment_count": 0,
        "description": "CASA EN VENTA",
    }
    payload.update(overrides)
    return payload


class FixtureFetcher:
    """Test double implementing `VideoFetcher` from canned data.

    `fail_ids` lets a test reproduce the ~50% per-video failure rate measured against
    the live site, which is the condition the resume and failure-log paths exist for."""

    def __init__(
        self,
        post_ids: list[str],
        *,
        fail_ids: set[str] | None = None,
        follower_count: int | None = 3955,
        account_error: str | None = None,
    ) -> None:
        self.post_ids = post_ids
        self.fail_ids = fail_ids or set()
        self.follower_count = follower_count
        self.account_error = account_error
        self.fetched: list[str] = []
        self.enumerate_limits: list[int | None] = []

    def enumerate_account(self, handle: str, limit: int | None) -> list[PostRef]:
        self.enumerate_limits.append(limit)
        selected = self.post_ids if limit is None else self.post_ids[:limit]
        return [
            PostRef(
                account_id=ACCOUNT_ID,
                post_id=post_id,
                post_url=f"https://www.tiktok.com/@{handle}/video/{post_id}",
            )
            for post_id in selected
        ]

    def fetch_account(self, handle: str) -> AccountProfile:
        if self.account_error:
            raise HarvestError("enumerate", self.account_error)
        return AccountProfile(
            account_id=ACCOUNT_ID,
            handle=handle,
            follower_count=self.follower_count,
            video_count=len(self.post_ids),
            fetched_at=datetime.now(UTC),
        )

    def fetch_post(self, ref: PostRef, dest_dir: Path) -> HarvestedPost:
        self.fetched.append(ref.post_id)
        if ref.post_id in self.fail_ids:
            raise HarvestError("fetch", "Unable to extract universal data for rehydration")
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / f"{ref.post_id}.mp4").write_bytes(b"\x00fake-mp4-bytes")
        info = _info(ref.post_id)
        (dest_dir / f"{ref.post_id}.info.json").write_text(json.dumps(info))
        return _post_from_info(ref, info, dest_dir)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_harvests_videos_and_writes_metrics(tmp_path: Path) -> None:
    fetcher = FixtureFetcher(["101", "102", "103"])

    report = harvest_corpus(fetcher, [HANDLE], tmp_path, target_per_account=3)

    assert report.harvested == 3
    assert report.failed == 0
    rows = _read_csv(tmp_path / "metrics.csv")
    assert [row["source_id"] for row in rows] == ["101", "102", "103"]
    assert all(row["account_id"] == ACCOUNT_ID for row in rows)
    for post_id in ("101", "102", "103"):
        assert (tmp_path / HANDLE / f"{post_id}.mp4").exists()
        assert (tmp_path / HANDLE / f"{post_id}.info.json").exists()


def test_metrics_csv_carries_the_columns_postobservation_consumes(tmp_path: Path) -> None:
    """The CSV is a contract with `qualify_models.hooks.analysis.PostObservation`.
    `duration_seconds` is included because that model has the field and the payload
    provides it for free."""
    harvest_corpus(FixtureFetcher(["101"]), [HANDLE], tmp_path, target_per_account=1)

    row = _read_csv(tmp_path / "metrics.csv")[0]
    for column in ("source_id", "account_id", "posted_at", "likes", "comments", "views"):
        assert row[column] != ""
    assert row["duration_seconds"] == "59.0"


def test_posted_at_uses_full_timestamp_not_upload_date(tmp_path: Path) -> None:
    """`upload_date` is date-only. Losing time of day would blunt the detrending the
    analysis does on posting time, so the runner must read `timestamp`."""
    harvest_corpus(FixtureFetcher(["101"]), [HANDLE], tmp_path, target_per_account=1)

    posted_at = datetime.fromisoformat(_read_csv(tmp_path / "metrics.csv")[0]["posted_at"])
    assert posted_at == datetime.fromtimestamp(1785101063, UTC)
    assert (posted_at.hour, posted_at.minute) != (0, 0)


def test_failed_videos_are_recorded_and_do_not_abort_the_run(tmp_path: Path) -> None:
    fetcher = FixtureFetcher(["101", "102", "103", "104"], fail_ids={"102", "103"})

    report = harvest_corpus(fetcher, [HANDLE], tmp_path, target_per_account=4)

    assert report.harvested == 2
    assert report.failed == 2
    failures = _read_csv(tmp_path / "failures.csv")
    assert {row["source_id"] for row in failures} == {"102", "103"}
    assert all(row["stage"] == "fetch" for row in failures)
    assert all(row["reason"] for row in failures)


def test_reports_success_rate_over_attempts(tmp_path: Path) -> None:
    fetcher = FixtureFetcher(["101", "102", "103", "104"], fail_ids={"103", "104"})

    report = harvest_corpus(fetcher, [HANDLE], tmp_path, target_per_account=4)

    assert report.attempted == 4
    assert report.success_rate == 0.5


def test_rerun_is_idempotent_and_makes_no_further_fetches(tmp_path: Path) -> None:
    """Resume is mandatory, not hygiene: at a ~50% per-video success rate a full run is
    expected to be partial and repeated, and re-downloading what is already on disk
    multiplies the rate-limit exposure the runner should be minimising."""
    first = FixtureFetcher(["101", "102"])
    harvest_corpus(first, [HANDLE], tmp_path, target_per_account=2)
    assert first.fetched == ["101", "102"]

    second = FixtureFetcher(["101", "102"])
    report = harvest_corpus(second, [HANDLE], tmp_path, target_per_account=2)

    assert second.fetched == []
    assert report.harvested == 0
    assert report.skipped_existing == 2
    assert report.success_rate is None
    assert len(_read_csv(tmp_path / "metrics.csv")) == 2


def test_rerun_retries_only_what_previously_failed(tmp_path: Path) -> None:
    harvest_corpus(
        FixtureFetcher(["101", "102"], fail_ids={"102"}), [HANDLE], tmp_path, target_per_account=2
    )

    retry = FixtureFetcher(["101", "102"])
    report = harvest_corpus(retry, [HANDLE], tmp_path, target_per_account=2)

    assert retry.fetched == ["102"]
    assert report.harvested == 1
    assert report.skipped_existing == 1
    assert {row["source_id"] for row in _read_csv(tmp_path / "metrics.csv")} == {"101", "102"}


def test_a_metrics_row_without_its_video_is_refetched(tmp_path: Path) -> None:
    """A CSV row is not proof the bytes are there. If the mp4 was deleted or truncated,
    the post must be fetched again rather than silently counted as present."""
    harvest_corpus(FixtureFetcher(["101"]), [HANDLE], tmp_path, target_per_account=1)
    (tmp_path / HANDLE / "101.mp4").unlink()

    retry = FixtureFetcher(["101"])
    harvest_corpus(retry, [HANDLE], tmp_path, target_per_account=1)

    assert retry.fetched == ["101"]


def test_follower_count_is_written_per_account_not_per_post(tmp_path: Path) -> None:
    """Measured 2026-08-06: the per-video payload carries no follower count, so it
    costs its own request and belongs in its own table."""
    harvest_corpus(FixtureFetcher(["101", "102"]), [HANDLE], tmp_path, target_per_account=2)

    accounts = _read_csv(tmp_path / "accounts.csv")
    assert len(accounts) == 1
    assert accounts[0]["handle"] == HANDLE
    assert accounts[0]["follower_count"] == "3955"
    assert "follower_count" not in _read_csv(tmp_path / "metrics.csv")[0]


def test_unavailable_account_is_recorded_and_other_accounts_still_run(tmp_path: Path) -> None:
    class Router:
        def __init__(self) -> None:
            self.good = FixtureFetcher(["201"])
            self.bad = FixtureFetcher([], account_error="Unable to extract secondary user ID")

        def _pick(self, handle: str) -> FixtureFetcher:
            return self.bad if handle == "deadhandle" else self.good

        def enumerate_account(self, handle: str, limit: int | None) -> list[PostRef]:
            return self._pick(handle).enumerate_account(handle, limit)

        def fetch_account(self, handle: str) -> AccountProfile:
            return self._pick(handle).fetch_account(handle)

        def fetch_post(self, ref: PostRef, dest_dir: Path) -> HarvestedPost:
            return self.good.fetch_post(ref, dest_dir)

    report = harvest_corpus(Router(), ["deadhandle", HANDLE], tmp_path, target_per_account=1)

    assert report.harvested == 1
    failures = _read_csv(tmp_path / "failures.csv")
    assert [row["account_id"] for row in failures] == ["deadhandle"]
    assert failures[0]["stage"] == "enumerate"


def test_enumerates_more_candidates_than_the_target_to_absorb_failures(tmp_path: Path) -> None:
    """With a measured ~50% success rate, asking for exactly N candidates yields ~N/2
    videos. The runner over-enumerates and stops once the target is met."""
    fetcher = FixtureFetcher([str(i) for i in range(10)], fail_ids={"0", "1", "2", "3", "4"})

    report = harvest_corpus(fetcher, [HANDLE], tmp_path, target_per_account=5)

    assert report.harvested == 5
    assert report.failed == 5


def test_payload_without_timestamp_is_a_failure_not_a_silent_zero(tmp_path: Path) -> None:
    ref = PostRef(account_id=ACCOUNT_ID, post_id="101", post_url="https://example.test/1")
    info = _info("101")
    del info["timestamp"]

    with pytest.raises(HarvestError) as excinfo:
        _post_from_info(ref, info, tmp_path)

    assert excinfo.value.stage == "parse"


def test_metadata_without_bytes_on_disk_is_a_failure(tmp_path: Path) -> None:
    """The extractor needs the mp4. Metadata alone is not a harvested post."""
    ref = PostRef(account_id=ACCOUNT_ID, post_id="101", post_url="https://example.test/1")

    with pytest.raises(HarvestError) as excinfo:
        _post_from_info(ref, _info("101"), tmp_path)

    assert excinfo.value.stage == "fetch"


def test_rerunning_does_not_duplicate_account_rows(tmp_path: Path) -> None:
    """Regression: `accounts.csv` is one row per account, not one per run. Appending
    blindly grew a duplicate row on every resume, which fans out any join on
    `account_id`. Caught on a live re-run, not by the original tests."""
    for _ in range(3):
        harvest_corpus(FixtureFetcher(["101"]), [HANDLE], tmp_path, target_per_account=1)

    accounts = _read_csv(tmp_path / "accounts.csv")
    assert len(accounts) == 1
    assert accounts[0]["handle"] == HANDLE


def test_account_row_is_refreshed_not_stale_on_rerun(tmp_path: Path) -> None:
    harvest_corpus(
        FixtureFetcher(["101"], follower_count=100), [HANDLE], tmp_path, target_per_account=1
    )
    harvest_corpus(
        FixtureFetcher(["101"], follower_count=250), [HANDLE], tmp_path, target_per_account=1
    )

    accounts = _read_csv(tmp_path / "accounts.csv")
    assert len(accounts) == 1
    assert accounts[0]["follower_count"] == "250"


def test_multiple_accounts_each_keep_their_own_row(tmp_path: Path) -> None:
    for handle in ("accounta", "accountb"):
        harvest_corpus(FixtureFetcher(["101"]), [handle], tmp_path, target_per_account=1)

    assert {row["handle"] for row in _read_csv(tmp_path / "accounts.csv")} == {
        "accounta",
        "accountb",
    }


def test_missing_views_is_empty_not_zero(tmp_path: Path) -> None:
    """A metric the platform did not report must reach the CSV as an empty cell.

    `views` is the analysis's primary outcome and the denominator of `engagement_rate`.
    Imputing 0 would rank an unmeasured post as the worst in its library and turn a
    missing denominator into a rate of zero — both fabricated measurements."""
    ref = PostRef(account_id=ACCOUNT_ID, post_id="101", post_url="https://example.test/1")
    info = _info("101")
    del info["view_count"]
    (tmp_path / "101.mp4").write_bytes(b"\x00")

    post = _post_from_info(ref, info, tmp_path)

    assert post.views is None
    assert post.metrics_row()["views"] == ""


def test_genuine_zero_metric_is_preserved_as_zero(tmp_path: Path) -> None:
    """The counterpart: a real 0 must not be flattened into "missing" either."""
    ref = PostRef(account_id=ACCOUNT_ID, post_id="101", post_url="https://example.test/1")
    (tmp_path / "101.mp4").write_bytes(b"\x00")

    post = _post_from_info(ref, _info("101", view_count=0, like_count=0), tmp_path)

    assert post.views == 0
    assert post.metrics_row()["views"] == "0"
    assert post.metrics_row()["likes"] == "0"


def test_spread_samples_across_the_whole_catalogue_not_just_the_newest(tmp_path: Path) -> None:
    """Enumeration is newest-first, so taking the head is a recency sample. On a
    long-lived account that is a severe bias for a question about whether an account's
    openings *vary*: measured on a real account, the 34 newest of 365 posts cover 4.3%
    of a 4.2-year span. `spread` must reach the old end of the catalogue."""
    catalogue = [str(i) for i in range(100)]
    fetcher = FixtureFetcher(catalogue)

    harvest_corpus(fetcher, [HANDLE], tmp_path, target_per_account=5, strategy="spread")

    fetched = [int(x) for x in fetcher.fetched]
    assert fetched[0] == 0
    assert fetched[-1] == 99, "spread must include the oldest post, not stop near the head"
    assert max(fetched) - min(fetched) > 90


def test_recent_takes_the_head_of_the_catalogue(tmp_path: Path) -> None:
    fetcher = FixtureFetcher([str(i) for i in range(100)])

    harvest_corpus(fetcher, [HANDLE], tmp_path, target_per_account=5, strategy="recent")

    assert [int(x) for x in fetcher.fetched] == [0, 1, 2, 3, 4]


def test_spread_requests_the_whole_catalogue_recent_only_the_head(tmp_path: Path) -> None:
    """`spread` cannot sample across a catalogue it has not seen, so it must enumerate
    with no limit; `recent` asks only for the head and costs less."""
    spread = FixtureFetcher([str(i) for i in range(100)])
    harvest_corpus(spread, [HANDLE], tmp_path / "a", target_per_account=3, strategy="spread")

    recent = FixtureFetcher([str(i) for i in range(100)])
    harvest_corpus(recent, [HANDLE], tmp_path / "b", target_per_account=3, strategy="recent")

    assert spread.enumerate_limits == [None]
    assert recent.enumerate_limits == [9]  # target 3 * attempt_multiplier 3.0


def test_spread_degrades_to_everything_when_the_catalogue_is_small(tmp_path: Path) -> None:
    fetcher = FixtureFetcher(["1", "2"])

    report = harvest_corpus(fetcher, [HANDLE], tmp_path, target_per_account=5, strategy="spread")

    assert report.harvested == 2
    assert fetcher.fetched == ["1", "2"]


def test_spread_is_the_default(tmp_path: Path) -> None:
    """The pilot's binding question is within-account variety, so the safe default is
    the sample that can see it."""
    fetcher = FixtureFetcher([str(i) for i in range(100)])

    harvest_corpus(fetcher, [HANDLE], tmp_path, target_per_account=4)

    assert int(fetcher.fetched[-1]) > 50


def _aged_refs(ages_days: list[int]) -> list[PostRef]:
    now = datetime.now(UTC)
    return [
        PostRef(
            account_id=ACCOUNT_ID,
            post_id=str(i),
            post_url=f"https://example.test/{i}",
            posted_at=now - timedelta(days=age),
        )
        for i, age in enumerate(ages_days)
    ]


def test_age_window_drops_posts_older_than_the_bound() -> None:
    refs = _aged_refs([10, 200, 400, 1500])

    kept = _within_age(refs, max_age_days=365)

    assert [r.post_id for r in kept] == ["0", "1"]


def test_posts_of_unknown_age_are_kept() -> None:
    """Dropping them would silently shrink a corpus on any platform whose ids carry no
    timestamp, and that looks identical to 'this account has few recent posts'."""
    refs = [PostRef(account_id=ACCOUNT_ID, post_id="x", post_url="https://example.test/x")]

    assert _within_age(refs, max_age_days=365) == refs


def test_no_age_bound_keeps_the_whole_catalogue() -> None:
    refs = _aged_refs([10, 4000])

    assert len(_within_age(refs, max_age_days=None)) == 2


def test_tiktok_ids_decode_to_their_posting_time() -> None:
    """Real id from `@inmobiliarialunaroman`, whose fetched payload reported
    `timestamp=1785101063` (2026-07-26 21:24:23 UTC).

    The decode agrees to within seconds but is NOT exact — measured 8 s later, which is
    plausibly id-minting time vs publish time. That is why this is only ever used for the
    age window, never as the analysis timestamp: a 365-day bound does not care about
    8 s, and `metrics.csv` carries the payload's exact `timestamp` instead."""
    decoded = _tiktok_posted_at("7666950720377097479")

    assert decoded is not None
    drift = abs((decoded - datetime.fromtimestamp(1785101063, UTC)).total_seconds())
    assert drift < 60, f"id decode drifted {drift}s from the reported timestamp"


def test_undecodable_ids_are_unknown_age_not_a_wrong_date() -> None:
    assert _tiktok_posted_at("not-a-number") is None
    assert _tiktok_posted_at("12345") is None


def test_age_window_applies_before_sampling(tmp_path: Path) -> None:
    """The window must shrink the population the spread runs over, not filter its
    output — otherwise a spread across 4 years is computed and then mostly discarded."""

    class AgedFetcher(FixtureFetcher):
        def enumerate_account(self, handle: str, limit: int | None) -> list[PostRef]:
            self.enumerate_limits.append(limit)
            return _aged_refs([5, 30, 100, 300, 900, 1400])

    fetcher = AgedFetcher([])
    harvest_corpus(fetcher, [HANDLE], tmp_path, target_per_account=2, max_age_days=365)

    assert set(fetcher.fetched) <= {"0", "1", "2", "3"}
    assert "4" not in fetcher.fetched and "5" not in fetcher.fetched


def test_report_records_the_span_actually_achieved(tmp_path: Path) -> None:
    """Measured live: a run requesting a 365-day spread came back covering 98 days,
    because the picks at both ends failed and only interior backups survived. The
    requested window is an intent; only the achieved span describes the corpus."""

    class DatedFetcher(FixtureFetcher):
        def fetch_post(self, ref: PostRef, dest_dir: Path) -> HarvestedPost:
            self.fetched.append(ref.post_id)
            dest_dir.mkdir(parents=True, exist_ok=True)
            (dest_dir / f"{ref.post_id}.mp4").write_bytes(b"\x00")
            days = {"a": 0, "b": 50, "c": 300}[ref.post_id]
            info = _info(ref.post_id, timestamp=int(datetime.now(UTC).timestamp()) - days * 86400)
            return _post_from_info(ref, info, dest_dir)

    fetcher = DatedFetcher(["a", "b", "c"])
    report = harvest_corpus(fetcher, [HANDLE], tmp_path, target_per_account=3)

    assert report.achieved_span_days is not None
    assert 299 < report.achieved_span_days < 301


def test_achieved_span_is_none_without_enough_dated_posts(tmp_path: Path) -> None:
    report = harvest_corpus(FixtureFetcher([]), [HANDLE], tmp_path, target_per_account=1)

    assert report.achieved_span_days is None


REAL_CORPUS_DIR = Path(__file__).parent / "fixtures" / "corpus"


def test_writer_output_matches_the_committed_real_corpus_format() -> None:
    """Pins the on-disk format against a real harvest (10 posts from
    `@inmobiliarialunaroman`, 2026-08-06), not a synthesized one.

    This file is also consumed by `qualify_models.hooks.join`'s test suite. Their
    fixtures test *their reading* of this format; only a real file tests the format
    itself. If a column here is renamed or re-encoded, both suites fail at the seam
    instead of the pilot failing later."""
    with (REAL_CORPUS_DIR / "metrics.csv").open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert tuple(reader.fieldnames or ()) == METRICS_COLUMNS
        rows = list(reader)

    assert len(rows) == 10
    # Every row must carry the two columns the within-account design cannot work without.
    assert all(row["source_id"] and row["account_id"] for row in rows)
    # posted_at must round-trip as an aware UTC datetime, not a bare date.
    sample = datetime.fromisoformat(rows[0]["posted_at"])
    assert sample.tzinfo is not None
    assert (sample.hour, sample.minute) != (0, 0)


def test_committed_accounts_fixture_has_one_row_per_account() -> None:
    with (REAL_CORPUS_DIR / "accounts.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert tuple(rows[0].keys()) == ACCOUNTS_COLUMNS
    assert len({row["handle"] for row in rows}) == len(rows)


def test_bounded_run_reports_the_window_as_requested_span(tmp_path: Path) -> None:
    class AgedFetcher(FixtureFetcher):
        def enumerate_account(self, handle: str, limit: int | None) -> list[PostRef]:
            self.enumerate_limits.append(limit)
            return _aged_refs([1, 2, 3])

    report = harvest_corpus(
        AgedFetcher([]), [HANDLE], tmp_path, target_per_account=1, max_age_days=365
    )

    assert report.requested_span_days == 365.0


def test_unbounded_run_reports_the_available_span_as_requested(tmp_path: Path) -> None:
    """An unbounded run still requested something: everything on offer. Without this the
    coverage check would be undefined for exactly the unbounded pilot it matters for."""

    class AgedFetcher(FixtureFetcher):
        def enumerate_account(self, handle: str, limit: int | None) -> list[PostRef]:
            self.enumerate_limits.append(limit)
            return _aged_refs([0, 500, 1000])

    report = harvest_corpus(AgedFetcher([]), [HANDLE], tmp_path, target_per_account=1)

    assert report.requested_span_days is not None
    assert 999 < report.requested_span_days < 1001


def test_span_coverage_flags_a_corpus_narrower_than_designed(tmp_path: Path) -> None:
    """The measured live case: a 365-day request that came back covering 98 days."""
    report = HarvestReport(requested_per_account=5, harvested=5, skipped_existing=0, failed=5)
    report.requested_span_days = 365.0
    report.earliest_posted_at = datetime(2026, 1, 13, tzinfo=UTC)
    report.latest_posted_at = datetime(2026, 4, 21, tzinfo=UTC)

    assert report.span_coverage is not None
    assert report.span_coverage < 0.3


def test_span_coverage_is_none_when_nothing_was_requested() -> None:
    report = HarvestReport(requested_per_account=1, harvested=0, skipped_existing=0, failed=0)

    assert report.span_coverage is None


def test_corpus_directory_carries_its_own_interpretation_caveats(tmp_path: Path) -> None:
    """The caveats must travel with the data, not only with the code. Whoever opens this
    directory later may not be in this repo and may not have read any README."""
    harvest_corpus(FixtureFetcher(["101", "102"]), [HANDLE], tmp_path, target_per_account=2)

    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    # Collapse wrapping before matching: the file is hard-wrapped prose.
    flat = " ".join(readme.split())
    assert 'may mean "we could not see it", not "it is not there."' in flat
    assert "2 videos harvested" in readme
    assert "1 account(s)" in readme
    # The account-margin warning must fire at n<=3, which is the real pilot's situation.
    assert "ZERO" in readme
    assert "failures.csv" in readme


def test_corpus_readme_carries_this_runs_own_coverage_number(tmp_path: Path) -> None:
    """A generic caution is easy to wave through; the run's own measured figure is not."""

    class AgedFetcher(FixtureFetcher):
        def enumerate_account(self, handle: str, limit: int | None) -> list[PostRef]:
            self.enumerate_limits.append(limit)
            return _aged_refs([0, 100, 200])

    harvest_corpus(AgedFetcher([]), [HANDLE], tmp_path, target_per_account=1, max_age_days=365)

    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "of the span this run asked for" in readme
    assert "**0%**" in readme, "the run's own coverage figure must be substituted in"


def test_corpus_readme_is_refreshed_on_rerun_not_appended(tmp_path: Path) -> None:
    for _ in range(3):
        harvest_corpus(FixtureFetcher(["101"]), [HANDLE], tmp_path, target_per_account=1)

    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert readme.count("# Research corpus") == 1
