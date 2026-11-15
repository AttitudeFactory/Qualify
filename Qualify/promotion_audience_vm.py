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
POINT_LABEL = "Punto en el mapa"
POINT_DISTANCES = ("1", "3", "5", "10")
DEFAULT_POINT_DISTANCE = "5"
LOCATION_FAILED = (
    "No pudimos usar tu ubicación. Ábrela desde tu negocio y vuelve a intentarlo, "
    "o elige «En una ciudad»."
)
COUNTRY_UNKNOWN = "No sabemos en qué país está tu negocio. Elige «En una ciudad»."


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
