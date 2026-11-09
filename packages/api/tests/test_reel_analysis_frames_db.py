"""`get_analysis` says whether an analysis' frames are still in R2 (UI-3, m-24921077),
against the live schema: an `ok` analysis reads `frames_available`, and after the 30-day
purge marks it (`mark_purged`) it does not — so the parts list shows no thumbnail path
for frames that are gone."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from qualify_api.referentes.reel_analysis import get_analysis
from qualify_api.referentes.reel_analysis_frames import representative_frame
from qualify_api.referentes.reel_analysis_queue import PostgresAnalysisQueue
from qualify_api.referentes.reel_analysis_store import (
    DescribeResult,
    PostgresAnalysisRequests,
    SourceFacts,
)
from qualify_api.referentes.reel_analysis_types import ANALYSIS_VERSION, ReelSource, ShotAnalysis

pytestmark = pytest.mark.db

NOW = datetime.now(UTC).replace(microsecond=0)
LEASE = timedelta(minutes=2)


@pytest.fixture(autouse=True)
def empty_tables() -> Iterator[None]:
    engine = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM public_reel_analyses"))
    yield
    engine.dispose()


def test_purged_frames_leave_the_analysis_without_a_thumbnail() -> None:
    queue = PostgresAnalysisQueue()
    post_id = f"P{uuid4().hex[:10]}"
    source = ReelSource(
        network="instagram",
        post_id=post_id,
        post_url=f"https://www.instagram.com/reel/{post_id}/",
        video_url="https://scontent-bog1-1.cdninstagram.com/o1/v/t16/clip.mp4?efg=abc",
    )
    record, _ = queue.ensure(source, ANALYSIS_VERSION, NOW)
    held = queue.claim(record.id, NOW, LEASE, max_attempts=3)
    assert held is not None
    root = f"public/reel-analyses/instagram/{post_id}/{record.id}/"
    purge_after = NOW + timedelta(days=30)
    facts = SourceFacts(
        source_key=f"{root}source/source.mp4",
        source_sha256="c" * 64,
        source_seconds=10.0,
        width=720,
        height=1280,
        fps=30.0,
        covered_from_s=0.0,
        covered_to_s=10.0,
        edit_eligible=True,
    )
    assert queue.record_source(record.id, held.token, facts, purge_after)
    frames = (f"{root}frames/00-0.jpg", f"{root}frames/00-1.jpg", f"{root}frames/00-2.jpg")
    result = DescribeResult(
        shots=(ShotAnalysis(0, 0.0, 10.0, frames, (2.0, 5.0, 8.0)),),
        reel_sheet={},
        model_id="claude-haiku-5-5",
        model_revision="rev",
        prompt_version="p1",
        schema_version="s1",
        detector_version="d1",
        sampling_version="m1",
        sampling_params={},
        input_tokens=1,
        output_tokens=1,
        cost_usd=Decimal("0"),
    )
    assert queue.complete(record.id, held.token, result, NOW)

    requests = PostgresAnalysisRequests()
    stored = get_analysis(uuid4(), record.id, store=requests)
    assert stored is not None and stored.frames_available
    pick = representative_frame(stored, [0])
    assert pick is not None and pick.frame == "00-1"

    assert queue.mark_purged(record.id, purge_after, NOW + timedelta(days=31))
    purged = get_analysis(uuid4(), record.id, store=requests)
    assert purged is not None and not purged.frames_available
    assert representative_frame(purged, [0]) is None
