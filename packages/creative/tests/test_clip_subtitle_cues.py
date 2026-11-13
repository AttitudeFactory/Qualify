"""A clip's copy as subtitles (founder, 2026-11-03: «como subtítulos»): the hook over the
opening, the CTA over the closing, never overlapping, nothing dropped."""

from __future__ import annotations

import pytest

from qualify_creative.subtitles import CLIP_TEXT_MIN_SECONDS, MAX_CHARS, clip_cues


@pytest.mark.parametrize("seconds", [4, 5, 8, 10, 15])
def test_the_hook_opens_and_the_cta_closes_without_overlap(seconds: float) -> None:
    cues = clip_cues("Rómpela con una Super Smash", "Pídela ya por WhatsApp", seconds)
    assert [c.text for c in cues] == [
        "Rómpela con una Super Smash",
        "Pídela ya por WhatsApp",
    ]
    hook, cta = cues
    assert 0 < hook.start < hook.end <= cta.start < cta.end < seconds
    if seconds >= 2 * CLIP_TEXT_MIN_SECONDS:
        assert hook.end - hook.start >= CLIP_TEXT_MIN_SECONDS - 0.5


def test_a_long_text_is_cut_into_lines_that_share_its_window() -> None:
    hook = "La smash más jugosa del barrio, con queso derretido y pan tostado en la plancha"
    cues = clip_cues(hook, "", 10)
    assert len(cues) > 1 and all(len(c.text) <= MAX_CHARS for c in cues)
    assert " ".join(c.text for c in cues) == hook
    assert all(a.end <= b.start + 1e-9 for a, b in zip(cues, cues[1:], strict=False))


def test_only_one_text_takes_its_own_window() -> None:
    (cta,) = clip_cues("", "Pide ya", 5)
    assert cta.end <= 5 and cta.start >= 0
    (hook,) = clip_cues("Gancho", "  ", 5)
    assert hook.start < 1


def test_no_text_or_no_length_has_no_cues() -> None:
    assert clip_cues("", "", 5) == []
    assert clip_cues("Gancho", "Pide ya", 0) == []


def test_a_hook_of_two_sentences_shows_them_in_turn_inside_its_window() -> None:
    cues = clip_cues("¿Rutina? Rómpela con una Super Smash", "Pídela ya", 5)
    assert [c.text for c in cues] == ["¿Rutina?", "Rómpela con una Super Smash", "Pídela ya"]
    assert cues[0].end <= cues[1].start and cues[1].end <= cues[2].start
