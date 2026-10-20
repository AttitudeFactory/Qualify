"""«Sin personas»: a free, versioned filter over a stock hit's own words (§5.1, layer 1).

Neither bank can exclude people server-side (Pixabay's `category` only includes), and adding
«sin personas» to the query tends to *bring* people, so the filter reads what the provider
says about the asset — Pixabay's `tags` (Spanish with `lang=es`), Pexels' `alt` (English) —
and drops a hit that names a person. Hands are NOT a person: a hand holding the product is
the typical product shot and identifies no one.

A heuristic, not a guarantee: it only sees words. Measured on the first real call
(2026-10-16) Pixabay translates «kid» as «cabrito» and tags most portraits with «mujer» /
«retrato» / «modelo», which this list catches; an untagged face is missed. The UI never
promises more than «filtramos fotos con personas».
"""

from __future__ import annotations

import re
import unicodedata

PEOPLE_FILTER_VERSION = "people-blocklist/1"

# Accent-free, casefolded: the text is folded the same way before matching.
_PEOPLE_WORDS: frozenset[str] = frozenset(
    {
        # es
        "persona", "personas", "gente", "mujer", "mujeres", "hombre", "hombres",
        "nino", "nina", "ninos", "ninas", "chica", "chicas", "chico", "chicos",
        "bebe", "bebes", "cara", "rostro", "rostros", "retrato", "retratos",
        "modelo", "modelos", "pareja", "parejas", "familia", "multitud", "selfie",
        "adolescente", "muchacho", "muchacha", "senora", "senor", "dama", "caballero",
        "madre", "padre", "abuela", "abuelo", "novia", "novio", "anciano", "anciana",
        "cocinero", "cocinera", "chef", "atleta", "jugador", "jugadora", "bailarina",
        "bailarin", "turista", "infancia",
        # en
        "people", "person", "woman", "women", "man", "men", "girl", "girls", "boy",
        "boys", "child", "children", "kid", "kids", "baby", "face", "portrait",
        "model", "couple", "family", "crowd", "businessman", "businesswoman", "teen",
        "lady", "guy",
    }
)  # fmt: skip

_WORD = re.compile(r"[a-z]+")


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def names_a_person(description: str) -> bool:
    """Whether the asset's own words name a person (`_PEOPLE_WORDS`, whole words only:
    «mano» is not «hombre», «modelado» is not «modelo»)."""
    return any(word in _PEOPLE_WORDS for word in _WORD.findall(_fold(description)))
