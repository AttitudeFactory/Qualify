"""ED-06 (m-25026636, PR 7 of the one editor, ADR 50 §13.7): «Idea» inside «Arma tu video»
and the video in 3 steps — pure: no Reflex, no database, no network.

D-E4 (signed): the context of the video («¿De qué trata tu video?», `topic`) moves from
«Qué decir» into the editor, so a Clip on «Arma tu video» walks 3 steps («Arma tu video ·
Cómo la quieres · Revisa y crea»); Imagen, Carrusel and Avatar keep their 4. In the editor:

- with nothing chosen, ONE folded row under the timeline (design D21): «Tu video trata
  de: «…»» · «Cambiar» (or «Cuenta de qué trata tu video: guía el texto.» · «Escribir»).
  Tapped, the general panel opens as the thing chosen, ending in «Listo»: the context,
  «Mejorar mi texto», and «Más opciones (a quién le habla, precio, descuento…)» folding
  «¿A quién le habla este video?» and «Datos clave»;
- an AI part chosen shows «Todo el video» above its panel (design D6/D21): what the whole
  video is about, the rule of who guides what, and «Cambiar»/«Escribir» to the general
  panel;
- the two entries of the plan (PR 7), both free until «Crear»:
  «Hacer uno parecido» (a reel's plan, `plan_blocks.blocks_from_plan`) opens the editor
  with the blocks already laid under the «Video de inspiración» card, and «Agregar →
  Pedir una idea» (Claude's `propose_parts`, no reel) ADDS the parts it proposes at the
  end of the track — never deleting anything — as far as the caps let (8 blocks, 6 AI
  parts, 60 s), saying how many went in and why not the rest.

The blocks are the server's (`qualify_api.creative.plan_blocks`, PR 5, m-25129409): this
module only turns them into the editor's operations (`editor_ops`) and finds how much of a
proposal fits (`fit_proposal`). Words: the ticket (m-25026636), the signed design
(`docs/mockups/editor-unico/notas.md` D6, D20, D21, D22 and 03C), the ED-06 UX review
(2026-11-27) and the existing `parts_start_vm` / `reel_parts_vm` / `ai_block_vm` — reused,
never copied.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from qualify_api.creative.parts import ExtendTooShort
from qualify_api.creative.parts_ai import PROPOSE_RETRY_TEXT
from qualify_api.creative.parts_plan import PartsPlanRefused
from qualify_api.creative.plan_blocks import (
    BLOCKS_TOO_MANY,
    BLOCKS_TOO_MANY_AI,
    PLAN_BLOCKS_TEXTS,
    ClipBlocks,
    PlanBlocksRefused,
    blocks_from_plan,
)
from qualify_creative.schemas import AI_PART_KIND, SourceSegment, VideoPartPlan

from . import ai_block_vm, clip_editor_vm, parts_start_vm

# -- the general panel («¿De qué trata tu video?», ticket m-25026636, design D21) ----------

#: The general panel's question (the same words as «Pedir una idea»'s tab).
TOPIC_QUESTION = clip_editor_vm.FLOW_QUESTIONS[clip_editor_vm.FLOW_IDEA]
#: Its help and its example (ticket: «Esto guía el texto de todo el video.»).
TOPIC_HELP = clip_editor_vm.IDEA_HELP
TOPIC_EXAMPLE = clip_editor_vm.IDEA_EXAMPLE
#: The field's id: «Cambiar» and «Editar» of «Revisa y crea» bring the focus here. The
#: same as step 2's field (`creative_state.CONTEXT_FIELD_ID`: «Mejorar mi texto» scrolls
#: to it); both are never on one screen — the video has no «Qué decir».
TOPIC_FIELD_ID = "q-context-field"
#: «¿A quién le habla este video?»'s selector in the general panel (`audience_question`).
AUDIENCE_FIELD_ID = "clip-audience"
#: … and its «Cambiar» once the answer shows as a closed line (`audience_closed`).
AUDIENCE_FIELD_IDS = (AUDIENCE_FIELD_ID, f"{AUDIENCE_FIELD_ID}-change")
#: «Datos clave»'s first field (`content_generator._highlight_row`'s ids): its «¿Qué
#: dato?», or its «¿Cuánto o cuál?» when the first row is the catalog's fixed price.
#: With no row yet, «Agregar dato» (review).
RULES_ADD_ID = "q-cr-hl-add"
RULES_FIELD_IDS = ("q-cr-hl-key-0", "q-cr-hl-value-0", RULES_ADD_ID)
#: «Debe mencionar» / «Debe evitar»: their own rows' views on «Revisa y crea» (the step
#: and its «Más opciones» are «Datos clave»'s) and their own fields (review).
MENTION_VIEW = "rules:more:mention"
AVOID_VIEW = "rules:more:avoid"
MENTION_FIELD_ID = "q-cr-must-mention"
AVOID_FIELD_ID = "q-cr-must-avoid"
#: With 12 phrases the field is off: its help (focusable, `tabindex=-1`) takes it.
MENTION_HELP_ID = f"{MENTION_FIELD_ID}-help"
AVOID_HELP_ID = f"{AVOID_FIELD_ID}-help"
RULES_FIELDS_BY_VIEW: dict[str, tuple[str, ...]] = {
    MENTION_VIEW: (MENTION_FIELD_ID, MENTION_HELP_ID),
    AVOID_VIEW: (AVOID_FIELD_ID, AVOID_HELP_ID),
}
#: The general panel's «Más opciones» (UX review): what it folds, said on the button.
MORE_LABEL = "Más opciones (a quién le habla, precio, descuento…)"
#: The folded row with nothing chosen (design D21).
ROW_SAID = "Tu video trata de: «{topic}»"
ROW_EMPTY = "Cuenta de qué trata tu video: guía el texto."
CHANGE_LABEL = "Cambiar"
WRITE_LABEL = "Escribir"
#: The buttons' accessible names: the word alone does not say what it changes.
CHANGE_ARIA = "Cambiar de qué trata tu video"
WRITE_ARIA = "Escribir de qué trata tu video"
#: The general panel's own title as the thing chosen (its «Listo» closes it); also the
#: «Contexto» row's name on «Revisa y crea» with the editor on (UX review).
PANEL_TITLE = "De qué trata tu video"
#: The folded row's button: «Listo» gives it the focus back.
ROW_BUTTON_ID = "clip-topic-row"
#: The general panel's word in the address (`?bloque=de-que-trata`, UX review P1): the
#: phone's «atrás» closes it, as it lets a chosen block go.
GENERAL_SLUG = "de-que-trata"


#: m-25026638 (live test): frames the field keeps the focus a step change took from it.
#: «Editar» on «Revisa y crea» moves to step 1 AND opens the panel; the step's own settle
#: (`ui.steps.step_settle_script`, run by `go_to_step` and again by `step_sync`, ~2–4
#: frames later) scrolls the panel to the top and focuses the step's title — after the
#: field already had the focus. ~0.5 s covers both settles.
FOCUS_HOLD_FRAMES = 30
#: What a step's settle focuses (`ui.steps._TITLE`): the focus taken back only from it
#: (or from nothing), never from what the owner touched meanwhile.
STEP_TITLE_SELECTOR = ".q-step-title"


def focus_script(*field_ids: str) -> str:
    """The focus on a field of the general panel (the first of `field_ids` drawn; the
    context's by default) as soon as it is there — the chosen block's panel goes first:
    it tries each frame for up to ~2 s, as `ai_block_vm.focus_description_script` does,
    never a fixed wait. m-25026638: for `FOCUS_HOLD_FRAMES` after that, a focus a step's
    settle moved to the step's title (or to nothing, right after the field or the title
    had it) comes back to the field, which is scrolled into view again (the settle
    scrolls the panel to the top)."""
    ids = json.dumps(list(field_ids or (TOPIC_FIELD_ID,)))
    title = json.dumps(STEP_TITLE_SELECTOR)
    return (
        "(function () { var tries = 0, held = -1, last = null;"
        f" function isTitle(n) {{ return !!n && !!n.matches && n.matches({title}); }}"
        " (function go() {"
        f" var el = {ids}.map(function (i) {{ return document.getElementById(i); }})"
        # a field turned off (12 phrases) cannot take the focus: the next one does
        ".filter(function (e) { return e && !e.disabled; })[0];"
        " if (el) {"
        " var now = document.activeElement;"
        # review: the body (or nothing) counts as lost only when the field or the title
        # had it a frame ago — Safari leaves the body focused after a tap on a button
        " var gone = !now || now === document.body;"
        " var lost = (now !== el && isTitle(now))"
        " || (gone && (last === el || isTitle(last)));"
        " if (held < 0 || lost) { el.focus(); el.scrollIntoView({block: 'nearest'}); }"
        " last = document.activeElement;"
        f" if (++held >= {FOCUS_HOLD_FRAMES}) return;"
        " } else if (++tries >= 120) return;"
        " window.requestAnimationFrame(go); })(); })()"
    )


def release_address_script(param: str = "bloque") -> str:
    """Drop the general panel's word from the address WITHOUT walking back (final
    review): `replaceState`, and the entry no longer carries `qBloque`, so the next step's
    entry (which copies it) never inherits a mark a later «Listo» would walk back by."""
    key = json.dumps(param)
    return (
        "(() => { const u = new URL(window.location.href);"
        " const st = Object.assign({}, window.history.state || {}); delete st.qBloque;"
        f" u.searchParams.delete({key});"
        " window.history.replaceState(st, '', u); })()"
    )


def replace_with_step_script(target: str) -> str:
    """The general panel's own entry becomes the step `target`'s (last review): the
    address of `target` (`ui.steps.step_url`) and the state `__qStepGo` would have pushed
    for it — the entry's own state without `qBloque`, plus `qPrevPaso` = the step it
    leaves. Mirrors `Qualify/ui/steps.py` `_STEP_GO_JS` (its `pushState({ ...st,
    qPrevPaso: cur })`), which this must not change: if that rule changes, change this.
    The step's own script runs next, finds its address already written and stacks
    nothing; «Atrás» then walks back (`qPrevPaso`) to the entry under the panel's.

    m-25026638 (review): only an entry THIS page load pushed (its `qBloque` is this
    document's `__qBloqueDoc`, the `mine` check of `clip_editor_vm.block_url_script`).
    One that came with the address (a link, a new tab, a reload) only loses its word,
    as `release_address_script` does, and stays step 1's: the step's own script then
    pushes the next step, and «Atrás» walks back to it inside this document."""
    return (
        "(() => { const st = Object.assign({}, window.history.state || {});"
        " const mine = !!window.__qBloqueDoc && st.qBloque === window.__qBloqueDoc;"
        " delete st.qBloque;"
        " if (!mine) { const u = new URL(window.location.href);"
        f" u.searchParams.delete({json.dumps(clip_editor_vm.BLOCK_PARAM)});"
        " window.history.replaceState(st, '', u); return; }"
        " st.qPrevPaso = new URL(window.location.href).searchParams.get('paso');"
        f" window.history.replaceState(st, '', {json.dumps(target)}); }})()"
    )


def focus_topic_script() -> str:
    return focus_script(TOPIC_FIELD_ID)


def said_topic(topic: str) -> str:
    """The context single-spaced ("" = nothing written)."""
    return " ".join((topic or "").split())


def row_text(topic: str) -> str:
    """The folded row (design D21): «Tu video trata de: «…»», or the invitation."""
    said = said_topic(topic)
    return ROW_SAID.format(topic=said) if said else ROW_EMPTY


# -- «Todo el video» over an AI part's panel (design D6, D21) ------------------------------

WHOLE_TITLE = "Todo el video"
#: The rule of who guides what, said on screen in one sentence (ticket, design D21).
WHOLE_RULE = (
    "Esto guía el texto y el tono de todo el video. Lo que escribas abajo dice qué se ve en "
    "esta parte."
)
#: Nothing written yet (design D21).
WHOLE_EMPTY = ROW_EMPTY


def whole_value(topic: str) -> str:
    """«Todo el video»'s line: the context in quotes, single-spaced, or `WHOLE_EMPTY`."""
    said = said_topic(topic)
    return f"«{said}»" if said else WHOLE_EMPTY


# -- «Hacer uno parecido» (design D20) ------------------------------------------------------

INSPIRATION_TITLE = "Video de inspiración"
GO_TO_VIDEO = "Ir al video"
GO_TO_VIDEO_ARIA = "Ir al video de inspiración (se abre en otra pestaña)"
#: The reel's plan could not go on the track as blocks: today's list, with «Qué decir».
REEL_FALLBACK_LINE = "No pudimos armarlo como el reel: agregamos el paso «Qué decir»."


def _count(n: int, one: str, many: str) -> str:
    return f"1 {one}" if n == 1 else f"{n} {many}"


@dataclass(frozen=True)
class ReelCut:
    """m-25143223: the reel's plan does not reach the reel's end — it follows `used_s`
    of its `reel_s` seconds (whole seconds). `capped`: cuts of the reel were left out
    because the plan reached the parts' cap (`PARTS_MAX`); False when the plan holds
    every cut the analysis read and the analysis itself stopped short of the reel."""

    used_s: int
    reel_s: int
    capped: bool = False


class ReelOps(list[dict[str, Any]]):
    """The reel's plan as the editor's ops (`editor_ops`), carrying `cut` (a `ReelCut`;
    None when the plan covers the whole reel) from the one read that made them."""

    def __init__(self, ops: Iterable[dict[str, Any]], *, cut: ReelCut | None = None) -> None:
        super().__init__(ops)
        self.cut = cut


#: The «Video de inspiración» card's line when the plan is cut (m-25143223).
REEL_CUT_CARD = "Usamos {used} s de los {reel} del reel."


def reel_cut_card(cut: ReelCut | None) -> str:
    """The card's short line for a cut plan, «Usamos 44 s de los 63 del reel.» ("" for a
    plan that covers the reel)."""
    return REEL_CUT_CARD.format(used=cut.used_s, reel=cut.reel_s) if cut else ""


def reel_line(ai: int, own: int, cut: ReelCut | None = None) -> str:
    """The live line once the reel's plan is on the track (design D20): «Te armamos tu
    video como el reel: 3 partes con IA y 2 tuyas. Revisa cada una; hasta «Crear» no
    gastas nada.» — one part: «Revísala»; only own parts: «2 partes tuyas». m-25143223:
    a plan that stops before the reel's end says so — «…: 6 partes con IA (el máximo por
    video), con 44 s de los 63 del reel. Revisa…». The bracket only when the cap of AI
    parts cut it: with own parts among them the cap was of parts, not of AI ones."""
    if ai and own:
        said = f"{_count(ai, 'parte con IA', 'partes con IA')} y {_count(own, 'tuya', 'tuyas')}"
    elif ai:
        said = _count(ai, "parte con IA", "partes con IA")
    else:
        said = _count(own, "parte tuya", "partes tuyas")
    if cut is not None:
        if cut.capped and ai and not own:
            said += " (el máximo por video)"
        said += f", con {cut.used_s} s de los {cut.reel_s} del reel"
    review = "Revísala" if ai + own == 1 else "Revisa cada una"
    return f"Te armamos tu video como el reel: {said}. {review}; hasta «Crear» no gastas nada."


# -- «Agregar → Pedir una idea» (design 03C, D22; Deivid's answer to P2: A) ----------------

PROPOSE_LABEL = parts_start_vm.PROPOSE_LABEL
#: Under the button (design 03C; Deivid 2026-11-27, m-25142725: where they go, in his words).
PROPOSE_NOTE = (
    "Proponer es gratis. Las partes se suman al final de tu video y las revisas antes de "
    "crear nada."
)
#: Why «Proponerme las partes» waits: the context is what Claude reads. m-25026636 (UX
#: review): it says where to write it — the field under the tab's own heading.
STORY_MISSING = (
    f"Escribe de qué trata tu video, arriba en «{TOPIC_QUESTION}», y te proponemos las partes."
)
#: The button's id, for its reason (`aria-describedby`).
PROPOSE_WHY_ID = "clip-idea-why"
#: An own video on the track is still being read (no length yet): said BEFORE the call…
TRACK_NOT_READY = (
    "Tu video todavía se está preparando. Cuando termine, toca «Proponerme las partes»."
)
#: … and if it still happens after it (UX review).
TRACK_NOT_READY_AFTER = (
    "Tu video todavía se estaba preparando y no pudimos poner las partes. No gastaste nada: "
    "toca «Proponerme las partes» otra vez."
)
#: The plan came back in a shape the track cannot take: the proposal's own retry words.
NOT_PLACED = PROPOSE_RETRY_TEXT

#: Why the rest of a proposal did not go in, after «y pusimos {k}:» (UX review: the
#: fact, never the order «Quita una…» — the owner asked for nothing to be taken out).
_PARTIAL_WHY = {
    BLOCKS_TOO_MANY: (f"tu video llegó a {ai_block_vm.BLOCKS_MAX} fotos o videos, el máximo."),
    BLOCKS_TOO_MANY_AI: f"tu video llegó a {ai_block_vm.AI_CHILDREN_MAX} partes con IA, el máximo.",
    "too_long": (f"con las demás, tu video pasaría de {int(clip_editor_vm.LOCAL_MAX_SECONDS)} s."),
}


def idea_line(proposed: int, placed: int, reason: str = "") -> str:
    """The live line once a proposal is on the track: «Te propusimos 4 partes. Revísalas:
    hasta «Crear» no gastas nada.» (design 03C); when only some went in, «Te propusimos 4
    partes y pusimos 2: tu video llegó a 8 fotos o videos, el máximo. Revísalas: …»; when
    none did, only the cap's words (`cap_text`)."""
    if placed <= 0:
        return cap_text(reason)
    review = "Revísala" if placed == 1 else "Revísalas"
    tail = f"{review}: hasta «Crear» no gastas nada."
    if placed >= proposed:
        return f"Te propusimos {_count(proposed, 'parte', 'partes')}. {tail}"
    why = _PARTIAL_WHY.get(reason) or cap_text(reason)
    head = f"Te propusimos {_count(proposed, 'parte', 'partes')} y pusimos {placed}"
    return f"{head}: {why} {tail}" if why else f"{head}. {tail}"


def cap_text(reason: str) -> str:
    """The owner's words for a cap a proposal hit with nothing put: the editor's own lines
    before the choque (8 blocks, 6 AI parts, 60 s — `ai_block_vm`), else the plan's
    (`PLAN_BLOCKS_TEXTS`)."""
    if reason == BLOCKS_TOO_MANY:
        return clip_editor_vm.FULL_LINE
    if reason == BLOCKS_TOO_MANY_AI:
        return ai_block_vm.FULL_AI_LINE
    if reason == "too_long":
        return ai_block_vm.FULL_SECONDS_LINE
    return PLAN_BLOCKS_TEXTS.get(reason, "")


def track_blocks(
    segments: Sequence[Mapping[str, Any]], ai_parts: Sequence[Mapping[str, Any]]
) -> ClipBlocks:
    """The editor's track as the server's `ClipBlocks` (`after` of a proposal): its
    stretches as the brief takes them and the AI parts' entries. Raises
    `ValidationError` while an own video has no length yet."""
    return ClipBlocks(
        segments=tuple(SourceSegment.model_validate(dict(s)) for s in segments),
        ai_parts=tuple(VideoPartPlan.model_validate(dict(p)) for p in ai_parts),
    )


def fit_proposal(
    plan: Sequence[VideoPartPlan],
    after: ClipBlocks,
    *,
    other_ai_children: int = 0,
) -> tuple[ClipBlocks | None, int, str]:
    """How much of a proposal goes on the track after `after` (Deivid P2 = A: at the end,
    nothing deleted, up to the caps): the longest first stretch of `plan` the server's
    `blocks_from_plan` takes (8 blocks, 6 AI children) that also keeps the video within
    60 s. Returns (the whole track, how many parts went in, the cap's code of the first
    part left out — "" when all went in). (None, 0, code) when none fits; a plan the
    server refuses outright (`PartsPlanRefused`, `ExtendTooShort`) is (None, 0, "")."""
    reason = ""
    for count in range(len(plan), 0, -1):
        try:
            blocks = blocks_from_plan(
                tuple(plan[:count]), None, after=after, other_ai_children=other_ai_children
            )
        except PlanBlocksRefused as exc:
            reason = reason or exc.reason
            continue
        except (PartsPlanRefused, ExtendTooShort):
            return None, 0, ""
        if blocks.seconds > clip_editor_vm.LOCAL_MAX_SECONDS + 1e-6:
            reason = reason or "too_long"
            continue
        return blocks, count, reason if count < len(plan) else ""
    return None, 0, reason


def editor_ops(blocks: ClipBlocks, start: int = 0) -> list[dict[str, Any]] | None:
    """The blocks from `start` on, as the editor puts them (in order): an AI part
    ``{"kind": "ai", "plan": <its entry as JSON>, "join": …}``, an own photo
    ``{"kind": "photo", "key", "seconds", "rotate", "join"}`` or an own video
    ``{"kind": "video", "key", "join"}`` — each `join` the block's `transition_in` as
    ``{"kind", "seconds", "direction"}`` (None = «Corte»).

    None when the editor cannot hold the blocks as they are — never a block lost in
    silence: the caller keeps today's way (the list, or «no pudimos»). That is an own
    video with a stretch, a speed or a turn (the editor cuts only the Clip's own video,
    with its measured length) and, for now, any text or effect of the plan."""
    # TODO(PR 5 follow-up): the plan's texts and effects (`blocks.text_layers` /
    # `blocks.effects`, already in seconds of the final video) go to the editor's tracks.
    # No plan brings them today (`plan_from_analysis`, `propose_parts`): a test fails the
    # day one does, so this is built before it reaches an owner.
    if blocks.text_layers or blocks.effects:
        return None
    out: list[dict[str, Any]] = []
    for segment in blocks.segments[start:]:
        join = _join(segment)
        if segment.kind == AI_PART_KIND:
            at = segment.ai_part_at
            if at is None or at >= len(blocks.ai_parts):
                return None
            out.append(
                {"kind": "ai", "plan": blocks.ai_parts[at].model_dump(mode="json"), "join": join}
            )
        elif segment.kind == "photo":
            out.append(
                {
                    "kind": "photo",
                    "key": segment.key,
                    "seconds": float(segment.end_s - segment.start_s),
                    "rotate": int(segment.rotate),
                    "join": join,
                }
            )
        else:
            if segment.start_s > 0 or segment.speed != 1 or segment.rotate:
                return None  # a stretch or a speed the editor cannot hold on that file
            out.append({"kind": "video", "key": segment.key, "join": join})
    return out


def _join(segment: SourceSegment) -> dict[str, Any] | None:
    use = segment.transition_in
    if use is None:
        return None
    params = dict(use.params or {})
    seconds = params.get("duration_s")
    return {
        "kind": use.effect_id,
        "seconds": float(seconds) if isinstance(seconds, int | float) else None,
        "direction": str(params.get("direction") or ""),
    }


def plans_of(entries: Sequence[Mapping[str, Any]]) -> list[VideoPartPlan]:
    """The `VideoPartPlan`s of the parts flow's entries (`{key, plan, …}`), in order.
    Raises `ValidationError` on a plan Claude sent malformed."""
    return [VideoPartPlan.model_validate(dict(entry.get("plan") or {})) for entry in entries]


__all__ = [
    "AUDIENCE_FIELD_ID",
    "AUDIENCE_FIELD_IDS",
    "AVOID_HELP_ID",
    "AVOID_FIELD_ID",
    "AVOID_VIEW",
    "CHANGE_ARIA",
    "CHANGE_LABEL",
    "GO_TO_VIDEO",
    "GENERAL_SLUG",
    "GO_TO_VIDEO_ARIA",
    "INSPIRATION_TITLE",
    "MENTION_FIELD_ID",
    "MENTION_HELP_ID",
    "MENTION_VIEW",
    "MORE_LABEL",
    "NOT_PLACED",
    "PANEL_TITLE",
    "PROPOSE_LABEL",
    "PROPOSE_NOTE",
    "PROPOSE_WHY_ID",
    "REEL_CUT_CARD",
    "REEL_FALLBACK_LINE",
    "ReelCut",
    "ReelOps",
    "ROW_BUTTON_ID",
    "RULES_ADD_ID",
    "RULES_FIELDS_BY_VIEW",
    "RULES_FIELD_IDS",
    "STORY_MISSING",
    "TOPIC_EXAMPLE",
    "TOPIC_FIELD_ID",
    "TOPIC_HELP",
    "TOPIC_QUESTION",
    "TRACK_NOT_READY",
    "TRACK_NOT_READY_AFTER",
    "WHOLE_EMPTY",
    "WHOLE_RULE",
    "WHOLE_TITLE",
    "WRITE_ARIA",
    "WRITE_LABEL",
    "cap_text",
    "editor_ops",
    "fit_proposal",
    "focus_script",
    "idea_line",
    "plans_of",
    "reel_cut_card",
    "reel_line",
    "release_address_script",
    "replace_with_step_script",
    "row_text",
    "track_blocks",
    "whole_value",
]
