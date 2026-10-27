"""Client-safe account access and literal comments copy (m-24854867)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from .planner_vm import time_label_12h


@dataclass(frozen=True)
class InboxConnectionVM:
    id: str
    external_username: str
    platform: str
    label: str
    status: str = "active"
    reconnect_reason: str = ""


@dataclass(frozen=True)
class InboxAccessVM:
    title: str = ""
    detail: str = ""
    needs_reconnect: bool = False
    cause: str = ""
    temporary_warning: bool = False


def access_moment(moment: datetime, zone: ZoneInfo) -> str:
    """The business's clock, independent of the server's locale/timezone."""
    local = (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).astimezone(zone)
    day = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
    return f"el {day[local.weekday()]} {time_label_12h(local)}"


def access_notice(
    *, status: str, cause: str, account: str, since: str, failures: int = 0
) -> InboxAccessVM:
    if status == "revoked":
        return InboxAccessVM(
            detail=f"{account} ya no está conectada a Qualify. Lo que ya tenías sigue aquí; "
            "para recibir lo nuevo, conéctala otra vez.",
            needs_reconnect=True,
            cause=cause or "auth_expired",
        )
    if cause == "permission_missing":
        return InboxAccessVM(
            title=f"Falta un paso para ver los comentarios de {account}",
            detail="Facebook no nos deja leer los comentarios de esta cuenta. Vuelve a "
            "conectarla y deja marcadas todas las casillas que te muestre.",
            needs_reconnect=True,
            cause=cause,
        )
    if status == "degraded":
        since_sentence = since.rstrip(".") + "."
        return InboxAccessVM(
            title=f"Instagram de {account} se desconectó",
            detail=f"No llegan comentarios nuevos desde {since_sentence} "
            "Los que ya tenías siguen aquí.",
            needs_reconnect=True,
            cause=cause or "auth_expired",
        )
    if failures >= 3:
        return InboxAccessVM(
            title="Instagram está tardando en responder",
            detail="Seguimos intentando cada pocos minutos. No tienes que hacer nada.",
            temporary_warning=True,
        )
    return InboxAccessVM()
