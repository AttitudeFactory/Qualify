"""«Sigue a la anterior» after the owner's OWN video (m-25129406, ADR 50 §13) — the pure part.

Deivid (2026-11-26) decided to build «Sigue a la anterior» right after a video the owner
uploaded, behind `QUALIFY_CLIP_EXTEND_OWN_VIDEO` (off), and to turn it on only after a
PAID measurement he approves in session. Today the producer continues only a previous
part's own vendor file, byte for byte, because BytePlus accepts a face only in its own
unedited outputs (VE-13). The open questions this bench answers, with the smallest set:

1. Does Seedance 2.5 accept an owner's video as the source of an `extend` task, or refuse
   it (and with what error)? → three of the owner's videos: with a person's face, a
   product close-up without people, a place without people.
2. Does the continuation look like the same scene (light, framing, product)? → judged by
   Deivid and Herwin on a sheet, as `avatar_escena`.
3. What does it really cost (billed tokens with the input video) against the quote? →
   every task's cost from the task's usage, next to the price guard's estimate.

What the producer sends is reproduced exactly: the LAST seconds of the stretch (at most
`EXTEND_OWN_SOURCE_MAX_S`, cut by `cut_window`), `omni_reference_task_type="extend"`,
`ratio="adaptive"`, the part's 5 s, at the 2.5 draft (480p) — the cheapest — with the
same prompt family as a part. The quote comes from the adapter's OWN price guard over the
versioned pricing table (`estimate_cost_usd`), never a hand formula.

Nothing here reads a file or the network. The runner is
`packages/api/evals/extender_video_propio/run_experiment.py`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from qualify_api.creative.part_extend import EXTEND_OWN_SOURCE_MAX_S
from qualify_api.evals.avatar_scene_bench import (
    HARD_CEILING_USD,
    PlanItem,
    SpendRefused,
    fits_ceiling,
    mode_refusal,
    reserved,
    validate_max_usd,
)

BENCH_TICKET = "m-25129406"
BENCH_VERSION = 1
PROMPT_VERSION = "extender-propio-v1"
PRICING_VERSION = "v10"
SEEDANCE_MODEL = "dreamina-seedance-2-5-260628"
#: The part's seconds (`VideoPartPlan.seconds` default) — what the extend asks for.
PART_SECONDS = 5
#: The ceiling proposed for the paid run (Deivid approves the exact figure in session).
PROPOSED_MAX_USD = Decimal("3.10")
#: A placeholder public link for the dry run's adapter validation (never sent).
DRY_VIDEO_URL = "https://example.invalid/own-video.mp4"


@dataclass(frozen=True)
class Case:
    """One of the owner's videos the bench continues."""

    id: str
    #: What the video shows (for the sheet; the file is outside the repo).
    what: str
    #: What the continuation should do, in the prompt.
    action: str
    #: Whether a person's face is in it (question 1: BytePlus's face rule).
    face: bool


CASES: tuple[Case, ...] = (
    Case(
        "rostro",
        "Una persona del negocio mira a la cámara y muestra el producto",
        "the same person keeps showing the product to the camera and smiles",
        face=True,
    ),
    Case(
        "producto",
        "Primer plano del producto, sin personas",
        "the camera slowly moves closer to the same product, same light",
        face=False,
    ),
    Case(
        "lugar",
        "El local del negocio, sin personas",
        "the camera keeps panning across the same place, same light",
        face=False,
    ),
)
CASE_IDS = tuple(c.id for c in CASES)


def extend_prompt(case: Case) -> str:
    """The continuation's prompt, as a «Sigue a la anterior» part asks it: continue the
    video given, the same scene, no captions."""
    return (
        "Continue the reference video exactly where it ends: the same scene, the same "
        f"camera, the same light and colors. Then {case.action}. "
        "No captions, no subtitles, no logos, no watermark."
    )


def tail_seconds(source_seconds: float) -> float:
    """What of the owner's stretch is sent: its last seconds, at most
    `EXTEND_OWN_SOURCE_MAX_S` — whole seconds, as `cut_window` writes them."""
    import math

    return float(min(math.ceil(source_seconds - 1e-3), int(EXTEND_OWN_SOURCE_MAX_S)))


def extend_params(case: Case, *, video_url: str, input_seconds: float) -> dict[str, Any]:
    """`request.params` for `SeedanceVideoAdapter`, as the producer sends an `extend`
    part: one reference video, task type `extend`, `adaptive` ratio, the 2.5 draft."""
    from qualify_creative.adapters.byteplus_ark import DRAFT_RESOLUTION

    return {
        "model": SEEDANCE_MODEL,
        "prompt": extend_prompt(case),
        "reference_videos": [video_url],
        "reference_video_seconds": input_seconds,
        "omni_reference_task_type": "extend",
        "ratio": "adaptive",
        "duration_seconds": PART_SECONDS,
        "generate_audio": False,
        "draft": True,
        "resolution": DRAFT_RESOLUTION,
    }


def case_quote(case: Case, pricing: Any, input_seconds: float) -> Decimal:
    """The price guard's own estimate for the case (the adapter, the versioned table)."""
    from qualify_creative.adapters.byteplus_ark import SeedanceVideoAdapter
    from qualify_creative.enums import GenerationTask
    from qualify_creative.providers import GenerationRequest, RenderedPrompt

    request = GenerationRequest(
        task=GenerationTask.SCENE_VIDEO,
        rendered_prompt=RenderedPrompt("", "", ""),
        params=extend_params(case, video_url=DRY_VIDEO_URL, input_seconds=input_seconds),
    )
    return SeedanceVideoAdapter(model=SEEDANCE_MODEL).estimate_cost_usd(request, pricing)


def plan_items(cases: Sequence[Case], pricing: Any, seconds: Mapping[str, float]) -> list[PlanItem]:
    """One extend task per case, quoted with the tail of its video (`seconds`: case id →
    the stretch's length; a case without one is quoted at the most that is sent)."""
    return [
        PlanItem(
            "extender",
            c.id,
            case_quote(c, pricing, tail_seconds(seconds.get(c.id, EXTEND_OWN_SOURCE_MAX_S))),
        )
        for c in cases
    ]


def plan_totals(items: Sequence[PlanItem]) -> dict[str, str | int]:
    return {
        "tasks": len(items),
        "quote_usd": str(sum((i.quote_usd for i in items), Decimal(0))),
        "reserved_usd": str(sum((i.reserved_usd for i in items), Decimal(0))),
    }


__all__ = [
    "BENCH_TICKET",
    "BENCH_VERSION",
    "CASES",
    "CASE_IDS",
    "DRY_VIDEO_URL",
    "HARD_CEILING_USD",
    "PART_SECONDS",
    "PRICING_VERSION",
    "PROMPT_VERSION",
    "PROPOSED_MAX_USD",
    "SEEDANCE_MODEL",
    "Case",
    "PlanItem",
    "SpendRefused",
    "case_quote",
    "extend_params",
    "extend_prompt",
    "fits_ceiling",
    "mode_refusal",
    "plan_items",
    "plan_totals",
    "reserved",
    "tail_seconds",
    "validate_max_usd",
]
