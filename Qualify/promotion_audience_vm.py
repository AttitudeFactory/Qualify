"""Safe display projections for audience preparation, never advertising authorization."""

from __future__ import annotations

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
