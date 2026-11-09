"""«Tu video completo» of a video by parts (m-24921084, `docs/ux-video-por-planos.md`
§3e and §4): plain-language words and states for the card under the parts list. Pure —
no state, provider, session or database object.

It reads the backend's `qualify_api.creative.final_video.FinalVideo` through the small
`FinalVideoFacts` protocol (attribute names only), so this module never imports the
join machinery. The month's video is counted in SECONDS (ADR 44 F1 = (b), VE-21): every
«videos del mes» of the UX copy reads «segundos de video del mes» here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .creative_vm import approval_videos_notice, renewal_day_label, videos_short_text

# the backend's `JoinState` / `Blocker` values (strings: no import of the backend)
WAITING = "waiting"
JOINING = "joining"
REJOINING = "rejoining"
READY = "ready"
FAILED = "failed"
APPROVED = "approved"
PURGED = "purged"

TITLE = "Tu video completo"
PREVIEW_BADGE = "Vista previa"
JOINING_WORD = "Juntando"
JOINING_TEXT = "Juntando tus partes…"
FAILED_WORD = "No salió"
PREVIEW_TEXT = (
    "Es una vista previa en calidad baja, para que decidas rápido. Al aprobarla "
    "preparamos cada parte en alta calidad y las juntamos."
)
APPROVE_LABEL = "Aprobar"
CHANGE_PART_LABEL = "Cambiar una parte"
JOIN_FAILED_TEXT = (
    "No pudimos juntar tus partes. Siguen guardadas y no se descontó nada. Toca «Juntar otra vez»."
)
REJOIN_LABEL = "Juntar otra vez"
#: `qualify_api.creative.parts.PURGED_PARENT_TEXT` (founder's text, m-24921069) — the
#: same words, kept equal by a test
PURGED_TEXT = (
    "Los archivos de este video ya se borraron, así que ya no puedes cambiar sus partes. "
    "Crea un video nuevo para empezar otra vez."
)
#: every part has its vista previa and the joined one is on its way (copy propuesto)
APPROVE_WAIT_JOIN_HINT = "Disponible cuando terminemos de juntar tus partes."

_WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


class VideoUseFacts(Protocol):
    uses: int
    quota: int
    left: int
    unlimited: bool
    in_seconds: bool
    renews_on: date | None


class PreviewUseFacts(Protocol):
    uses: int
    left: int
    quota: int
    unlimited: bool
    renews_on: date | None


class FinalVideoFacts(Protocol):
    """What the card reads of the backend's `FinalVideo`."""

    @property
    def state(self) -> str: ...
    @property
    def seconds(self) -> int: ...
    @property
    def planned(self) -> int: ...
    @property
    def can_approve(self) -> bool: ...
    @property
    def blocker(self) -> str | None: ...
    @property
    def expires_at(self) -> datetime | None: ...
    @property
    def expired_parts(self) -> tuple[int, ...]: ...
    @property
    def failed_parts(self) -> tuple[int, ...]: ...
    @property
    def redo_parts(self) -> tuple[int, ...]: ...
    @property
    def video_use(self) -> VideoUseFacts | None: ...
    @property
    def recreate_use(self) -> PreviewUseFacts | None: ...


@dataclass(frozen=True)
class ExpiredPartVM:
    """One expired part's notice (§4 «Vista previa vencida»); the action is the card's
    one recreate button."""

    index: int
    text: str


@dataclass(frozen=True)
class FinalVideoCardVM:
    header: str  # «Tu video completo · 18 s · Vista previa»
    title: str
    seconds_label: str  # «18 s»
    badge: str  # «Vista previa»
    pill_word: str  # «Juntando» / «No salió» / "" (no pill)
    pill_tone: str  # `signal_pill` tone: info / error / neutral
    status_text: str  # «Juntando tus partes…» / the join failure / purged / ""
    show_video: bool  # a joined preview to play (the earlier one while rejoining)
    preview_text: str
    deadline_text: str  # «Apruébalo antes del jueves 6 de noviembre para tener el video final.»
    approve_visible: bool
    approve_label: str
    approve_enabled: bool
    approve_hint: str  # why it is off, beside the button ("" when on)
    quota_text: str  # «Al aprobar usas 15 de tus 40 segundos de video del mes. …»
    change_part_visible: bool
    change_part_label: str
    rejoin_visible: bool
    rejoin_label: str
    recreate_visible: bool
    recreate_label: str  # «Crear la parte 3 otra vez» / «Crear las partes 2 y 3 otra vez»
    recreate_text: str  # «Crea otra vez la parte 3. Usa 1 vista previa. Te quedan 9 …»
    expired_parts: tuple[ExpiredPartVM, ...] = ()


def seconds_header(seconds: int) -> str:
    """«Tu video completo · 18 s · Vista previa» (no length while it is unknown)."""
    if seconds > 0:
        return f"{TITLE} · {seconds} s · {PREVIEW_BADGE}"
    return f"{TITLE} · {PREVIEW_BADGE}"


def pill(state: str) -> tuple[str, str]:
    """The `signal_pill` (word, tone) of the card's header: «Juntando» (`info`) only
    while the parts are really being joined, «No salió» (`error`) when they could not
    be; none while waiting for the parts, once ready, approved or purged."""
    if state in (JOINING, REJOINING):
        return JOINING_WORD, "info"
    if state == FAILED:
        return FAILED_WORD, "error"
    return "", "neutral"


def local_day(moment: datetime, zone: str) -> datetime:
    """`moment` in the business's zone (UTC when the zone is unknown)."""
    try:
        return moment.astimezone(ZoneInfo(zone))
    except (ZoneInfoNotFoundError, ValueError):
        return moment


def deadline_text(expires_at: datetime | None, zone: str = "UTC") -> str:
    """«Apruébalo antes del jueves 6 de noviembre para tener el video final.» — the
    nearest of the parts' deadlines, in the business's zone ("" when unknown)."""
    if expires_at is None:
        return ""
    day = local_day(expires_at, zone)
    return (
        f"Apruébalo antes del {_WEEKDAYS[day.weekday()]} {day.day} de "
        f"{_MONTHS[day.month - 1]} para tener el video final."
    )


def parts_list(indexes: Sequence[int]) -> str:
    """«la parte 3» / «las partes 2 y 3» / «las partes 1, 2 y 4»."""
    if len(indexes) == 1:
        return f"la parte {indexes[0]}"
    head = ", ".join(str(i) for i in indexes[:-1])
    return f"las partes {head} y {indexes[-1]}"


def approve_hint(facts: FinalVideoFacts) -> str:
    """Beside a disabled «Aprobar», one notice per reason: «Disponible cuando cambies la
    parte 2.» (failed or to redo), «Disponible cuando crees otra vez la parte 3.»
    (expired), «Disponible cuando las 4 partes tengan su vista previa.» (still being
    made), `APPROVE_WAIT_JOIN_HINT` (only the join missing). "" when on, approved,
    purged, or the join failed (its own message says what to do)."""
    blocker = None if facts.blocker is None else str(facts.blocker)
    if facts.can_approve or blocker in (None, APPROVED, PURGED, "join_failed"):
        return ""
    if blocker in ("part_failed", "needs_redo"):
        fix = sorted({*facts.failed_parts, *facts.redo_parts})
        if fix:
            return f"Disponible cuando cambies {parts_list(fix)}."
    if blocker == "expired" and facts.expired_parts:
        return f"Disponible cuando crees otra vez {parts_list(facts.expired_parts)}."
    if blocker == "joining":
        return APPROVE_WAIT_JOIN_HINT
    if facts.planned == 1:
        return "Disponible cuando la parte tenga su vista previa."
    return f"Disponible cuando las {facts.planned} partes tengan su vista previa."


def quota_text(use: VideoUseFacts | None) -> str:
    """Beside «Aprobar», in seconds: «Al aprobar usas 15 de tus 40 segundos de video del
    mes. Te quedarían 25 segundos.» — or, when the month cannot pay it all, the
    shortfall («Esta publicación usa 15 segundos de video y este mes te quedan 10…»).
    "" without a quota, with an unlimited plan, or when approving uses nothing."""
    if use is None or use.unlimited or use.quota <= 0 or use.uses <= 0:
        return ""
    if use.uses > use.left:
        return videos_short_text(
            use.uses, use.left, use.quota, renews=renewal_day_label(use.renews_on)
        )
    return approval_videos_notice(use.uses, use.left, use.quota)


def _previews(count: int) -> str:
    return "1 vista previa" if count == 1 else f"{count} vistas previas"


def recreate_label(indexes: Sequence[int]) -> str:
    """The card's ONE button: «Crear la parte 3 otra vez» / «Crear las partes 2 y 3
    otra vez». "" without an expired part."""
    return f"Crear {parts_list(indexes)} otra vez" if indexes else ""


def recreate_text(indexes: Sequence[int], use: PreviewUseFacts | None) -> str:
    """The line under that button (UX §3e), always naming the unit: «Crea otra vez la
    parte 3. Usa 1 vista previa. Te quedan 9 vistas previas.» — and, when the month is
    short, when they come back: «… y este mes te queda 1 vista previa. Vuelven el 1 de
    diciembre.» "" without an expired part."""
    if not indexes:
        return ""
    what = f"Crea otra vez {parts_list(indexes)}."
    if use is None or use.unlimited or use.quota <= 0 or use.uses <= 0:
        return what
    verb = "Usa" if len(indexes) == 1 else "Usan"
    left = ("te queda " if use.left == 1 else "te quedan ") + _previews(max(use.left, 0))
    if use.uses > use.left:
        day = renewal_day_label(use.renews_on)
        back = f" Vuelven el {day}." if day else ""
        return f"{what} {verb} {_previews(use.uses)} y este mes {left}.{back}"
    return f"{what} {verb} {_previews(use.uses)}. {left[0].upper()}{left[1:]}."


def expired_part(index: int) -> ExpiredPartVM:
    """§4 «Vista previa vencida (7 días)», for one part."""
    return ExpiredPartVM(
        index=index,
        text=(
            f"La vista previa de la parte {index} venció. "
            "Créala otra vez para tener el video final."
        ),
    )


def final_video_card(facts: FinalVideoFacts, *, zone: str = "UTC") -> FinalVideoCardVM:
    """The whole card from the backend's `FinalVideo`. Pure."""
    state = str(facts.state)
    word, tone = pill(state)
    if state in (JOINING, REJOINING):
        status = JOINING_TEXT
    elif state == FAILED:
        status = JOIN_FAILED_TEXT
    elif state == PURGED:
        status = PURGED_TEXT
    else:
        status = ""
    closed = state in (APPROVED, PURGED)
    expired = () if closed else tuple(facts.expired_parts)
    return FinalVideoCardVM(
        header=seconds_header(facts.seconds),
        title=TITLE,
        seconds_label=f"{facts.seconds} s" if facts.seconds > 0 else "",
        badge=PREVIEW_BADGE,
        pill_word=word,
        pill_tone=tone,
        status_text=status,
        show_video=state in (READY, REJOINING),
        preview_text=PREVIEW_TEXT if state in (READY, REJOINING) else "",
        deadline_text="" if closed else deadline_text(facts.expires_at, zone),
        approve_visible=not closed,
        approve_label=APPROVE_LABEL,
        approve_enabled=bool(facts.can_approve),
        approve_hint=approve_hint(facts),
        quota_text="" if closed else quota_text(facts.video_use),
        change_part_visible=not closed,
        change_part_label=CHANGE_PART_LABEL,
        rejoin_visible=state == FAILED,
        rejoin_label=REJOIN_LABEL,
        recreate_visible=bool(expired),
        recreate_label=recreate_label(expired),
        recreate_text=recreate_text(expired, facts.recreate_use),
        expired_parts=tuple(expired_part(i) for i in expired),
    )


__all__ = [
    "APPROVE_LABEL",
    "APPROVE_WAIT_JOIN_HINT",
    "CHANGE_PART_LABEL",
    "JOIN_FAILED_TEXT",
    "JOINING_TEXT",
    "JOINING_WORD",
    "PREVIEW_TEXT",
    "PURGED_TEXT",
    "REJOIN_LABEL",
    "TITLE",
    "ExpiredPartVM",
    "FinalVideoCardVM",
    "FinalVideoFacts",
    "approve_hint",
    "deadline_text",
    "expired_part",
    "final_video_card",
    "parts_list",
    "pill",
    "quota_text",
    "recreate_label",
    "recreate_text",
    "seconds_header",
]
