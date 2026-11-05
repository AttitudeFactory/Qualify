"""Asking for a reel's shared analysis, offline (ADR 44, m-24921056 VE-04a): the contract
types and their sample, `request_analysis`, the status the screen polls, the badges.

The screen side never touches the network: none of these tests gives it an HTTP client,
and none is needed.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from qualify_api.referentes import reel_runs
from qualify_api.referentes.reel_analysis import (
    analysis_badges,
    get_analysis,
    get_analysis_status,
    request_analysis,
)
from qualify_api.referentes.reel_analysis_store import (
    BADGE_LOOKING,
    BADGE_NONE,
    BADGE_NOT_ANALYZED,
    BADGE_PERSON,
    AnalysisRecord,
    InMemoryAnalysisStore,
)
from qualify_api.referentes.reel_analysis_types import (
    ANALYSIS_VERSION,
    NOT_OBSERVED,
    OBSERVED,
    STATUS_DAILY_LIMIT,
    STATUS_FAILED,
    STATUS_NO_VIDEO,
    STATUS_OK,
    STATUS_QUEUED,
    UNKNOWN,
    ReelAnalysis,
    ReelSource,
    ShotAnalysis,
)

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
TENANT_A, TENANT_B = uuid4(), uuid4()
SAMPLE = Path(__file__).parent / "fixtures" / "reel_analysis_sample.json"
CDN = "https://scontent-bog1-1.cdninstagram.com/o1/v/t16/f2/m86/clip.mp4?efg=x"


def _source(post_id: str = "DABC123", **kw: object) -> ReelSource:
    values: dict[str, object] = {
        "network": "instagram",
        "post_id": post_id,
        "post_url": f"https://www.instagram.com/reel/{post_id}/",
        "video_url": CDN,
        "caption": "",
        "transcript": "",
    }
    values.update(kw)
    return ReelSource(**values)  # type: ignore[arg-type]


def _ok_record(post_id: str = "DABC123") -> AnalysisRecord:
    return AnalysisRecord(
        id=uuid4(),
        network="instagram",
        post_id=post_id,
        analysis_version=ANALYSIS_VERSION,
        status=STATUS_OK,
        post_url=f"https://www.instagram.com/reel/{post_id}/",
        created_at=NOW - timedelta(days=1),
        source_key=f"public/reel-analyses/instagram/{post_id}/x/source/source.mp4",
        source_sha256="b" * 64,
        source_seconds=12.0,
        width=720,
        height=1280,
        fps=30.0,
        covered_from_s=0.0,
        covered_to_s=12.0,
        edit_eligible=True,
        model_id="claude-haiku-5-5",
        prompt_version="p1",
        schema_version="s1",
        detector_version="d1",
        sampling_version="m1",
        sampling_params={},
        reel_sheet={"hook": {"status": UNKNOWN}},
        cost_usd=Decimal("0.0055"),
        finished_at=NOW - timedelta(hours=20),
    )


# -- the contract -------------------------------------------------------------------------


def test_the_sample_fixture_loads_and_round_trips() -> None:
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    analysis = ReelAnalysis.from_dict(data)
    assert len(analysis.shots) == 5
    assert all(s.end_s > s.start_s for s in analysis.shots)
    assert {s.people_presence for s in analysis.shots} <= {OBSERVED, NOT_OBSERVED, UNKNOWN}
    assert analysis.covered_to_s <= 60
    again = ReelAnalysis.from_dict(analysis.to_dict())
    assert again == analysis
    with pytest.raises(dataclasses.FrozenInstanceError):
        analysis.post_id = "x"  # type: ignore[misc]


def test_the_source_carries_no_metric_verdict_or_handle() -> None:
    """V12: the extractor sees a public reel, never its numbers nor who posted it."""
    names = {f.name for f in dataclasses.fields(ReelSource)}
    assert names == {
        "network",
        "post_id",
        "post_url",
        "video_url",
        "caption",
        "transcript",
        "transcript_segments",
        "transcript_source",
        "video_url_at",
    }
    forbidden = ("view", "like", "lift", "affinity", "verdict", "reason", "handle", "tenant")
    assert not [n for n in names if any(f in n for f in forbidden)]


def test_r4_ideas_are_reel_sources() -> None:
    assert reel_runs.IdeaSource is ReelSource


def test_no_record_field_names_a_business() -> None:
    names = {f.name for f in dataclasses.fields(AnalysisRecord)}
    assert not [n for n in names if any(f in n for f in ("tenant", "brand", "user", "owner"))]


# -- request_analysis ---------------------------------------------------------------------


def test_two_businesses_asking_for_the_same_reel_make_one_row() -> None:
    store = InMemoryAnalysisStore()
    first = request_analysis(TENANT_A, _source(), store=store, clock=lambda: NOW)
    second = request_analysis(
        TENANT_B, _source(), store=store, clock=lambda: NOW + timedelta(minutes=1)
    )
    assert first.status == STATUS_QUEUED and first.id is not None and not first.reused
    assert second.id == first.id and second.status == STATUS_QUEUED
    (row,) = store.rows()
    assert row.wanted_at == NOW  # the first ask; a second one never pushes it back
    assert row.pending_video_url == CDN
    assert row.analysis_version == ANALYSIS_VERSION


def test_an_existing_ok_is_reused_without_a_new_row() -> None:
    store = InMemoryAnalysisStore()
    ok = _ok_record()
    store.put(ok)
    ref = request_analysis(TENANT_A, _source(video_url=""), store=store, clock=lambda: NOW)
    assert (ref.id, ref.status, ref.reused) == (ok.id, STATUS_OK, True)
    assert len(store.rows()) == 1


def test_a_weekly_row_still_queued_joins_the_on_demand_lane() -> None:
    store = InMemoryAnalysisStore()
    weekly, _ = store.ensure(_source(), ANALYSIS_VERSION, NOW - timedelta(hours=2))
    assert weekly.wanted_at is None
    ref = request_analysis(TENANT_A, _source(), store=store, clock=lambda: NOW)
    assert ref.id == weekly.id and ref.status == STATUS_QUEUED
    assert store.get(weekly.id).wanted_at == NOW  # type: ignore[union-attr]


def test_a_failed_row_is_returned_as_it_is() -> None:
    store = InMemoryAnalysisStore()
    failed = dataclasses.replace(
        _ok_record(), status=STATUS_FAILED, error_code="source_expired", reel_sheet=None
    )
    store.put(failed)
    ref = request_analysis(TENANT_A, _source(), store=store, clock=lambda: NOW)
    assert (ref.id, ref.status) == (failed.id, STATUS_FAILED)
    assert store.get(failed.id).status == STATUS_FAILED  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "kw",
    [
        {"video_url": ""},
        {"video_url": "https://evil.example.com/clip.mp4"},
        {"video_url": "http://scontent.cdninstagram.com/clip.mp4"},
        {"video_url": "https://169.254.169.254/latest/meta-data"},
        {"video_url": "https://user:pw@scontent.cdninstagram.com/clip.mp4"},
        {"video_url": "https://v16.tiktokcdn.com/clip.mp4"},  # TikTok host, Instagram reel
        {"video_url_at": NOW - timedelta(hours=21)},
        {"video_url": CDN + "&oe=" + format(int((NOW - timedelta(minutes=1)).timestamp()), "x")},
    ],
)
def test_without_a_usable_video_url_nothing_is_created(kw: dict[str, object]) -> None:
    store = InMemoryAnalysisStore()
    ref = request_analysis(TENANT_A, _source(**kw), store=store, clock=lambda: NOW)
    assert (ref.id, ref.status) == (None, STATUS_NO_VIDEO)
    assert store.rows() == []


def test_the_51st_on_demand_request_of_the_day_is_refused_without_a_row() -> None:
    store = InMemoryAnalysisStore()
    for i in range(50):
        ref = request_analysis(
            TENANT_A, _source(f"P{i}"), store=store, clock=lambda: NOW, daily_limit=50
        )
        assert ref.status == STATUS_QUEUED
    refused = request_analysis(
        TENANT_B, _source("P50"), store=store, clock=lambda: NOW, daily_limit=50
    )
    assert (refused.id, refused.status) == (None, STATUS_DAILY_LIMIT)
    assert len(store.rows()) == 50
    # Asking again for a reel already queued costs nothing and is still answered.
    again = request_analysis(TENANT_B, _source("P7"), store=store, clock=lambda: NOW)
    assert again.status == STATUS_QUEUED
    # A day later the quota is free again.
    later = request_analysis(
        TENANT_B, _source("P50"), store=store, clock=lambda: NOW + timedelta(hours=25)
    )
    assert later.status == STATUS_QUEUED


def test_the_quota_reads_its_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUALIFY_REEL_ANALYSIS_ON_DEMAND_DAILY", "1")
    store = InMemoryAnalysisStore()
    assert request_analysis(TENANT_A, _source("A"), store=store, clock=lambda: NOW).status == (
        STATUS_QUEUED
    )
    assert request_analysis(TENANT_A, _source("B"), store=store, clock=lambda: NOW).status == (
        STATUS_DAILY_LIMIT
    )


def test_a_bad_identity_is_refused() -> None:
    with pytest.raises(ValueError):
        request_analysis(TENANT_A, _source(network="facebook"), store=InMemoryAnalysisStore())
    with pytest.raises(ValueError):
        request_analysis(TENANT_A, _source(post_id=""), store=InMemoryAnalysisStore())


# -- status, analysis, badges -------------------------------------------------------------


def test_status_of_a_queued_row() -> None:
    store = InMemoryAnalysisStore()
    earlier = request_analysis(TENANT_A, _source("E"), store=store, clock=lambda: NOW)
    mine = request_analysis(
        TENANT_A, _source("M"), store=store, clock=lambda: NOW + timedelta(seconds=10)
    )
    assert earlier.id and mine.id
    status = get_analysis_status(
        TENANT_A, mine.id, store=store, clock=lambda: NOW + timedelta(seconds=70)
    )
    assert status is not None
    assert (status.status, status.queue_ahead, status.queued_for_s) == (STATUS_QUEUED, 1, 60.0)
    assert not status.source_available and not status.retryable and not status.fleet_paused
    assert get_analysis(TENANT_A, mine.id, store=store) is None  # not ok yet
    assert get_analysis_status(TENANT_A, uuid4(), store=store) is None


def test_status_says_when_the_fleet_cap_holds_the_row(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUALIFY_REEL_ANALYSIS_FLEET_DAILY", "2")
    store = InMemoryAnalysisStore()
    store.put(dataclasses.replace(_ok_record("X"), model_calls=2))
    ref = request_analysis(TENANT_A, _source("Y"), store=store, clock=lambda: NOW)
    assert ref.id is not None
    status = get_analysis_status(TENANT_A, ref.id, store=store, clock=lambda: NOW)
    assert status is not None and status.fleet_paused


def test_an_ok_analysis_reads_back_with_its_shots() -> None:
    store = InMemoryAnalysisStore()
    ok = _ok_record()
    shots = [
        ShotAnalysis(1, 4.0, 12.0, people_presence=OBSERVED),
        ShotAnalysis(0, 0.0, 4.0, people_presence=NOT_OBSERVED, visible_faces=NOT_OBSERVED),
    ]
    store.put(ok, shots)
    analysis = get_analysis(TENANT_A, ok.id, store=store)
    assert analysis is not None
    assert [s.shot_index for s in analysis.shots] == [0, 1]
    assert analysis.source_available and analysis.edit_eligible
    assert analysis.provenance.cost_usd == Decimal("0.0055")
    status = get_analysis_status(TENANT_A, ok.id, store=store, clock=lambda: NOW)
    assert status is not None and status.shots_found == 2 and status.queue_ahead == 0


def test_badges_for_a_whole_list_in_one_call() -> None:
    store = InMemoryAnalysisStore()
    person, clear, unknown = _ok_record("PER"), _ok_record("CLR"), _ok_record("UNK")
    store.put(person, [ShotAnalysis(0, 0, 2, visible_faces=OBSERVED)])
    store.put(clear, [ShotAnalysis(0, 0, 2, people_presence=NOT_OBSERVED)])
    store.put(unknown, [ShotAnalysis(0, 0, 2)])
    store.put(dataclasses.replace(_ok_record("BAD"), status=STATUS_FAILED, error_code="x"))
    request_analysis(TENANT_A, _source("Q"), store=store, clock=lambda: NOW)
    keys = [("instagram", p) for p in ("PER", "CLR", "UNK", "BAD", "Q", "NONE", "PER")]
    assert analysis_badges(TENANT_A, keys, store=store) == {
        ("instagram", "PER"): BADGE_PERSON,
        ("instagram", "CLR"): BADGE_NONE,
        ("instagram", "UNK"): BADGE_NONE,
        ("instagram", "BAD"): BADGE_NOT_ANALYZED,
        ("instagram", "Q"): BADGE_LOOKING,
        ("instagram", "NONE"): BADGE_NOT_ANALYZED,
    }
