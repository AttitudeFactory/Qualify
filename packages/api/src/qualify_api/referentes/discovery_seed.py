"""The referentes search's SEED read from the brand's own account — `seed_from_profile` and
the pure tables and text helpers it stands on (niche taxonomy, countries and cities,
location detection, the `DiscoverySeed` the phased search runs on).

Moved verbatim out of `Qualify/creator_discovery.py` (m-24852195, epic m-24852192) so the
Brand Kit prefill can run in a worker without importing the Reflex app. No behaviour
changed: `Qualify/creator_discovery.py` imports every name back and keeps the phased
search, the vendor calls and the CLI. No I/O here — no HTTP, no database, no files.

`PHASED_PLAN_VERSION` lives here because `DiscoverySeed.signature` reads it; the guard
that forces a bump when the algorithm changes (`Qualify/test_creator_discovery_version.py`)
fingerprints this module together with `creator_discovery.py`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

#: Niche taxonomy — PROVISIONAL. `keywords` are regexes matched against bio / caption
#: (lower-cased, accents stripped); `queries` are the free-text searches — by
#: position: [0] the head term (local phase, city appended), [1] the national term
#: (country appended), [2:] extra sector terms (`sector_terms`); `hashtags` are the
#: hashtag searches (the city is composed in, see `hashtags_for`). Measured
#: 2026-09-11: "aprende a programar" surfaces the programming creators (mouredev,
#: brujeriatech…) that "programación" alone never did.
NICHE_TAXONOMY: dict[str, dict[str, list[str]]] = {
    "food_drink": {
        "keywords": [
            r"foodie",
            r"comida",
            r"restaurante",
            r"gastronom",
            r"cafeter",
            r"cocina",
            r"receta",
            r"chef",
            r"brunch",
            r"postre",
            r"🍽",
            r"🍔",
            r"🍕",
        ],
        "queries": ["foodie", "comida", "restaurantes", "recetas"],
        "hashtags": ["food", "foodie", "comida"],
    },
    "fashion_beauty": {
        "keywords": [
            r"\bmodas?\b",
            r"fashion",
            r"makeup",
            r"maquillaje",
            r"outfit",
            r"\bstyle\b",
            r"belleza",
            r"beauty",
            r"skincare",
            r"peluquer",
            r"barber",
        ],
        "queries": ["moda", "makeup", "outfit", "belleza"],
        "hashtags": ["moda", "fashion", "makeup"],
    },
    "fitness_health": {
        "keywords": [
            r"\bfit",
            r"\bgym\b",
            r"entrenad",
            r"saludable",
            r"gimnasio",
            r"crossfit",
            r"nutrici",
            r"yoga",
            r"running",
            r"🏋",
            r"💪",
        ],
        "queries": ["fitness", "gym", "entrenador personal", "rutina de ejercicio"],
        "hashtags": ["fitness", "gym", "fit"],
    },
    "travel_lifestyle": {
        "keywords": [
            r"viaj",
            r"travel",
            r"blogger",
            r"turismo",
            r"estilo de vida",
            r"lifestyle",
            r"aventura",
            r"✈",
            r"🌎",
        ],
        "queries": ["viajes", "turismo", "lifestyle", "viajero"],
        "hashtags": ["travel", "viajes", "turismo"],
    },
    "real_estate": {
        "keywords": [
            r"inmobiliar",
            r"inmueble",
            r"apartamento",
            r"\bcasa[s]?\b",
            r"bienes raices",
            r"real estate",
            r"arriendo",
            r"venta de",
            r"🏠",
            r"🏡",
        ],
        "queries": [
            "inmobiliaria",
            "apartamentos en venta",
            "bienes raíces",
            "agente inmobiliario",
        ],
        "hashtags": ["inmobiliaria", "bienesraices", "apartamentos"],
    },
    # Added 2026-09-11 with the Brand Kit integration: a brand choosing its sector
    # needs more than the five niches the Cúcuta experiment started from.
    "technology": {
        "keywords": [
            r"tecnolog",
            r"technolog",
            r"software",
            r"programaci",
            r"\bprograma(?:r|dor)",
            r"programming",
            r"desarrollador",
            r"developer",
            r"javascript",
            r"python",
            r"inteligencia artificial",
            r"\bia\b",
            r"💻",
        ],
        "queries": ["programación", "tecnología", "aprende a programar", "programador"],
        "hashtags": ["tecnologia", "programacion", "tech"],
    },
    "education": {
        "keywords": [
            r"educaci",
            r"education",
            r"\bcursos?\b",
            r"profesor",
            r"docente",
            r"academ",
            r"school",
            r"colegio",
            r"📚",
        ],
        "queries": ["educación", "cursos", "aprende", "profesor"],
        "hashtags": ["educacion", "aprende", "cursos"],
    },
    "entertainment": {
        "keywords": [
            r"humor",
            r"comedia",
            r"comedian",
            r"entreten",
            r"entertain",
            r"musica",
            r"musician",
            r"cantante",
            r"artista",
            r"😂",
        ],
        "queries": ["humor", "comedia", "música", "comediante"],
        "hashtags": ["humor", "comedia", "musica"],
    },
}


#: Instagram's own business `category_name` values are English ("Restaurant",
#: "Clothing (Brand)", "Gym/Physical Fitness Center"...). Extra patterns per niche so
#: the category reads through the same `detect_niches` as a Spanish bio does.
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "food_drink": [r"restaurant", r"bakery", r"\bcafe\b", r"\bfood", r"coffee", r"beverage"],
    "fashion_beauty": [r"clothing", r"cosmetic", r"salon", r"jewelry"],
    "fitness_health": [r"fitness", r"trainer", r"\bsport", r"health"],
    "travel_lifestyle": [r"hotel", r"\btour", r"travel"],
    "real_estate": [r"real estate", r"property"],
    "technology": [r"computer", r"internet", r"\bapp\b", r"electronics"],
    "education": [r"\bschool", r"tutor", r"university"],
    "entertainment": [r"music", r"artist", r"\bband\b"],
}


for _niche, _patterns in _CATEGORY_KEYWORDS.items():
    NICHE_TAXONOMY[_niche]["keywords"].extend(_patterns)


#: Spanish label per niche — what the Brand Kit's rubro select shows.
NICHE_LABELS: dict[str, str] = {
    "food_drink": "Comida y bebida",
    "fashion_beauty": "Moda y belleza",
    "fitness_health": "Fitness y salud",
    "travel_lifestyle": "Viajes y estilo de vida",
    "real_estate": "Inmobiliaria",
    "technology": "Tecnología",
    "education": "Educación",
    "entertainment": "Entretenimiento y humor",
}


#: Aliases so the filter JSON can use market spellings ("travel", "beauty", ...).
NICHE_ALIASES: dict[str, str] = {
    "food": "food_drink",
    "foodie": "food_drink",
    "gastronomia": "food_drink",
    "fashion": "fashion_beauty",
    "beauty": "fashion_beauty",
    "moda": "fashion_beauty",
    "fitness": "fitness_health",
    "health": "fitness_health",
    "gym": "fitness_health",
    "travel": "travel_lifestyle",
    "lifestyle": "travel_lifestyle",
    "viajes": "travel_lifestyle",
    "inmobiliaria": "real_estate",
    "realestate": "real_estate",
    "tech": "technology",
    "tecnologia": "technology",
    "educacion": "education",
    "humor": "entertainment",
}


def _fold(text: str) -> str:
    """Lower-case + strip accents, so `Cúcuta`, `cucuta` and `CÚCUTA` all match one
    pattern and the taxonomy regexes stay ASCII."""
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _fold(text))


def resolve_niche(name: str) -> str:
    """`food_drink`, `Food & Drink`, `travel`, `Viajes` → a taxonomy key, or ValueError."""
    key = re.sub(r"[^a-z0-9]+", "_", _fold(name)).strip("_")
    if key in NICHE_TAXONOMY:
        return key
    alias = key.replace("_", "")
    if alias in NICHE_ALIASES:
        return NICHE_ALIASES[alias]
    raise ValueError(f"unknown niche {name!r}; known: {sorted(NICHE_TAXONOMY)}")


def detect_niches(text: str) -> list[str]:
    folded = _fold(text)
    return [
        niche
        for niche, spec in NICHE_TAXONOMY.items()
        if any(re.search(pattern, folded) for pattern in spec["keywords"])
    ]


#: Bumped when the phase plan changes (queries, ranking, filters, the tables they read)
#: so a cached or stored result computed under the old plan is a miss instead of a stale
#: answer. Not left to memory: `test_creator_discovery_version.py` fingerprints the
#: algorithm's code and fails when it changes without a bump (5 = the 2026-09-15
#: country aliases / city lists, which shipped still stamped 4; 6 = the shared hashtag
#: catalog: the rubro's catalog hashtags join the sector queries, the local hashtag
#: query and the relevance stems — `hashtag_catalog.catalog_hashtags_for`; 7 = an
#: Instagram profile read contributes its last posts' captions and hashtags as evidence,
#: and the sector phase searches up to three catalog hashtags, now chosen per brand by
#: Claude — `hashtag_catalog.ai_hashtags_for`; 8 = the operator's own hashtag pills
#: on Tu rubro y ubicación, `DiscoverySeed.chosen_hashtags`: they replace the catalog's
#: choice, join the sector/local keys and run as up to `CHOSEN_HASHTAGS` sector queries;
#: 9 = Claude reviews each phase's shortlist; 10 = no change in what is found — the two
#: networks' walks run at once, `_run_networks`, and `run_phase`'s text changed with it;
#: 11 = no change in what is found either — each account keeps its profile link and how
#: many of its feed videos carried TikTok's AI label, and the profile reads are
#: remembered in Postgres instead of a JSON file; 12 = the local phase searches up to
#: `LOCAL_TERMS` rubro terms with the city instead of one — `local_terms` — because a
#: niche rubro in a small city found nobody with its single head term (measured
#: 2026-10-05: "programacion tachira" → 0 accounts, so the city category never showed).
PHASED_PLAN_VERSION = 12


@dataclass(frozen=True)
class Country:
    """One country the location detection and the rubro step know.

    `aliases` is what a bio calls the country when it does not spell its name: the
    demonym above all ("venezolana", "colombiano") plus the short forms people
    actually type ("vzla", "eeuu"). Matched as whole words and only from four
    characters up — "col", "mx" and "rd" appear inside too much ordinary text to be
    evidence of anything. The flag emoji is handled separately, from the ISO code.

    `cities` is the display list AND the evidence list. Keep it to the real metros:
    every name added is a name that can collide, and the ambiguity indexes below are
    what keep a collision from inventing a country.
    """

    name: str
    aliases: tuple[str, ...]
    cities: tuple[str, ...]


#: Countries the location detection and the rubro step know. PROVISIONAL, same status
#: as the taxonomy — LatAm first because that is where the first customers are, plus
#: Spain / US for the Spanish-speaking accounts a sector search surfaces anyway.
#:
#: Coverage is deliberately EVEN across countries (§ 2026-09-15): the list used to run
#: from 15 cities for Colombia down to one for Panamá, which made "is this account
#: from country X" a question whose answer depended on how well X happened to be
#: typed up rather than on the account. A country entered with two cities silently
#: loses every creator from its third city — `test_every_country_carries_enough_cities`
#: is the guard against adding the next one that way.
COUNTRIES: dict[str, Country] = {
    "CO": Country(
        "Colombia",
        ("colombiano", "colombiana", "colombianos", "colombianas"),
        (
            "Bogotá",
            "Medellín",
            "Cali",
            "Barranquilla",
            "Cartagena",
            "Bucaramanga",
            "Cúcuta",
            "Pereira",
            "Santa Marta",
            "Manizales",
            "Ibagué",
            "Villavicencio",
            "Pasto",
            "Montería",
            "Neiva",
        ),
    ),
    "VE": Country(
        "Venezuela",
        ("venezolano", "venezolana", "venezolanos", "venezolanas", "vzla"),
        (
            "Caracas",
            "Maracaibo",
            "Valencia",
            "Barquisimeto",
            "Maracay",
            "Ciudad Guayana",
            "Puerto Ordaz",
            "San Cristóbal",
            "Puerto La Cruz",
            "Mérida",
            "Barcelona",
            "Maturín",
            "Barinas",
            "Cumaná",
            "Punto Fijo",
        ),
    ),
    "MX": Country(
        "México",
        ("mexicano", "mexicana", "mexicanos", "mexicanas"),
        (
            "Ciudad de México",
            "Guadalajara",
            "Monterrey",
            "Puebla",
            "Tijuana",
            "Cancún",
            "Mérida",
            "Querétaro",
            "León",
            "Toluca",
            "Ciudad Juárez",
            "Mexicali",
            "Culiacán",
            "Aguascalientes",
            "Morelia",
        ),
    ),
    "AR": Country(
        "Argentina",
        ("argentino", "argentina", "argentinos", "argentinas"),
        (
            "Buenos Aires",
            "Córdoba",
            "Rosario",
            "Mendoza",
            "La Plata",
            "Mar del Plata",
            "San Miguel de Tucumán",
            "Salta",
            "Santa Fe",
            "Neuquén",
            "Bariloche",
        ),
    ),
    "CL": Country(
        "Chile",
        ("chileno", "chilena", "chilenos", "chilenas"),
        (
            "Santiago de Chile",
            "Valparaíso",
            "Viña del Mar",
            "Concepción",
            "Antofagasta",
            "La Serena",
            "Temuco",
            "Iquique",
            "Puerto Montt",
        ),
    ),
    "PE": Country(
        "Perú",
        ("peruano", "peruana", "peruanos", "peruanas"),
        (
            "Lima",
            "Arequipa",
            "Cusco",
            "Trujillo",
            "Chiclayo",
            "Piura",
            "Iquitos",
            "Huancayo",
            "Tacna",
        ),
    ),
    "EC": Country(
        "Ecuador",
        ("ecuatoriano", "ecuatoriana", "ecuatorianos", "ecuatorianas"),
        (
            "Quito",
            "Guayaquil",
            "Cuenca",
            "Ambato",
            "Manta",
            "Machala",
            "Portoviejo",
            "Loja",
            "Esmeraldas",
        ),
    ),
    "PA": Country(
        "Panamá",
        ("panameño", "panameña", "panameños", "panameñas"),
        (
            "Ciudad de Panamá",
            "Colón",
            "David",
            "Chitré",
            "Penonomé",
            "Bocas del Toro",
            "La Chorrera",
            "Arraiján",
        ),
    ),
    "DO": Country(
        "República Dominicana",
        ("dominicano", "dominicana", "dominicanos", "dominicanas", "quisqueya"),
        (
            "Santo Domingo",
            "Santiago de los Caballeros",
            "Punta Cana",
            "La Romana",
            "Puerto Plata",
            "San Pedro de Macorís",
            "Bávaro",
            "San Francisco de Macorís",
        ),
    ),
    "ES": Country(
        "España",
        ("español", "española", "españoles", "españolas", "spain"),
        (
            "Madrid",
            "Barcelona",
            "Sevilla",
            "Valencia",
            "Málaga",
            "Bilbao",
            "Zaragoza",
            "Murcia",
            "Alicante",
            "Córdoba",
            "Valladolid",
            "Granada",
            "Vigo",
            "San Sebastián",
            "Palma de Mallorca",
        ),
    ),
    "US": Country(
        "Estados Unidos",
        # NOT "usa": three letters, and in Spanish it is the verb ("usa este código").
        ("eeuu", "estadounidense", "united states"),
        (
            "Miami",
            "Nueva York",
            "Los Ángeles",
            "Houston",
            "Chicago",
            "Orlando",
            "Dallas",
            "Atlanta",
            "San Francisco",
            "Las Vegas",
            "Phoenix",
            "Boston",
            "Seattle",
            "San Antonio",
            "San Diego",
        ),
    ),
}


#: City names too generic to name a country BY THEMSELVES — either because more than
#: one country in the table has them (computed: Valencia and Barcelona are Spanish and
#: Venezuelan, Mérida is Mexican and Venezuelan, Córdoba is Argentine and Spanish,
#: Santiago… is three countries' prefix) or because the word is ordinary Spanish or a
#: person's name (listed: `salta` is a verb, `david` and `rosario` are names, `granada`
#: and `palma` are fruit and tree, `manta` is a blanket).
#:
#: This is THE generalization (§ 2026-09-15): a weak name never decides a country on
#: its own — it needs the country named alongside it. Adding a country later cannot
#: reintroduce the bug, because the ambiguous half of this set is DERIVED from the
#: table rather than listed.
_COMMON_WORD_CITY_SLUGS = frozenset(
    {"salta", "david", "colon", "rosario", "mendoza", "manta", "granada", "leon", "concepcion"}
)


def _city_country_index() -> dict[str, frozenset[str]]:
    index: dict[str, set[str]] = {}
    for code, country in COUNTRIES.items():
        for city in country.cities:
            index.setdefault(_slug(city), set()).add(code)
    return {slug: frozenset(codes) for slug, codes in index.items()}


#: City slug → the countries claiming it. Derived, never hand-maintained.
CITY_COUNTRIES: dict[str, frozenset[str]] = _city_country_index()


#: The slugs that may not decide a country alone: shared by two countries, or an
#: ordinary word.
WEAK_CITY_SLUGS: frozenset[str] = frozenset(
    {slug for slug, codes in CITY_COUNTRIES.items() if len(codes) > 1} | _COMMON_WORD_CITY_SLUGS
)


#: Hashtags that say nothing about what an account is about — dropped from the
#: account's own vocabulary before it seeds a search.
_GENERIC_HASHTAGS = frozenset(
    {
        "capcut",
        "explore",
        "explorepage",
        "follow",
        "foryou",
        "foryoupage",
        "fy",
        "fyp",
        "instagood",
        "instagram",
        "like",
        "love",
        "parati",
        "paratii",
        "reel",
        "reels",
        "tendencia",
        "tiktok",
        "trend",
        "trending",
        "viral",
        "viralvideo",
        "xyzbca",
    }
)


def _flag(code: str) -> str:
    """ISO code → flag emoji (`CO` → the Colombian flag): bios mark a country with it
    as often as with the name."""
    return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in code.upper())


def country_name(code: str) -> str:
    country = COUNTRIES.get(code.upper())
    return country.name if country else ""


#: Below this, an alias is a substring of too much ordinary text to be evidence —
#: see `Country.aliases`.
_MIN_ALIAS_LENGTH = 4


def _mentions_country(text: str, code: str) -> bool:
    """Whether the text names `code` explicitly — by name, by demonym or short form,
    or by flag emoji. Never by a city: a city is circumstantial (`_city_evidence`),
    a name is not."""
    country = COUNTRIES.get(code.upper())
    if country is None:
        return False
    folded = _fold(text)
    name = _fold(country.name)
    if name and (re.search(rf"\b{re.escape(name)}\b", folded) or _slug(name) in _slug(text)):
        return True
    for alias in country.aliases:
        folded_alias = _fold(alias)
        if len(folded_alias) >= _MIN_ALIAS_LENGTH and re.search(
            rf"\b{re.escape(folded_alias)}\b", folded
        ):
            return True
    return _flag(code) in text


def named_countries(text: str) -> list[str]:
    """Every country the text names explicitly, in table order. Empty for a text that
    only drops a city name."""
    return [code for code in COUNTRIES if _mentions_country(text, code)]


def _city_in(text: str, tag_slugs: list[str], city: str) -> bool:
    """Word match on the folded text, or — for names long enough not to collide with
    ordinary words (`cali` is in `calidad`) — a substring of a hashtag
    (`#cucutafood`)."""
    key = _fold(city)
    slug = _slug(city)
    if re.search(rf"\b{re.escape(key)}\b", _fold(text)):
        return True
    return len(slug) >= 6 and any(slug in tag for tag in tag_slugs)


def detect_location(
    text: str,
    hashtags: list[str] | tuple[str, ...] = (),
    *,
    country_hint: str = "",
) -> tuple[str, str]:
    """`(country code, city)` read from a bio / category / hashtags, `""` for what is
    not there.

    A named country narrows the city search to that country — `Valencia` next to
    "España" is not ambiguous, and neither is it next to "Venezuela". A city alone
    implies its country ONLY when the name belongs to one country and is not an
    ordinary word (`WEAK_CITY_SLUGS`): a bare "Valencia" yields `("", "Valencia")`,
    the city kept because it still scopes a local search, the country left blank
    rather than guessed. Guessing is what used to file Venezuelan accounts under
    Spain, and it would file Argentine ones under Spain the moment Córdoba appeared
    in both lists (§ 2026-09-15).

    `country_hint` is the country the OPERATOR already answered. It settles the
    ambiguity the same way naming the country in the text would — a Venezuelan
    business that wrote only "Valencia" in its bio is in the Venezuelan Valencia."""
    tag_slugs = [_slug(tag) for tag in hashtags]
    named = next(iter(named_countries(text)), "")
    hint = country_hint.upper() if country_hint.upper() in COUNTRIES else ""
    scope = named or hint
    for code, info in COUNTRIES.items():
        if scope and code != scope:
            continue
        for city in info.cities:
            if not _city_in(text, tag_slugs, city):
                continue
            if scope or _slug(city) not in WEAK_CITY_SLUGS:
                return code, city
            # An ambiguous name with no country named and none answered: the city is
            # real, the country is not knowable from this text.
            return "", city
    # No city matched — only what the text itself named counts, never the hint.
    return named, ""


@dataclass(frozen=True)
class DiscoverySeed:
    """Everything the phased search reads, and nothing else — so its `signature` is a
    sound cache key."""

    handle: str
    niches: tuple[str, ...]
    hashtags: tuple[str, ...] = ()
    country_code: str = ""
    city: str = ""
    #: Instagram's related accounts of the seed profile (`relatedProfiles`), the free
    #: starting point of the Instagram sector walk.
    related: tuple[str, ...] = ()
    #: The operator's own words for the rubro ("peluquería canina", "fisioterapia
    #: deportiva") — searched as typed and used as relevance stems, so the discovery
    #: works for any rubro, not only the taxonomy's. Filled by the Brand Kit's rubro
    #: step (`rubro_text`); empty when only a taxonomy category was chosen.
    terms: tuple[str, ...] = ()
    #: Hashtags the shared catalog (`hashtag_catalog.catalog_hashtags_for`, migration 0023)
    #: knows for this rubro — what the operator's words resolve to even when they are
    #: misspelled, plus the niche's most seen tags. Set by the wizard AFTER
    #: `seed_from_profile`; deliberately NOT part of `signature` / `phase_signature`: the
    #: catalog grows with every search, and a cache key that followed it would throw away
    #: a stored phase (and spend its credits again) each time it did. A result is reused
    #: for the answers that produced it; the catalog's improvements land on the next
    #: search that is not a cache hit (a new city, the weekly TTL, a version bump).
    catalog_hashtags: tuple[str, ...] = ()
    #: Hashtags the operator curated on Tu rubro y ubicación (the pills — suggested by
    #: Claude with its catalog tools and/or typed by hand). When present they REPLACE
    #: `catalog_hashtags` as the tags the search uses (`steering_hashtags`), and unlike
    #: those they ARE part of the signature: they only change when a person changes
    #: them, and a person who changed them expects a new search, not the stored one.
    chosen_hashtags: tuple[str, ...] = ()

    def steering_hashtags(self) -> tuple[str, ...]:
        """The catalog-side hashtags this search runs with: the operator's pills when
        there are any, otherwise what the catalog / Claude chose."""
        return self.chosen_hashtags or self.catalog_hashtags

    def signature(self) -> str:
        return "|".join(
            [
                f"v{PHASED_PLAN_VERSION}",
                _slug(self.handle),
                ",".join(self.niches),
                ",".join(self.hashtags[:3]),
                self.country_code.upper(),
                _slug(self.city),
                ",".join(_slug(r) for r in self.related[:3]),
                ",".join(_slug(t) for t in self.terms),
                ",".join(sorted(_slug(t) for t in self.chosen_hashtags)),
            ]
        )

    def chips(self) -> list[str]:
        """What the insights screen shows under "Buscamos con": the signals, readable."""
        out = list(self.terms)
        out.extend(NICHE_LABELS.get(n, n) for n in self.niches)
        shown: list[str] = []
        extra = self.chosen_hashtags or self.catalog_hashtags[:3]
        for tag in (*self.hashtags[:3], *extra):
            if tag not in shown:
                shown.append(tag)
        out.extend(f"#{tag}" for tag in shown)
        place = ", ".join(p for p in (self.city, country_name(self.country_code)) if p)
        if place:
            out.append(place)
        return out


def split_terms(text: str) -> tuple[str, ...]:
    """Free text → search terms: split on commas / slashes / "y", trimmed, de-duplicated,
    at most three ("peluquería canina, spa para mascotas" → two terms)."""
    parts = re.split(r"\s*(?:,|/|;|\by\b|\be\b|&)\s*", text or "")
    out: list[str] = []
    for part in parts:
        term = " ".join(part.split())
        if len(term) >= 3 and _slug(term) not in {_slug(t) for t in out}:
            out.append(term)
    return tuple(out[:3])


def seed_from_profile(
    profile: dict[str, Any],
    *,
    sector: str = "",
    rubro_text: str = "",
    country_code: str = "",
    city: str = "",
) -> DiscoverySeed:
    """Read the account's own signals — bio, Instagram's business category, and the
    hashtags it actually uses (`topHashtags`, `scrapecreators_client.
    fetch_profile_and_posts`) — and let explicit answers from the Brand Kit's rubro
    step override what was detected. An explicit `sector` replaces the detected
    niches outright (the operator knows their business better than a regex over
    their bio); an explicit country keeps a detected city only if it is in that
    country."""
    handle = str(profile.get("username") or "")
    own = _slug(handle)
    raw_tags = [str(t).lower() for t in profile.get("topHashtags") or [] if isinstance(t, str)]
    tags = tuple(
        tag for tag in raw_tags if tag not in _GENERIC_HASHTAGS and not (own and own in _slug(tag))
    )
    text = " ".join(
        [str(profile.get("bio") or ""), str(profile.get("category") or "")]
        + [f"#{tag}" for tag in tags]
    )
    terms = split_terms(rubro_text)
    if sector:
        niches: tuple[str, ...] = (resolve_niche(sector),)
    elif terms:
        # Free text only: the taxonomy is consulted, never required — an unknown rubro
        # simply searches with its own words.
        niches = tuple(detect_niches(" ".join(terms)))
    else:
        niches = tuple(detect_niches(text))
    if sector or terms:
        # An explicit rubro overrides the detected one — so hashtags about another
        # topic must not steer the search (a food brand seeded from a programming
        # account's snapshot, measured 2026-09-11). Place tags stay: they locate.
        stems = _stems(" ".join(terms))
        tags = tuple(
            t
            for t in tags
            if (niches and set(detect_niches(f"#{t}")) & set(niches))
            or any(stem in _slug(t) for stem in stems)
            or _is_place_tag_anywhere(t)
        )
    detected_country, detected_city = detect_location(text, tags, country_hint=country_code)
    country = (country_code or detected_country).upper()
    if not city and detected_city and detected_country == country:
        city = detected_city
    related = tuple(
        str(r)
        for r in profile.get("relatedProfiles") or []
        if isinstance(r, str) and r and _slug(r) != own
    )
    return DiscoverySeed(
        handle=handle,
        niches=niches,
        hashtags=tags,
        country_code=country,
        city=city,
        related=related,
        terms=terms,
    )


def _is_place_tag_anywhere(tag: str) -> bool:
    """A hashtag naming any known country or city (`#cucutafood`, `#comidacolombia`,
    `#comidavzla`). Aliases count here too — a short form is still a place."""
    slug = _slug(tag)
    for country in COUNTRIES.values():
        if _slug(country.name) in slug:
            return True
        if any(len(_slug(a)) >= _MIN_ALIAS_LENGTH and _slug(a) in slug for a in country.aliases):
            return True
        if any(len(_slug(city)) >= 6 and _slug(city) in slug for city in country.cities):
            return True
    return False


_STOPWORDS = frozenset(
    {"para", "con", "sin", "del", "las", "los", "una", "uno", "por", "que", "and", "the", "for"}
)


def _stems(text: str) -> set[str]:
    """Word stems (first five letters, accents stripped) of the words worth matching in
    a rubro's own words — `peluquería canina` → {"peluq", "canin"}, so "peluquero",
    "peluquerías" and "canino" all count as the same rubro."""
    out: set[str] = set()
    for word in re.findall(r"[a-z0-9]+", _fold(text)):
        if len(word) >= 4 and word not in _STOPWORDS:
            out.add(word[:5])
    return out
