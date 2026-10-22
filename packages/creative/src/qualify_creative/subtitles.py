"""A talking video's subtitles (m-24828920): the script it reads, cut into lines a viewer
reads at a glance, each shown while it is being said.

We know WHAT is said (the script the voice read) but not WHEN each word is: neither Seed
Speech nor Seedance hands back timestamps. What the audio does tell is when there is a
voice and when there is a pause, and a voice pauses where the script has punctuation.
So a line that ends on punctuation is ANCHORED to the pause nearest to where it should
end, and between anchors the lines share the VOICED time in proportion to their length:
the pauses fall between lines, and an error in one sentence does not carry into the
next (measured 2026-10-21 on a real video: without anchors a line started 1 s early).

Pure: the audio is analysed by `video.speech.voice_spans`, which feeds `voiced_spans`
here with one loudness value per short window.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

#: The longest line a subtitle shows (two lines of ~21 characters on a phone).
MAX_CHARS = 42
#: Words a long phrase is best cut BEFORE ("Pídela por WhatsApp | y te llega caliente"),
#: and how many characters away from an even cut such a word still wins.
_BREAK_BEFORE = frozenset(
    "y e o u ni que pero porque para por con en sin desde hasta cuando donde como mientras"
    " and or but with for to".split()
)
_BREAK_BONUS = 12
#: Loudness windows (see `voiced_spans`): how far under the loudest window a window
#: still counts as voice, the shortest pause that separates two spans, and the
#: shortest span that is a voice and not a click.
SILENCE_DB = 30.0
MIN_PAUSE_SECONDS = 0.2
MIN_VOICE_SECONDS = 0.12
#: How far from its estimated time a pause may be and still anchor a line's end.
ANCHOR_SECONDS = 1.2
#: How long a line stays up after it was said, unless the next one starts first.
LINGER_SECONDS = 0.4

_SENTENCE = re.compile(r"(?<=[.!?…])\s+")
_CLAUSE = re.compile(r"(?<=[,;:])\s+")
_PAUSE_AFTER = tuple(",;:.!?…")

Span = tuple[float, float]


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


def _pack(words: Sequence[str], max_chars: int) -> list[str]:
    """`words` as lines of at most `max_chars` (one longer word stays whole), cut into
    parts of even length — before a joining word («y», «que», «por»…) when one is near."""
    lines: list[str] = []
    rest = list(words)
    while rest:
        remaining = " ".join(rest)
        if len(remaining) <= max_chars or len(rest) == 1:
            lines.append(remaining)
            break
        target = len(remaining) / math.ceil(len(remaining) / max_chars)
        best, best_score = 1, math.inf
        for cut in range(1, len(rest)):
            length = len(" ".join(rest[:cut]))
            if length > max_chars:
                break
            score = abs(length - target)
            if rest[cut].lower() in _BREAK_BEFORE:
                score -= _BREAK_BONUS
            if score < best_score:
                best, best_score = cut, score
        lines.append(" ".join(rest[:best]))
        rest = rest[best:]
    return lines


def chunk_script(script: str, max_chars: int = MAX_CHARS) -> list[str]:
    """The script as subtitle lines, in order: a sentence per line when it fits, else
    its clauses (cut at commas) grouped while they fit, else cut evenly between words.
    Nothing is dropped."""
    lines: list[str] = []
    for sentence in _SENTENCE.split(" ".join(script.split())):
        if not sentence:
            continue
        if len(sentence) <= max_chars:
            lines.append(sentence)
            continue
        group: list[str] = []
        for clause in _CLAUSE.split(sentence):
            if group and len(" ".join((*group, clause))) > max_chars:
                lines.extend(_pack(group, max_chars))
                group = []
            group.extend(clause.split())
        lines.extend(_pack(group, max_chars))
    return lines


def voiced_spans(levels_db: Sequence[float], window_seconds: float) -> list[Span]:
    """(start, end) in seconds of each stretch with a voice, from one loudness value
    (dBFS) per window: a window within `SILENCE_DB` of the loudest one is voice; voiced
    stretches closer than `MIN_PAUSE_SECONDS` are one; shorter than
    `MIN_VOICE_SECONDS`, a click, dropped."""
    if not levels_db:
        return []
    threshold = max(levels_db) - SILENCE_DB
    spans: list[Span] = []
    start: float | None = None
    for index, level in enumerate((*levels_db, float("-inf"))):
        t = index * window_seconds
        if level >= threshold and start is None:
            start = t
        elif level < threshold and start is not None:
            if spans and start - spans[-1][1] < MIN_PAUSE_SECONDS:
                spans[-1] = (spans[-1][0], t)
            else:
                spans.append((start, t))
            start = None
    return [(a, b) for a, b in spans if b - a >= MIN_VOICE_SECONDS]


def _at(spans: Sequence[Span], voiced: float, *, starting: bool) -> float:
    """The real time at which `voiced` seconds of voice have gone by. On the edge
    between two spans a line that STARTS there starts when the next span does."""
    for a, b in spans:
        length = b - a
        if voiced < length or (not starting and voiced <= length):
            return a + voiced
        voiced -= length
    return spans[-1][1]


def _spread(lines: Sequence[str], spans: Sequence[Span]) -> list[Cue]:
    """`lines` over the voiced time of `spans`, in proportion to their lengths."""
    total_voiced = sum(b - a for a, b in spans)
    total_chars = sum(len(line) for line in lines) or 1
    cues: list[Cue] = []
    said = 0
    for line in lines:
        before = total_voiced * said / total_chars
        said += len(line)
        after = total_voiced * said / total_chars
        cues.append(Cue(_at(spans, before, starting=True), _at(spans, after, starting=False), line))
    return cues


def timed_cues(lines: Sequence[str], spans: Sequence[Span]) -> list[Cue]:
    """Each line shown while it is said. A line ending on punctuation ends at the pause
    (a gap between two spans) nearest to its proportional estimate — within
    `ANCHOR_SECONDS`, and in order; between anchors the lines share the voiced time in
    proportion to their lengths. A line stays up `LINGER_SECONDS` after it ends unless
    the next one starts first. No voice → no cues."""
    if not lines or not spans:
        return []
    gaps = [((spans[i][1] + spans[i + 1][0]) / 2, i) for i in range(len(spans) - 1)]
    cues: list[Cue] = []
    first_line, first_span = 0, 0
    for index in range(1, len(lines)):
        if not lines[index - 1].endswith(_PAUSE_AFTER):
            continue
        # estimated from the last anchor on, so one sentence's error stays in it
        estimate = _spread(lines[first_line:], spans[first_span:])[index - 1 - first_line].end
        near = [(abs(mid - estimate), gap) for mid, gap in gaps if gap >= first_span]
        distance, gap = min(near, default=(math.inf, -1))
        if distance > ANCHOR_SECONDS:
            continue
        cues.extend(_spread(lines[first_line:index], spans[first_span : gap + 1]))
        first_line, first_span = index, gap + 1
    cues.extend(_spread(lines[first_line:], spans[first_span:]))
    for index, cue in enumerate(cues):
        limit = cues[index + 1].start if index + 1 < len(cues) else cue.end + LINGER_SECONDS
        cues[index] = Cue(cue.start, max(cue.end, min(cue.end + LINGER_SECONDS, limit)), cue.text)
    return cues
