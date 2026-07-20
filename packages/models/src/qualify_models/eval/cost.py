from __future__ import annotations

from pydantic import BaseModel


class StageCost(BaseModel):
    stage: str
    usd_per_video: float | None  # None = required input, not documented anywhere yet
    documented: bool
    source: str
    note: str | None = None


class CostEstimate(BaseModel):
    stages: list[StageCost]
    total_usd_per_video: float | None  # None if any stage cost is undocumented
    total_usd_per_1k_videos: float | None
    caveats: list[str]


def estimate_cost(
    vlm_usd_per_video: float | None = None,
    asr_usd_per_video: float | None = None,
    filter_usd_per_video: float = 0.0,
    sentiment_usd_per_video: float = 0.0,
) -> CostEstimate:
    """Parametric per-video cost of the cascade.

    Deliberately does NOT invent absolute VLM/ASR rates: docs/modelos-multimodal-fase1.md
    and packages/models/NOTES_pain_signal_feasibility.md §5 only establish
    *relative* magnitudes (VLM F3 + ASR F1 dominate; the small CPU encoders are
    marginal). Pass measured/quoted VLM and ASR rates to get a real total;
    otherwise the total is None and the missing inputs are flagged as caveats.
    """
    stages = [
        StageCost(
            stage="filter",
            usd_per_video=filter_usd_per_video,
            documented=True,
            source="NOTES_pain_signal_feasibility.md §5 (self-hosted small CPU encoder, marginal)",
            note="siglip2-base zero-shot on CPU; treated as ~marginal when self-hosted",
        ),
        StageCost(
            stage="vision",
            usd_per_video=vlm_usd_per_video,
            documented=vlm_usd_per_video is not None,
            source="caller-supplied" if vlm_usd_per_video is not None else "UNDOCUMENTED",
            note="dominant cost driver (F3 VLM); no absolute $/video in the docs — REQUIRED INPUT",
        ),
        StageCost(
            stage="transcription",
            usd_per_video=asr_usd_per_video,
            documented=asr_usd_per_video is not None,
            source="caller-supplied" if asr_usd_per_video is not None else "UNDOCUMENTED",
            note="second cost driver (F1 whisper); no absolute $/video documented — REQUIRED INPUT",
        ),
        StageCost(
            stage="sentiment",
            usd_per_video=sentiment_usd_per_video,
            documented=True,
            source="NOTES_pain_signal_feasibility.md §5 (self-hosted CPU, marginal)",
            note="robertuito on CPU; treated as ~marginal when self-hosted",
        ),
    ]

    caveats: list[str] = []
    if vlm_usd_per_video is None:
        caveats.append(
            "VLM (F3) $/video is undocumented — pass vlm_usd_per_video from a quoted/measured rate."
        )
    if asr_usd_per_video is None:
        caveats.append(
            "ASR (F1) $/video is undocumented — pass asr_usd_per_video from a quoted/measured rate."
        )
    caveats.append(
        "filter/sentiment costs assume self-hosted CPU (~marginal); non-zero if bought per-call."
    )

    if any(s.usd_per_video is None for s in stages):
        total_per_video: float | None = None
        total_per_1k: float | None = None
    else:
        total_per_video = sum(s.usd_per_video for s in stages if s.usd_per_video is not None)
        total_per_1k = total_per_video * 1000

    return CostEstimate(
        stages=stages,
        total_usd_per_video=total_per_video,
        total_usd_per_1k_videos=total_per_1k,
        caveats=caveats,
    )
