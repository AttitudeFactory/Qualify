"""Phone numbers masked in free text before it reaches any vendor, trace, log or stored
proposal (m-24854323, OL2-7; founder decision 7 of docs/epica-prellenado-brand-kit-alta.md
§5: the full number stays in the tenant, out of the logs, and never goes to BytePlus).

Bios and captions carry phone numbers often — typed by hand, with spaces, dots or
dashes, or as a WhatsApp link — and those texts go to Claude, to Langfuse, into the Brand
Kit proposal and, through `brand_context.build_context`, into generation. `mask_phones`
turns every number it recognizes into a fixed-length mask that keeps only the country
code it was written with and the last two digits:

    "WhatsApp +57 300 123 4548"     → "WhatsApp +57 ••• ••• ••48"
    "https://wa.me/573001234548"    → "https://wa.me/+57 ••• ••• ••48"
    "Pedidos al 0414-123.45.67"     → "Pedidos al ••• ••• ••67"

The mask's length never depends on the number's, so it says nothing about the digits it
hides; it carries no digit run a second pass would recognize, so masking is idempotent.

**What counts as a phone** (Colombia, Venezuela, Uruguay — the markets — plus any number
written in international form):

- strong, masked wherever they appear: `+` or `00` followed by 8-15 digits; the country
  code without `+` (57 + 10 digits, 58 + 10 digits, 598 + 8 digits); Colombian mobiles
  (10 digits, 30x-35x) and landlines (60x + 7); Venezuelan numbers (04xx / 02xx + 7, or
  4[12]x without the 0); Uruguayan mobiles with the 0 (09x + 6);
- weak — 8 digits, Uruguay's mobiles without the 0 and its landlines (2xxx / 4xxx) —
  only next to a word that says phone («tel», «cel», «WhatsApp», «llámanos», 📞…) or
  written as `xxxx xxxx` / `xxxx-xxxx`: 8 bare digits are as often a price or a date;
- any number inside a WhatsApp link (`wa.me/…`, `api.whatsapp.com/send?phone=…`) or a
  link's `phone=` / `tel=` parameter.

**What is never touched:** prices (a currency sign or word beside it, or thousands
grouping like `25.000.000`), dates and years (`2026-10-25`, `25/10/2026`, `2026`),
opening hours (`8:00-17:00`, `20.00 - 23.00`), follower counts (`12.000 seguidores`,
`1,2 M`), hashtags (`#3001234567`), @handles (`@tienda3001234567`) and the digits inside
any other link (a CDN picture URL must keep working).

Known gaps, kept on purpose: an 8-digit Uruguayan mobile written `91 234 567` (it reads
exactly like a price) and numbers spelled out in words.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

#: The mask's fixed body; the last two digits follow it.
MASK_BODY = "••• ••• ••"

#: Country codes the mask keeps (the markets); any other `+` number keeps only the `+`.
_MARKET_CODES = ("598", "57", "58")

_WHATSAPP_LINK = re.compile(
    r"(?i)((?:https?://)?(?:www\.)?(?:wa\.me/(?:c/)?|(?:api\.|web\.)?whatsapp\.com/"
    r"(?:catalog/|send/?\?(?:[^\s#]*?&)?phone=)))(\+|%2B)?(\d[\d\-]{5,18}\d)"
)
_PHONE_PARAM = re.compile(
    r"(?i)([?&](?:phone|tel|telefono|whatsapp|celular|cel|numero|number)=)(\+|%2B)?(\d{7,15})"
)
#: Any other link: its digits are left alone (picture URLs, post ids).
_URL = re.compile(r"(?i)(?:https?://|www\.)[!#-+\--:=?-~]+")
#: A run of digits with the separators people type between them.
_RUN = re.compile(r"(?<![\d_@#$€£/=&?%\-])[+(]{0,2}\d(?:[  .\-()]{0,3}\d)*(?![\w%])")
_GROUP = re.compile(r"\d+")
#: A number glued to a word is a phone only when the word says so («Tel3001234567»).
_GLUED_CUE = re.compile(
    r"(?i)(tel|tel[eé]fono|cel|celular|m[oó]vil|whatsapp|wsp|wpp|wa|fijo|llama|ll[aá]manos)$"
)
_WORD_BEFORE = re.compile(r"[^\W\d_]+$")
_CUE = re.compile(
    r"(?i)(tel|cel|m[oó]vil|whats|wsp|wpp|\bwa\b|ll[aá]m|contact|n[uú]mero|fijo|"
    r"📞|☎|📱|💬)"
)
_CURRENCY_BEFORE = re.compile(r"(?i)(\$|us\$|usd|cop|bs\.?|bss|ves|uyu|€|precio:?)\s*$")
_QUANTITY_AFTER = re.compile(
    r"(?i)^\s*(cop|usd|bs\b|pesos|mil\b|k\b|m\b|%|seguidores|followers|likes|me gusta|"
    r"vistas|views|uyu|ves|bol[ií]vares)"
)
#: How far before a weak number a cue word may sit.
_CUE_WINDOW = 40


def _mask(code: str, digits: str) -> str:
    """`+57 ••• ••• ••48`; `+••• ••• ••48` for a foreign code; no prefix without one."""
    prefix = f"+{code} " if code in _MARKET_CODES else ("+" if code else "")
    return f"{prefix}{MASK_BODY}{digits[-2:]}"


def _code_of(digits: str) -> str:
    """The market code an international number starts with, else `?` (foreign)."""
    return next((code for code in _MARKET_CODES if digits.startswith(code)), "?")


def _classify(digits: str, plus: bool) -> tuple[str, bool] | None:
    """`(country code, weak)` when `digits` is a phone; code `""` = written without one."""
    if not plus and digits.startswith("00") and len(digits) >= 10:
        plus, digits = True, digits[2:]
    n = len(digits)
    if plus:
        return (_code_of(digits), False) if 8 <= n <= 15 else None
    if n == 12 and digits.startswith("57") and (digits[2] == "3" or digits[2:4] == "60"):
        return "57", False
    if n == 12 and digits.startswith("58") and digits[2] in "24":
        return "58", False
    if n == 11 and digits.startswith("598") and digits[3] in "249":
        return "598", False
    if n == 10 and digits[0] == "3" and digits[1] in "012345":
        return "", False  # Colombian mobile
    if n == 10 and digits.startswith("60") and digits[2] in "12345678":
        return "", False  # Colombian landline (since 2021)
    if n == 11 and digits[:2] in ("04", "02"):
        return "", False  # Venezuelan mobile / landline
    if n == 10 and digits[:2] in ("41", "42"):
        return "", False  # Venezuelan mobile without the 0
    if n == 9 and digits.startswith("09") and digits[2] != "0":
        return "", False  # Uruguayan mobile
    if n == 8 and (digits[0] in "24" or (digits[0] == "9" and digits[1] != "0")):
        return "", True  # Uruguayan landline / mobile without the 0
    return None


def _thousands(groups: list[str], seps: list[str], plus: bool) -> bool:
    """`25.000.000`, `1,234,567`, `350 000`: a quantity, not a phone."""
    if len(groups) < 2 or groups[0].startswith("0") or not 1 <= len(groups[0]) <= 3:
        return False
    if any(len(group) != 3 for group in groups[1:]):
        return False
    marks = {sep.strip() or " " for sep in seps}
    return marks in ({"."}, {","}) or (marks == {" "} and not plus)


def _datelike(groups: list[str]) -> bool:
    """A year in it (`2026-10-25`, `25 10 2026`), or 8 digits that read as a date."""
    if any(len(g) == 4 and 1900 <= int(g) <= 2099 for g in groups):
        return True
    digits = "".join(groups)
    if len(digits) != 8:
        return False
    readings = ((digits[:4], digits[4:6], digits[6:]), (digits[4:], digits[2:4], digits[:2]))
    for year, month, day in readings:
        if 1900 <= int(year) <= 2099 and 1 <= int(month) <= 12 and 1 <= int(day) <= 31:
            return True
    return False


def _mask_run(text: str, match: re.Match[str]) -> list[tuple[int, int, str]]:
    """The phones inside one run of digits, as `(start, end, mask)` in `text`. A run can
    hold several numbers or a number beside a year («2024 300 123 4567»): the longest
    window of groups that is a phone wins, left to right."""
    run, base = match.group(0), match.start()
    found = list(_GROUP.finditer(run))
    groups = [g.group(0) for g in found]
    seps = [run[found[k - 1].end() : found[k].start()] for k in range(1, len(found))]
    plus_first = "+" in run[: found[0].start()]
    if _thousands(groups, seps, plus_first):
        return []
    out: list[tuple[int, int, str]] = []
    i = 0
    while i < len(groups):
        hit = None
        for j in range(len(groups) - 1, i - 1, -1):
            window, window_seps = groups[i : j + 1], seps[i:j]
            digits = "".join(window)
            if not 7 <= len(digits) <= 17:
                continue
            plus = plus_first and i == 0
            kind = _classify(digits, plus)
            if kind is None or _thousands(window, window_seps, plus):
                continue
            start = base if i == 0 else base + found[i].start()
            if i > 0 and "(" in seps[i - 1]:
                start = base + found[i - 1].end() + seps[i - 1].index("(")
            end = base + found[j].end()
            if _CURRENCY_BEFORE.search(text[max(0, start - 8) : start]):
                continue
            if _QUANTITY_AFTER.search(text[end : end + 14]):
                continue
            code, weak = kind
            if weak:
                if _datelike(window):
                    continue
                spaced = len(window) == 2 and len(window[0]) == 4 and window_seps[0] in (" ", "-")
                if not spaced and not _CUE.search(text[max(0, start - _CUE_WINDOW) : start]):
                    continue
            hit = (j, (start, end, _mask(code, digits)))
            break
        if hit is None:
            i += 1
            continue
        j, span = hit
        out.append(span)
        i = j + 1
    return out


def _link_digits(prefix: str, plus: str | None, digits: str) -> str:
    """The number inside a WhatsApp link or a `phone=` parameter: always a phone. Written
    with `+`, it is international; without, it reads as written (`573001234567` is
    Colombian with its code, `3001234567` a Colombian mobile without one)."""
    digits = digits.replace("-", "")
    kind = None if plus else _classify(digits, False)
    if kind is None:
        kind = _classify(digits, True)
    return prefix + _mask(kind[0] if kind else "", digits)


def mask_phones(text: str) -> str:
    """`text` with every phone number masked (`+57 ••• ••• ••48`). Pure and idempotent;
    anything that is not a phone comes back byte for byte."""
    if not text or not any(ch.isdigit() for ch in text):
        return text
    text = _WHATSAPP_LINK.sub(lambda m: _link_digits(m.group(1), m.group(2), m.group(3)), text)
    text = _PHONE_PARAM.sub(lambda m: _link_digits(m.group(1), m.group(2), m.group(3)), text)
    links = [m.span() for m in _URL.finditer(text)]
    spans: list[tuple[int, int, str]] = []
    for match in _RUN.finditer(text):
        if any(lo <= match.start() < hi for lo, hi in links):
            continue
        word = _WORD_BEFORE.search(text[: match.start()])
        if word is not None and word.end() == match.start():
            if not _GLUED_CUE.search(word.group(0)):
                continue  # «cafe3001234567», a handle or a code: not a phone
        spans.extend(_mask_run(text, match))
    for start, end, masked in reversed(spans):
        text = text[:start] + masked + text[end:]
    return text


#: Keys whose values are identifiers, never free text: a handle, a post id, an R2 key or
#: a hash can hold a digit run that reads like a phone, and must stay byte for byte.
IDENTIFIER_KEYS = frozenset(
    {
        "username",
        "handle",
        "relatedProfiles",
        "id",
        "postId",
        "code",
        "shortcode",
        "stable_id",
        "key",
        "pic_key",
        "pic_content_type",
        "content_type",
        "sha256",
    }
)


def mask_phones_in(value: Any, *, keep: frozenset[str] = IDENTIFIER_KEYS) -> Any:
    """Every string inside `value` (dicts, lists, tuples, nested) masked, except under the
    keys in `keep` (identifiers); keys, numbers and everything else as they were. `value`
    is never modified: what changed is a copy, and what did not change is returned as
    the same object."""
    if isinstance(value, str):
        masked = mask_phones(value)
        return value if masked == value else masked
    if isinstance(value, Mapping):
        items = {
            key: item if key in keep else mask_phones_in(item, keep=keep)
            for key, item in value.items()
        }
        same = all(items[key] is item for key, item in value.items())
        return value if same else items
    if isinstance(value, list | tuple):
        masked = [mask_phones_in(item, keep=keep) for item in value]
        if all(new is old for new, old in zip(masked, value, strict=True)):
            return value
        return masked if isinstance(value, list) else tuple(masked)
    return value


def whatsapp_numbers(text: str) -> list[str]:
    """The full digits of each WhatsApp link in `text` (`wa.me/…`, `phone=…`), for the
    one place the full number may live: the tenant's `connect.contact` document. Never
    log, trace or send what this returns."""
    out: list[str] = []
    for match in _WHATSAPP_LINK.finditer(text or ""):
        digits = match.group(3).replace("-", "")
        if digits not in out:
            out.append(digits)
    return out
