"""Market-niche personas the E2E suite drives the app as.

The suite is organised **by module × by niche**: every module test file takes a persona
fixture and exercises the module as that kind of business would. The first niche is
**locales de comida** (food venues) — an arepera, a food stall in a gastronomic fair, a
neighbourhood restaurant. Add a new niche by adding a `Persona` here and a fixture in
`conftest.py`; do NOT fork the module tests per niche.

Personas are data, not behaviour: the module tests decide what to click. Everything a
persona carries is what the product's own forms ask for (signup fields, brand kit,
content-order copy), phrased the way an operator of that business would phrase it, so a
regression that only shows up with real-looking Spanish content is caught.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Persona:
    """One business the suite registers and logs in as."""

    niche: str
    business_name: str
    email: str
    password: str
    country: str = "VE"
    timezone: str = "America/Caracas"
    currency: str = "USD"
    # Brand-kit content, worded by the operator (Spanish, like the product).
    brand: dict[str, str] = field(default_factory=dict)
    # A content order (encargo) this business would actually place.
    encargo: dict[str, str] = field(default_factory=dict)
    # Free-text mentions/queries the operator would type into search boxes.
    search_terms: tuple[str, ...] = ()


def _unique_email(slug: str) -> str:
    # The fake auth provider compares emails literally and refuses duplicates, and each
    # signup creates a real tenant row in the local Postgres — a fresh alias per run keeps
    # runs independent and makes leftover rows greppable (`e2e-<slug>-…@example.com`).
    return f"e2e-{slug}-{uuid.uuid4().hex[:8]}@example.com"


# --- Niche 1: locales de comida ------------------------------------------------------


def food_venue_persona() -> Persona:
    """An arepera in San Cristóbal that just rented a stall in a gastronomic fair.

    Chosen because it touches every module the product has today: it publishes reels of
    the food, wants replies to comments, cares about walk-in flow (Vitrina) and needs a
    brand kit + content orders (Brand Content Engine) with food-specific vocabulary.
    """

    return Persona(
        niche="locales-de-comida",
        business_name="E2E · Arepera Doña Carmen",
        email=_unique_email("arepera"),
        password="arepas-de-pabellon-2026",
        country="VE",
        timezone="America/Caracas",
        currency="USD",
        brand={
            "name": "Arepera Doña Carmen",
            "tagline": "Arepas de pabellón hechas al momento, desde 1998",
            "audience": (
                "Jugadores de padel y familias que salen del Korner Club con hambre entre las "
                "19:00 y las 21:00; oficinistas del centro al mediodía."
            ),
            "tone": "Cercano, de barrio, con humor tachirense; nunca formal ni corporativo.",
            "offer": (
                "Arepa reina pepiada $4, arepa de pabellón $5, combo arepa + jugo natural $6,80. "
                "Promo martes: 2x1 en arepas de queso de mano después de las 20:00."
            ),
            "words_to_avoid": "gourmet, premium, experiencia culinaria",
        },
        encargo={
            "goal": "Llenar el local el martes con la promo 2x1 de queso de mano",
            "format": "Reel de 15 segundos para Instagram y TikTok",
            "brief": (
                "Mostrar la arepa abriéndose con el queso de mano derritiéndose, música "
                "llanera de fondo, texto en pantalla con la promo y la hora. Cerrar con la "
                "fachada del local en el Korner Club."
            ),
        },
        search_terms=("arepa", "queso de mano", "Korner Club"),
    )
