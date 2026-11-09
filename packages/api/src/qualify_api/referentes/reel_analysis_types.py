"""The contract of a reel's shared analysis (ADR 44, m-24921056 VE-04a) — the types the
screen, the `reels-worker` and creative's `plan_from_analysis` (VE-08) agree on.

Pure types, no I/O: creative builds against these and the sample in
`packages/api/tests/fixtures/reel_analysis_sample.json` (`ReelAnalysis.from_dict`) before a
single real analysis exists. The analysis is GLOBAL (0119): nothing here names a business,
a brand or a user, and `ReelSource` carries no metrics, verdicts nor handle (V12 of the
backend handoff) — the extractor sees a public reel and nothing about who received it.

What is VE-04c's to fill: the per-shot `families` (the D3 families of m-24880680, each
`{status, value, evidence_frames}`) and the `reel_sheet` (hook, structure, closing, call to
action, style, tone). This contract only fixes their envelope: a mapping per shot and per
reel, versioned by `schema_version`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

#: Raise it when any of the four versions it stands for changes (prompt, sheet schema,
#: shot detector, frame sampling): a new version is a new row, an `ok` is never rewritten.
#: 2 (2026-11-05): VE-04c prompt 3 — on-screen text verbatim, emphasis marked, whole
#: quotes. 3: prompt 4 — the real look of an emphasis, reel-level fields point at a shot's
#: on-screen text instead of re-quoting it. 4: prompt 5 + schema 2 — hook and closing
#: carry the shot they happen in. 5: prompt 6 + schema 3 — burned-in subtitles kept out
#: of on-screen text; per-shot speech reconciled with the subtitles
#: (`reel_analysis_ai.ANALYSIS_VERSIONS`). 6: prompt 7 — on-screen text is only the text,
#: and speech goes to the shot it overlaps most. 7 (m-24955652): prompt 8 + schema 4 —
#: terse values, and the model describes groups of consecutive short shots (≤ 12) so the
#: sheet fits its output ceiling; the detected shots are still the ones stored. 8
#: (m-24955652): prompt 9 + schema 5 — people and faces are asked per FRAME and decided
#: per detected shot from its own frames (per group they over-called «person present»).
ANALYSIS_VERSION = 8

NETWORKS = ("instagram", "tiktok")

# Row state (0119 `ck_pra_status`) and the two answers `request_analysis` gives without a
# row: no usable video URL, or the platform's on-demand quota for today is spent.
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_OK = "ok"
STATUS_FAILED = "failed"
STATUS_NO_VIDEO = "no_video"
STATUS_DAILY_LIMIT = "daily_limit"

STAGE_DOWNLOADING = "downloading"
STAGE_DETECTING = "detecting"
STAGE_DESCRIBING = "describing"
STAGE_DONE = "done"

# The closed list of 0119 `ck_pra_error_code`.
ERROR_SOURCE_UNAVAILABLE = "source_unavailable"
ERROR_SOURCE_EXPIRED = "source_expired"
ERROR_SOURCE_TOO_LARGE = "source_too_large"
ERROR_SOURCE_UNREADABLE = "source_unreadable"
ERROR_MODEL_FAILED = "model_failed"
ERROR_CODES = (
    ERROR_SOURCE_UNAVAILABLE,
    ERROR_SOURCE_EXPIRED,
    ERROR_SOURCE_TOO_LARGE,
    ERROR_SOURCE_UNREADABLE,
    ERROR_MODEL_FAILED,
)

# 0119 `ck_pra_transcript_source` (same values as `public_reels.transcript_source`).
TRANSCRIPT_VENDOR = "vendor_stt"
TRANSCRIPT_TIKTOK = "tiktok_vtt"
TRANSCRIPT_NONE = "none"

OBSERVED = "observed"
NOT_OBSERVED = "not_observed"
UNKNOWN = "unknown"
OBSERVATIONS = (OBSERVED, NOT_OBSERVED, UNKNOWN)


@dataclass(frozen=True)
class TranscriptSegment:
    """One timed stretch of what the reel says, in seconds (VE-04b: Instagram's
    `transcript_with_timestamp`, TikTok's subtitle cues). `text` is what was heard, kept
    verbatim — a stretch of music heard as "ah" stays "ah"; it is never a script."""

    start_s: float
    end_s: float
    text: str


@dataclass(frozen=True)
class ReelSource:
    """A public reel as the analysis may read it: where it is, its words, its video URL.

    `video_url` is the signed CDN URL just read from the vendor — UNTRUSTED input: the
    worker only downloads it from the network's own CDN hosts, without redirects, and never
    logs it. `video_url_at` is when it was read (None = just now); past 20 h it is not used.
    No metrics, no verdict, no handle (V12): R4's `IdeaSource` is this type."""

    network: str
    post_id: str
    post_url: str
    video_url: str
    caption: str = ""
    transcript: str = ""
    transcript_segments: tuple[TranscriptSegment, ...] = ()
    transcript_source: str | None = None
    video_url_at: datetime | None = None

    def resolved_transcript_source(self) -> str:
        """The row's `transcript_source`: given, or inferred from how R4 transcribes each
        network (Instagram's paid STT, TikTok's free subtitles), `none` without text."""
        if self.transcript_source:
            return self.transcript_source
        if not (self.transcript or "").strip():
            return TRANSCRIPT_NONE
        return TRANSCRIPT_VENDOR if self.network == "instagram" else TRANSCRIPT_TIKTOK


@dataclass(frozen=True)
class AnalysisRef:
    """What asking for an analysis answers. `id` is None for `no_video` / `daily_limit`
    (no row was made); `reused` = an `ok` of the current version already existed."""

    id: UUID | None
    status: str
    reused: bool = False


@dataclass(frozen=True)
class AnalysisStatus:
    """What the screen polls (handoff §3). `retryable`: a `queued` row waiting to retry
    after a transient failure (`error_code` says which). `queue_ahead`: on-demand rows
    asked before this one still waiting. `fleet_paused`: the fleet's daily model-call cap
    is spent and this row waits for it. `source_available`: the stored source still
    exists (False once purged at 30 d, or never downloaded)."""

    analysis_id: UUID
    status: str
    stage: str | None
    error_code: str | None
    retryable: bool
    queued_for_s: float
    queue_ahead: int
    shots_found: int
    covered_to_s: float | None
    source_seconds: float | None
    source_available: bool
    fleet_paused: bool = False


@dataclass(frozen=True)
class ShotAnalysis:
    """One detected shot of an `ok` analysis (`public_reel_analysis_shots`)."""

    shot_index: int
    start_s: float
    end_s: float
    frame_keys: tuple[str, ...] = ()
    frame_times_s: tuple[float, ...] = ()
    people_presence: str = UNKNOWN
    visible_faces: str = UNKNOWN
    families: Mapping[str, Any] = field(default_factory=dict)
    spoken_text: str = ""

    @property
    def seconds(self) -> float:
        return self.end_s - self.start_s


@dataclass(frozen=True)
class AnalysisProvenance:
    """Rule 5: what produced the analysis, and what it cost (the row is the cost record —
    decision #10 of the epic: a shared analysis is nobody's, so it is not charged to a
    business's consumption ledger; Langfuse traces the model call)."""

    model_id: str
    model_revision: str | None
    prompt_version: str
    schema_version: str
    detector_version: str
    sampling_version: str
    sampling_params: Mapping[str, Any]
    source_sha256: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")


@dataclass(frozen=True)
class ReelAnalysis:
    """An `ok` analysis, as `plan_from_analysis` (VE-08) reads it. Immutable."""

    id: UUID
    network: str
    post_id: str
    analysis_version: int
    post_url: str
    source_seconds: float
    width: int
    height: int
    fps: float
    covered_from_s: float
    covered_to_s: float
    edit_eligible: bool
    source_available: bool
    transcript_text: str
    transcript_segments: tuple[TranscriptSegment, ...]
    transcript_source: str
    reel_sheet: Mapping[str, Any]
    shots: tuple[ShotAnalysis, ...]
    provenance: AnalysisProvenance
    finished_at: datetime

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready (the sample fixture's shape)."""
        p = self.provenance
        return {
            "id": str(self.id),
            "network": self.network,
            "post_id": self.post_id,
            "analysis_version": self.analysis_version,
            "post_url": self.post_url,
            "source_seconds": self.source_seconds,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "covered_from_s": self.covered_from_s,
            "covered_to_s": self.covered_to_s,
            "edit_eligible": self.edit_eligible,
            "source_available": self.source_available,
            "transcript": {
                "text": self.transcript_text,
                "segments": [
                    {"start_s": s.start_s, "end_s": s.end_s, "text": s.text}
                    for s in self.transcript_segments
                ],
                "source": self.transcript_source,
            },
            "reel_sheet": dict(self.reel_sheet),
            "shots": [
                {
                    "shot_index": s.shot_index,
                    "start_s": s.start_s,
                    "end_s": s.end_s,
                    "frame_keys": list(s.frame_keys),
                    "frame_times_s": list(s.frame_times_s),
                    "people_presence": s.people_presence,
                    "visible_faces": s.visible_faces,
                    "families": dict(s.families),
                    "spoken_text": s.spoken_text,
                }
                for s in self.shots
            ],
            "provenance": {
                "model_id": p.model_id,
                "model_revision": p.model_revision,
                "prompt_version": p.prompt_version,
                "schema_version": p.schema_version,
                "detector_version": p.detector_version,
                "sampling_version": p.sampling_version,
                "sampling_params": dict(p.sampling_params),
                "source_sha256": p.source_sha256,
                "input_tokens": p.input_tokens,
                "output_tokens": p.output_tokens,
                "cost_usd": str(p.cost_usd),
            },
            "finished_at": self.finished_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ReelAnalysis:
        transcript = data.get("transcript") or {}
        p = data["provenance"]
        return cls(
            id=UUID(str(data["id"])),
            network=data["network"],
            post_id=data["post_id"],
            analysis_version=int(data["analysis_version"]),
            post_url=data["post_url"],
            source_seconds=float(data["source_seconds"]),
            width=int(data["width"]),
            height=int(data["height"]),
            fps=float(data["fps"]),
            covered_from_s=float(data["covered_from_s"]),
            covered_to_s=float(data["covered_to_s"]),
            edit_eligible=bool(data["edit_eligible"]),
            source_available=bool(data["source_available"]),
            transcript_text=transcript.get("text", ""),
            transcript_segments=tuple(
                TranscriptSegment(float(s["start_s"]), float(s["end_s"]), s["text"])
                for s in transcript.get("segments", ())
            ),
            transcript_source=transcript.get("source", TRANSCRIPT_NONE),
            reel_sheet=dict(data.get("reel_sheet") or {}),
            shots=tuple(
                ShotAnalysis(
                    shot_index=int(s["shot_index"]),
                    start_s=float(s["start_s"]),
                    end_s=float(s["end_s"]),
                    frame_keys=tuple(s.get("frame_keys", ())),
                    frame_times_s=tuple(float(t) for t in s.get("frame_times_s", ())),
                    people_presence=s.get("people_presence", UNKNOWN),
                    visible_faces=s.get("visible_faces", UNKNOWN),
                    families=dict(s.get("families") or {}),
                    spoken_text=s.get("spoken_text", ""),
                )
                for s in data.get("shots", ())
            ),
            provenance=AnalysisProvenance(
                model_id=p["model_id"],
                model_revision=p.get("model_revision"),
                prompt_version=p["prompt_version"],
                schema_version=p["schema_version"],
                detector_version=p["detector_version"],
                sampling_version=p["sampling_version"],
                sampling_params=dict(p.get("sampling_params") or {}),
                source_sha256=p["source_sha256"],
                input_tokens=int(p.get("input_tokens", 0)),
                output_tokens=int(p.get("output_tokens", 0)),
                cost_usd=Decimal(str(p.get("cost_usd", "0"))),
            ),
            finished_at=datetime.fromisoformat(data["finished_at"]),
        )


__all__ = [
    "ANALYSIS_VERSION",
    "ERROR_CODES",
    "ERROR_MODEL_FAILED",
    "ERROR_SOURCE_EXPIRED",
    "ERROR_SOURCE_TOO_LARGE",
    "ERROR_SOURCE_UNAVAILABLE",
    "ERROR_SOURCE_UNREADABLE",
    "NETWORKS",
    "NOT_OBSERVED",
    "OBSERVATIONS",
    "OBSERVED",
    "STAGE_DESCRIBING",
    "STAGE_DETECTING",
    "STAGE_DONE",
    "STAGE_DOWNLOADING",
    "STATUS_DAILY_LIMIT",
    "STATUS_FAILED",
    "STATUS_NO_VIDEO",
    "STATUS_OK",
    "STATUS_QUEUED",
    "STATUS_RUNNING",
    "TRANSCRIPT_NONE",
    "TRANSCRIPT_TIKTOK",
    "TRANSCRIPT_VENDOR",
    "UNKNOWN",
    "AnalysisProvenance",
    "AnalysisRef",
    "AnalysisStatus",
    "ReelAnalysis",
    "ReelSource",
    "ShotAnalysis",
    "TranscriptSegment",
]
