"""What to search the stock bank for, from what the Brand Kit already says about the brand
(§ request 2026-10-16: «que la búsqueda se pase directamente cuando le doy al botón
trayendo de contexto lo expuesto en el brandkit»).

A bank matches short keywords word by word, not sentences — a positioning paragraph
returns nothing — so the candidates are the kit's short words: the rubro in the
operator's own words and the brand's hashtags (Tu rubro y ubicación). Measured on the
burger test brand (2026-10-16), which is why the list is what it is:
- the rubro «smashburguer» (misspelled) and the joined hashtag «smashburger» bring
  nothing; «hamburguesas» and «burger» bring full pages — so a word that misses gives its
  place to the next one (`StockService.search_many`);
- the CATALOG's product names are left out: Pixabay matches them word by word, so
  «smash doble» brought a typewriter and a DNA helix, «super smash» Super Mario;
- the niche label is a last resort, used only when the kit has no rubro and no hashtag:
  «comida y bebida» brought 2 images (tea, lemons).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

#: Never more candidates than this — each one that misses the cache is a request to the
#: bank, and they all answer one click.
MAX_CANDIDATES = 6
_MIN_CHARS = 3
_SPACES = re.compile(r"\s+")


def _clean(value: str) -> str:
    text = _SPACES.sub(" ", value.replace("#", " ").replace("_", " ")).strip().casefold()
    return text[:100]


def kit_queries(
    *,
    rubro: Iterable[str] = (),
    hashtags: Iterable[str] = (),
    niches: Iterable[str] = (),
) -> list[str]:
    """The stock searches the brand's kit suggests, deduplicated: the rubro, then the
    hashtags; the niche only when there is neither."""
    seen: dict[str, None] = {}

    def add(group: Iterable[str]) -> None:
        for raw in group:
            text = _clean(str(raw or ""))
            if len(text) >= _MIN_CHARS and text not in seen:
                seen[text] = None

    add(rubro)
    add(hashtags)
    if not seen:
        add(niches)
    return list(seen)[:MAX_CANDIDATES]
