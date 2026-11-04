"""Display-only promotion drafts and local validation; no advertising authorization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

STEP_TITLES = (
    "¿Qué publicación quieres promocionar?",
    "¿A qué página los llevamos?",
    "¿A quién quieres llegar?",
    "¿Cuánto quieres invertir?",
)
LOAD_FAILED = "No pudimos consultar esta publicación. Vuelve a intentarlo."
PREVIEW_FAILED = "No pudimos preparar el anuncio. Revisa los datos y vuelve a intentarlo."
CONFIRM_FAILED = (
    "No pudimos confirmar el resultado. Revisa el anuncio antes de volver a intentarlo."
)
NO_SESSION = "Vuelve a iniciar sesión para preparar este anuncio."
EMPTY_SOURCES = (
    "No encontramos una publicación de Instagram que puedas promocionar desde esta pieza. "
    "Vuelve a la publicación o revisa otra que ya haya salido en Instagram."
)


@dataclass(frozen=True)
class PromotionSourceVM:
    id: str
    account_label: str
    caption: str
    account_name: str = ""
    currency: str = ""
    default_link_url: str = ""
    timezone_name: str = ""
    published_label: str = ""
    unavailable_reason: str = ""


@dataclass(frozen=True)
class PromotionDraftVM:
    source_id: str = ""
    link_url: str = ""
    city_name: str = ""
    radius_km: str = "10"
    age_min: str = "18"
    age_max: str = "65"
    advantage_audience: bool = False
    housing: bool = False
    budget: str = ""
    start_local: str = ""
    end_local: str = ""


@dataclass(frozen=True)
class PromotionReviewVM:
    promotion_id: str = ""
    review_id: str = ""
    preview_url: str = ""
    charge_notice: str = ""
    expires_label: str = ""


def cop_minor(value: str) -> int:
    """Whole pesos, never a float or an ambiguous thousands separator."""
    value = value.strip()
    if not value.isascii() or not value.isdigit() or not 0 < int(value) < 10**10:
        raise ValueError("Escribe el presupuesto en pesos, sin puntos ni comas. Ejemplo: 25000.")
    return int(value) * 100


def cop_label(value: str) -> str:
    try:
        minor = cop_minor(value)
    except ValueError:
        return "Presupuesto por definir"
    return "$" + f"{minor // 100:,}".replace(",", ".") + " COP"


def readable_date(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%d/%m/%Y · %H:%M")
    except ValueError:
        return "Por definir"


def local_datetime(value: str, timezone_name: str) -> datetime:
    """Reject unknown zones, DST gaps and ambiguous local hours instead of assuming UTC."""
    try:
        zone = ZoneInfo(timezone_name)
        naive = datetime.fromisoformat(value)
        if naive.tzinfo is not None:
            raise ValueError
        local = naive.replace(tzinfo=zone)
        if local.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != naive:
            raise ValueError
        if local.utcoffset() != naive.replace(tzinfo=zone, fold=1).utcoffset():
            raise ValueError
        return local
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError("Revisa las fechas y la zona horaria de tu negocio.") from None


def step_problem(draft: PromotionDraftVM, step: int, timezone_name: str = "") -> str:
    """Local form guidance only; Meta eligibility, minimum and payment are server gates."""
    if step == 1:
        return "Elige la publicación que quieres promocionar." if not draft.source_id else ""
    if step == 2:
        try:
            url = urlsplit(draft.link_url.strip())
            valid = (
                url.scheme == "https"
                and url.hostname
                and not (url.username or url.password)
                and not any(char.isspace() for char in draft.link_url)
            )
        except ValueError:
            valid = False
        return "" if valid else "Escribe un enlace completo que comience por https://."
    if step == 3:
        if len(draft.city_name.strip()) < 2:
            return "Escribe la ciudad donde quieres mostrar el anuncio."
        try:
            radius, low, high = int(draft.radius_km), int(draft.age_min), int(draft.age_max)
            valid = 1 <= radius <= 80 and 18 <= low <= high <= 65
        except ValueError:
            valid = False
        return "" if valid else "Usa un radio entre 1 y 80 km y edades entre 18 y 65 años."
    if step == 4:
        try:
            cop_minor(draft.budget)
            start = local_datetime(draft.start_local, timezone_name)
            end = local_datetime(draft.end_local, timezone_name)
            if end <= start:
                return "El final debe ser posterior al inicio."
        except ValueError as exc:
            return str(exc)
    return ""


def first_problem(draft: PromotionDraftVM, timezone_name: str) -> str:
    return next(
        (reason for n in range(1, 5) if (reason := step_problem(draft, n, timezone_name))), ""
    )
