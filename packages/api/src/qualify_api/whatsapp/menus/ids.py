"""Generated identifiers for menu steps, buttons and answers (m-24848536).

The owner never types an identifier: a step is created with an id made of a slug of
its name plus a short random suffix (`horario-3fa9`), and that id **never changes
again** — renaming a step changes its `title` (schema), not its id. That is what keeps
a published menu working while it is edited: every arrow, keyword and WhatsApp
shortcut points at an id, and ids are stable.

Rules (architect review, 2026-10-23):

- slug: NFKD, accents dropped, lowercase, every run of other characters → one
  separator, trimmed, at most `SLUG_MAX_LEN` characters; empty → a fallback word;
- suffix: `SUFFIX_BYTES` random bytes in hex (`secrets`), retried until unused;
- node ids match `schema._NODE_ID_RE` (a slug starts with `[a-z0-9]`, and with the
  suffix stays far under 64 characters).

A question's answer key (`CollectNode.field`) is not generated: the editor offers a short
list of plain-word fields (dirección, teléfono…) that Chats already knows how to label.

Pure apart from the randomness, which is injectable (`token`) for tests.
"""

from __future__ import annotations

import re
import secrets
import unicodedata
from collections.abc import Callable, Collection

SLUG_MAX_LEN = 40
SUFFIX_BYTES = 2
_MAX_TRIES = 64

_NON_SLUG = re.compile(r"[^a-z0-9]+")


def _random_token() -> str:
    return secrets.token_hex(SUFFIX_BYTES)


def slugify(text: str, *, sep: str = "-", fallback: str = "paso") -> str:
    """`"¿Horario y ubicación?"` → `"horario-y-ubicacion"`."""
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    slug = _NON_SLUG.sub(sep, ascii_only.casefold()).strip(sep)
    slug = slug[:SLUG_MAX_LEN].rstrip(sep)
    return slug or fallback


def _unique(base: str, sep: str, taken: Collection[str], token: Callable[[], str]) -> str:
    used = set(taken)
    for _ in range(_MAX_TRIES):
        candidate = f"{base}{sep}{token()}"
        if candidate not in used:
            return candidate
    # A stubborn (or constant, in a test) token: widen the suffix until it is free.
    suffix = token()
    n = 2
    while f"{base}{sep}{suffix}{n}" in used:
        n += 1
    return f"{base}{sep}{suffix}{n}"


def new_node_id(
    label: str, taken: Collection[str], *, token: Callable[[], str] = _random_token
) -> str:
    """A step id for a new step called `label`, unused in `taken`."""
    return _unique(slugify(label, fallback="paso"), "-", taken, token)


def new_option_id(
    label: str, taken: Collection[str], *, token: Callable[[], str] = _random_token
) -> str:
    """A button / list-row id (what WhatsApp echoes back when it is tapped)."""
    return _unique(slugify(label, fallback="boton"), "-", taken, token)


__all__ = ["SLUG_MAX_LEN", "new_node_id", "new_option_id", "slugify"]
