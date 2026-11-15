"""The text layer's two free-text rules, structured (REGLAS-001, m-25017292).

1. **Price figures** (`price_problem`): no amount of money travels in free text — a price
   enters only by reference to a catalog product (catalog §1.8, founder 2026-11-14).
2. **Claims** (`claims_in`, `ContextSupport`): a promise about days, every day, opening hours,
   a closure, a discount, something free, delivery, a promotion or a novelty, which the
   piece's context (brief, approved hook and invitation, saved data) must state with the same
   TYPE — and, for days, the same days — to be written.

The text is normalised once (Unicode compatibility, non-breaking spaces, case, accents) and
tokenised; every decision reads small explicit tables below, never one-off patterns. Linear
in the length of the text: no backtracking regular expression.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

# -- normalisation and tokens ----------------------------------------------------------------

_TOKEN = re.compile(r"\d+(?:[.,]\d+)*|[a-zñ]+|[^\sa-zñ\d]")


def normalise(text: str) -> str:
    """Compatibility form, no accents (ñ kept), lower case, one space between words."""
    plain = unicodedata.normalize("NFKC", text).replace(" ", " ").lower()
    decomposed = unicodedata.normalize("NFD", plain.replace("ñ", "\x00"))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c)).replace("\x00", "ñ")
    return " ".join(stripped.split())


def tokens(text: str) -> list[str]:
    """Numbers (with their separators), words, and single symbols, in order."""
    return _TOKEN.findall(normalise(text))


def _is_number(token: str) -> bool:
    return token[:1].isdigit()


def _digits(token: str) -> str:
    return "".join(c for c in token if c.isdigit())


def _below_ten(token: str) -> bool:
    """A one-digit count («2x1», «paga 1») — by length, never `int()` on a long digit run."""
    d = _digits(token).lstrip("0")
    return len(d) <= 1


# -- 1. price figures -----------------------------------------------------------------------

CURRENCY_SYMBOLS = frozenset("$€£¥₡₲₱")
#: a currency or amount word next to a number («15 mil», «20 bs», «USD 5», «12 lucas»)
AMOUNT_AFTER = frozenset(
    {
        "cop",
        "usd",
        "us",
        "ves",
        "uyu",
        "bs",
        "bsf",
        "bss",
        "bsd",
        "eur",
        "euro",
        "euros",
        "peso",
        "pesos",
        "pesitos",
        "sol",
        "soles",
        "bolivar",
        "bolivares",
        "dolar",
        "dolares",
        "ref",
        "verdes",
        "mil",
        "k",
        "luca",
        "lucas",
        "luquitas",
        "millon",
        "millones",
        "palo",
        "palos",
    }
)
#: the codes that may also come BEFORE the number («USD 5», «Bs 250», «COP 25.000»)
AMOUNT_BEFORE = frozenset({"cop", "usd", "us", "ves", "uyu", "bs", "bsf", "bss", "eur"})
#: written numbers before an amount word («Por veinte mil», «Un palo el arriendo»)
WRITTEN = frozenset(
    {
        "un",
        "uno",
        "una",
        "dos",
        "tres",
        "cuatro",
        "cinco",
        "seis",
        "siete",
        "ocho",
        "nueve",
        "diez",
        "once",
        "doce",
        "trece",
        "catorce",
        "quince",
        "dieciseis",
        "diecisiete",
        "dieciocho",
        "diecinueve",
        "veinte",
        "veintiuno",
        "veintidos",
        "veinticinco",
        "treinta",
        "cuarenta",
        "cincuenta",
        "sesenta",
        "setenta",
        "ochenta",
        "noventa",
        "cien",
        "ciento",
        "doscientos",
        "trescientos",
        "cuatrocientos",
        "quinientos",
        "medio",
    }
)
#: words that put a price after them («a 2000», «por 25», «solo 99», «desde 15», «precio 18»)
PRICE_WORDS = frozenset(
    {
        "a",
        "por",
        "solo",
        "desde",
        "precio",
        "en",
        "cuesta",
        "cuestan",
        "vale",
        "valen",
        "valor",
        "apenas",
        "pagas",
        "paga",
        "pague",
        "sale",
        "dejamos",
        "x",
    }
)
_PAY = frozenset({"paga", "pagas", "pague"})
#: what a number counts or measures, when it follows the number — then it is no price
UNITS = frozenset(
    {
        "%",
        "g",
        "gr",
        "grs",
        "gramo",
        "gramos",
        "kg",
        "kilo",
        "kilos",
        "ml",
        "l",
        "litro",
        "litros",
        "cc",
        "onza",
        "onzas",
        "oz",
        "cm",
        "m",
        "m2",
        "²",
        "metro",
        "metros",
        "km",
        "cuadra",
        "cuadras",
        "unidad",
        "unidades",
        "pieza",
        "piezas",
        "porcion",
        "porciones",
        "persona",
        "personas",
        "sabor",
        "sabores",
        "ingrediente",
        "ingredientes",
        "opcion",
        "opciones",
        "tipo",
        "tipos",
        "paso",
        "pasos",
        "segundo",
        "segundos",
        "minuto",
        "minutos",
        "min",
        "hora",
        "horas",
        "h",
        "dia",
        "dias",
        "noche",
        "noches",
        "semana",
        "semanas",
        "mes",
        "meses",
        "ano",
        "anos",
        "habitacion",
        "habitaciones",
        "bano",
        "banos",
        "piso",
        "pisos",
        "estrella",
        "estrellas",
        "queso",
        "quesos",
        "relleno",
        "rellenos",
        "taza",
        "tazas",
        "dona",
        "donas",
        "pedido",
        "pedidos",
        "favorito",
        "favoritos",
        "mas",
        "talla",
        "tallas",
    }
)
#: words before a number that make it an address, a code, a size or a rank — no price
NOT_PRICE_BEFORE = frozenset(
    {
        "calle",
        "cl",
        "carrera",
        "cra",
        "kr",
        "avenida",
        "av",
        "diagonal",
        "transversal",
        "local",
        "piso",
        "apto",
        "apartamento",
        "oficina",
        "torre",
        "casa",
        "manzana",
        "sector",
        "km",
        "#",
        "n",
        "no",
        "numero",
        "talla",
        "tallas",
        "modelo",
        "ref",
        "referencia",
        "estrato",
        "mesa",
        "top",
        "puesto",
        "lote",
        "bloque",
        "etapa",
        "la",
        "el",
        "las",
        "los",
        "tus",
        "tu",
        "sus",
        "su",
        "celebra",
        "cumplimos",
        "cumple",
        "para",
        "con",
        "y",
        "al",
        "-",
        "/",
        "cada",
    }
)
#: nouns before «de»/«del» or before the year itself that make a 1900–2099 number a year
YEAR_NOUNS = frozenset(
    {
        "navidad",
        "temporada",
        "coleccion",
        "edicion",
        "verano",
        "invierno",
        "primavera",
        "otono",
        "cosecha",
        "novedades",
        "ano",
        "version",
        "generacion",
        "promocion",
        "clase",
    }
)
#: what may follow «desde YYYY» for it to be a year («Desde 1998 contigo»); an article or
#: nothing reads as a price («Desde 2000», «Desde 2000 el café»)
_ARTICLES = frozenset({"el", "la", "los", "las", "un", "una", "por", "cada", "c", "/"})


def _word_before(toks: Sequence[str], i: int) -> str:
    """The nearest word or symbol before position `i`, skipping «:» and «,»."""
    j = i - 1
    while j >= 0 and toks[j] in (":", ",", "."):
        j -= 1
    return toks[j] if j >= 0 else ""


def _is_year(toks: Sequence[str], i: int) -> bool:
    value = toks[i]
    if not (len(value) == 4 and value.isdigit() and 1900 <= int(value) <= 2099):
        return False
    before = _word_before(toks, i)
    after = toks[i + 1] if i + 1 < len(toks) else ""
    if before in YEAR_NOUNS:
        return True
    if before in ("de", "del") and i >= 2 and _word_before(toks, i - 1) in YEAR_NOUNS:
        return True
    if before == "en":
        return True
    if before == "desde":
        return bool(after) and after.isalpha() and after not in _ARTICLES
    return before == "" and bool(after) and after in (",", "contigo")


def price_problem(text: str) -> str | None:
    """«currency» when an amount word or symbol travels with a number (or a written one),
    «price figure» when a number reads as an amount; None when the text carries no price."""
    toks = tokens(text)
    if any(t in CURRENCY_SYMBOLS for t in toks):
        return "currency"
    for i, tok in enumerate(toks):
        nxt = toks[i + 1] if i + 1 < len(toks) else ""
        if tok in AMOUNT_AFTER and i > 0 and (_is_number(toks[i - 1]) or toks[i - 1] in WRITTEN):
            # «ref» only after the number: «Ref. 2045» before it is a product code
            return "currency"
        if tok in AMOUNT_BEFORE and _is_number(nxt):
            return "currency"
    for i, tok in enumerate(toks):
        if not _is_number(tok):
            continue
        before = _word_before(toks, i)
        after = toks[i + 1] if i + 1 < len(toks) else ""
        # «2x1», «3 x 2»: a promotion count; «3 x 2000», «4 x 10.000»: a price
        if after == "x" and i + 2 < len(toks) and _is_number(toks[i + 2]):
            continue
        if before == "x" and i >= 2 and _is_number(toks[i - 2]) and _below_ten(tok):
            continue
        # «de 7 a 20», «Talla 38 a 42»: a range, not a price
        if before == "a" and i >= 2 and _is_number(toks[i - 2]):
            continue
        if after in UNITS:
            continue
        if before in NOT_PRICE_BEFORE:
            continue
        separated = bool(re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+|\d+[.,]\d{2}", tok))
        if separated:
            return "price figure"
        if _is_year(toks, i):
            continue
        if before in PRICE_WORDS:
            # «Lleva 2 y paga 1»: paying for a count of units, not an amount
            if before in _PAY and _below_ten(tok):
                continue
            return "price figure"
        if len(_digits(tok)) >= 3 and "." not in tok and "," not in tok:
            return "price figure"
    return None


# -- 2. claims ------------------------------------------------------------------------------

DAYS = (
    "lunes",
    "martes",
    "miercoles",
    "jueves",
    "viernes",
    "sabado",
    "domingo",
)
_DAY_OF = {d: d for d in DAYS} | {d + "s": d for d in DAYS if not d.endswith("s")}
#: before a day name: it is plain language, not a schedule («Tu sábado», «Un domingo cualquiera»)
_POSSESSIVE = frozenset({"tu", "tus", "su", "sus", "mi", "mis", "nuestro", "nuestros", "un", "una"})
#: words around «abierto»/«abrimos» that make it an availability promise
AVAILABILITY = frozenset(
    {
        "hoy",
        "manana",
        "ya",
        "temprano",
        "tarde",
        "todos",
        "todo",
        "toda",
        "desde",
        "hasta",
        "siempre",
        "24",
        "este",
        "esta",
        "estamos",
        "seguimos",
        "ahora",
        "festivo",
        "festivos",
        "de",
        "del",
        "los",
        "las",
        "medianoche",
    }
)
_OPEN_WORDS = frozenset({"abierto", "abierta", "abiertos", "abiertas"})
_OPEN_VERBS = frozenset({"abrimos", "abre", "abren", "atendemos", "atiende", "atienden"})
_CLOSED_WORDS = frozenset({"cerrado", "cerrada", "cerrados", "cerradas", "cerramos", "cierra"})
#: phrases by claim type, matched on whole normalised words
PHRASES: dict[str, tuple[str, ...]] = {
    "every_day": (
        "todos los dias",
        "cada dia",
        "cada noche",
        "todas las noches",
        "24 horas",
        "24 / 7",
        "toda la semana",
        "toda la noche",
        "los 7 dias",
        "sin dias de descanso",
        "sin descanso",
        "lunes a domingo",
        "siempre abierto",
        "siempre abiertos",
        "abiertos siempre",
        "abierto siempre",
        "siempre listos",
        "siempre disponibles",
    ),
    "hours": ("horario extendido", "nuevo horario", "horario especial", "hasta tarde"),
    "closure": ("no abrimos", "cerrado por", "cerrados por"),
    "discount": (
        "descuento",
        "descuentos",
        "dcto",
        "rebaja",
        "rebajas",
        "rebajado",
        "% off",
        "% menos",
        "mitad de precio",
        "precios de locura",
        "liquidacion",
        "black friday",
        "oferta",
        "ofertas",
        "ahorra",
        "precio rebajado",
        "% de descuento",
    ),
    "free": (
        "gratis",
        "gratuito",
        "gratuita",
        "gratuitos",
        "de regalo",
        "te regalamos",
        "regalamos",
        "obsequio",
        "cortesia",
        "sin costo",
        "sin cargo",
    ),
    "delivery": (
        "domicilio",
        "domicilios",
        "envio",
        "envios",
        "enviamos",
        "delivery",
        "despacho",
        "despachos",
        "te lo llevamos",
        "lo llevamos",
        "llevamos tu",
        "te llevamos",
        "llega a casa",
        "llega a tu casa",
        "a tu puerta",
        "en tu puerta",
        "entregas",
        "llega a tu puerta",
    ),
    "promotion": (
        "dos por uno",
        "tres por dos",
        "lleva 2 y paga 1",
        "paga 1 lleva 2",
        "paga 1 , lleva 2",
        "al doble",
        "por la sencilla",
        "refill",
        "ilimitado",
        "ilimitada",
        "ilimitados",
        "que no se acaban",
        "promo",
        "promocion",
        "segunda unidad",
        "noche extra",
    ),
    "novelty": (
        "inauguracion",
        "inauguramos",
        "inaugurados",
        "inaugurado",
        "inaugura",
        "estreno",
        "estrenamos",
        "reapertura",
        "reabrimos",
        "volvemos a abrir",
        "nuevo local",
        "nueva sede",
        "nuevo horario",
        "nuevo menu",
        "nueva carta",
        "nueva tienda",
        "nueva sucursal",
        "nuevo punto",
        "un nuevo local",
        "nuestra nueva sede",
    ),
}


def _has_phrase(words: Sequence[str], phrase: str) -> bool:
    target = phrase.split()
    n = len(target)
    return any(list(words[i : i + n]) == target for i in range(len(words) - n + 1))


def _days(words: Sequence[str]) -> set[str]:
    """Day names claimed, ranges expanded («de martes a domingo»), «fin de semana» as
    Saturday and Sunday, «festivo» as itself; a day after a possessive is plain language."""
    found: set[str] = set()
    i = 0
    while i < len(words):
        w = words[i]
        day = _DAY_OF.get(w)
        if day and (i == 0 or words[i - 1] not in _POSSESSIVE):
            if i + 2 < len(words) and words[i + 1] == "a" and words[i + 2] in _DAY_OF:
                a, b = DAYS.index(day), DAYS.index(_DAY_OF[words[i + 2]])
                found.update(DAYS[k] for k in range(a, b + 1) if a <= b)
                i += 3
                continue
            found.add(day)
        if w in ("festivo", "festivos") and (i == 0 or words[i - 1] not in _POSSESSIVE):
            found.add("festivo")
        if w in ("fin", "fines") and words[i + 1 : i + 3] == ["de", "semana"]:
            if i == 0 or words[i - 1] not in _POSSESSIVE:
                found.update({"sabado", "domingo"})
        i += 1
    return found


def _promo_count(words: Sequence[str]) -> bool:
    """«2x1», «3x2», «2 x 1», «2 x 1 en …»: a multi-buy promotion (small numbers)."""
    for i, w in enumerate(words):
        if w == "x" and 0 < i < len(words) - 1:
            a, b = words[i - 1], words[i + 1]
            if a.isdigit() and b.isdigit() and _below_ten(a) and _below_ten(b):
                return True
    return False


def _opening(words: Sequence[str]) -> bool:
    """«abierto hoy», «estamos abiertos», «abrimos de martes…», «atendemos hasta tarde»."""
    for i, w in enumerate(words):
        near = set(words[max(0, i - 2) : i] + words[i + 1 : i + 3])
        if w in _OPEN_WORDS and near & AVAILABILITY:
            return True
        if w in _OPEN_VERBS:
            nxt = words[i + 1 : i + 3]
            if not nxt:
                return True
            if nxt[0] in AVAILABILITY or nxt[0] in _DAY_OF:
                return True
            if nxt[0] == "el" and len(nxt) > 1 and (nxt[1] in _DAY_OF or nxt[1] == "festivo"):
                return True
    return False


def _closing(words: Sequence[str]) -> bool:
    for i, w in enumerate(words):
        if w in _CLOSED_WORDS and w != "cierra":
            nxt = words[i + 1 : i + 3]
            if not nxt or nxt[0] in AVAILABILITY or nxt[0] in _DAY_OF or nxt[0] == "por":
                return True
            if words[max(0, i - 1) : i] in (["estamos"], ["hoy"]):
                return True
            if nxt[0] == "el" and len(nxt) > 1:
                return True
    return False


def _mask(normalised: str, names: Iterable[str]) -> str:
    """The text without the catalog's product names: «Combo Domingo» is not a schedule."""
    out = f" {normalised} "
    for name in names:
        n = normalise(name)
        if n:
            out = out.replace(f" {n} ", " ")
    return out.strip()


@dataclass(frozen=True)
class Claims:
    """What a text promises: claim types, and the days it names."""

    types: frozenset[str] = frozenset()
    days: frozenset[str] = frozenset()


def claims_in(text: str, *, product_names: Iterable[str] = ()) -> Claims:
    words = _TOKEN.findall(_mask(normalise(text), product_names))
    found: set[str] = set()
    joined = " ".join(words)
    for kind, phrases in PHRASES.items():
        if any(_has_phrase(words, p) for p in phrases):
            found.add(kind)
    if _promo_count(words):
        found.add("promotion")
    if re.search(r"(?:^| )- ?\d+ ?%", joined):
        found.add("discount")
    if _opening(words):
        found.add("hours")
    if _closing(words):
        found.add("closure")
    days = _days(words)
    if days:
        found.add("day")
    if len(days - {"festivo"}) == 7:
        found.add("every_day")
    return Claims(frozenset(found), frozenset(days))


@dataclass(frozen=True)
class ContextSupport:
    """What the piece's context states (brief, approved hook and invitation, saved data —
    never product names): the claim types it supports, the days it names, and whether the
    business saved its hours."""

    claims: Claims = field(default_factory=Claims)
    has_hours: bool = False

    @classmethod
    def of(cls, texts: Iterable[str], *, saved_hours: str | None = None) -> ContextSupport:
        merged = Claims()
        for text in [*texts, saved_hours or ""]:
            if text and text.strip():
                c = claims_in(text)
                merged = Claims(merged.types | c.types, merged.days | c.days)
        if "every_day" in merged.types:
            merged = Claims(merged.types, merged.days | frozenset(DAYS))
        return cls(merged, bool(saved_hours and saved_hours.strip()))

    def unsupported(self, claims: Claims) -> list[str]:
        """Each claim of `claims` the context does not state, by type (days: by day)."""
        missing = []
        for kind in sorted(claims.types):
            if kind == "day":
                extra = claims.days - self.claims.days
                if extra:
                    missing.append(f"day ({', '.join(sorted(extra))})")
                continue
            if kind == "hours" and (self.has_hours or {"hours", "every_day"} & self.claims.types):
                continue
            if kind not in self.claims.types:
                missing.append(kind)
        return missing


__all__ = [
    "Claims",
    "ContextSupport",
    "claims_in",
    "normalise",
    "price_problem",
    "tokens",
]
