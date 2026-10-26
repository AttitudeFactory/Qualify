"""Plain-language final review states; no provider, session or database objects."""

from __future__ import annotations

from dataclasses import dataclass

FINAL_SCHEDULED_NOTE = "Tu video final estará listo mañana temprano."
FINAL_NIGHT_RUNNING_NOTE = "Tu video final estará listo en unas horas."
FINAL_IMMEDIATE_NOTE = (
    "Tu video final estará listo en unos minutos. Te lo mostramos aquí para que lo confirmes."
)
FINAL_READY_NOTE = "Tu video final está listo. Míralo y confírmalo para que salga."
FINAL_FAILED_NOTE = "No pudimos preparar el video final. Inténtalo de nuevo; no usa otro video."
FINAL_APPROVED_NOTE = (
    "Tu video final estará listo mañana temprano. Elige ya cuándo sale: "
    "lo confirmas antes de que salga."
)
FINAL_KEEP_NOTE = (
    "Te quedas con esta versión. Esta noche preparamos el video final "
    "y mañana lo confirmas antes de que salga."
)


@dataclass(frozen=True)
class FinalVideoVM:
    url: str
    label: str


@dataclass(frozen=True)
class FinalPanelVM:
    piece_id: str = ""
    title: str = "Revisa el video final"
    state: str = ""
    badge: str = ""
    tone: str = "neutral"
    note: str = ""
    videos: tuple[FinalVideoVM, ...] = ()
    date_note: str = "Todavía sin fecha"
    can_confirm: bool = False
    can_retry: bool = False
    can_another: bool = False
    another_note: str = ""
    confirm_label: str = "Confirmar video"
    confirmed_note: str = ""
    reschedule_href: str = ""
    event_id: str = ""
    next_count: int = 0
    next_label: str = ""
    other_version_pending: str = ""


def final_state(
    state: str,
    *,
    nightly: bool = False,
    during_night: bool = False,
    overdue: bool = False,
    expired: bool = False,
    hour: str = "",
) -> tuple[str, str, str]:
    if expired:
        return "Vencido", "warn", "La hora de esta publicación ya venció. Elige otra hora."
    if overdue and state != "final":
        return (
            "Falta tu confirmación",
            "warn",
            f"No salió a las {hour} porque falta que confirmes el video.",
        )
    if state == "final_scheduled":
        return "Video final mañana", "neutral", FINAL_SCHEDULED_NOTE
    if state == "rendering":
        if nightly:
            return (
                "Video final mañana",
                "neutral",
                FINAL_NIGHT_RUNNING_NOTE if during_night else FINAL_SCHEDULED_NOTE,
            )
        return "Preparando el video final", "info", FINAL_IMMEDIATE_NOTE
    if state == "final_ready":
        return "Revisa el video", "warn", FINAL_READY_NOTE
    if state == "final":
        return "Listo para publicar", "ok", "Video confirmado."
    if state == "failed":
        return "Falta el video final", "error", FINAL_FAILED_NOTE
    return (
        "Por revisar",
        "warn",
        "Estamos creando otra versión. Cuando esté, la revisas y la apruebas.",
    )


def another_version_use(videos_left: int, *, quota: int = 4, renews: str = "") -> str:
    if videos_left <= 0:
        return f"Ya usaste tus {quota} videos de este mes." + (
            f" Vuelven el {renews}." if renews else ""
        )
    left = videos_left - 1
    ending = "Te quedaría 1." if left == 1 else f"Te quedarían {left}."
    return "Usa 1 vista previa y 1 de tus videos del mes. " + ending


def other_version_pending(
    *, day: str = "", hour: str = "", today: bool = False, dates: int = 0
) -> str:
    start = "Estamos creando otra versión. Cuando esté, la revisas y la apruebas."
    end = ": si no la confirmas antes, no se publica."
    if dates > 1:
        return start + f" Sigue programada en las {dates} fechas que elegiste" + end
    if dates == 1:
        when = "hoy" if today else f"el {day}"
        return start + f" Sigue programada para {when} a las {hour}" + end
    return start


def confirmation_note(*, dates: int, day: str = "", hour: str = "") -> str:
    if dates > 1:
        return f"Confirmado. Sale en las {dates} fechas que elegiste."
    if dates:
        return f"Confirmado. Sale el {day} a las {hour.rstrip(chr(46))}."
    return "Confirmado. Ahora elige cuándo sale."
