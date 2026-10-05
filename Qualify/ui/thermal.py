"""The POST's temperature — one badge for its whole life (docs/ux-post-journey-termico.md).

A POST is born lit, gets hot while it generates, steams while it waits for the human,
is **frozen** when approved (it stops changing), gets a date, is published, and then is
either reusable (recurrente: the same cold POST goes back on the calendar) or archived
(promocional: used once). The temperature is the ONE lifecycle vocabulary the operator
sees — in the drafts list, on the Planificador card and in the detail header — instead
of the three the code has today (`DraftStatus`, the calendar event's status, and the
Planificador's approval label).

This module is the mapping, nothing else: real states in (the creative FSM's status,
the calendar event's status, the reuse type), a temperature out, and the badge that
renders it. It owns no state and reads no database.

Rules it encodes (design-system P1/P7, §5.2):

* every temperature is a **tone** (`ok`/`warn`/`error`/`info`/`neutral`), never a Radix
  colour name — the hot side is `warn`, the cold side is `info`, delivered is `ok`;
* every temperature has a static lucide glyph, and only five have an animation — the
  animation is the same file everywhere it appears, so the state looks the same on
  every screen;
* the word is always rendered next to the glyph.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import reflex as rx

from . import tokens as T
from .lottie import lottie

# ---------------------------------------------------------------------------------------
# The scale
# ---------------------------------------------------------------------------------------

LIT = "lit"  # Encendido — brief armed, nothing generated (no row yet; a UI state)
HOT = "hot"  # Caliente — generating (copy, render in flight)
STEAMING = "steaming"  # Humeante — generated, waiting for review; editable
OFF = "off"  # Apagado — rejected; nothing happens until it is reheated
FROZEN = "frozen"  # Congelado — approved: immutable
SCHEDULED = "scheduled"  # Programado — frozen, with a date
PUBLISHING = "publishing"  # En camino — staged on the platform / the worker is on it
PUBLISHED = "published"  # Publicado
REUSABLE = "reusable"  # Frío reutilizable — recurrente: ready to be scheduled again
ARCHIVED = "archived"  # Archivado — promocional, used once
FAILED = "failed"  # Fallido
UNKNOWN = "unknown"  # a status this module has never heard of: neutral, never alarm


@dataclass(frozen=True)
class Temperature:
    """One step of the scale, as the UI shows it."""

    key: str
    label: str  # the word in the badge
    tone: str  # a design-system tone
    icon: str  # lucide, the static glyph (lists, tables, reduced motion)
    verb: str  # what the operator does next, in the imperative
    hint: str  # one line for a tooltip / the detail header
    lottie: str | None = None  # `/lottie/<name>.json`, or None = static only
    loop: bool = False  # a looping animation = "something is happening right now"
    melt: str | None = None  # the animation played when LEAVING this state by editing


_SCALE: tuple[Temperature, ...] = (
    Temperature(
        LIT,
        "Encendido",
        "neutral",
        "zap",
        "Generar",
        "El brief está listo; aún no hay nada generado.",
    ),
    Temperature(
        HOT,
        "Caliente",
        "warn",
        "flame",
        "Esperar",
        "Se está cocinando: copy y salidas en curso.",
        "/lottie/flame.json",
        True,
    ),
    Temperature(
        STEAMING,
        "Humeante",
        "warn",
        "wind",
        "Revisar y congelar",
        "Generado. Edítalo o regenéralo; al aprobarlo se congela.",
        "/lottie/steam.json",
        True,
    ),
    Temperature(
        OFF,
        "Apagado",
        "neutral",
        "circle-slash",
        "Recalentar",
        "Rechazado. Regenerar lo vuelve a calentar.",
    ),
    Temperature(
        FROZEN,
        "Congelado",
        "info",
        "snowflake",
        "Programar",
        "Aprobado: ya no cambia. Editar lo descongela.",
        "/lottie/freeze.json",
        False,
        "/lottie/thaw.json",
    ),
    Temperature(
        SCHEDULED,
        "Programado",
        "info",
        "clock",
        "Esperar la hora",
        "Congelado con fecha. Se publica solo.",
        "/lottie/scheduled.json",
    ),
    Temperature(
        PUBLISHING,
        "En camino",
        "info",
        "send",
        "Esperar",
        "Preparado en la plataforma; publicando.",
    ),
    Temperature(
        PUBLISHED,
        "Publicado",
        "ok",
        "circle-check",
        "Ver en Instagram",
        "Ya está en tu cuenta.",
        "/lottie/published.json",
    ),
    Temperature(
        REUSABLE,
        "Frío · reutilizable",
        "info",
        "repeat",
        "Volver a programar",
        "Recurrente: el mismo post, listo para otra fecha.",
        "/lottie/freeze.json",
        False,
        "/lottie/thaw.json",
    ),
    Temperature(
        ARCHIVED,
        "Archivado",
        "neutral",
        "archive",
        "Duplicar",
        "Promocional: se usó una vez. Duplícalo para reusarlo.",
    ),
    Temperature(
        FAILED,
        "Fallido",
        "error",
        "triangle-alert",
        "Reintentar",
        "Algo falló; el motivo dice qué hacer.",
    ),
    Temperature(UNKNOWN, "Sin estado", "neutral", "circle-help", "", "Estado no reconocido."),
)

TEMPERATURES: dict[str, Temperature] = {t.key: t for t in _SCALE}

#: The scale in reading order (what `/design` shows). `UNKNOWN` is not a step.
SCALE_ORDER: tuple[str, ...] = tuple(t.key for t in _SCALE if t.key != UNKNOWN)


def temperature(key: str) -> Temperature:
    return TEMPERATURES.get(key, TEMPERATURES[UNKNOWN])


# ---------------------------------------------------------------------------------------
# Real states → temperature. The inputs are the vocabularies that exist today:
# `qualify_creative.enums.DraftStatus` values (the FSM), the calendar event's status
# (`planner_vm._STATUS_LABEL`) and `ReuseType` values. Plain strings, so this module
# compiles with or without the backend packages on the path.
# ---------------------------------------------------------------------------------------

RECURRENTE = "recurrente"
PROMOCIONAL = "promocional"

#: Draft statuses that mean "there is no row yet": the generator's own recap screen.
_BRIEF_STATUSES: frozenset[str] = frozenset({"", "brief"})


def thermal_for(
    status: str,
    *,
    reuse_type: str | None = None,
    event_status: str | None = None,
    publish_count: int = 0,
) -> str:
    """The temperature of a POST.

    ``status`` is the draft's FSM status; ``event_status`` the status of its calendar
    event when it has one (``scheduled`` / ``publishing`` / ``published`` / ``failed`` /
    ``cancelled``, or None); ``reuse_type`` ``recurrente`` / ``promocional`` / None;
    ``publish_count`` how many times it has already gone out (a recurrente POST that was
    published once and is approved again is reusable, not merely frozen).

    Precedence, top to bottom: a failure anywhere is Fallido; then the draft's own
    status; the event only refines an approved POST (date → Programado, in flight → En
    camino); reuse only refines a published one.
    """
    if status == "failed" or event_status == "failed":
        return FAILED
    if status in _BRIEF_STATUSES:
        return LIT
    if status == "drafting":
        return HOT
    if status == "generated":
        return STEAMING
    if status == "rejected":
        return OFF
    if status == "staged" or event_status == "publishing":
        return PUBLISHING
    if status == "approved":
        if event_status == "scheduled":
            return SCHEDULED
        if reuse_type == RECURRENTE and publish_count > 0:
            return REUSABLE
        return FROZEN
    if status == "published":
        if reuse_type == RECURRENTE:
            return REUSABLE
        if reuse_type == PROMOCIONAL:
            return ARCHIVED
        return PUBLISHED
    return UNKNOWN


# ---------------------------------------------------------------------------------------
# Transitions: which temperature changes exist, and which animation accompanies each.
# Derived from the creative FSM's edges + the Planificador's event lifecycle + the reuse
# rule; `test_thermal_vm.py` pins that every FSM edge lands on an allowed transition.
# ---------------------------------------------------------------------------------------

IGNITE = "ignite"  # the flame lights (flame.json from frame 0, then loops)
COOL = "cool"  # flame → steam cross-fade (CSS, DUR)
FREEZE = "freeze"  # freeze.json forward, once
THAW = "thaw"  # freeze.json in reverse, once, then steam
TICK = "tick"  # scheduled.json once
DELIVER = "deliver"  # published.json once
NONE = None  # the badge simply changes (with its colour transition); nothing plays

TRANSITIONS: dict[tuple[str, str], str | None] = {
    (LIT, HOT): IGNITE,  # Generar
    (HOT, STEAMING): COOL,  # generate_ok
    (HOT, FAILED): NONE,  # generate_fail / reap
    (STEAMING, STEAMING): NONE,  # edit while reviewing
    (STEAMING, FROZEN): FREEZE,  # approve = Congelar
    (STEAMING, OFF): NONE,  # reject
    (OFF, OFF): NONE,  # edit a rejected draft
    (OFF, HOT): IGNITE,  # regenerate = Recalentar
    (FROZEN, STEAMING): THAW,  # edit = Descongelar (a new revision, re-approve)
    (FROZEN, SCHEDULED): TICK,  # Asignar in the Planificador
    (FROZEN, PUBLISHING): NONE,  # stage
    (FROZEN, PUBLISHED): DELIVER,  # publish now, never staged (FSM: approved --publish_ok-->)
    (SCHEDULED, FROZEN): NONE,  # event cancelled or expired
    (SCHEDULED, PUBLISHING): NONE,  # the worker claims the event
    (SCHEDULED, PUBLISHED): DELIVER,  # the worker published it in one tick
    (SCHEDULED, FAILED): NONE,  # the event failed
    (PUBLISHING, PUBLISHED): DELIVER,  # publish_ok
    (PUBLISHING, FROZEN): NONE,  # stage_expired
    (PUBLISHING, FAILED): NONE,
    (PUBLISHED, REUSABLE): NONE,  # recurrente, automatic
    (PUBLISHED, ARCHIVED): NONE,  # promocional, automatic
    (REUSABLE, SCHEDULED): TICK,  # schedule it again
    (REUSABLE, STEAMING): THAW,  # edit a reusable post (new revision)
    (ARCHIVED, LIT): NONE,  # duplicate as a new post (a new row)
    (FAILED, HOT): IGNITE,  # retry / regenerate
}


def transition(from_key: str, to_key: str) -> str | None:
    """The animation for a temperature change, or None for a plain badge swap. Raises
    ``KeyError`` for a change the lifecycle does not allow — a UI that asks for one has
    a bug, not a missing animation."""
    return TRANSITIONS[(from_key, to_key)]


def allowed_next(from_key: str) -> tuple[str, ...]:
    return tuple(to for (frm, to) in TRANSITIONS if frm == from_key and to != frm)


# ---------------------------------------------------------------------------------------
# The badge
# ---------------------------------------------------------------------------------------

_GLYPH_SIZE: Mapping[str, str] = {"1": "1rem", "2": "1.25rem", "3": "1.5rem"}


def _badge(temp: Temperature, *, animate: bool, size: str) -> rx.Component:
    if animate and temp.lottie:
        glyph = lottie(
            temp.lottie,
            loop=temp.loop,
            size=_GLYPH_SIZE.get(size, "1rem"),
            reduced_motion_fallback=temp.icon,
            tone=temp.tone,
        )
    else:
        glyph = rx.icon(temp.icon, size=12 if size == "1" else T.ICON_SM)
    return rx.badge(
        glyph,
        temp.label,
        variant="soft",
        size=size,
        radius="full",
        class_name="q-thermal",
        title=temp.hint,
        **T.tone_scheme(temp.tone),
    )


def thermal_badge(
    state: str | rx.Var[str], *, animate: bool = False, size: str = "1"
) -> rx.Component:
    """The temperature as a badge: tone + glyph + word.

    ``animate=False`` (the default, and the rule for lists, tables and Planificador
    cards) draws the static lucide glyph. ``animate=True`` — the detail header and the
    result screen only — plays the temperature's animation: looping for Caliente and
    Humeante (something is happening), once for Congelado, Programado, Publicado (a
    moment). At most one looping animation per screen.
    """
    if isinstance(state, str):
        return _badge(temperature(state), animate=animate, size=size)
    return rx.match(
        state,
        *[(key, _badge(temp, animate=animate, size=size)) for key, temp in TEMPERATURES.items()],
        _badge(TEMPERATURES[UNKNOWN], animate=animate, size=size),
    )


def thermal_glyph(state: str, *, size: str = "4rem", melting: bool = False) -> rx.Component:
    """The temperature's animation on its own, big — the hero of a transition moment
    (the freeze when approving, the check when published). Static temperatures draw
    their icon in the tone's colour. ``melting=True`` plays the state's ``melt`` file —
    the thaw of Congelado — which only the cold states have."""
    temp = temperature(state)
    src = temp.melt if melting else temp.lottie
    if melting and not src:
        raise ValueError(f"{state!r} has no melt animation")
    if src:
        return lottie(
            src,
            loop=temp.loop,
            size=size,
            reduced_motion_fallback=temp.icon,
            tone=temp.tone,
        )
    return rx.box(
        rx.icon(temp.icon, size=T.ICON_LG, color=T.tone_color(temp.tone, 9)),
        width=size,
        height=size,
        display="flex",
        align_items="center",
        justify_content="center",
        aria_hidden="true",
    )
