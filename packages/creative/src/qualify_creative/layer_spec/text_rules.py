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

_TOKEN = re.compile(r"\d+(?:[.,]\d+)*|[a-z]+|[^\sa-z\d]")


def normalise(text: str) -> str:
    """Compatibility form, lower case, no accents — «ñ» folds to «n» like every other mark
    («año» → «ano», «mañana» → «manana») —, one space between words. Every table below is
    written in this form (a test checks it)."""
    plain = unicodedata.normalize("NFKC", text).replace("\u00a0", " ").lower()
    decomposed = unicodedata.normalize("NFD", plain)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
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
        if not after:
            # nothing after: a round figure reads as a price («Desde 2000»), a year that is
            # not round, up to this decade, as a year («… desde 1985»)
            year = int(value)
            return year <= 2029 and year % 50 != 0
        return after.isalpha() and after not in _ARTICLES
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

DAYS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")
#: day names as free text writes them (plural «los domingos» included)
_DAY_OF = {d: d for d in DAYS} | {d + "s": d for d in DAYS if not d.endswith("s")}
#: abbreviations, read ONLY in the saved hours («Lun-Dom», «L a V», «sáb»): in free text
#: «mar» is the sea and «sol» the sun
_DAY_ABBREVIATIONS = {
    "lun": "lunes",
    "mar": "martes",
    "mie": "miercoles",
    "mier": "miercoles",
    "jue": "jueves",
    "vie": "viernes",
    "sab": "sabado",
    "dom": "domingo",
    "l": "lunes",
    "m": "martes",
    "x": "miercoles",
    "j": "jueves",
    "v": "viernes",
    "s": "sabado",
    "d": "domingo",
}
#: one-letter abbreviations count only inside a range («L a V», «L-D»)
_ONE_LETTER = frozenset({"l", "m", "x", "j", "v", "s", "d"})
_HOLIDAY = frozenset({"festivo", "festivos", "feriado", "feriados"})
_WEEKEND = frozenset({"finde", "findes"})
#: before a day name, within the same clause: plain language, not a schedule («Tu sábado»,
#: «Un domingo cualquiera», «Tu look de viernes»)
_POSSESSIVE = frozenset({"tu", "tus", "su", "sus", "mi", "mis", "nuestro", "nuestros", "un", "una"})
#: words around «abierto» that make it an availability promise («abierto hoy», «estamos
#: abiertos», «abierto 24 horas»)
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
        "feriado",
        "feriados",
        "medianoche",
    }
)
#: words that lead into a schedule after «abrimos»/«cerrado» only when a day, an hour or a
#: time word follows them («abrimos de martes…», «cerrado los lunes», «abrimos el domingo»)
_LEAD_INS = frozenset({"de", "del", "los", "las", "el"})
_TIME_WORDS = frozenset({"manana", "noche", "tarde", "festivo", "feriado", "fin", "finde"})
_OPEN_WORDS = frozenset({"abierto", "abierta", "abiertos", "abiertas"})
_OPEN_VERBS = frozenset({"abrimos", "abre", "abren", "atendemos", "atiende", "atienden"})
_CLOSED_WORDS = frozenset({"cerrado", "cerrada", "cerrados", "cerradas", "cerramos"})
#: before a mention in the CONTEXT, in the same clause: it is denied, so it supports nothing
#: («No hacemos domicilios ni nada gratis»)
NEGATIONS = frozenset({"no", "sin", "nunca", "ni", "tampoco", "jamas"})
_CLAUSE_END = frozenset({".", ",", ";", ":", "!", "?", "¡", "¿"})
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
        "siempre abierto",
        "siempre abiertos",
        "abiertos siempre",
        "abierto siempre",
        "siempre listos",
        "siempre disponibles",
        "diario",
        "diarios",
        "diaria",
        "diarias",
        "diariamente",
        "a diario",
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
        "happy hour",
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
#: every word the claim tables use: a product name made only of these is itself a claim
#: phrase («Envío Gratis») and is never masked
CLAIM_WORDS = frozenset(
    {w for phrases in PHRASES.values() for p in phrases for w in p.split() if w.isalpha()}
    | set(_DAY_OF)
    | _OPEN_WORDS
    | _OPEN_VERBS
    | _CLOSED_WORDS
    | _HOLIDAY
    | _WEEKEND
)


def _negated(words: Sequence[str], start: int) -> bool:
    """A negation before `start` in the same clause (at most 4 words back)."""
    j = start - 1
    while j >= 0 and start - j <= 4 and words[j] not in _CLAUSE_END:
        if words[j] in NEGATIONS:
            return True
        j -= 1
    return False


def _find(words: Sequence[str], phrase: str) -> list[int]:
    target = phrase.split()
    n = len(target)
    return [i for i in range(len(words) - n + 1) if list(words[i : i + n]) == target]


def _day_at(word: str, abbreviations: bool) -> str | None:
    if word in _DAY_OF:
        return _DAY_OF[word]
    if abbreviations and word in _DAY_ABBREVIATIONS and word not in _ONE_LETTER:
        return _DAY_ABBREVIATIONS[word]
    return None


def _range(a: str, b: str) -> list[str]:
    """Days from `a` to `b`, wrapping the week («viernes a lunes»); «lunes a lunes» = all."""
    i, j = DAYS.index(a), DAYS.index(b)
    if i == j:
        return list(DAYS)
    return [DAYS[k % 7] for k in range(i, i + ((j - i) % 7) + 1)]


def _days(
    words: Sequence[str], *, abbreviations: bool = False, negation: bool = False
) -> list[tuple[int, list[str], str]]:
    """Each day mention: (position, days, the words). Ranges expanded and wrapped; «fin de
    semana»/«finde» = Saturday and Sunday; «festivo»/«feriado» = «festivo». A day with a
    possessive before it in its clause is plain language. With `abbreviations` (saved hours
    only) «Lun-Dom», «L a V», «sáb» count."""
    found: list[tuple[int, list[str], str]] = []

    def plain(i: int) -> bool:
        j = i - 1
        while j >= 0 and i - j <= 3 and words[j] not in _CLAUSE_END:
            if words[j] in _POSSESSIVE:
                return True
            j -= 1
        return negation and _negated(words, i)

    i = 0
    while i < len(words):
        w = words[i]
        first = _day_at(w, abbreviations)
        if first is None and abbreviations and w in _ONE_LETTER:
            # a one-letter day only inside a range: «L a V», «L-D»
            if i + 2 < len(words) and words[i + 1] in ("a", "-") and words[i + 2] in _ONE_LETTER:
                first = _DAY_ABBREVIATIONS[w]
        if first is not None and not plain(i):
            if i + 2 < len(words) and words[i + 1] in ("a", "-", "al"):
                end = _day_at(words[i + 2], abbreviations) or (
                    _DAY_ABBREVIATIONS.get(words[i + 2]) if abbreviations else None
                )
                if end is not None:
                    found.append((i, _range(first, end), " ".join(words[i : i + 3])))
                    i += 3
                    continue
            found.append((i, [first], w))
        elif w in _HOLIDAY and not plain(i):
            found.append((i, ["festivo"], w))
        elif (w in ("fin", "fines") and list(words[i + 1 : i + 3]) == ["de", "semana"]) or (
            w in _WEEKEND
        ):
            if not plain(i):
                found.append((i, ["sabado", "domingo"], w if w in _WEEKEND else "fin de semana"))
        i += 1
    return found


def _promo_count(words: Sequence[str]) -> str | None:
    """«2x1», «3x2», «2 x 1»: a multi-buy promotion (small numbers)."""
    for i, w in enumerate(words):
        if w == "x" and 0 < i < len(words) - 1:
            a, b = words[i - 1], words[i + 1]
            if a.isdigit() and b.isdigit() and _below_ten(a) and _below_ten(b):
                return f"{a}x{b}"
    return None


def _leads_into_schedule(nxt: Sequence[str]) -> bool:
    if not nxt:
        return True
    head = nxt[0]
    if head in AVAILABILITY or head in _DAY_OF or head in _HOLIDAY:
        return True
    if head in _LEAD_INS and len(nxt) > 1:
        follow = nxt[1]
        return follow in _DAY_OF or follow in _HOLIDAY or follow in _TIME_WORDS or follow.isdigit()
    return False


def _opening(words: Sequence[str]) -> tuple[int, str] | None:
    """«abierto hoy», «estamos abiertos», «abrimos de martes…», «ya abrimos»."""
    for i, w in enumerate(words):
        if w in _OPEN_WORDS:
            near = set(words[max(0, i - 2) : i]) | set(words[i + 1 : i + 3])
            if near & AVAILABILITY:
                return i, w
        if w in _OPEN_VERBS:
            if _leads_into_schedule(words[i + 1 : i + 3]):
                return i, w
            if i > 0 and words[i - 1] in ("ya", "hoy", "ahora"):
                return i, f"{words[i - 1]} {w}"
    return None


def _closing(words: Sequence[str]) -> tuple[int, str] | None:
    for i, w in enumerate(words):
        if w in _CLOSED_WORDS:
            nxt = words[i + 1 : i + 3]
            if _leads_into_schedule(nxt) or (nxt and nxt[0] == "por"):
                return i, w
            if i > 0 and words[i - 1] in ("estamos", "hoy"):
                return i, w
    return None


def _mask(normalised: str, names: Iterable[str]) -> str:
    """The text without the catalog's product names: «Combo Domingo» is not a schedule. A
    name made only of claim words («Envío Gratis») is a claim phrase itself: never masked."""
    out = f" {normalised} "
    for name in names:
        n = normalise(name)
        words = _TOKEN.findall(n)
        if not n or all(w in CLAIM_WORDS for w in words if w.isalpha()):
            continue
        out = out.replace(f" {n} ", " ")
    return out.strip()


@dataclass(frozen=True)
class Claims:
    """What a text promises: claim types, the days it names, and for each type the words
    that make the claim (to quote in a repair)."""

    types: frozenset[str] = frozenset()
    days: frozenset[str] = frozenset()
    evidence: tuple[tuple[str, str], ...] = ()

    def words_for(self, kind: str) -> str:
        return next((w for k, w in self.evidence if k == kind), kind)


def claims_in(
    text: str,
    *,
    product_names: Iterable[str] = (),
    abbreviations: bool = False,
    negation: bool = False,
) -> Claims:
    """The claims of `text`. `negation` (the context's view): a mention denied in its
    clause states nothing. `abbreviations` (saved hours): «Lun-Dom», «L a V» count."""
    words = _TOKEN.findall(_mask(normalise(text), product_names))
    evidence: list[tuple[str, str]] = []
    for kind, phrases in PHRASES.items():
        for phrase in phrases:
            hits = [i for i in _find(words, phrase) if not (negation and _negated(words, i))]
            if hits:
                evidence.append((kind, phrase))
                break
    promo = _promo_count(words)
    if promo and not (negation and _negated(words, words.index("x") - 1)):
        evidence.append(("promotion", promo))
    joined = " ".join(words)
    minus = re.search(r"(?:^| )(- ?\d+ ?%)", joined)
    if minus:
        evidence.append(("discount", minus.group(1)))
    opening = _opening(words)
    if opening and not (negation and _negated(words, opening[0])):
        evidence.append(("hours", opening[1]))
    closing = _closing(words)
    if closing and not (negation and _negated(words, closing[0])):
        evidence.append(("closure", closing[1]))
    days: set[str] = set()
    day_words: list[str] = []
    for _, named, said in _days(words, abbreviations=abbreviations, negation=negation):
        days.update(named)
        day_words.append(said)
    if days:
        evidence.append(("day", ", ".join(day_words)))
    if len(days - {"festivo"}) == 7:
        evidence.append(("every_day", ", ".join(day_words)))
    return Claims(frozenset(k for k, _ in evidence), frozenset(days), tuple(evidence))


@dataclass(frozen=True)
class ContextSupport:
    """What the piece's context states (brief, approved hook and invitation, saved data —
    never product names, never what it denies): the claim types it supports, the days it
    names, and whether the business saved its hours."""

    claims: Claims = field(default_factory=Claims)
    has_hours: bool = False

    @classmethod
    def of(cls, texts: Iterable[str], *, saved_hours: str | None = None) -> ContextSupport:
        types: set[str] = set()
        days: set[str] = set()
        for text in texts:
            if text and text.strip():
                c = claims_in(text, negation=True)
                types |= c.types
                days |= c.days
        if saved_hours and saved_hours.strip():
            c = claims_in(saved_hours, negation=True, abbreviations=True)
            types |= c.types
            days |= c.days
        if "every_day" in types:
            days |= set(DAYS)
        return cls(
            Claims(frozenset(types), frozenset(days)), bool(saved_hours and saved_hours.strip())
        )

    def unsupported(self, claims: Claims) -> list[tuple[str, str]]:
        """Each claim of `claims` the context does not state: (type, the words that make it).
        Days are checked day by day."""
        missing = []
        for kind in sorted(claims.types):
            if kind == "day":
                extra = claims.days - self.claims.days
                if extra:
                    missing.append(("day", claims.words_for("day")))
                continue
            if kind == "hours" and (self.has_hours or {"hours", "every_day"} & self.claims.types):
                continue
            if kind not in self.claims.types:
                missing.append((kind, claims.words_for(kind)))
        return missing


__all__ = [
    "CLAIM_WORDS",
    "Claims",
    "ContextSupport",
    "claims_in",
    "normalise",
    "price_problem",
    "tokens",
]
