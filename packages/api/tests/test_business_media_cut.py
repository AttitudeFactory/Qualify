"""The Galería cut's request, offline (m-24955923, CM-3): span validation with the texts
the owner reads, and the idempotency key `cut:{source}:{sha256 of kept spans}:{version}`."""

from __future__ import annotations

from uuid import UUID

import pytest

from qualify_api.catalog.business_media import (
    CUT_INVALID_TEXT,
    NO_PART_KEPT_TEXT,
    PART_TOO_SHORT_TEXT,
    CutSpan,
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
