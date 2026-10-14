"""The Dashboard de Menciones' paging and refresh rules (QUA-152) — pure, no Reflex, no I/O.

`DashboardState` gathers the facts (page, totals, the snapshot it is showing, what a
refresh tick just read) and asks these functions what to show and what to do. Keeping them
pure is what lets the rules be tested directly; a Reflex handler cannot run outside a live
app (same split `inbox_sync_policy.py` makes for `/inbox`).

## The snapshot rule

Every page of a listing is read under one snapshot, `as_of` (`received_at <= as_of`, see
`qualify_api.mentions.repository.MentionPage`). Paging keeps it, so walking pages never
shows a duplicate or skips a row. A new mention therefore never appears by itself: a
refresh tick only COUNTS what arrived after `as_of` and announces it; the user takes it in
with "Actualizar lista", which starts a new snapshot on page 1. The order stays
chronological by publication date, so a new mention about an old post can land on a later
page — the guarantee is to detect and announce it, not to put it first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

# Filter labels as the selects show them -> the codes `MentionQuery` takes. The first
# entry of each is "no filter".
ALL_ACCOUNTS: Final = "Todas las cuentas"
ALL_ORIGINS: Final = "Todos los orígenes"
ALL_SENTIMENTS: Final = "Todos los sentimientos"

ORIGIN_OPTIONS: Final[dict[str, str | None]] = {
    ALL_ORIGINS: None,
    "Publicación": "post",
    "Comentario": "comment",
}

# The view window (QUA-152, founder's call 2026-10-13: a mention older than two weeks rarely
# matters, so the screen opens on the last 14 days). A VIEW filter only — nothing is
# deleted, and "Todo el historial" shows every stored mention.
ALL_HISTORY: Final = "Todo el historial"
DEFAULT_PERIOD: Final = "Últimos 14 días"
PERIOD_OPTIONS: Final[dict[str, int | None]] = {
    "Últimos 7 días": 7,
    DEFAULT_PERIOD: 14,
    "Últimos 30 días": 30,
    ALL_HISTORY: None,
}

SENTIMENT_OPTIONS: Final[dict[str, str | None]] = {
    ALL_SENTIMENTS: None,
    "Positiva": "POS",
    "Neutra": "NEU",
    "Negativa": "NEG",
    "Pendiente": "PENDING",
}
# "Sin texto" / "Error de análisis" are not sentiments (founder review 2026-10-13): those
# rows read "Sin análisis" and are not offered as a sentiment filter.


PAGE_WINDOW: Final = 10


def page_items(current: int, total_pages: int, *, window: int = PAGE_WINDOW) -> list[str]:
    """Up to `window` consecutive page numbers around the current one, no gaps — the
    compact pager the founder picked (2026-10-13): "‹ 1 2 3 … 10 ›" style, arrows apart.

    >>> page_items(1, 40)
    ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10']
    """
    if total_pages <= 1:
        return ["1"]
    current = min(max(1, current), total_pages)
    first = max(1, min(current - window // 2 + 1, total_pages - window + 1))
    last = min(total_pages, first + window - 1)
    return [str(page) for page in range(first, last + 1)]


def pages_label(total_pages: int) -> str:
    return "Total de 1 página" if total_pages <= 1 else f"Total de {total_pages} páginas"


def new_mentions_label(count: int, *, cap: int) -> str:
    """The notice text; '' when there is nothing new. At the cap it reads 'N+'."""
    if count <= 0:
        return ""
    amount = f"{cap}+" if count >= cap else str(count)
    return "1 mención nueva" if amount == "1" else f"{amount} menciones nuevas"


TickAction = Literal["update_rows", "announce_change"]


@dataclass(frozen=True)
class TickDecision:
    """What a refresh tick does with the page it just re-read under the SAME snapshot."""

    action: TickAction
    new_count: int


def decide_tick(*, snapshot_total: int, reread_total: int, new_count: int) -> TickDecision:
    """Same total under the same snapshot = the same set of rows: replace them in place,
    which only refreshes their data (a sentiment that just got analyzed). A different total
    means the set itself changed (a row deleted, a mention committed late into the
    snapshot, or a sentiment filter whose matches moved): never swap the rows silently —
    announce it and let the user refresh."""
    if reread_total != snapshot_total:
        return TickDecision(action="announce_change", new_count=new_count)
    return TickDecision(action="update_rows", new_count=new_count)


# --- "Actualizar menciones" outcome (QUA-152) ------------------------------------------

REFRESHING_NOTICE: Final = "Actualizando las menciones del periodo…"


@dataclass(frozen=True)
class RefreshOutcome:
    """What the dashboard says once a refresh run over the scope has finished."""

    message: str
    tone: Literal["ok", "warn", "info", ""]


def refresh_outcome(
    *,
    in_scope: int,
    refreshed: int,
    already_fresh: int,
    failed: int,
    not_attempted: int,
    rate_limited: bool,
) -> RefreshOutcome:
    """Never says "done" while anything of the scope is still pending: a mention the
    network refused, or one left for a later run (per-run cap, throttling), keeps the
    notice in warning tone with what to do next."""
    if failed == 0 and not_attempted == 0:
        if in_scope == 0:
            return RefreshOutcome("No hay menciones en este periodo para actualizar.", "info")
        noun = "la mención" if in_scope == 1 else f"las {in_scope} menciones"
        return RefreshOutcome(f"Se actualizaron {noun} del periodo.", "ok")
    current = refreshed + already_fresh
    parts = [f"Se actualizaron {current} de {in_scope} menciones."]
    if failed:
        parts.append(
            "1 no se pudo leer en la red social y conserva sus datos."
            if failed == 1
            else f"{failed} no se pudieron leer en la red social y conservan sus datos."
        )
    if not_attempted:
        reason = (
            "la red social limitó las consultas"
            if rate_limited
            else "se alcanzó el límite de esta actualización"
        )
        parts.append(
            f"1 quedó pendiente porque {reason}."
            if not_attempted == 1
            else f"{not_attempted} quedaron pendientes porque {reason}."
        )
    parts.append("Vuelve a pulsar Actualizar para continuar.")
    return RefreshOutcome(" ".join(parts), "warn")
