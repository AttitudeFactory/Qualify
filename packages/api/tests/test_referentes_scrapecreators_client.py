"""The transcript a reel listing already pays for, kept WITH its timings (VE-04b,
m-24921057, ADR 44) — offline: the vendor is a `MockTransport`, the consumption ledger a
recorder. The answer shapes are the CLI's: `just sc instagram media-transcript --url
https://www.instagram.com/reel/DeZIKSUNIea/ --cache-max-age 30d` (2026-11-05 and again
2026-11-06, a cached answer, 0 credits) gives `transcripts[].text` and, nested in each
entry, `transcripts[].transcript_with_timestamp[].start/end/text` in float seconds, plus
`credits_charged` / `cached` / `cached_at`. `LIVE_ANSWER` keeps that answer's keys and
timings with neutral text; the other answers vary it. No test calls the vendor.

What it pins, per the ticket's acceptance criteria:
1. the timings come from the SAME call (one request per transcript, as before) and the
   plain text is the one the untimed readers returned;
2. a `transcript_with_timestamp` answer gives stretches with start and end in seconds; a
   VTT with three cues gives three stretches;
3. a stretch of music heard as "ah" is kept as given — never dropped nor rewritten;
4. every PAID transcript leaves one consumption-ledger row with its credits (none for a
   free cached answer)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
import pytest

from qualify_api.referentes import reel_runs as rr
from qualify_api.referentes import reels as rd
from qualify_api.vendors import scrapecreators as sc
from qualify_api.vendors import usage

#: These tests exercise the vendor module itself: every paid read is charged to the
#: conftest's placeholder business (ADR 42 R5).
pytestmark = pytest.mark.usefixtures("paid_reads_charged")

URL = "https://www.instagram.com/reel/A/"
CAPTIONS = "https://v16-cla.tiktokcdn-eu.com/es"

#: The shape of `just sc instagram media-transcript --url <reel> --pretty` (m-24888194):
#: the musical sample of the inventory gave the single stretch "ah", 10.749–12.829.
TIMED_ANSWER: dict[str, Any] = {
    "success": True,
    "credits_charged": 1,
    "credits_remaining": 9_000,
    "cached": False,
    "transcripts": [{"id": "1", "text": "La salsa de trufa "}, {"id": "2", "text": None}],
    "transcript_with_timestamp": [
        {"start": 0.42, "end": 2.9, "text": "La salsa de trufa"},
        {"start": 10.749, "end": 12.829, "text": "ah"},
        {"start": "13.0", "end": 14.5, "text": " y listo "},
        {"start": 15.0, "end": 14.0, "text": "al revés"},  # end before start: left out
        {"start": None, "end": 16.0, "text": "sin inicio"},  # no start: left out
        {"start": 16.0, "end": 17.0, "text": ""},  # no text: left out
        "not a stretch",
    ],
}

#: The live answer of 2026-11-06 (see the docstring): its keys, ids and timings as the
#: vendor sent them; the sung lyrics replaced by neutral text.
LIVE_ANSWER: dict[str, Any] = {
    "success": True,
    "credits_remaining": 1393,
    "credits_charged": 0,
    "transcripts": [
        {
            "id": "4006269234755962778",
            "shortcode": "DeZIKSUNIea",
            "text": "uno dos tres",
            "transcript_with_timestamp": [
                {"start": 5.426, "end": 9.496, "text": "uno"},
                {"start": 10.966, "end": 15.56, "text": "dos"},
                {"start": 17.58, "end": 19.34, "text": "tres"},
            ],
        }
    ],
    "duration_seconds": 29.928,
    "duration_minutes": 0.5,
    "cached": True,
    "cached_at": "2026-11-05T15:34:40.000Z",
}

THREE_CUES = (
    "WEBVTT\n\n"
    "1\n00:00:00.660 --> 00:00:01.460\nDolores!\n\n"
    "NOTE not a cue\n\n"
    "c-2\n00:00:02.460 --> 00:00:05.160 align:start\nDolores, tus\nhot dogs.\n\n"
    "01:05.161 --> 01:06.000\nDolores, tus hot dogs.\n"
)


def _vendor(answer: dict[str, Any]) -> tuple[httpx.Client, list[dict[str, str]]]:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=answer)

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def _cdn(body: str) -> tuple[httpx.Client, list[str]]:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text=body)

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "test-key")


@pytest.fixture
def ledger() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    sc.configure_consumption_ledger(lambda **row: rows.append(row))
    return rows  # the repo-wide conftest restores the default afterwards


# --------------------------------------------------------------------------------------
# criterion 1 — the same calls, the same text
# --------------------------------------------------------------------------------------


def test_the_timings_come_from_the_same_single_call() -> None:
    client, seen = _vendor(TIMED_ANSWER)
    timed = sc.fetch_instagram_transcript_timed(URL, client=client)
    assert len(seen) == 1  # one request: the timings cost nothing more
    assert seen[0] == {"url": URL, "cache_max_age": sc.TRANSCRIPT_CACHE_DAYS}
    plain_client, plain_seen = _vendor(TIMED_ANSWER)
    assert sc.fetch_instagram_transcript(URL, client=plain_client) == timed.text
    assert len(plain_seen) == 1
    assert timed.text == "La salsa de trufa"  # what the untimed reader always returned
    assert timed.source == sc.TRANSCRIPT_VENDOR_STT


def test_an_answer_without_timings_still_gives_its_text() -> None:
    client, _ = _vendor({"success": True, "transcripts": [{"text": "hola"}]})
    timed = sc.fetch_instagram_transcript_timed(URL, client=client)
    assert (timed.text, timed.segments) == ("hola", ())


def test_listing_transcripts_makes_one_call_per_reel_as_before() -> None:
    """`transcribe_one` — what a listing fetches each transcript with — makes exactly one
    request per reel: one paid vendor call for Instagram, one free CDN read for TikTok."""
    vendor, vendor_seen = _vendor(TIMED_ANSWER)
    with usage.bind(vendor, usage.current()):
        got = rd.transcribe_one({"network": "instagram", "id": "A", "url": URL}, vendor)
    assert len(vendor_seen) == 1 and got.text == "La salsa de trufa" and len(got.segments) == 3
    cdn, cdn_seen = _cdn(THREE_CUES)
    tiktok = {"network": "tiktok", "id": "T", "url": "", "captionUrl": CAPTIONS}
    got = rd.transcribe_one(tiktok, cdn)
    assert cdn_seen == [CAPTIONS] and len(got.segments) == 3
    assert got.text == sc.vtt_text(THREE_CUES)


def test_a_plain_string_fetcher_still_works_and_claims_no_timings() -> None:
    plain = rd.as_transcript("  hola   qué tal ")
    assert (plain.text, plain.segments, plain.source) == ("hola qué tal", (), "")
    assert rr._timed_segments(plain) is None  # nothing read with timings: NULL, not []
    read = sc.Transcript(text="", source=sc.TRANSCRIPT_TIKTOK_VTT)
    assert rr._timed_segments(read) == []  # read, no stretch


# --------------------------------------------------------------------------------------
# criterion 2 — stretches with start and end; three cues, three stretches
# --------------------------------------------------------------------------------------


def test_transcript_with_timestamp_gives_stretches_in_seconds() -> None:
    client, _ = _vendor(TIMED_ANSWER)
    segments = sc.fetch_instagram_transcript_timed(URL, client=client).segments
    assert segments == (
        sc.Segment(start_s=0.42, end_s=2.9, text="La salsa de trufa"),
        sc.Segment(start_s=10.749, end_s=12.829, text="ah"),
        sc.Segment(start_s=13.0, end_s=14.5, text="y listo"),
    )


def test_the_live_answer_shape_gives_its_text_and_stretches(
    ledger: list[dict[str, Any]],
) -> None:
    """The answer as the vendor sent it (nested timings, a free cached answer): text and
    stretches from one call, and no consumption row — it cost 0 credits."""
    client, seen = _vendor(LIVE_ANSWER)
    timed = sc.fetch_instagram_transcript_timed(URL, client=client)
    assert len(seen) == 1
    assert timed.text == "uno dos tres"
    assert timed.segments == (
        sc.Segment(5.426, 9.496, "uno"),
        sc.Segment(10.966, 15.56, "dos"),
        sc.Segment(17.58, 19.34, "tres"),
    )
    assert ledger == []


def test_timings_nested_in_each_transcript_are_read_too() -> None:
    answer = {
        "success": True,
        "transcripts": [
            {"text": "hola", "transcript_with_timestamp": [{"start": 1, "end": 2, "text": "hola"}]}
        ],
    }
    assert sc.instagram_segments(answer) == (sc.Segment(1.0, 2.0, "hola"),)


def test_a_vtt_with_three_cues_gives_three_stretches() -> None:
    cues = sc.vtt_cues(THREE_CUES)
    assert cues == (
        sc.Segment(start_s=0.66, end_s=1.46, text="Dolores!"),
        sc.Segment(start_s=2.46, end_s=5.16, text="Dolores, tus hot dogs."),
        sc.Segment(start_s=65.161, end_s=66.0, text="Dolores, tus hot dogs."),
    )
    # the plain text reader is unchanged (it merges a repeated LINE, and the second cue
    # here spans two lines, so nothing repeats line for line)
    assert sc.vtt_text(THREE_CUES) == "Dolores! Dolores, tus hot dogs. Dolores, tus hot dogs."


def test_tiktok_captions_carry_their_cues() -> None:
    client, _ = _cdn(THREE_CUES)
    timed = sc.fetch_tiktok_captions_timed(CAPTIONS, client=client)
    assert len(timed.segments) == 3 and timed.source == sc.TRANSCRIPT_TIKTOK_VTT
    plain_client, _ = _cdn(THREE_CUES)
    assert sc.fetch_tiktok_captions(CAPTIONS, client=plain_client) == timed.text
    off_cdn = sc.fetch_tiktok_captions_timed("https://evil.example/x.vtt")
    assert (off_cdn.text, off_cdn.segments) == ("", ())


# --------------------------------------------------------------------------------------
# criterion 3 — music heard as "ah" is kept as given
# --------------------------------------------------------------------------------------


def test_a_music_only_stretch_is_kept_as_given() -> None:
    answer = {
        "success": True,
        "credits_charged": 1,
        "transcripts": [{"text": "ah"}],
        "transcript_with_timestamp": [{"start": 10.749, "end": 12.829, "text": "ah"}],
    }
    client, _ = _vendor(answer)
    timed = sc.fetch_instagram_transcript_timed(URL, client=client)
    assert timed.text == "ah"
    assert timed.segments == (sc.Segment(10.749, 12.829, "ah"),)
    # and it reaches the reel dict verbatim, as a plain {start, end, text}
    assert rr._timed_segments(timed) == [{"start": 10.749, "end": 12.829, "text": "ah"}]


# --------------------------------------------------------------------------------------
# criterion 4 — one consumption row per paid transcript
# --------------------------------------------------------------------------------------


def test_a_paid_transcript_leaves_one_consumption_row(
    ledger: list[dict[str, Any]], paid_reads_charged: UUID
) -> None:
    client, _ = _vendor({**TIMED_ANSWER, "credits_charged": 1})
    with usage.bind(client, usage.current()):
        sc.fetch_instagram_transcript_timed(URL, client=client)
    (row,) = ledger
    assert row["tenant_id"] == paid_reads_charged
    assert row["provider"] == "scrapecreators"
    assert row["operation"] == sc.FEATURE_REELS_TRANSCRIPT
    assert row["model_id"] == sc.TRANSCRIPT_LEDGER_MODEL
    assert row["metadata"] == {"credits": 1, "cached": False}
    assert row["cost_usd"] == usage.usd_per_credit() * 1
    assert row["pricing_table_version"] == usage.PRICING_TABLE_VERSION


def test_the_row_carries_what_the_vendor_charged(ledger: list[dict[str, Any]]) -> None:
    client, _ = _vendor({**TIMED_ANSWER, "credits_charged": 3})
    sc.fetch_instagram_transcript_timed(URL, client=client)
    assert ledger[0]["metadata"]["credits"] == 3
    assert ledger[0]["cost_usd"] == usage.usd_per_credit() * 3
    ledger.clear()
    silent, _ = _vendor({key: v for key, v in TIMED_ANSWER.items() if key != "credits_charged"})
    sc.fetch_instagram_transcript_timed(URL, client=silent)
    assert ledger[0]["metadata"]["credits"] == 1  # unsaid: what the gate booked


def test_a_free_cached_transcript_leaves_no_row(ledger: list[dict[str, Any]]) -> None:
    client, _ = _vendor({**TIMED_ANSWER, "credits_charged": 0, "cached": True})
    sc.fetch_instagram_transcript_timed(URL, client=client)
    assert ledger == []


def test_a_ledger_failure_never_loses_the_paid_answer() -> None:
    def broken(**_: Any) -> None:
        raise RuntimeError("database down")

    sc.configure_consumption_ledger(broken)
    client, _ = _vendor(TIMED_ANSWER)
    assert sc.fetch_instagram_transcript_timed(URL, client=client).text == "La salsa de trufa"


def test_the_row_carries_the_gate_request_key(ledger: list[dict[str, Any]]) -> None:
    """The row's `idempotency_key` is the gate's per-request key, so it reconciles with
    the credit booked in `vendor_usage_events` for the same call."""
    client, _ = _vendor(TIMED_ANSWER)
    sc.fetch_instagram_transcript_timed(URL, client=client)
    (row,) = ledger
    booked = [e for e in usage.store().events if e.feature == sc.FEATURE_REELS_TRANSCRIPT]
    assert row["idempotency_key"] == booked[-1].request_key
    assert row["idempotency_key"].startswith(f"{sc.FEATURE_REELS_TRANSCRIPT}:")
    client2, _ = _vendor(TIMED_ANSWER)
    sc.fetch_instagram_transcript_timed(URL, client=client2)
    assert ledger[1]["idempotency_key"] != row["idempotency_key"]  # one key per request


def test_a_cached_answer_that_reports_no_credits_leaves_no_row(
    ledger: list[dict[str, Any]],
) -> None:
    answer = {key: v for key, v in TIMED_ANSWER.items() if key != "credits_charged"}
    client, _ = _vendor({**answer, "cached": True})
    assert sc.fetch_instagram_transcript_timed(URL, client=client).text == "La salsa de trufa"
    assert ledger == []


# --------------------------------------------------------------------------------------
# WebVTT inline tags are not speech
# --------------------------------------------------------------------------------------

TAGGED_CUES = (
    "WEBVTT\n\n"
    "00:00:00.000 --> 00:00:02.000\n<v Ana>Hola, <c.yellow>Dolores</c></v>\n\n"
    "00:00:02.000 --> 00:00:04.000\n<i>tus</i> <00:00:02.500>hot dogs &amp; papas &lt;3\n\n"
    "00:00:04.000 --> 00:00:06.000\nah\n\n"
    "00:00:06.000 --> 00:00:07.000\n<v Ana></v>\n"
)


def test_vtt_inline_tags_are_stripped_and_music_is_kept() -> None:
    assert sc.vtt_cues(TAGGED_CUES) == (
        sc.Segment(0.0, 2.0, "Hola, Dolores"),
        sc.Segment(2.0, 4.0, "tus hot dogs & papas <3"),
        sc.Segment(4.0, 6.0, "ah"),
    )  # a cue that is only tags says nothing: left out
    # the card's plain text is what it was before VE-04b: `vtt_text` does not touch tags
    assert sc.vtt_text(TAGGED_CUES) == (
        "<v Ana>Hola, <c.yellow>Dolores</c></v> "
        "<i>tus</i> <00:00:02.500>hot dogs &amp; papas &lt;3 ah <v Ana></v>"
    )
