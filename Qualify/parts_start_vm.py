"""«Armar mi video por partes» WITHOUT a reel on step 2 of a Clip (ADR 44 entry B,
m-24921079) — pure.

A Clip of one part is today's Clip. Under step 2 a card offers a longer video by parts;
tapped, it asks ONE question («¿De qué trata tu video?», filled with the product) and
offers two ways on:

- «Proponerme las partes»: Claude proposes 3 to 6 parts (`qualify_api.creative.parts_ai.
  propose_parts`) while a `progress_panel` «Armando tu propuesta» walks its three stages;
- «Prefiero armarlas yo»: two empty parts (`describe_it`), so `create_parts` holds them
  until the owner says what each one shows (UI-4's sheet).

Either way the sentence fills step 3 («Qué decir») so the owner never writes it twice.

This module holds everything about that card that is not I/O nor Reflex: its words, the
prefilled sentence, the progress stages, the rule that shows the card, and the plan as
the same ENTRIES `reel_parts_vm` keeps (`{key, plan, person, reason}`), so «Orden del
clip» lists, moves and removes these parts exactly like a reel's.

Copy: `docs/ux-video-por-planos.md` §3a (entry B) and §4 (`qualify-copy-es`).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from qualify_api.creative.parts_ai import (
    PROPOSE_RETRY_TEXT,
    STORY_MAX,
    PartsProposal,
    PartsProposalUnavailable,
    unavailable_text,
)
from qualify_creative.schemas import VideoPartPlan

from . import reel_parts_vm

# -- copy -------------------------------------------------------------------------------

#: The closed card, under what step 2 of a Clip shows today (§3a, entry B).
CARD_TITLE = "¿Quieres un video más largo?"
CARD_ACTION = "Armar mi video por partes"
CARD_HELP = "Te proponemos las partes con tu producto y tu marca. Las revisas antes de crear nada."

#: The one question, once the card is open.
QUESTION = "¿De qué trata tu video?"
QUESTION_HINT = "Ej.: «Qué tiene de especial y cómo conseguirlo»."
PROPOSE_LABEL = "Proponerme las partes"
MANUAL_LABEL = "Prefiero armarlas yo"
#: «Prefiero armarlas yo» is hidden (Deivid, 2026-11-10, option A): two empty parts are of
#: no use until UI-4's sheet lets the owner describe a part. Turn it on with UI-4; the
#: empty parts (`empty_entries`) and their empty state are ready for it.
MANUAL_PARTS_ENABLED = False
CLOSE_LABEL = "Ahora no"

#: The wait while Claude proposes (a `progress_panel`, never a spinner).
PROGRESS_TITLE = "Armando tu propuesta"
PROGRESS_STAGES: tuple[str, ...] = (
    "Pensando el comienzo",
    "Mostrando tu producto",
    "Cerrando con la invitación",
)
#: One proposal is a single call that reports no progress: the stages advance by time.
STAGE_SECONDS = 6
#: The bar creeps towards ~90 % over this long (one Sonnet call, at most one more turn).
PROGRESS_CREEP_SECONDS = 25

#: «Prefiero armarlas yo»: the parts are there, nothing says what they show yet (§4; the
#: body is UX's «te dejamos dos partes listas para llenar», `parts_ai`).
EMPTY_TITLE = "Tu video todavía no tiene partes."
EMPTY_BODY = "Te dejamos 2 partes para llenar: cuenta qué pasa en cada una y elige qué mostrar."

#: «Proponerme las partes» with nothing written.
STORY_MISSING_TEXT = "Cuéntanos de qué trata tu video para proponerte las partes."
#: The session ended between the tap and the call.
NO_SESSION_TEXT = "Tu sesión terminó. Vuelve a entrar para armar tu video."

# -- the card's phases ------------------------------------------------------------------

Phase = Literal["idle", "proposing", "ready", "error"]
PHASE_IDLE: Phase = "idle"
PHASE_PROPOSING: Phase = "proposing"
PHASE_READY: Phase = "ready"
PHASE_ERROR: Phase = "error"

#: How many empty parts «Prefiero armarlas yo» leaves (§3a: «abre 2 partes vacías»).
EMPTY_PARTS = 2
#: An empty part's length until the owner says otherwise (a part's default).
EMPTY_PART_SECONDS = 5


def card_shown(kind: str, *, from_reel: bool, has_plan: bool) -> bool:
    """The card is offered on a Clip only, when no plan is on screen and the piece does
    not come from «Hacer uno parecido» (that one has its reel's own plan and wait)."""
    return kind == "clip" and not from_reel and not has_plan


def initial_story(product_name: str, topic: str = "") -> str:
    """The question's prefilled sentence: what the owner already wrote in «Qué decir»
    when it says more than the product's name, otherwise the product's name."""
    name = " ".join((product_name or "").split())
    said = " ".join((topic or "").split())
    if said and said.casefold() != name.casefold():
        return said
    return name


def field_text(value: object) -> str:
    """What the field sent, as the card keeps it: text only (anything else is ""), at
    most `STORY_MAX` characters (what the proposal reads of it)."""
    return value[:STORY_MAX] if isinstance(value, str) else ""


def clean_story(text: object) -> str:
    """The sentence as it is sent and written into «Qué decir»: single-spaced, at most
    `STORY_MAX` characters."""
    return " ".join(field_text(text).split())[:STORY_MAX].strip()


def progress_steps(stage: int) -> list[dict[str, str]]:
    """The panel's stages (`progress_step_row`): those before `stage` done, `stage`
    running (the last one keeps running until the proposal comes), the rest pending."""
    last = len(PROGRESS_STAGES) - 1
    at = max(0, min(stage, last))
    return [
        {
            "title": title,
            "status": "done" if i < at else ("running" if i == at else "pending"),
        }
        for i, title in enumerate(PROGRESS_STAGES)
    ]


def next_stage(stage: int) -> int:
    """The stage after `stage`, never past the last."""
    return min(stage + 1, len(PROGRESS_STAGES) - 1)


# -- entries (the same shape as `reel_parts_vm.entries_from_plan`) ----------------------


def entries_from_parts(parts: Sequence[VideoPartPlan]) -> list[dict[str, Any]]:
    """No reel: nobody was seen (`person` False) and the form says it all («Nueva, con
    tu producto»), so there is no why line (`reason` "") — `reel_parts_vm`'s own entries."""
    return reel_parts_vm.entries_from_plan(None, parts)


def entries_from_proposal(proposal: PartsProposal) -> list[dict[str, Any]]:
    """Claude's plan as the state's entries, in order (every part `reference`, no reel)."""
    return entries_from_parts(proposal.parts)


def empty_parts() -> tuple[VideoPartPlan, ...]:
    """«Prefiero armarlas yo»: two new parts with nothing said yet. `describe_it` makes
    `create_parts` hold each one until its description is written."""
    return tuple(
        VideoPartPlan(mode="reference", seconds=EMPTY_PART_SECONDS, notices=("describe_it",))
        for _ in range(EMPTY_PARTS)
    )


def empty_entries() -> list[dict[str, Any]]:
    return entries_from_parts(empty_parts())


def plan_is_empty(entries: Sequence[dict[str, Any]]) -> bool:
    """No part says what it shows yet: the plan reads «Tu video todavía no tiene
    partes.» (a plan of no parts is «Orden del clip»'s own empty state, not this one)."""
    return bool(entries) and all(
        not str(e["plan"].get("description") or "").strip() for e in entries
    )


def provenance_json(proposal: PartsProposal) -> dict[str, Any]:
    """Who proposed the plan, as JSON for the parent's `MediaInputs.parts_provenance`."""
    return proposal.provenance.model_dump(mode="json")


def error_text(error: BaseException) -> str:
    """The owner's words for a proposal that did not come (`parts_ai`'s, the one source):
    a retry «en un minuto» only when the same request may work soon; anything unexpected
    reads as «try again»."""
    if isinstance(error, PartsProposalUnavailable):
        return unavailable_text(error)
    return PROPOSE_RETRY_TEXT
