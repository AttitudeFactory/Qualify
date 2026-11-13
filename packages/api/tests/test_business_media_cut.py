"""The Galería cut's request, offline (m-24955923, CM-3): span validation with the texts
the owner reads, and the idempotency key `cut:{source}:{sha256 of kept spans}:{version}`."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from qualify_api.catalog.business_media import (
    CUT_INVALID_TEXT,
    NO_PART_KEPT_TEXT,
    PART_TOO_SHORT_TEXT,
    CutSpan,
    _job_record,
    cut_idempotency_key,
    validate_cut_spans,
)
from qualify_api.catalog.service import CatalogError

SOURCE = UUID("5a5a5a5a-0000-4000-8000-00000000c003")


def _texts(spans: list[CutSpan], duration: int | None = 20_000) -> str:
    with pytest.raises(CatalogError) as caught:
        validate_cut_spans(spans, duration)
    return str(caught.value.args[0])


def test_kept_spans_come_back_in_order_and_removed_ones_are_dropped() -> None:
    spans = [
        CutSpan(0, 4_000, keep=True),
        CutSpan(4_000, 9_000, keep=False),
        CutSpan(9_000, 20_000, keep=True),
    ]
    assert validate_cut_spans(spans, 20_000) == ((0, 4_000), (9_000, 20_000))


@pytest.mark.parametrize(
    "spans",
    [
        [CutSpan(-1, 4_000, True)],  # before the start
        [CutSpan(0, 20_001, True)],  # past the end
        [CutSpan(5_000, 9_000, True), CutSpan(0, 4_000, True)],  # not ordered
        [CutSpan(0, 5_000, True), CutSpan(4_000, 9_000, True)],  # overlapping
        [CutSpan(4_000, 4_000, True)],  # empty
        [CutSpan(0, 4_000.5, True)],  # type: ignore[arg-type]  # not whole ms
        [CutSpan(0, 4_000, "yes")],  # type: ignore[arg-type]
    ],
)
def test_malformed_spans_are_refused_in_spanish(spans: list[CutSpan]) -> None:
    assert _texts(spans) == CUT_INVALID_TEXT


def test_every_kept_part_lasts_at_least_three_seconds() -> None:
    assert _texts([CutSpan(0, 2_999, True), CutSpan(2_999, 20_000, False)]) == PART_TOO_SHORT_TEXT
    # a short REMOVED span is fine
    assert validate_cut_spans([CutSpan(0, 1_000, False), CutSpan(1_000, 4_000, True)], 20_000)


def test_at_least_one_part_stays() -> None:
    assert _texts([]) == NO_PART_KEPT_TEXT
    assert _texts([CutSpan(0, 20_000, False)]) == NO_PART_KEPT_TEXT


def test_no_upper_bound_without_a_duration() -> None:
    assert validate_cut_spans([CutSpan(0, 90_000, True)], None) == ((0, 90_000),)


def test_the_key_depends_only_on_source_and_kept_spans() -> None:
    a = cut_idempotency_key(SOURCE, [(0, 4_000), (9_000, 20_000)])
    assert a == cut_idempotency_key(SOURCE, [(9_000, 20_000), (0, 4_000)])  # ordered
    assert a.startswith(f"cut:{SOURCE}:") and a.endswith(":gallery-cut-v1")
    assert len(a.split(":")[2]) == 64
    assert a != cut_idempotency_key(SOURCE, [(0, 4_000)])
    other = UUID("5a5a5a5a-0000-4000-8000-00000000c004")
    assert a != cut_idempotency_key(other, [(0, 4_000), (9_000, 20_000)])


def _job_row(segments: object, result: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        id=UUID(int=1),
        brand_id=UUID(int=2),
        kind="cut",
        status="queued",
        filename="cocina.mp4",
        attempts=0,
        last_error_code=None,
        source_media_id=SOURCE,
        result=result,
        created_at=datetime(2026, 11, 8, tzinfo=UTC),
        segments=segments,
    )


def test_a_cut_jobs_record_carries_its_kept_spans_and_the_source_length() -> None:
    """m-24976806: the screen says «Cortando tu video en N partes…» before the parts
    exist, and «Intentar de nuevo» asks for the same spans again."""
    record = _job_record(
        _job_row(
            [{"start_ms": 0, "end_ms": 8_000}, {"start_ms": 14_000, "end_ms": 20_000}],
            {"source_duration_ms": 20_000},
        )
    )
    assert record.segments == ((0, 8_000), (14_000, 20_000))
    assert record.source_duration_ms == 20_000
    # an ingest job (no segments) or a malformed row reads as «no spans», never a crash
    assert _job_record(_job_row(None, {})).segments == ()
    assert _job_record(_job_row([{"start": 1}], {})).segments == ()
    assert _job_record(_job_row([], {"source_duration_ms": "x"})).source_duration_ms is None
