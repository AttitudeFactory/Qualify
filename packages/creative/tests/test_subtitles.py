"""m-24828920: a talking video's subtitles — the script cut into lines and each one timed
on the voice. The spans below were MEASURED on a real video (2026-10-21: a Spanish
voice read the script, starting 1 s into the clip)."""

from __future__ import annotations

from qualify_creative.subtitles import (
    MAX_CHARS,
    chunk_script,
    timed_cues,
    voiced_spans,
)

SCRIPT = (
    "¿Tienes hambre? Esta es la smash doble de Nibbles. Dos carnes prensadas, queso "
    "fundido y pan brioche tostado. Pídela hoy por WhatsApp y te llega caliente en menos "
    "de treinta minutos."
)
#: Where the voice was, measured by `video.speech.voice_spans` on the real video.
MEASURED = [(1.28, 1.88), (2.76, 4.28), (5.22, 6.36), (6.86, 8.7), (9.66, 12.9)]


def test_the_script_is_cut_into_lines_a_viewer_reads_at_a_glance() -> None:
    lines = chunk_script(SCRIPT)
    assert lines == [
        "¿Tienes hambre?",
        "Esta es la smash doble de Nibbles.",
        "Dos carnes prensadas,",
        "queso fundido y pan brioche tostado.",
        "Pídela hoy por WhatsApp",
        "y te llega caliente",
        "en menos de treinta minutos.",
    ]
    assert all(len(line) <= MAX_CHARS for line in lines)
    assert " ".join(lines) == SCRIPT  # nothing dropped, nothing added


def test_a_long_phrase_is_cut_evenly_and_one_huge_word_stays_whole() -> None:
    lines = chunk_script("palabra " * 20)
    assert all(len(line) <= MAX_CHARS for line in lines)
    assert max(map(len, lines)) - min(map(len, lines)) <= len("palabra") + 1
    assert chunk_script("x" * 60) == ["x" * 60]
    assert chunk_script("   ") == []


def test_voice_is_what_is_near_the_loudest_and_short_gaps_do_not_split_it() -> None:
    quiet, loud = -80.0, -10.0
    # 0.02 s windows: 0.2 s silence, 0.4 s voice, a 0.1 s dip, 0.4 s voice, 0.6 s silence,
    # a 0.04 s click, 0.3 s silence, then voice again
    levels = (
        [quiet] * 10 + [loud] * 20 + [quiet] * 5 + [loud] * 20 + [quiet] * 30 + [loud] * 2
        + [quiet] * 15 + [loud] * 25
    )  # fmt: skip
    spans = voiced_spans(levels, 0.02)
    assert [(round(a, 2), round(b, 2)) for a, b in spans] == [(0.2, 1.1), (2.04, 2.54)]
    assert voiced_spans([], 0.02) == []


def test_each_sentence_starts_when_its_voice_does() -> None:
    """Measured: without anchoring each sentence on its pause, «Pídela…» showed 1 s before
    it was said; anchored, every sentence starts where the voice starts again."""
    cues = timed_cues(chunk_script(SCRIPT), MEASURED)
    starts = {cue.text: cue.start for cue in cues}
    assert starts["¿Tienes hambre?"] == 1.28
    assert starts["Esta es la smash doble de Nibbles."] == 2.76
    assert starts["Dos carnes prensadas,"] == 5.22
    assert starts["queso fundido y pan brioche tostado."] == 6.86
    assert starts["Pídela hoy por WhatsApp"] == 9.66
    # in order, never overlapping, nothing shown before the voice or long after it
    for before, after in zip(cues, cues[1:], strict=False):
        assert before.start < before.end <= after.start
    assert cues[-1].end <= MEASURED[-1][1] + 0.4 + 1e-9


def test_a_line_that_does_not_end_on_punctuation_is_shared_proportionally() -> None:
    cues = timed_cues(["aaaa bbbb", "cccc dddd"], [(0.0, 2.0)])
    assert [(c.start, round(c.end, 2)) for c in cues] == [(0.0, 1.0), (1.0, 2.4)]


def test_no_voice_means_no_subtitles() -> None:
    assert timed_cues(chunk_script(SCRIPT), []) == []
    assert timed_cues([], MEASURED) == []
