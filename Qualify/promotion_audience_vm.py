"""Safe display projections for audience preparation, never advertising authorization."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class AudiencePlaceVM:
    key: str = ""
    kind: str = ""
    country: str = ""
    label: str = ""
    region: str = ""
    kind_label: str = ""  # «(ciudad)» / «(región)» next to the name in the results


@dataclass(frozen=True)
class AudienceInterestVM:
    id: str = ""
    label: str = ""
    notice: str = ""


@dataclass(frozen=True)
class AudienceReachVM:
    label: str = "Elige un lugar para consultar cuántas personas podrían verlo."
    notice: str = "Es una estimación del público, no una promesa de visitas o ventas."
    available: bool = False


PLACE_KIND_LABELS = {"city": "Ciudad", "region": "Región", "country": "País"}
GENDER_LABELS = {"all": "Todas las personas", "men": "Hombres", "women": "Mujeres"}
PLACEMENT_LABELS = {
    "facebook_feed": "Facebook: publicaciones",
    "instagram_feed": "Instagram: publicaciones",
    "instagram_story": "Instagram: historias",
    "instagram_reels": "Instagram: reels (videos cortos)",
    "instagram_explore": "Instagram: Explorar",
}


def placements_label(mode: str, placements: list[str]) -> str:
    if mode == "automatic":
        return "Meta elige dónde mostrarlo en Facebook e Instagram"
    return ", ".join(PLACEMENT_LABELS[key] for key in placements if key in PLACEMENT_LABELS)


def reach_label(lower: int, upper: int) -> str:
    """Only normalized, ready bounds belong here; absent estimates never become zero."""
    if type(lower) is not int or type(upper) is not int or not 0 <= lower <= upper:
        raise ValueError("invalid ready audience bounds")
    lo, hi = f"{lower:,}".replace(",", "."), f"{upper:,}".replace(",", ".")
    return f"Entre {lo} y {hi} personas en este público"


# «Cerca de mi negocio» (m-24828977): a distance around the phone's location at the business.
POINT_NAME = "Tu negocio"  # MapPoint.name: internal, Meta never receives it
POINT_CAPTURED = "Listo: usamos la ubicación de tu negocio"
# m-25038694: the business location saved on the tenant, so the owner need not be there.
POINT_FROM_SAVED = "Usamos la ubicación guardada de tu negocio"
POINT_LOADING = "Buscando la ubicación guardada de tu negocio…"
# A good reading at the business is saved right away (UX review, m-25038694).
BUSINESS_LOCATION_SAVED = (
    "Guardamos la ubicación de tu negocio. La próxima vez la usamos aunque no estés allí."
)
BUSINESS_LOCATION_UPDATED = "Listo: actualizamos la ubicación de tu negocio."
BUSINESS_LOCATION_SAVE_FAILED = (
    "No pudimos guardarla para la próxima vez, pero este anuncio sí la usa."
)
NEAR_PLACE_LABEL = "Cerca de tu negocio"
NEAR_HOUSING = "No disponible para anuncios de vivienda."
POINT_DISTANCES = ("1", "3", "5", "10")
DEFAULT_POINT_DISTANCE = "5"
# A reading less precise than this could place the business in another neighborhood.
MAX_ACCURACY_M = 500
LOCATION_FAILED = (
    "No pudimos usar tu ubicación. Ábrela desde tu negocio y vuelve a intentarlo, "
    "o elige «En una ciudad o región»."
)
LOCATION_DENIED = (
    "Tu teléfono no nos dejó ver tu ubicación. Si estás en el negocio, permite la ubicación "
    "para esta página (en el candado junto a la dirección) y vuelve a tocar el botón. "
    "Si no estás allí, elige «En una ciudad o región»."
)
LOCATION_NOT_FOUND = (
    "No pudimos encontrar tu ubicación. Revisa que la ubicación del teléfono esté encendida "
    "y vuelve a intentarlo."
)
LOCATION_UNSUPPORTED = (
    "Este navegador no nos deja usar tu ubicación. Abre Qualify en el navegador de tu "
    "teléfono, como Chrome o Safari, y vuelve a intentarlo, o elige «En una ciudad o región»."
)
LOCATION_IMPRECISE = (
    "No pudimos ubicar bien tu negocio. Sal a un lugar abierto o activa la ubicación precisa "
    "del teléfono y vuelve a intentarlo, o elige «En una ciudad o región»."
)
COUNTRY_UNKNOWN = "No sabemos en qué país está tu negocio. Elige «En una ciudad o región»."
NEAR_LOCATION_MISSING = "Toca «Estoy en el negocio: usar mi ubicación» para marcar tu negocio."
LOCATE_BUTTON_ID = "audience-locate"
CITY_RADIUS_EMPTY_HINT = (
    "Si la dejas vacía, el anuncio se muestra en toda la ciudad. "
    "Si escribes una distancia, que sea de 17 km o más."
)
CITY_RADIUS_WRONG_HINT = (
    "Escribe una distancia entre 17 y 80 km, o déjala vacía para usar toda la ciudad. "
    "Para llegar más cerca, elige «Cerca de mi negocio»."
)
NEAR_HOUSING_PROBLEM = (
    "«Cerca de mi negocio» no está disponible para anuncios de vivienda. "
    "Elige «En una ciudad o región»."
)
_LOCATION_ERRORS = {"1": LOCATION_DENIED, "2": LOCATION_NOT_FOUND, "3": LOCATION_NOT_FOUND}


def location_problem(value: object) -> str:
    """Why the browser's answer cannot be used ("" when it can). The accuracy is only
    checked here, never stored or sent."""
    if not isinstance(value, dict):
        return LOCATION_FAILED
    if "error" in value:
        return _LOCATION_ERRORS.get(str(value["error"]), LOCATION_UNSUPPORTED)
    if captured_point(value) is None:
        return LOCATION_FAILED
    accuracy = value.get("accuracy")
    if (
        isinstance(accuracy, bool)
        or not isinstance(accuracy, int | float)
        or not math.isfinite(accuracy)
        or not 0 <= accuracy <= MAX_ACCURACY_M
    ):
        return LOCATION_IMPRECISE
    return ""


def place_kind_label(kind: str) -> str:
    """The search result's tag: Meta does not tell a state from a department, so «región»."""
    return f"({PLACE_KIND_LABELS[kind].lower()})" if kind in PLACE_KIND_LABELS else ""


def captured_point(value: object) -> tuple[str, str] | None:
    """The browser's reading as 6-decimal strings, or None for an error or impossible value.

    The browser is untrusted: anything but two finite, in-range numbers is refused."""
    if not isinstance(value, dict):
        return None
    result = []
    for name, limit in (("latitude", 90), ("longitude", 180)):
        raw = value.get(name)
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            return None
        number = float(raw)
        if not math.isfinite(number) or not -limit <= number <= limit:
            return None
        result.append(str(round(number, 6) + 0.0))  # + 0.0 turns -0.0 into 0.0
    return result[0], result[1]


def point_distance_problem(value: str) -> str:
    try:
        km = int(value)
    except ValueError:
        km = 0
    return "" if 1 <= km <= 80 else "Escribe una distancia entre 1 y 80 km."


def point_distance_hint(value: str) -> str:
    return point_distance_problem(value) or (
        f"Personas que viven o pasaron hace poco a menos de {int(value)} km de tu negocio."
    )


def point_distance_label(value: str) -> str:
    return f"A {value} km de tu negocio"
