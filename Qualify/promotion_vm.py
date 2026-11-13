"""Display-only promotion drafts and local validation; no advertising authorization."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from qualify_api.ads.wizard import WEBSITE_CTAS
from qualify_creative.ad_destination import AD_CTA_LABELS, AdCTA

from .ad_custom_audiences_vm import CustomAudienceVM
from .ad_enhancements_vm import BrandEnhancementsVM
from .ad_health_vm import AccountHealthVM
from .promotion_audience_vm import AudienceInterestVM

STEP_TITLES = (
    "¿Qué publicación quieres promocionar?",
    "¿Qué quieres que haga la gente?",
    "¿A quién quieres llegar?",
    "¿Cuánto quieres invertir?",
)
# m-24828982: an approved, unpublished piece is another source of the same wizard. Its
# steps follow the backend's recipe (two files of the piece, explicit text, one country);
# placements are fixed: 4:5 in the feed, 9:16 in stories and reels.
PUBLISHED_STEPS = ("source", "destination", "audience", "budget")
IMAGE_STEPS = ("source", "images", "text", "country", "budget")
VIDEO_STEPS = ("source", "feed_video", "vertical_video", "covers", "text", "country", "budget")
STEP_TITLE_BY_KEY = dict(zip(PUBLISHED_STEPS, STEP_TITLES, strict=True)) | {
    "images": "Elige las dos imágenes del anuncio",
    "feed_video": "Video para el perfil (4:5)",
    "vertical_video": "Video vertical de pantalla completa (9:16)",
    "covers": "Portadas",
    "text": "¿Qué dirá tu anuncio?",
    "country": "¿En qué país quieres mostrarlo?",
}
UNPUBLISHED_SOURCE_TITLE = "¿Con qué cuenta quieres anunciar esta pieza?"
COUNTRY_LABELS = {"CO": "Colombia", "VE": "Venezuela", "UY": "Uruguay"}
VIDEO_WAITING = "Meta está preparando tu video. Te avisamos aquí; puedes salir."
# Lead-ad buttons in the order the owner sees them (m-25026344); codes from `lead_ads.LEAD_CTAS`.
LEAD_CTA_LABELS = {
    "GET_QUOTE": "Pedir cotización",
    "SIGN_UP": "Registrarme",
    "LEARN_MORE": "Más información",
}
# Buttons for an ad that opens a web page (m-24828976): the server allowlist, with the
# same names the owner saw when saving the piece.
WEBSITE_CTA_LABELS = {code: AD_CTA_LABELS[AdCTA(code)] for code in WEBSITE_CTAS}
CHECK_LABELS = {
    "permissions": "Permisos de Meta",
    "account": "Cuenta publicitaria",
    "payment": "Método de pago",
    "media": "Publicación de Instagram",
    "currency": "Importe y moneda",
    "validation": "Configuración del anuncio",
    "remote": "Anuncio creado en pausa",
}
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
class MessagingDestinationVM:
    key: str
    label: str
    notice: str


@dataclass(frozen=True)
class LeadFormChoiceVM:
    id: str
    name: str


@dataclass(frozen=True)
class AdMediaVM:
    """One final file of the piece's active version; `url` is a short-lived view path."""

    id: str
    url: str = ""
    media_type: str = "image"
    label: str = ""


@dataclass(frozen=True)
class PromotionSourceVM:
    id: str
    account_label: str
    caption: str
    account_name: str = ""
    currency: str = ""
    default_link_url: str = ""
    default_cta_type: str = "LEARN_MORE"
    timezone_name: str = ""
    published_label: str = ""
    unavailable_reason: str = ""
    # The block is the piece's own button: the fix is in the piece, not in Tus redes.
    fix_in_piece: bool = False
    health: AccountHealthVM = field(default_factory=AccountHealthVM)
    ad_account_id: str = ""
    messaging_destinations: list[MessagingDestinationVM] = field(default_factory=list)
    connection_id: str = ""
    enhancements: BrandEnhancementsVM = field(default_factory=BrandEnhancementsVM)
    brand_id: str = ""
    # Ready (published) forms of this source's account, last used first.
    lead_forms: list[LeadFormChoiceVM] = field(default_factory=list)
    lead_forms_error: str = ""
    # m-24828982: "" = a published post; "images"/"videos" = the piece's unpublished pair.
    media_kind: str = ""
    feed_media: list[AdMediaVM] = field(default_factory=list)
    vertical_media: list[AdMediaVM] = field(default_factory=list)
    feed_covers: list[AdMediaVM] = field(default_factory=list)
    vertical_covers: list[AdMediaVM] = field(default_factory=list)
    default_message: str = ""
    default_headline: str = ""
    default_country: str = ""


@dataclass(frozen=True)
class PromotionDraftVM:
    source_id: str = ""
    goal: str = "visit"  # "visit" (link) or "lead" (Meta form)
    link_url: str = ""
    lead_form_id: str = ""
    lead_cta: str = "GET_QUOTE"
    cta_type: str = "LEARN_MORE"
    city_name: str = ""
    location_key: str = ""
    location_kind: str = "city"
    location_country: str = ""
    location_region: str = ""
    radius_km: str = ""
    age_min: str = "18"
    age_max: str = "65"
    advantage_audience: bool = False
    housing: bool = False
    gender: str = "all"
    interests: list[AudienceInterestVM] = field(default_factory=list)
    placement_mode: str = "automatic"
    placements: list[str] = field(default_factory=list)
    custom_audiences: list[CustomAudienceVM] = field(default_factory=list)
    budget: str = ""
    start_local: str = ""
    end_local: str = ""
    enhancements: BrandEnhancementsVM = field(default_factory=BrandEnhancementsVM)
    media_kind: str = ""
    feed_asset_id: str = ""
    vertical_asset_id: str = ""
    feed_cover_id: str = ""
    vertical_cover_id: str = ""
    message: str = ""
    headline: str = ""
    country: str = ""


@dataclass(frozen=True)
class PromotionCheckVM:
    key: str = ""
    label: str = "Comprobación pendiente"
    status: str = "unavailable"
    detail: str = "No pudimos confirmar esta comprobación. Vuelve a consultar."


def promotion_checks(raw: object) -> list[PromotionCheckVM]:
    """Only closed, owner-readable diagnostics cross the presentation boundary."""
    if raw is None or raw == () or raw == []:
        return []
    if not isinstance(raw, tuple | list) or len(raw) > len(CHECK_LABELS):
        return [PromotionCheckVM()]
    rows = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            rows.append(PromotionCheckVM())
            continue
        key, status, detail = item.get("key"), item.get("status"), item.get("detail")
        if (
            not isinstance(key, str)
            or key not in CHECK_LABELS
            or key in seen
            or not isinstance(status, str)
            or status not in {"verified", "blocked", "unavailable"}
            or not isinstance(detail, str)
            or not detail.strip()
            or len(detail) > 1000
        ):
            rows.append(PromotionCheckVM())
            continue
        seen.add(key)
        rows.append(
            PromotionCheckVM(
                key=key,
                label=CHECK_LABELS[key],
                status=status,
                detail=(
                    "Meta informa que hay un método de pago registrado. "
                    "Esto no garantiza que acepte el cobro."
                    if key == "payment" and status == "verified"
                    else detail
                ),
            )
        )
    return rows


@dataclass(frozen=True)
class PromotionReviewVM:
    promotion_id: str = ""
    review_id: str = ""
    preview_url: str = ""
    charge_notice: str = ""
    expires_label: str = ""
    checks: list[PromotionCheckVM] = field(default_factory=list)
    # m-24828982: the unpublished recipe and its 9:16 preview (stories and reels).
    recipe_id: str = ""
    vertical_preview_url: str = ""


@dataclass(frozen=True)
class PromotionResultVM:
    promotion_id: str = ""
    status: str = ""
    message: str = ""


def promotion_result(raw: object, expected_id: str) -> PromotionResultVM:
    """Unknown provider outcomes cannot become a successful launch or a paid retry."""
    status = getattr(raw, "status", "unknown")
    if (
        not isinstance(status, str)
        or status not in {"active", "unknown", "pending"}
        or str(getattr(raw, "promotion_id", "")) != expected_id
    ):
        status = "unknown"
    return PromotionResultVM(
        promotion_id=expected_id,
        status=status,
        message=(
            "Activación solicitada a Meta. Meta todavía puede revisar el anuncio."
            if status == "active"
            else "No pudimos confirmar si Meta activó el anuncio. "
            "Revisa su estado antes de repetir la operación."
        ),
    )


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


def step_keys(draft: PromotionDraftVM) -> tuple[str, ...]:
    if draft.media_kind == "videos":
        return VIDEO_STEPS
    return IMAGE_STEPS if draft.media_kind == "images" else PUBLISHED_STEPS


def step_count(draft: PromotionDraftVM) -> int:
    return len(step_keys(draft))


def step_title(draft: PromotionDraftVM, step: int) -> str:
    keys = step_keys(draft)
    return STEP_TITLE_BY_KEY[keys[min(max(step, 1), len(keys)) - 1]]


def link_problem(value: str) -> str:
    try:
        url = urlsplit(value.strip())
        valid = (
            url.scheme == "https"
            and url.hostname
            and not (url.username or url.password)
            and not any(char.isspace() for char in value)
        )
    except ValueError:
        valid = False
    return "" if valid else "Escribe un enlace completo que comience por https://."


UNPUBLISHED_PROBLEMS = {
    "images": lambda d: (
        ""
        if d.feed_asset_id and d.vertical_asset_id
        else "Elige una imagen para el perfil (4:5) y otra vertical (9:16)."
    ),
    "feed_video": lambda d: "" if d.feed_asset_id else "Elige el video para el perfil (4:5).",
    "vertical_video": lambda d: (
        "" if d.vertical_asset_id else "Elige el video vertical de pantalla completa (9:16)."
    ),
    "covers": lambda d: (
        "" if d.feed_cover_id and d.vertical_cover_id else "Elige la portada de cada video."
    ),
    "country": lambda d: (
        "" if d.country in COUNTRY_LABELS else "Elige el país donde quieres mostrar el anuncio."
    ),
}


def step_problem(draft: PromotionDraftVM, step: int, timezone_name: str = "") -> str:
    """Local form guidance only; Meta eligibility, minimum and payment are server gates."""
    keys = step_keys(draft)
    key = keys[step - 1] if 1 <= step <= len(keys) else ""
    if key in UNPUBLISHED_PROBLEMS:
        return UNPUBLISHED_PROBLEMS[key](draft)
    if key == "text":
        if not draft.message.strip():
            return "Escribe el texto del anuncio."
        if len(draft.message) > 2200:
            return "El texto del anuncio admite hasta 2.200 caracteres."
        if not draft.headline.strip():
            return "Escribe el título del anuncio."
        if len(draft.headline) > 100:
            return "El título del anuncio admite hasta 100 caracteres."
        return link_problem(draft.link_url)
    if key == "source":
        return "Elige la publicación que quieres promocionar." if not draft.source_id else ""
    if key == "destination" and draft.goal == "lead":
        if not draft.lead_form_id:
            return "Elige el formulario que llenará la gente."
        return "" if draft.lead_cta in LEAD_CTA_LABELS else "Elige el texto del botón."
    if key == "destination":
        return link_problem(draft.link_url)
    if key == "audience":
        if draft.housing and any(row.kind == "lookalike" for row in draft.custom_audiences):
            return "Quita el público de personas parecidas antes de continuar con vivienda."
        if any(not row.available for row in draft.custom_audiences):
            return "Vuelve a consultar el público de Instagram o quítalo antes de continuar."
        if not draft.location_key or not draft.city_name.strip():
            return "Busca un lugar y elígelo entre los resultados de Meta."
        try:
            low, high = int(draft.age_min), int(draft.age_max)
            valid = draft.housing or 18 <= low <= high <= 65
            if draft.radius_km:
                valid = valid and draft.location_kind == "city" and 1 <= int(draft.radius_km) <= 80
        except ValueError:
            valid = False
        if not valid:
            return "Revisa la distancia y las edades antes de continuar."
        if draft.placement_mode == "manual" and not draft.placements:
            return "Elige al menos un lugar donde mostrar el anuncio."
        if not draft.housing and any(
            row.notice in {"retiring", "unavailable"} for row in draft.interests
        ):
            return "Quita los intereses que Meta va a retirar o ya no permite usar."
        return ""
    if key == "budget":
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
        (
            reason
            for n in range(1, step_count(draft) + 1)
            if (reason := step_problem(draft, n, timezone_name))
        ),
        "",
    )


def video_outcome(message: str) -> str:
    """What a refused unpublished preparation means for the screen: "waiting" (Meta is
    processing a video: repeat the same preparation later), "help" (an uncertain upload:
    never offer to send it again) or "" (an ordinary, owner-fixable refusal)."""
    from qualify_api.ads.unpublished_service import VIDEO_WAIT  # noqa: PLC0415

    if message in (VIDEO_WAIT["processing"], VIDEO_WAIT["submitting"]):
        return "waiting"
    return "help" if "Pide ayuda" in message else ""
