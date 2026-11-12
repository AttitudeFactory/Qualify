"""Owner-readable custom audience choices, never remote eligibility evidence."""

from __future__ import annotations

from dataclasses import dataclass, field

AUDIENCE_KIND_LABELS = {
    "engagement": "Personas que interactuaron con tu Instagram",
    "messages": "Personas que escribieron a tu Instagram",
    "lookalike": "Personas parecidas a un público tuyo",
}


@dataclass(frozen=True)
class CustomAudienceVM:
    local_id: str = ""
    meta_id: str = ""
    name: str = ""
    kind: str = ""
    available: bool = False
    notice: str = ""


@dataclass(frozen=True)
class CustomAudienceCatalogVM:
    loaded: bool = False
    terms_accepted: bool = False
    creation_available: bool = False
    notice: str = "Consulta los públicos de esta cuenta antes de elegir uno."
    audiences: list[CustomAudienceVM] = field(default_factory=list)


def audience_choices(audiences: list[CustomAudienceVM], housing: bool) -> list[CustomAudienceVM]:
    """Housing never offers a lookalike, including old or unavailable rows."""
    return [row for row in audiences if not (housing and row.kind == "lookalike")]


def selection_label(audiences: list[CustomAudienceVM]) -> str:
    return ", ".join(row.name for row in audiences) or "Sin público de Instagram elegido"


def creation_problem(
    *, name: str, kind: str, retention: str, seed_id: str, country: str, housing: bool
) -> str:
    if not name.strip() or len(name.strip()) > 100:
        return "Escribe un nombre de hasta cien letras para reconocer este público."
    if kind not in AUDIENCE_KIND_LABELS or (housing and kind == "lookalike"):
        return "Elige un tipo de público permitido para este anuncio."
    if kind == "lookalike":
        if not seed_id:
            return "Elige el público con el que Meta buscará personas parecidas."
        if len(country) != 2 or not country.isascii() or not country.isalpha():
            return "Elige el país donde quieres encontrar personas parecidas."
    elif not retention.isascii() or not retention.isdigit() or not 1 <= int(retention) <= 730:
        return "Elige entre uno y 730 días de interacción."
    return ""
