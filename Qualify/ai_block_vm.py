"""The «parte con IA» block of the one editor (ED-07, m-25026638): its words and rules,
pure — no Reflex, no database, no network.

One editor (ADR 50 §13, plan `docs/plan-editor-unico-clip-partes.md` §2-§3): a block of
the Clip's «Fotos y videos» track is the owner's own photo or video, or a part made by
AI — a segment ``{"kind": "ai_part", "key": "ai_part:<n>", "start_s": 0, "end_s":
seconds, "speed": 1, "rotate": 0, "transition_in": …}`` whose entry ``media.ai_parts[n]``
is a `VideoPartPlan` unchanged. This module gives the screen (PR 6-8) what it draws for
such a block and what it says before the server refuses:

- the mode badge, short on the track and full in the panel, with the rule's reason
  (EF-09) or «Lo cambiaste tú.» (`mode_badge`);
- «¿Cómo la hacemos?» with why each option is off, mirroring the contract (`mode_options`);
- the seconds, whole from 1 to 10 (`clamp_seconds`, `seconds_control`);
- the block on the track: accessible name, its two lines and its state (`track_block`);
- the caps, said before the server's refusal (`add_reason`, `preflight_problems`);
- the cost of «Probar esta parte», of «Crear» on «Revisa y crea» and of «Rehacer esta
  parte» (`try_line`, `review_cost_lines`, `create_reason`, `redo_line`);
- building the block for «Agregar → Parte con IA» (`ai_part_key`, `new_ai_block`,
  `insert_ai_block`, `remove_ai_block`).

The server's contract is PR 1's (m-25129405, `docs/contrato-editor-unico.md`, on `main`
since f7d8c350), read here, never copied: the owner's words of each code come from
`ai_parts.ai_part_text`, the block's key from `qualify_creative.schemas.ai_part_key` and
`SourceSegment.ai_part_at`, the own material's seconds from `ai_parts.own_seconds`, the
guide's checks from `ai_parts.guide_problems` and every rule from `validate_recipe`
(`preflight_problems`). What stays here is only what the contract does not cover: the
3-60 s line in the editor's own words, the screen's caps before «Agregar», the cost lines
and the panel's words.

Words: the signed design m-25026602 (`docs/mockups/editor-unico/notas.md`, screens 01-05)
and the decisions Deivid signed on 2026-11-26 («bloque» stays where the screen already
says it, contract §3.3). What already exists is reused, never copied: `part_editor_vm`,
`part_progress_vm`, `part_review_vm`, `reel_parts_vm`, `clip_editor_vm` and EF-09's
`MODE_REASON_TEXTS`.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any, Final, cast
from uuid import UUID

from pydantic import ValidationError
from qualify_api.creative import media
from qualify_api.creative.part_progress import PartState
from qualify_api.creative.video_pipeline import ai_parts as contract_ai
from qualify_api.creative.video_pipeline import validate_recipe
from qualify_api.creative.video_pipeline.mode_choice import (
    MODE_REASON_TEXTS,
    MODE_RULE_VERSION,
    ModeReason,
    proposed_mode,
)
from qualify_creative import schemas
from qualify_creative.schemas import PART_GENERATION_MIN_SECONDS, VideoPartPlan

from . import clip_editor_vm, part_editor_vm, part_progress_vm, part_review_vm
from . import editor_preview_contract as contract
from . import reel_parts_vm as parts
from .ui import timeline_vm

# -- the block's shape (contract §2) ----------------------------------------------------

#: `SourceSegment.kind` of an AI block (`qualify_creative.schemas.AI_PART_KIND`).
AI_PART_KIND: Final = schemas.AI_PART_KIND
#: The block's `key` is not a file: `ai_part:<n>`, n = its entry in `media.ai_parts`.
AI_PART_KEY_PREFIX: Final = schemas.AI_PART_KEY_PREFIX

#: Seconds of an AI part before it is created: whole, 1 to 10 (Deivid, P5 = A).
SECONDS_MIN: Final = 1
SECONDS_MAX: Final = 10
#: «Agregar → Parte con IA» puts it with 5 s, or what fits up to 60 s (design D10).
SECONDS_DEFAULT: Final = 5

#: Contract §3 caps: blocks (`SEGMENTS_MAX`), AI children (`part_index` 1-6: AI parts +
#: character scenes + avatars), the Clip's 3-60 s, and 3 s of own material when the Clip
#: also carries scenes or avatars.
BLOCKS_MAX: Final = contract.SEGMENTS_MAX
AI_CHILDREN_MAX: Final = contract_ai.AI_CHILDREN_MAX
CLIP_MIN_SECONDS: Final = clip_editor_vm.LOCAL_MIN_SECONDS
CLIP_MAX_SECONDS: Final = clip_editor_vm.LOCAL_MAX_SECONDS
OWN_MEDIA_MIN_SECONDS: Final = contract_ai.OWN_MEDIA_MIN_S

# -- the contract's refusal texts (§3) --------------------------------------------------

#: The server's words for each code of the contract (`ai_parts.AI_PART_TEXTS`), read —
#: never copied: the screen says exactly what the server would.
AI_PART_TEXTS: Final[Mapping[str, str]] = contract_ai.AI_PART_TEXTS
#: Contract §3 «de siempre»: a guide file or photo of the entry that is not a business
#: path, or another business's — today's words of `media` for those codes.
KEY_TEXTS: Final[Mapping[str, str]] = {
    "malformed_key": media._BAD_KEY,
    "foreign_key": media._FOREIGN_FILE,
}


def refusal_text(code: str) -> str:
    """The owner's words for a refusal code of the contract (`ai_part_text`;
    `malformed_key` and `foreign_key` with today's words), "" for any other code."""
    return contract_ai.ai_part_text(code) or KEY_TEXTS.get(code, "")


# -- names ------------------------------------------------------------------------------

#: Design D1: on screen an AI block is «Parte con IA n», counted on its own, like «Foto n».
NAME = "Parte con IA {n}"
#: Its badge marks it (design §2: ✦ + mode word, never colour alone).
MARK = "✦"
#: The panel's head before creating (design 02).
NOT_CREATED_LINE = "Sin crear · gratis hasta «Crear»"
#: The mark on the preview while the playhead is on an AI part not created (design 01).
PREVIEW_MARK = "Parte con IA {n} · se crea al tocar «Crear»"
#: The live line of a timeline with AI parts not created yet (design 01).
FREE_UNTIL_CREATE = "Las partes con IA se crean al tocar «Crear». Hasta entonces, todo es gratis."
#: The live line after «Agregar → Parte con IA» (design 03B).
ADDED_LINE = "Pusiste una parte con IA. Cuéntanos qué pasa en ella."
#: Under «Fotos de tu producto» when the new part took the chosen product's photo (03B).
PRODUCT_PHOTO_NOTE = "Pusimos la foto de tu producto elegido. Puedes cambiarla."
#: «¿Cómo la hacemos?» without a reel: one form, shown as a fact (design 03B).
NO_REEL_MODE_TEXT = (
    "Sin un reel de inspiración, la parte se hace nueva. «Igual al original» aparece "
    "cuando tu video nace de un reel."
)
#: «Siguiente» waits for the description (design D10, 02B).
MISSING_DESCRIPTION = "Falta contar qué pasa en la parte con IA {n}."
#: «Probar esta parte» waits for the description too (design 02B).
TRY_NEEDS_DESCRIPTION = "Cuéntanos qué pasa en esta parte para probarla."


def ai_part_name(n: int) -> str:
    """«Parte con IA 1» — `n` counts the AI parts only, 1-based, in track order."""
    return NAME.format(n=n)


def missing_description_line(n: int) -> str:
    """«Falta contar qué pasa en la parte con IA 2.» — beside «Siguiente»."""
    return MISSING_DESCRIPTION.format(n=n)


_PART_N = re.compile(r"\b([Ll]a) parte (\d+)\b")


def with_ai_name(text: str) -> str:
    """Design D16: the words of `part_progress_vm` / `part_review_vm` with «la parte n»
    turned into «la parte con IA n» — in the one editor «parte 3» is no longer the
    third block of the track. «La parte 1 está para revisar.» → «La parte con IA 1 está
    para revisar.»"""
    return _PART_N.sub(r"\1 parte con IA \2", text)


# -- the mode badge (design D4, D7) -----------------------------------------------------

#: The short badge on the track (Deivid, P8 = A): «Nueva» covers the three «Nueva, …».
MODE_SHORT: Final[Mapping[str, str]] = {
    "reference": "Nueva",
    "edit": "Igual al original",
    "extend": parts.FORM_EXTEND,
}
#: The owner changed the rule's proposal (design D7, ticket ED-07).
CHANGED_BY_OWNER = "Lo cambiaste tú."
#: …and the way back to it (design D7).
BACK_TO_PROPOSED = "Volver a lo que te propusimos"


def proposal_of(plan: Mapping[str, Any]) -> str:
    """The mode the rule proposed for this entry ("" when none did: a plan from before
    the rule, a merged part, one without a stored reason)."""
    return (
        proposed_mode(int(plan.get("mode_rule_version") or 0), str(plan.get("mode_reason") or ""))
        or ""
    )


def changed_by_owner(plan: Mapping[str, Any]) -> bool:
    """The owner chose a mode other than the rule's: the stored flag, or a mode that is
    not the one the stored reason proposed (the panel changes the mode before anything
    recomputes the flag)."""
    if plan.get("mode_changed_by_owner"):
        return True
    proposed = proposal_of(plan)
    return bool(proposed) and proposed != plan.get("mode")


def mode_reason_text(plan: Mapping[str, Any]) -> str:
    """The why line under «¿Cómo la hacemos?»: «Lo cambiaste tú.» when the owner changed
    it, else EF-09's `MODE_REASON_TEXTS[mode_reason]`, "" when no rule proposed it.

    Unlike `reel_parts_vm._rule_text` (the old list, limited to three reasons until «the
    new editor», Deivid 2026-11-14), this IS that editor: every reason is said."""
    if changed_by_owner(plan):
        return CHANGED_BY_OWNER
    if not proposal_of(plan):
        return ""
    return MODE_REASON_TEXTS[cast(ModeReason, plan.get("mode_reason"))]


def mode_badge(plan: Mapping[str, Any], *, has_product: bool = True) -> dict[str, str]:
    """The mode as the track and the panel show it: `short` («Nueva»), `full` («Nueva,
    inspirada en el original», `reel_parts_vm.form_label`), `reason` (`mode_reason_text`),
    `changed` ("1" when the owner changed it: the reason line takes the pencil icon and
    «Volver a lo que te propusimos») and `back_to` (the proposed mode for that button)."""
    mode = str(plan.get("mode") or "reference")
    changed = changed_by_owner(plan)
    return {
        "mode": mode,
        "short": MODE_SHORT.get(mode, MODE_SHORT["reference"]),
        "full": parts.form_label(plan, has_product=has_product),
        "reason": mode_reason_text(plan),
        "changed": "1" if changed else "",
        "back_to": proposal_of(plan) if changed else "",
        "back_label": BACK_TO_PROPOSED if changed else "",
    }


# -- «¿Cómo la hacemos?» (contract §3 rules, design D8) ---------------------------------


def _kind(segment: Mapping[str, Any] | None) -> str:
    return str((segment or {}).get("kind") or "video")


def has_reel_window(plan: Mapping[str, Any]) -> bool:
    """«Igual al original» changes a window of the analysed reel: it needs both the
    analysis and its cuts (`edit_needs_reel_window`)."""
    return bool(plan.get("analysis_id")) and bool(plan.get("shot_indexes"))


def _entry_of(
    segments: Sequence[Mapping[str, Any]], ai_parts: Sequence[Mapping[str, Any]], at: int
) -> Mapping[str, Any] | None:
    """The entry the AI block at `at` points to (None: not an AI block, or a key that
    points nowhere — `ai_parts_mismatch` says that one)."""
    if not 0 <= at < len(segments) or not is_ai_block(segments[at]):
        return None
    entry_at = ai_part_at(str(segments[at].get("key") or ""))
    return ai_parts[entry_at] if entry_at is not None and entry_at < len(ai_parts) else None


def same_moment(entry: Mapping[str, Any], previous: Mapping[str, Any]) -> bool:
    """Contract §3.2: an `extend` entry the plan split from one long take of the reel
    (`original_mode` «extend»), of the same reel as the AI part before it, starting on
    that part's last cut (`parts_plan._editable_match`, `check_extend_parts`)."""
    cuts = list(entry.get("shot_indexes") or ())
    before = list(previous.get("shot_indexes") or ())
    return (
        entry.get("original_mode") == "extend"
        and entry.get("analysis_id") is not None
        and entry.get("analysis_id") == previous.get("analysis_id")
        and bool(cuts)
        and bool(before)
        and cuts[0] == before[-1]
    )


def extend_code(
    segments: Sequence[Mapping[str, Any]],
    ai_parts: Sequence[Mapping[str, Any]],
    at: int,
    entry: Mapping[str, Any] | None = None,
) -> str:
    """The contract's code why the AI block at `at` cannot be «Sigue a la anterior», ""
    when it can (§3.2, v1). Seedance continues the vendor file of the AI part right
    before — never an owner's photo or video:

    - nothing before (the first block): `extend_needs_block_before`;
    - an own photo or video before: `extend_after_own_media`;
    - an AI part before, but not the same moment of the reel: `extend_not_same_moment`.

    `entry`: the entry as it would be (the panel asks before changing the mode); None
    reads it from `ai_parts`. An AI key that points nowhere says nothing here."""
    if at <= 0:
        return "extend_needs_block_before"
    before = segments[at - 1] if at - 1 < len(segments) else {}
    if not is_ai_block(before):
        return "extend_after_own_media"
    previous = _entry_of(segments, ai_parts, at - 1)
    current = entry if entry is not None else _entry_of(segments, ai_parts, at)
    if previous is None or current is None:
        return ""
    return "" if same_moment(current, previous) else "extend_not_same_moment"


def extend_reason(
    segments: Sequence[Mapping[str, Any]],
    ai_parts: Sequence[Mapping[str, Any]],
    at: int,
    *,
    extend_on: bool,
    entry: Mapping[str, Any] | None = None,
) -> str:
    """Why «Sigue a la anterior» cannot be chosen for the AI block at `at` (0-based), ""
    when it can: switched off (`part_editor_vm.EXTEND_REASON`, as today — nothing on
    the screen fixes it, so it is said first), else the contract's words of
    `extend_code`. `extend_on` is `part_extend.extend_available()`, read by the caller
    (this module reads no switch)."""
    if not extend_on:
        return part_editor_vm.EXTEND_REASON
    code = extend_code(segments, ai_parts, at, entry)
    return AI_PART_TEXTS[code] if code else ""


def edit_reason(
    entry: Mapping[str, Any],
    *,
    images: Sequence[Mapping[str, str]] = (),
    videos: Sequence[Mapping[str, str]] = (),
    audios: Sequence[Mapping[str, str]] = (),
    durations: Mapping[str, float | None] | None = None,
) -> str:
    """Why «Igual al original» cannot be chosen, "" when it can. Without the reel's
    window, the contract's words (`edit_needs_reel_window`); with it, today's reasons of
    `part_editor_vm.edit_reason` (someone is seen, under 4 s, no product photo…).
    `entry` is the state's entry: ``{"plan": …, "person": …, "reason": …}``."""
    if not has_reel_window(entry.get("plan") or {}):
        return AI_PART_TEXTS["edit_needs_reel_window"]
    return part_editor_vm.edit_reason(
        entry, images=images, videos=videos, audios=audios, durations=durations or {}
    )


def mode_options(
    entry: Mapping[str, Any],
    segments: Sequence[Mapping[str, Any]],
    ai_parts: Sequence[Mapping[str, Any]],
    at: int,
    *,
    extend_on: bool,
    has_product: bool = True,
    images: Sequence[Mapping[str, str]] = (),
    videos: Sequence[Mapping[str, str]] = (),
    audios: Sequence[Mapping[str, str]] = (),
    durations: Mapping[str, float | None] | None = None,
) -> list[dict[str, str]]:
    """The three ways of «¿Cómo la hacemos?» for the AI block at `at` (0-based in
    `segments`; `entry` is the state's ``{"plan": …, "person": …}`` of its `ai_parts`
    entry): `mode`, `label` (full), `short`, `help`, `reason` (why it is off, ""
    = it can be chosen; an option that is off stays focusable, `aria-disabled`, design
    D8) and `chosen` ("1" for the entry's mode). «Nueva» is never off."""
    plan = entry.get("plan") or {}
    from_reel = bool(plan.get("analysis_id"))
    person = bool(entry.get("person")) or entry.get("reason") == parts.REASON_UNCLEAR
    mode = str(plan.get("mode") or "reference")
    if from_reel:
        new_label = parts.FORM_INSPIRED
    else:
        new_label = parts.FORM_NEW if has_product else parts.FORM_NEW_BRAND
    rows = [
        {
            "mode": "edit",
            "label": parts.FORM_EDIT,
            "help": part_editor_vm.EDIT_HELP,
            "reason": edit_reason(
                entry, images=images, videos=videos, audios=audios, durations=durations
            ),
        },
        {
            "mode": "reference",
            "label": new_label,
            "help": part_editor_vm.REFERENCE_HELP
            if from_reel and person
            else part_editor_vm.NEW_HELP,
            "reason": "",
        },
        {
            "mode": "extend",
            "label": parts.FORM_EXTEND,
            "help": part_editor_vm.EXTEND_HELP,
            "reason": extend_reason(segments, ai_parts, at, extend_on=extend_on, entry=plan),
        },
    ]
    for row in rows:
        row["short"] = MODE_SHORT[row["mode"]]
        row["chosen"] = "1" if row["mode"] == mode else ""
    return rows


# -- «Video o audio tuyo» (contract §3.1, Deivid P9 = A) --------------------------------

#: The file types a guide may be — the ones the producer sends (contract §3.1).
GUIDE_VIDEO_SUFFIXES: Final = contract_ai.GUIDE_VIDEO_SUFFIXES
GUIDE_AUDIO_SUFFIXES: Final = contract_ai.GUIDE_AUDIO_SUFFIXES
#: Where it lives in the panel (Deivid, P9 = A) and its name today.
MORE_OPTIONS = "Más opciones"
GUIDE_LABEL = part_editor_vm.MORE_LABEL
#: Only «Nueva» takes a guide: in any other mode, today's words of the part editor
#: (`part_editor_vm.save_reason`).
GUIDE_NEEDS_NEW = "Para usar tu video o audio, elige hacer esta parte nueva."


def guide_option(mode: str) -> dict[str, str]:
    """«Más opciones → Video o audio tuyo» for an AI part in `mode`: `shown` "1" only in
    «Nueva» (`reference`, contract §3.1); otherwise `reason` says how to get it. The
    type refuses a guide in «Sigue a la anterior», and «Igual al original»'s one video
    is the reel's window: the screen never writes either (`with_mode` drops it)."""
    shown = mode == "reference"
    return {
        "shown": "1" if shown else "",
        "section": MORE_OPTIONS,
        "label": GUIDE_LABEL,
        "reason": "" if shown else GUIDE_NEEDS_NEW,
    }


def with_mode(plan: Mapping[str, Any], mode: str) -> dict[str, Any]:
    """The entry in another mode. Leaving «Nueva» drops the guide (`clip_video_keys` /
    `clip_audio_keys`) before anything is saved: the type would not read it (§3.1)."""
    out = {**plan, "mode": mode}
    if mode != "reference":
        out["clip_video_keys"] = []
        out["clip_audio_keys"] = []
    return out


#: A tenant id that owns nothing: an unreadable one is never the business's.
_NO_TENANT = UUID(int=0)


def _tenant(tenant_id: UUID | str | None) -> UUID | None:
    if tenant_id is None or isinstance(tenant_id, UUID):
        return tenant_id
    try:
        return UUID(str(tenant_id))
    except ValueError:
        return _NO_TENANT


def _plan(entry: Mapping[str, Any]) -> VideoPartPlan | None:
    """An entry as the type reads it (None: it cannot — `preflight_problems` says so)."""
    try:
        return VideoPartPlan.model_validate(dict(entry))
    except ValidationError:
        return None


def guide_problems(
    entry: Mapping[str, Any], entry_at: int, tenant_id: UUID | str | None = None
) -> list[dict[str, str]]:
    """The guide of `ai_parts[entry_at]` (and its photos), by the contract's
    `ai_parts.guide_problems`: a video `.mp4`/`.mov` and an audio `.mp3`/`.wav`
    (`ai_part_guide_type`); with a `tenant_id`, every file is the business's
    (`malformed_key` / `foreign_key`, today's words; an unreadable id owns nothing).
    ``{"code", "field", "text"}`` in field order; an entry the type cannot read says
    nothing here. How long each file lasts is read when the part is made, as today."""
    plan = _plan(entry)
    if plan is None:
        return []
    found = contract_ai.guide_problems(plan, entry_at, _tenant(tenant_id))
    return [_problem(p.code, p.field or "") for p in found]


# -- seconds (whole, 1-10; design D9) ---------------------------------------------------

#: The panel's control (design 02).
SECONDS_LABEL = "Cuánto dura en tu video"
#: ED-07: before «Crear» its seconds change here only (whole seconds; the track's handles
#: of an AI part come with its trim after creating, PR 8).
SECONDS_HELP = "De 1 a 10 s."
MINUS_LABEL = "− 1 s"
PLUS_LABEL = "+ 1 s"
#: Design D9 / 02B: a part under 4 s is made at 4 and uses 4 s of the month.
SHORT_PART_NOTE = (
    f"Se crea de {PART_GENERATION_MIN_SECONDS} s y usa {PART_GENERATION_MIN_SECONDS} s de "
    "tu mes. Cuando esté lista, eliges qué {n} s usar arrastrando sus barras."
)
#: Why «− 1 s» / «+ 1 s» is off. «Tu video pasaría de 60 s.» is the design's (03D);
#: the 1 s and 10 s ones are proposed here (pending ux-designer).
MINUS_OFF = "Una parte con IA dura al menos 1 s."
PLUS_OFF_MAX = "Una parte con IA dura 10 s como máximo."
PLUS_OFF_CLIP = "Tu video pasaría de 60 s."


def clamp_seconds(raw: object, *, default: int = SECONDS_DEFAULT) -> int:
    """Whole seconds from 1 to 10 out of whatever came (a drag's float, a typed string):
    rounded to the nearest whole second, then clamped; unreadable → `default`."""
    try:
        value = float(str(raw).strip().replace(",", "."))
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value):
        return default
    return max(SECONDS_MIN, min(SECONDS_MAX, math.floor(value + 0.5)))


def seconds_text(seconds: int) -> str:
    """«5 s» — the control's value and the block's second line."""
    return f"{seconds} s"


def short_part_note(seconds: int) -> str:
    """The line under the control for a part under 4 s, "" otherwise."""
    if seconds >= PART_GENERATION_MIN_SECONDS:
        return ""
    return SHORT_PART_NOTE.format(n=seconds)


def seconds_control(seconds: int, clip_seconds: float) -> dict[str, str]:
    """The «Cuánto dura en tu video» control: `value`, `text`, `help`, why «− 1 s» /
    «+ 1 s» is off ("" = on) and the short-part `note`. `clip_seconds` is how long the
    whole video lasts now, this part included: one more second may not pass 60 s."""
    value = clamp_seconds(seconds)
    if value >= SECONDS_MAX:
        plus = PLUS_OFF_MAX
    elif clip_seconds + 1 > CLIP_MAX_SECONDS + 1e-6:
        plus = PLUS_OFF_CLIP
    else:
        plus = ""
    return {
        "value": str(value),
        "text": seconds_text(value),
        "label": SECONDS_LABEL,
        "help": SECONDS_HELP,
        "minus_reason": MINUS_OFF if value <= SECONDS_MIN else "",
        "plus_reason": plus,
        "note": short_part_note(value),
    }


# -- the block on the track (design §2) -------------------------------------------------

#: `data-ai-state` of the block: today's `PartState` plus `plan` (not created yet).
STATE_PLAN: Final = "plan"
_STATE_KEYS: Final[Mapping[PartState, str]] = {
    PartState.UNMADE: STATE_PLAN,
    PartState.QUEUED: "queued",
    PartState.CREATING: "creating",
    PartState.TO_REVIEW: "review",
    PartState.READY: "ready",
    PartState.FAILED: "failed",
    PartState.ORIGINAL_REFUSED: "refused",
    PartState.REDO: "redo",
    PartState.EXPIRED: "expired",
}
#: The states whose block shows its poster (the reel's or the product's, dimmed); the
#: others show the part's own frame (design §2, «Estados»).
POSTER_STATES: Final = frozenset({STATE_PLAN, "queued", "creating", "failed", "refused"})
#: The states that keep the handles on (before creating: seconds, 1 s; made: the trim,
#: ½ s, free).
SECONDS_HANDLES: Final = frozenset({STATE_PLAN})
TRIM_HANDLES: Final = frozenset({"review", "ready"})


def state_of(state: PartState | str | None) -> PartState:
    """A `PartState` from what the provider gives (None / "" / unknown = not created)."""
    if isinstance(state, PartState):
        return state
    try:
        return PartState(str(state or ""))
    except ValueError:
        return PartState.UNMADE


def _clock(seconds: float) -> str:
    # m-25129389: the track's times read to the tenth, as the styleguide's AI block
    return timeline_vm.clock_tenth(seconds)


def track_block(
    n: int,
    plan: Mapping[str, Any],
    *,
    start_s: float,
    state: PartState | str | None = None,
    poster: str = "",
    frame: str = "",
    detail: str = "",
    has_product: bool = True,
) -> dict[str, str]:
    """The AI block of the «Fotos y videos» track as strings (for `rx.foreach`):

    - `name` «Parte con IA 1»; `badge` (short mode word) and `full` (panel, aria);
    - `line` — the second line: «Parte con IA 1 · 5 s» before creating, the state's word
      after («En fila», «Creando», «Lista», «No salió»…);
    - `state` (`data-ai-state`), `state_word`, `tone` (`signal_pill`: `STATE_TONES`);
    - `picture` — the poster before it is made (and while queued, creating or failed),
      its own frame once made; `dimmed` "1" for the poster;
    - `aria` — the whole sentence: «Parte con IA 1, Nueva, de 0:06 a 0:11, sin crear»;
    - `detail` — why it failed (or what it waits for), with «la parte con IA n»
      (`with_ai_name`); the caller passes `part_progress_vm`'s line;
    - `handles` — `seconds` (1 s steps), `trim` (½ s, free) or "" (being made / failed).

    `start_s` is where the block starts in the video; its end is `start_s + seconds`."""
    seconds = clamp_seconds(plan.get("seconds"))
    part_state = state_of(state)
    key = _STATE_KEYS[part_state]
    word = part_progress_vm.STATE_WORDS[part_state]
    name = ai_part_name(n)
    made = key != STATE_PLAN
    badge = mode_badge(plan, has_product=has_product)
    picture = poster if key in POSTER_STATES or not frame else frame
    span = f"de {_clock(start_s)} a {_clock(start_s + seconds)}"
    if key in SECONDS_HANDLES:
        handles = "seconds"
    elif key in TRIM_HANDLES:
        handles = "trim"
    else:
        handles = ""
    return {
        "name": name,
        "mark": MARK,
        "badge": badge["short"],
        "full": badge["full"],
        "line": word if made else f"{name} · {seconds_text(seconds)}",
        "seconds": str(seconds),
        "state": key,
        "state_word": word,
        "tone": part_progress_vm.STATE_TONES[part_state],
        "picture": picture,
        "dimmed": "1" if picture and picture == poster and key in POSTER_STATES else "",
        "aria": f"{name}, {badge['short']}, {span}, {word.lower()}",
        "detail": with_ai_name(detail),
        "handles": handles,
    }


def announcement(n: int, state: PartState | str | None) -> str:
    """The ONE live line when an AI part changes state: `part_progress_vm.ANNOUNCE` with
    «la parte con IA n» (design D16): «La parte con IA 1 está para revisar.»"""
    return with_ai_name(part_progress_vm.ANNOUNCE[state_of(state)].format(n=n))


# -- caps, said before the server refuses (contract §3, design D22) ---------------------


def _float(value: Any) -> float:
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def is_ai_block(segment: Mapping[str, Any]) -> bool:
    return _kind(segment) == AI_PART_KIND


def block_seconds(segment: Mapping[str, Any]) -> float:
    """How long a block lasts in the video: its stretch at its speed (an AI block is
    always ×1; a photo, from 0 to `end_s`)."""
    speed = _float(segment.get("speed")) or 1.0
    return max(_float(segment.get("end_s")) - _float(segment.get("start_s")), 0.0) / speed


def _join_seconds(segment: Mapping[str, Any]) -> float:
    use = segment.get("transition_in") or {}
    if not isinstance(use, Mapping):
        return 0.0
    return _float((use.get("params") or {}).get("duration_s"))


def laid_seconds(segments: Sequence[Mapping[str, Any]]) -> float:
    """The blocks laid end to end (what 60 s is judged against)."""
    return sum(block_seconds(s) for s in segments)


def clip_seconds(segments: Sequence[Mapping[str, Any]]) -> float:
    """The length the server judges against 3-60 s (`clip_editor_vm.judged_length`):
    laid end to end, unless what comes out once the joins overlap is under 3 s."""
    laid = laid_seconds(segments)
    joined = laid - sum(_join_seconds(s) for at, s in enumerate(segments) if at > 0)
    return clip_editor_vm.judged_length(laid, joined)


#: The fields of a `SourceSegment` (a timeline's block may carry more of the screen's).
_SEGMENT_FIELDS: Final = frozenset(schemas.SourceSegment.model_fields)


def _segment(segment: Mapping[str, Any]) -> schemas.SourceSegment:
    """A block as the contract's type reads it (`ValidationError` when it cannot)."""
    data = {k: v for k, v in segment.items() if k in _SEGMENT_FIELDS and v is not None}
    return schemas.SourceSegment.model_validate(data)


def _segments(segments: Sequence[Mapping[str, Any]]) -> tuple[schemas.SourceSegment, ...]:
    """The blocks the type can read, in order (one it cannot is left out)."""
    out: list[schemas.SourceSegment] = []
    for segment in segments:
        try:
            out.append(_segment(segment))
        except ValidationError:
            continue
    return tuple(out)


def own_seconds(segments: Sequence[Mapping[str, Any]]) -> float:
    """How long the owner's OWN photos and videos last (never an AI block), by the
    contract's `ai_parts.own_seconds`."""
    return contract_ai.own_seconds(_segments(segments))


def ai_block_count(segments: Sequence[Mapping[str, Any]]) -> int:
    return sum(1 for s in segments if is_ai_block(s))


#: «Agregar → Parte con IA» off, its reason above the «+» (design 03D). 8 blocks is
#: today's ED-12 line (AI parts count as videos); 6 and 60 s are the design's.
FULL_AI_LINE = (
    f"Tu video ya tiene {AI_CHILDREN_MAX} partes con IA, el máximo. Quita una para agregar otra."
)
SCENES_COUNT_LINE = "Las escenas con personaje también cuentan."
FULL_SECONDS_LINE = (
    f"Tu video ya dura {int(CLIP_MAX_SECONDS)} s, el máximo. "
    "Acorta o quita una parte para agregar otra."
)
#: The live line when less than 5 s were left (design 03D).
ONLY_LEFT_LINE = "Solo quedaban {n} s: la parte nueva dura {n} s."


def room_seconds(segments: Sequence[Mapping[str, Any]]) -> int:
    """Whole seconds a new AI part may last without passing 60 s (0 to 10)."""
    room = math.floor(CLIP_MAX_SECONDS - laid_seconds(segments) + 1e-6)
    return max(0, min(SECONDS_MAX, room))


def new_part_seconds(segments: Sequence[Mapping[str, Any]]) -> int:
    """5 s, or what fits up to 60 s (design D10); 0 when not even 1 s fits."""
    return min(SECONDS_DEFAULT, room_seconds(segments))


def only_left_line(segments: Sequence[Mapping[str, Any]]) -> str:
    """«Solo quedaban 3 s: la parte nueva dura 3 s.» — "" when 5 s fit (or none)."""
    seconds = new_part_seconds(segments)
    return ONLY_LEFT_LINE.format(n=seconds) if 0 < seconds < SECONDS_DEFAULT else ""


def add_reason(segments: Sequence[Mapping[str, Any]], *, other_ai_children: int = 0) -> str:
    """Why «Agregar → Parte con IA» is off ("" = on), before any refusal: 8 blocks
    (`clip_editor_vm.FULL_LINE`), 6 AI children (+ «Las escenas con personaje también
    cuentan.» when scenes or avatars take some), no second left under 60 s.
    `other_ai_children`: character scenes + avatars (`ai_parts.ai_children_of`)."""
    if len(segments) >= BLOCKS_MAX:
        return clip_editor_vm.FULL_LINE
    if ai_block_count(segments) + other_ai_children >= AI_CHILDREN_MAX:
        return f"{FULL_AI_LINE} {SCENES_COUNT_LINE}" if other_ai_children else FULL_AI_LINE
    if room_seconds(segments) < SECONDS_MIN:
        return FULL_SECONDS_LINE
    return ""


def _problem(code: str, field: str, text: str = "") -> dict[str, str]:
    return {"code": code, "field": field, "text": text or refusal_text(code)}


def preflight_problems(
    segments: Sequence[Mapping[str, Any]],
    ai_parts: Sequence[Mapping[str, Any]],
    *,
    other_ai_children: int = 0,
    tenant_id: UUID | str | None = None,
) -> list[dict[str, str]]:
    """What the server would refuse in this Clip's AI blocks, said first and free:
    ``{"code", "field", "text"}`` in the contract's codes and fields (`segments[i]`,
    `ai_parts[n]`) with its words verbatim. The judge is the contract itself —
    `validate_recipe((part,), video_by_parts=False, ai_parts=…, other_ai_children=…)`, as
    contract §4 says — and this keeps of its answer what is the AI blocks' (the codes of
    `AI_PART_TEXTS`, the guide's files) plus the 3-60 s rule counting them
    (`local_length_out_of_range`, in `clip_editor_vm`'s words). The rest of the recipe
    (the joins, the own videos) is `clip_editor_vm.recipe_problem`'s, as before.

    Only what the type cannot even read stays a layer of its own: more than 8 blocks
    (`too_many_blocks`, the contract's defence — the type refuses 9 before any rule) and
    a block or an entry the type refuses (`ai_parts_mismatch`: «quítala y agrégala de
    nuevo»; the screen never writes one). `ai_parts` are the entries (`VideoPartPlan` as
    JSON); `tenant_id` also checks that each entry's guide files and photos are the
    business's. `[]` when there is no AI block and no entry. With
    `QUALIFY_CLIP_AI_PARTS` off the contract answers only `switched_off`."""
    blocks = [at for at, s in enumerate(segments) if is_ai_block(s)]
    if not blocks and not ai_parts:
        return []
    if len(segments) > BLOCKS_MAX:
        return [_problem("too_many_blocks", "segments")]
    broken: list[dict[str, str]] = []
    typed: list[schemas.SourceSegment] = []
    for at, segment in enumerate(segments):
        try:
            typed.append(_segment(segment))
        except ValidationError:
            broken.append(_problem("ai_parts_mismatch", f"segments[{at}]"))
    entries: list[VideoPartPlan] = []
    for entry_at, entry in enumerate(ai_parts):
        plan = _plan(entry)
        if plan is None:
            broken.append(_problem("ai_parts_mismatch", f"ai_parts[{entry_at}]"))
        else:
            entries.append(plan)
    if broken:
        return broken
    laid = sum(s.output_seconds for s in typed)
    part = schemas.PartRecipe(index=1, mode="local", seconds=max(laid, 0.1), segments=typed)
    problems = validate_recipe(
        (part,),
        video_by_parts=False,
        tenant_id=_tenant(tenant_id),
        ai_parts=tuple(entries),
        other_ai_children=other_ai_children,
    )
    found: list[dict[str, str]] = []
    for problem in problems:
        field = problem.field or ""
        if problem.code == "local_length_out_of_range":
            seconds = problem.duration_s if problem.duration_s is not None else laid
            text = clip_editor_vm.length_out_of_range_line(float(seconds))
            found.append(_problem(problem.code, field, text))
        elif problem.code in AI_PART_TEXTS or (
            problem.code in KEY_TEXTS and field.startswith("ai_parts")
        ):
            found.append(_problem(problem.code, field))
    return found


# -- cost (design D11-D13, D17) ---------------------------------------------------------

#: The panel's button (Deivid, P7 = A).
TRY_LABEL = "Probar esta parte"
#: Pinned to it, no dialog (design D11, 04B).
TRY_COST = "Usa 1 vista previa. {left} Las demás las creas con «Crear»."
#: …when the month's balance is not wired (never a block: the service still refuses).
TRY_COST_NO_COUNT = "Usa 1 vista previa. Las demás las creas con «Crear»."
#: After it: the part is «En fila» / «Creando» and the owner keeps building (04B).
TRY_STARTED_LINE = "Estamos creando la parte con IA {n}. Puedes seguir armando tu video."
#: The panel of a part being made (04B).
CREATING_NOTE = (
    "Tarda unos minutos. Te avisamos aquí cuando esté; mientras, puedes cambiar el resto "
    "de tu video."
)
CREATING_LOCKED = "Mientras se crea, su descripción y sus fotos no se pueden cambiar."
#: The panel of a created part: «Rehacer esta parte», folded (design D17).
REDO_LABEL = "Rehacer esta parte"
REDO_CONFIRM_LABEL = "Crear otra versión"
REDO_MODE_NOTE = "Cambiar la forma también crea una versión nueva."
REDO_KEEPS_NOTE = "La versión de ahora no se pierde: la puedes volver a usar con «Ver la anterior»."
TRIM_FREE_NOTE = (
    "Para usar otro pedazo de esta parte, arrastra sus barras en la línea de tiempo. Es gratis."
)

#: «Revisa y crea» (design D12, 04A): the two spends, each with when it happens.
#: Its heading (design 04A).
REVIEW_TITLE = "Lo que usa de tu mes"
NOW_HEAD = "Ahora, al crear"
LATER_HEAD = "Después, al aprobar"
NOT_COUNTED_LINE = "Si una parte no sale, no se descuenta su vista previa."


def _left_sentence(previews_left: int) -> str:
    return "Te queda 1." if previews_left == 1 else f"Te quedan {previews_left}."


def no_previews_text(renews: str = "") -> str:
    """No vista previa left this month (`part_review_vm`'s words)."""
    return (
        part_review_vm.NO_PREVIEWS_TEXT.format(renews=renews)
        if renews
        else part_review_vm.NO_PREVIEWS_SOON_TEXT
    )


def try_line(
    plan: Mapping[str, Any], *, previews_left: int, previews_quota: int, renews: str = ""
) -> tuple[str, str]:
    """«Probar esta parte»: (the cost line, why the button is off — "" = on). The
    description comes first (02B); with no vista previa left, the month's words; no quota
    wired: the line without the count, never a block (the service still refuses)."""
    reason = "" if str(plan.get("description") or "").strip() else TRY_NEEDS_DESCRIPTION
    if previews_quota <= 0:
        return TRY_COST_NO_COUNT, reason
    if previews_left <= 0:
        text = no_previews_text(renews)
        return text, reason or text
    return TRY_COST.format(left=_left_sentence(previews_left)), reason


def redo_line(*, previews_left: int, previews_quota: int, renews: str = "") -> tuple[str, bool]:
    """«Rehacer esta parte»: (the cost line, no vista previa left). Today's words
    verbatim: «Usa 1 vista previa. Te quedan {n}.» (`part_review_vm.CHANGE_USE_TEXT`)."""
    if previews_quota <= 0:
        return part_review_vm.CHANGE_NOTE, False
    if previews_left <= 0:
        return no_previews_text(renews), True
    return part_review_vm.CHANGE_USE_TEXT.format(p=previews_left), False


def _own_words(photos: int, videos: int) -> tuple[str, bool]:
    """(«tus fotos y tu video», several things) — what costs nothing, as 04A says it."""
    said: list[str] = []
    if photos:
        said.append("tu foto" if photos == 1 else "tus fotos")
    if videos:
        said.append("tu video" if videos == 1 else "tus videos")
    return " y ".join(said), len(said) > 1 or photos > 1 or videos > 1


def _own_counts(segments: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    photos = sum(1 for s in segments if _kind(s) == "photo")
    videos = sum(1 for s in segments if _kind(s) == "video")
    return photos, videos


def ai_seconds_used(entries: Sequence[Mapping[str, Any]]) -> int:
    """The month's seconds the AI parts use at approval: each part's seconds, a 1-3 s
    part counted as 4 (`PART_GENERATION_MIN_SECONDS`). Own blocks use none."""
    return sum(max(clamp_seconds(e.get("seconds")), PART_GENERATION_MIN_SECONDS) for e in entries)


def _short_note(entries: Sequence[Mapping[str, Any]]) -> str:
    short = [clamp_seconds(e.get("seconds")) for e in entries]
    short = [s for s in short if s < PART_GENERATION_MIN_SECONDS]
    if not short:
        return ""
    floor = PART_GENERATION_MIN_SECONDS
    if len(short) == 1:
        return f" (la de {short[0]} s cuenta como {floor})"
    return f" (las de menos de {floor} s cuentan como {floor})"


def review_cost_lines(
    segments: Sequence[Mapping[str, Any]],
    entries: Sequence[Mapping[str, Any]],
    *,
    previews_left: int,
    previews_quota: int,
    seconds_left: int,
    seconds_quota: int,
) -> dict[str, str]:
    """«Lo que usa de tu mes» on «Revisa y crea» (design D12, 04A), the two spends apart:

    - `now`: «Ahora, al crear: 2 vistas previas, una por cada parte con IA. Te quedan
      12. Tus fotos y tu video no gastan nada.»
    - `later`: «Después, al aprobar: 9 s de video, solo los de las partes con IA (la de
      3 s cuenta como 4). Este mes te quedan 40 s.»
    - `not_counted`: «Si una parte no sale, no se descuenta su vista previa.»
    - `foot`: the short line beside «Crear»: «Usa 2 vistas previas. Te quedan 12.»

    All "" without AI parts (an own-material Clip costs nothing here). A quota of 0 (none
    wired) leaves its count out, never blocks."""
    count = len(entries)
    if count <= 0:
        return {"now": "", "later": "", "not_counted": "", "foot": ""}
    if count == 1:
        spend, use = "1 vista previa, la de tu parte con IA", "Usa 1 vista previa."
    else:
        spend = f"{count} vistas previas, una por cada parte con IA"
        use = f"Usa {count} vistas previas."
    left = f" {_left_sentence(previews_left)}" if previews_quota > 0 and previews_left > 0 else ""
    own, many = _own_words(*_own_counts(segments))
    free = f" {own[0].upper()}{own[1:]} no {'gastan' if many else 'gasta'} nada." if own else ""
    used = ai_seconds_used(entries)
    which = "los de las partes con IA" if count > 1 else "los de la parte con IA"
    month = ""
    if seconds_quota > 0:
        month = (
            " Este mes te queda 1 s."
            if seconds_left == 1
            else f" Este mes te quedan {max(seconds_left, 0)} s."
        )
    return {
        "now": f"{NOW_HEAD}: {spend}.{left}{free}",
        "later": f"{LATER_HEAD}: {used} s de video, solo {which}{_short_note(entries)}.{month}",
        "not_counted": NOT_COUNTED_LINE,
        "foot": f"{use}{left}",
    }


def create_reason(
    segments: Sequence[Mapping[str, Any]],
    entries: Sequence[Mapping[str, Any]],
    *,
    previews_left: int,
    previews_quota: int,
    renews: str = "",
) -> tuple[str, str]:
    """Why «Crear» is off for the vistas previas (body, foot) — ("", "") when the month
    pays them (or no quota is wired). At 0 (design D13, 04C): «Crear tu video usa 2
    vistas previas, y ya usaste tus 15 de este mes. Vuelven el 1 de diciembre.» plus the
    free way out when there is own material («Si lo quieres hoy, quita las 2 partes con
    IA: con tus fotos y tu video se crea gratis.»). Short of some: how many to take out
    or when they come back. Feet: `reel_parts_vm`'s."""
    count = len(entries)
    if count <= 0 or previews_quota <= 0 or count <= previews_left:
        return "", ""
    uses = "usa 1 vista previa" if count == 1 else f"usa {count} vistas previas"
    day = renews or "próximo mes"
    if previews_left <= 0:
        body = f"Crear tu video {uses}, y ya usaste tus {previews_quota} de este mes. " + (
            f"Vuelven el {renews}." if renews else "Vuelven el próximo mes."
        )
        own, _many = _own_words(*_own_counts(segments))
        if own:
            which = "la parte con IA" if count == 1 else f"las {count} partes con IA"
            body += f" Si lo quieres hoy, quita {which}: con {own} se crea gratis."
        return body, parts.FOOT_NO_PREVIEWS
    drop = count - previews_left
    remove = "Quita 1 parte con IA" if drop == 1 else f"Quita {drop} partes con IA"
    left = "te queda 1" if previews_left == 1 else f"te quedan {previews_left}"
    body = (
        f"Crear tu video {uses} y este mes {left}. {remove}, prueba una sola o espera al "
        f"{day}, cuando vuelven tus {previews_quota} vistas previas."
    )
    return body, parts.FOOT_SHORT


# -- building the block («Agregar → Parte con IA», design D10) --------------------------


def ai_part_key(n: int) -> str:
    """The block's key for `media.ai_parts[n]` (0-based): the contract's
    `schemas.ai_part_key`, for a whole place from 0 only (the screen never asks for
    another)."""
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        raise ValueError(f"an AI part's place is a whole number from 0, not {n!r}")
    return schemas.ai_part_key(n)


def ai_part_at(key: str) -> int | None:
    """The entry an AI block's key points to, None when it is not an AI key: the
    contract's `SourceSegment.ai_part_at` of an AI block with that key."""
    try:
        block = schemas.SourceSegment(kind=AI_PART_KIND, key=key or "-", start_s=0, end_s=1)
    except ValidationError:
        return None
    return block.ai_part_at


def new_ai_block(
    n: int,
    *,
    seconds: int = SECONDS_DEFAULT,
    image_keys: Sequence[str] | None = None,
    description: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The (segment, entry) pair of a new AI part whose entry goes at `ai_parts[n]`:
    the segment as contract §2 (`start_s` 0, `end_s` = seconds, `speed` 1, `rotate` 0,
    no join) and the entry as a `VideoPartPlan` dumped to JSON — «Nueva» by the rule
    (`no_source`, so its reason line says «Nueva, con tu producto.»), with the chosen
    product's photos (`image_keys`; None = the brief's). `seconds` is clamped to 1-10."""
    whole = clamp_seconds(seconds)
    plan = VideoPartPlan(
        mode="reference",
        seconds=whole,
        description=description.strip(),
        clip_image_keys=tuple(image_keys) if image_keys is not None else None,
        mode_rule_version=MODE_RULE_VERSION,
        mode_reason="no_source",
    )
    segment: dict[str, Any] = {
        "kind": AI_PART_KIND,
        "key": ai_part_key(n),
        "start_s": 0,
        "end_s": whole,
        "speed": 1,
        "rotate": 0,
        "transition_in": None,
    }
    return segment, plan.model_dump(mode="json")


def insert_ai_block(
    segments: Sequence[Mapping[str, Any]],
    ai_parts: Sequence[Mapping[str, Any]],
    at: int,
    *,
    image_keys: Sequence[str] | None = None,
    other_ai_children: int = 0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """«Agregar → Parte con IA»: the new block put at track place `at` (clamped; the
    playhead's block), its entry appended to `ai_parts` (no other key changes), with 5 s
    or what fits (`new_part_seconds`). Returns (segments, ai_parts, place) — the place is
    -1 and nothing changes when `add_reason` says it does not fit. A block put first
    loses nothing: only its own `transition_in` is None."""
    out_segments = [dict(s) for s in segments]
    out_parts = [dict(p) for p in ai_parts]
    if add_reason(segments, other_ai_children=other_ai_children):
        return out_segments, out_parts, -1
    segment, entry = new_ai_block(
        len(out_parts), seconds=new_part_seconds(segments), image_keys=image_keys
    )
    place = max(0, min(at, len(out_segments)))
    out_segments.insert(place, segment)
    out_parts.append(entry)
    return out_segments, out_parts, place


def remove_ai_block(
    segments: Sequence[Mapping[str, Any]], ai_parts: Sequence[Mapping[str, Any]], at: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """«Quitar» on the AI block at track place `at`: the block and its entry go, and the
    keys of the later entries move down one (each block keeps pointing at its own entry:
    contract §2, one block per entry). The new first block loses its join (never on the
    first block). Anything else at `at`: unchanged copies."""
    out_segments = [dict(s) for s in segments]
    out_parts = [dict(p) for p in ai_parts]
    if not 0 <= at < len(out_segments) or not is_ai_block(out_segments[at]):
        return out_segments, out_parts
    entry_at = ai_part_at(str(out_segments[at].get("key") or ""))
    del out_segments[at]
    if entry_at is not None and entry_at < len(out_parts):
        del out_parts[entry_at]
        for segment in out_segments:
            other = ai_part_at(str(segment.get("key") or "")) if is_ai_block(segment) else None
            if other is not None and other > entry_at:
                segment["key"] = ai_part_key(other - 1)
    if out_segments:
        out_segments[0]["transition_in"] = None
    return out_segments, out_parts


def ai_numbers(segments: Sequence[Mapping[str, Any]]) -> dict[int, int]:
    """Track place → «Parte con IA n» number (1-based, AI blocks only, in track order)."""
    out: dict[int, int] = {}
    for at, segment in enumerate(segments):
        if is_ai_block(segment):
            out[at] = len(out) + 1
    return out


# -- on the Clip's timeline (ED-07: the state's shapes) ---------------------------------
#
# The state keeps each AI part as ``{"uid": …, "plan": <VideoPartPlan as JSON>}`` in
# `CreativeState.clip_ai_parts` — in that order they are `media.ai_parts`, so the block of
# entry `n` is `ai_part:<n>` — and its place in the Clip's order of files
# (`clip_sequence`) as a token ``ai:<uid>``: not a file key, so `_clip_strip` skips it,
# and stable while blocks move (the block's id on the timeline). An AI part goes before
# the file that followed it in that order (its «anchor»), or last.

#: The token of an AI part in the Clip's order, and its block's id on the timeline.
AI_TOKEN: Final = "ai:"
#: The timeline's kind of an AI block (`data-tl-block="ai"`).
TL_KIND: Final = clip_editor_vm.AI_BLOCK_KIND
#: The mode's icon (lucide) beside its word (docs/design-system.md §5.10.1).
MODE_ICONS: Final[Mapping[str, str]] = {
    "reference": "wand-sparkles",
    "edit": "copy",
    "extend": "corner-down-right",
}
#: The state's mark before its word, an icon with a shape where a narrow block may hide
#: the word (errors and warnings); the rest the dot (`.q-tl__state-dot`, "").
STATE_ICONS: Final[Mapping[str, str]] = {
    "queued": "clock",
    "ready": "check",
    "failed": "circle-x",
    "refused": "triangle-alert",
    "redo": "triangle-alert",
    "expired": "triangle-alert",
}
#: «Agregar»'s option (≤ 16 characters, the orbit's pill) — its key and icon.
ADD_KEY: Final = "ai_part"
ADD_LABEL = "Parte con IA"
ADD_ICON: Final = "sparkles"  # the ✦ of «hecho con IA» (`T.AI_ICON`, design notas §4)


#: The panel's description field (design D10: the focus goes there once it is put).
DESCRIPTION_FIELD_ID: Final = "q-ai-part-description"


def focus_description_script() -> str:
    """The focus on «¿Qué pasa en esta parte?» as soon as the panel has rendered it: it
    tries again each frame, for up to ~2 s, until the field exists (never a fixed wait
    that a slow phone outlasts)."""
    return (
        "(function () { var tries = 0; (function go() {"
        f" var el = document.getElementById('{DESCRIPTION_FIELD_ID}');"
        " if (el) { el.focus(); return; }"
        " if (++tries < 120) window.requestAnimationFrame(go); })(); })()"
    )


def add_options(
    base: Sequence[tuple[str, str, str]], *, on: bool
) -> tuple[tuple[str, str, str], ...]:
    """«Agregar»'s options with «Parte con IA» last — only `on`: off, `base` exactly. Last
    (review): the other options keep their places, and so their `--q-orbit-i`, as on
    `main` while the option is not drawn."""
    return (*base, (ADD_KEY, ADD_ICON, ADD_LABEL)) if on else tuple(base)


def switch_on() -> bool:
    """`QUALIFY_CLIP_AI_PARTS` read as the server reads it (`ai_parts.clip_ai_parts_on`,
    contract §1): only «on» turns it on. The screen also needs `QUALIFY_CLIP_EDITOR`."""
    return contract_ai.clip_ai_parts_on()


def token(uid: str) -> str:
    """The order's token and the timeline id of the AI part `uid`."""
    return f"{AI_TOKEN}{uid}"


def is_token(key: str) -> bool:
    return str(key or "").startswith(AI_TOKEN)


def uid_of(block_id: str) -> str:
    """The AI part a block id names ("" = not an AI block)."""
    return block_id[len(AI_TOKEN) :] if is_token(block_id) else ""


def new_uid(parts: Sequence[Mapping[str, Any]]) -> str:
    """A uid none of `parts` has («p1», «p2»…): one per AI part, never reused while on."""
    taken = {str(p.get("uid") or "") for p in parts}
    n = len(taken) + 1
    while f"p{n}" in taken:
        n += 1
    return f"p{n}"


def plans(parts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """`media.ai_parts`: each part's entry, in the state's order — its description
    trimmed (the field keeps it as typed)."""
    out = []
    for part in parts:
        plan = dict(part.get("plan") or {})
        plan["description"] = str(plan.get("description") or "").strip()
        out.append(plan)
    return out


def merge_order(files: Sequence[str], sequence: Sequence[str], tokens: Sequence[str]) -> list[str]:
    """The Clip's whole order: its files as `_clip_strip` orders them (`files`) with each
    AI part's token (`tokens`, the parts that exist) before its anchor — the next file
    after it in the order kept (`sequence`) —, last when no file follows it there, and
    those the order does not know yet at the very end. Without tokens: `files` as they
    are (nothing changes for a Clip with no AI part)."""
    if not tokens:
        return list(files)
    known = set(files)
    live = set(tokens)
    anchors: dict[str, list[str]] = {}
    last: list[str] = []
    seen: set[str] = set()
    for at, key in enumerate(sequence):
        if key not in live or key in seen:
            continue
        seen.add(key)
        anchor = next((k for k in sequence[at + 1 :] if k in known), None)
        if anchor is None:
            last.append(key)
        else:
            anchors.setdefault(anchor, []).append(key)
    out: list[str] = []
    for key in files:
        out.extend(anchors.get(key, ()))
        out.append(key)
    out.extend(last)
    out.extend(t for t in tokens if t not in seen)
    return out


def timeline_items(
    media: Sequence[Mapping[str, object]],
    order: Sequence[str],
    parts: Sequence[Mapping[str, Any]],
) -> list[dict[str, object]]:
    """«Fotos y videos» with the AI parts in their places (`order`, `merge_order`'s):
    each AI block a stretch of the timeline's own shape — ``kind`` «ai», from 0 to its
    whole seconds at ×1, ``entry`` its place in `media.ai_parts`, ``ai_n`` its number
    among the AI parts — so every reader (the rows, the joins, the preview, the recipe:
    `clip_editor_vm.timeline_segments`) lays it like any block. No AI part: `media`
    unchanged."""
    if not parts:
        return [dict(item) for item in media]
    by_uid = {str(p.get("uid") or ""): (n, p) for n, p in enumerate(parts)}
    pool: dict[str, list[dict[str, object]]] = {}
    for item in media:
        pool.setdefault(str(item.get("key") or ""), []).append(dict(item))
    out: list[dict[str, object]] = []
    count = 0
    for key in order:
        if not is_token(key):
            out.extend(pool.pop(key, []))
            continue
        found = by_uid.get(uid_of(key))
        if found is None:
            continue
        entry_at, part = found
        count += 1
        seconds = float(clamp_seconds((part.get("plan") or {}).get("seconds")))
        out.append(
            {
                "id": key,
                "key": key,
                "kind": TL_KIND,
                "src_start": 0.0,
                "src_end": seconds,
                "src_len": seconds,
                "speed": 1.0,
                "rotate": 0,
                "entry": entry_at,
                "ai_n": count,
            }
        )
    for rest in pool.values():
        out.extend(rest)
    return out


def place_token(
    order: Sequence[str], media: Sequence[Mapping[str, object]], at: int, tok: str
) -> list[str]:
    """The order with `tok` put at block `at` of the timeline (`media`, AI blocks
    included): before the file (or AI part) there — never between two pieces of the own
    video, which stay side by side: such a place goes after the last piece —, last past
    the end."""
    at = min(max(int(at), 0), len(media))
    while 0 < at < len(media) and media[at].get("key") == media[at - 1].get("key"):
        at += 1
    out = [key for key in order if key != tok]
    if at >= len(media):
        out.append(tok)
        return out
    anchor = str(media[at].get("key") or "")
    out.insert(out.index(anchor) if anchor in out else len(out), tok)
    return out


def row_fields(
    item: Mapping[str, object],
    plan: Mapping[str, Any],
    *,
    start_s: float,
    poster: str = "",
    has_product: bool = True,
) -> dict[str, str]:
    """What an AI block's row of the track adds to `timeline_vm.media_blocks`' row: its
    name and panel title, its accessible name (`track_block`'s `aria`), its badge and
    the mode's icon, its second line, its state and mark, its poster (`thumb`), and no
    handles before «Crear» (its whole seconds change in its panel: `seconds_control`)."""
    n = int(item.get("ai_n") or 1)  # type: ignore[call-overload]
    block = track_block(n, plan, start_s=start_s, poster=poster, has_product=has_product)
    mode = str(plan.get("mode") or "reference")
    return {
        "label": block["name"],
        "name": block["aria"],
        "panel": f"{block['name']} · {seconds_text(int(block['seconds']))}",
        "thumb": block["picture"],
        "secs": "",
        "speed_tag": "",
        "handles": "",
        "ai_badge": block["badge"],
        "ai_mode_icon": MODE_ICONS.get(mode, MODE_ICONS["reference"]),
        "ai_line": block["line"],
        "ai_secs": seconds_text(int(block["seconds"])),
        "ai_state": block["state"],
        "ai_state_word": block["state_word"],
        "ai_state_icon": STATE_ICONS.get(block["state"], ""),
        "ai_tone": block["tone"],
    }


#: The live lines of the AI parts on the timeline (ED-07).
REMOVED_LINE = "Quitaste la parte con IA {n}."
SECONDS_LINE = "La parte con IA {n} ahora dura {s} s."
MODE_LINE = "Cambiaste cómo se hace la parte con IA {n}: «{mode}»."
DESCRIPTION_LINE = "Guardamos lo que contaste de la parte con IA {n}."
PHOTOS_LINE = "Cambiaste las fotos de la parte con IA {n}."
#: «Video o audio tuyo» put or taken out (`guide_line`).
GUIDE_ADDED = {
    "video": "Agregaste tu video a la parte con IA {n}.",
    "audio": "Agregaste tu audio a la parte con IA {n}.",
}
GUIDE_REMOVED = {
    "video": "Quitaste tu video de la parte con IA {n}.",
    "audio": "Quitaste tu audio de la parte con IA {n}.",
}
GUIDE_FULL = "Esta parte ya tiene 3 {what} tuyos, el máximo. Quita uno para agregar otro."
MERGED_LINE = "Juntaste las partes con IA {n} y {m}: ahora son una de {s} s."
#: «Juntar con la siguiente» (`part_editor_vm`'s words): only for a short part of a reel
#: with another AI part right after it — as today's sheet (`reel_merge_shown`). Why not,
#: by what follows it (`merge_needs_ai_next`).
MERGE_LABEL = "Juntar con la siguiente"
_MERGE_ONLY_AI = "solo se juntan dos partes con IA seguidas."
MERGE_NEXT_PHOTO = f"La siguiente es una foto tuya: {_MERGE_ONLY_AI}"
MERGE_NEXT_VIDEO = f"La siguiente es un video tuyo: {_MERGE_ONLY_AI}"
MERGE_NEXT_NONE = f"No hay otra parte después: {_MERGE_ONLY_AI}"
#: The panel's words (design 02).
MODE_TITLE = "¿Cómo la hacemos?"
DESCRIPTION_TITLE = "¿Qué pasa en esta parte?"
#: Under the field, its example only (in the help, never as a placeholder).
DESCRIPTION_EXAMPLE = "Ej.: «Una mano acerca el vaso»."
#: Without a reel the way is a fact, not a question (ux review): the badge, this line
#: (with or without a product) and `NO_REEL_MODE_TEXT`.
NO_REEL_FACT = "Creamos una parte nueva con tu producto y tu marca."
NO_REEL_FACT_BRAND = "Creamos una parte nueva con tu marca."
PHOTOS_TITLE = "Fotos de tu producto"
#: No photo in the Clip yet: a photo chosen in «Foto o video» goes on the track too.
PHOTOS_NONE = (
    "Todavía no hay fotos en tu video. Toca «Agregar» y elige «Foto o video»: la parte con "
    "IA la usa para mostrar tu producto, y la foto también queda en tu video."
)
GUIDE_HELP = (
    "La parte con IA copia el movimiento de tu video o sigue el ritmo de tu audio. "
    "Sirven MP4, MOV, MP3 o WAV, hasta 3 de cada uno."
)

#: Until PR 2 (m-25129406, `create_clip_with_ai_parts`) is on `main`, the server refuses
#: a Clip with AI parts (`create_draft` → `recipe_unavailable`): «Crear» and «Probar esta
#: parte» stay off, saying why. Flipped by the PR that wires that call — never by itself.
AI_CREATE_BUILT: Final = False
#: The body's words (under the editor and on «Revisa y crea», once) …
CREATE_OFF_LINE = (
    "Todavía no podemos crear videos con partes con IA. Si lo quieres hoy, quítalas: con tus "
    "fotos y videos se crea igual."
)
#: … and the short line beside «Crear».
CREATE_OFF_SHORT = "Para crear hoy, quita las partes con IA."
TRY_OFF_LINE = (
    "Todavía no podemos crear partes con IA, ni para probarlas. Por ahora, tu video se crea "
    "solo con tus fotos y videos."
)


def no_business_problem() -> dict[str, str]:
    """Review: the session's business is not known yet, so its files cannot be checked —
    said as the contract's `ai_parts_mismatch`, never skipped in silence."""
    return _problem("ai_parts_mismatch", "ai_parts")


def guide_line(kind: str, n: int, *, added: bool) -> str:
    """«Agregaste tu video a la parte con IA 1.» / «Quitaste tu audio de …»."""
    words = GUIDE_ADDED if added else GUIDE_REMOVED
    return words.get(kind, words["video"]).format(n=n)


def guide_kind(key: str) -> str:
    """`video` / `audio` by the file's type ("" = neither: not a guide)."""
    lower = str(key or "").lower()
    if lower.endswith(GUIDE_VIDEO_SUFFIXES):
        return "video"
    return "audio" if lower.endswith(GUIDE_AUDIO_SUFFIXES) else ""


def merged_line(n: int, seconds: int) -> str:
    return MERGED_LINE.format(n=n, m=n + 1, s=seconds)


def merge_needs_ai_next(following_kind: str | None) -> str:
    """Why «Juntar con la siguiente» cannot join, by what follows ("" = an AI part)."""
    if following_kind is None:
        return MERGE_NEXT_NONE
    if following_kind == TL_KIND:
        return ""
    return MERGE_NEXT_PHOTO if following_kind == "photo" else MERGE_NEXT_VIDEO


def mode_fact(*, has_product: bool) -> str:
    return NO_REEL_FACT if has_product else NO_REEL_FACT_BRAND


def removed_line(n: int) -> str:
    return REMOVED_LINE.format(n=n)


def seconds_line(n: int, seconds: int) -> str:
    return SECONDS_LINE.format(n=n, s=seconds)


def mode_line(n: int, mode: str) -> str:
    return MODE_LINE.format(n=n, mode=MODE_SHORT.get(mode, MODE_SHORT["reference"]))


def merge_shown(plan: Mapping[str, Any]) -> bool:
    """«Juntar con la siguiente» shows as on today's sheet: a part of a reel under 4 s."""
    return bool(plan.get("analysis_id")) and clamp_seconds(plan.get("seconds")) < 4


def with_seconds(plan: Mapping[str, Any], seconds: int) -> dict[str, Any]:
    """The entry with whole `seconds` (1-10, clamped)."""
    return {**plan, "seconds": clamp_seconds(seconds)}


def with_owner_mode(plan: Mapping[str, Any], mode: str) -> dict[str, Any]:
    """The owner's choice of mode: `with_mode` plus whether it is not the rule's
    proposal (`mode_changed_by_owner`, the golden set's label; back to the proposal, it
    is the rule's again)."""
    out = with_mode(plan, mode)
    proposed = proposal_of(plan)
    out["mode_changed_by_owner"] = bool(proposed) and proposed != mode
    return out


def with_photos(plan: Mapping[str, Any], keys: Sequence[str]) -> dict[str, Any]:
    """The entry's own photos (at most the type's 9), each «Producto»."""
    chosen = list(dict.fromkeys(str(k) for k in keys if k))[: schemas.CLIP_MAX_IMAGES]
    return {**plan, "clip_image_keys": chosen, "clip_image_roles": ["product"] * len(chosen)}


def with_guide(plan: Mapping[str, Any], key: str) -> tuple[dict[str, Any], str]:
    """«Video o audio tuyo»: `key` added as a guide video or audio by its type — (the
    entry, "") — or the entry unchanged and why not: not «Nueva» (`GUIDE_NEEDS_NEW`), a
    file of another type (the contract's `ai_part_guide_type`), 3 of its kind already
    (`GUIDE_FULL`)."""
    if str(plan.get("mode") or "reference") != "reference":
        return dict(plan), GUIDE_NEEDS_NEW
    lower = key.lower()
    if lower.endswith(GUIDE_VIDEO_SUFFIXES):
        name, most = "clip_video_keys", schemas.CLIP_MAX_VIDEOS
    elif lower.endswith(GUIDE_AUDIO_SUFFIXES):
        name, most = "clip_audio_keys", schemas.CLIP_MAX_AUDIOS
    else:
        return dict(plan), refusal_text("ai_part_guide_type")
    held = [str(k) for k in plan.get(name) or ()]
    if key in held:
        return dict(plan), ""
    if len(held) >= most:
        return dict(plan), GUIDE_FULL.format(
            what="videos" if name == "clip_video_keys" else "audios"
        )
    return {**plan, name: [*held, key]}, ""


def without_guide(plan: Mapping[str, Any], key: str) -> dict[str, Any]:
    return {
        **plan,
        "clip_video_keys": [k for k in plan.get("clip_video_keys") or () if k != key],
        "clip_audio_keys": [k for k in plan.get("clip_audio_keys") or () if k != key],
    }


def problems_of(problems: Sequence[Mapping[str, str]], entry_at: int, block_at: int) -> list[str]:
    """The words of `preflight_problems` that are about ONE AI part — its entry
    (`ai_parts[n]…`) or its block (`segments[i]…`) —, once each, in order."""
    mine = (f"ai_parts[{entry_at}]", f"segments[{block_at}]")
    said: list[str] = []
    for problem in problems:
        field = str(problem.get("field") or "")
        if field.startswith(mine) and problem["text"] not in said:
            said.append(problem["text"])
    return said


__all__ = [
    "AI_CHILDREN_MAX",
    "AI_PART_KEY_PREFIX",
    "AI_PART_KIND",
    "AI_PART_TEXTS",
    "BACK_TO_PROPOSED",
    "BLOCKS_MAX",
    "CHANGED_BY_OWNER",
    "MODE_SHORT",
    "REDO_LABEL",
    "SECONDS_MAX",
    "SECONDS_MIN",
    "TRY_LABEL",
    "add_reason",
    "ai_numbers",
    "ai_part_at",
    "ai_part_key",
    "ai_part_name",
    "ai_seconds_used",
    "announcement",
    "clamp_seconds",
    "clip_seconds",
    "create_reason",
    "edit_reason",
    "extend_code",
    "extend_reason",
    "guide_option",
    "guide_problems",
    "insert_ai_block",
    "mode_badge",
    "mode_options",
    "mode_reason_text",
    "new_ai_block",
    "new_part_seconds",
    "own_seconds",
    "preflight_problems",
    "redo_line",
    "refusal_text",
    "remove_ai_block",
    "review_cost_lines",
    "seconds_control",
    "same_moment",
    "track_block",
    "try_line",
    "with_ai_name",
    "with_mode",
]
