"""EF-05 (Deivid, 2026-11-16, «Que el dueño elija»): the owner picks each text's fade in,
0.3 to 1.0 s, both included; 0.5 s when not chosen and for every text stored before."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from qualify_creative.schemas import (
    VIDEO_TEXT_FADE_DEFAULT_S,
    VIDEO_TEXT_FADE_MAX_S,
    VIDEO_TEXT_FADE_MIN_S,
    VideoTextLayer,
)


def test_the_limits() -> None:
    assert (VIDEO_TEXT_FADE_MIN_S, VIDEO_TEXT_FADE_DEFAULT_S, VIDEO_TEXT_FADE_MAX_S) == (
        0.3,
        0.5,
        1.0,
    )


@pytest.mark.parametrize("fade", [0.3, 0.5, 1.0])
def test_a_fade_inside_the_limits_is_kept(fade: float) -> None:
    assert VideoTextLayer(text="Hola", fade_s=fade).fade_s == fade


@pytest.mark.parametrize("fade", [0.29, 1.01, 0.0, -0.5])
def test_a_fade_outside_the_limits_is_refused(fade: float) -> None:
    with pytest.raises(ValidationError):
        VideoTextLayer(text="Hola", fade_s=fade)


def test_absent_reads_as_half_a_second_also_from_a_stored_text() -> None:
    assert VideoTextLayer(text="Hola").fade_s == 0.5
    stored = '{"text": "Hola", "place": "top", "start_s": 0, "end_s": null}'
    assert VideoTextLayer.model_validate_json(stored).fade_s == 0.5


def test_the_fade_round_trips() -> None:
    layer = VideoTextLayer(text="Hola", fade_s=0.8)
    assert layer.model_dump()["fade_s"] == 0.8
    assert VideoTextLayer.model_validate_json(layer.model_dump_json()) == layer
