"""The Dashboard de Menciones' paging and refresh rules (QUA-152) — pure, no Reflex, no I/O.

`DashboardState` gathers the facts (page, totals, the snapshot it is showing, what a
refresh tick just read) and asks these functions what to show and what to do. Keeping them
pure is what lets the rules be tested directly; a Reflex handler cannot run outside a live
app (same split `inbox_sync_policy.py` makes for `/inbox`).

## The snapshot rule

Every page of a listing is read under one snapshot, `as_of` (`received_at <= as_of`, see
`qualify_api.mentions.repository.MentionPage`). Paging keeps it, so walking pages never
shows a duplicate or skips a row. A refresh tick COUNTS what arrived after `as_of`; on the
first page it takes those mentions in directly — a new snapshot, silently: a mention is not
a message, so its arrival is never announced as one (no notice, no "Nueva" mark; QUA-152,
founder's call 2026-10-15). On a later page the snapshot is kept, so paging never shifts
under the person; the next tick on page 1 takes them in. The order stays chronological by
publication date, so a new mention about an old post can land on a later page.
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


TickAction = Literal["take_new", "update_rows", "announce_change"]


def decide_tick(*, snapshot_total: int, reread_total: int, new_count: int, page: int) -> TickAction:
    """What a refresh tick does with the page it just re-read under the SAME snapshot.

    Mentions arrived after the snapshot and the person is on page 1: take them in — the
    first page is re-read under a new snapshot, with no notice (a mention is not a
    message). Otherwise, same total = the same set of rows: replace them in place, which
    only refreshes their data (a sentiment that just got analyzed). A different total means
    the set itself changed (a row deleted, a mention committed late into the snapshot, or a
    sentiment filter whose matches moved): never swap the rows silently — announce it and
    let the user refresh."""
    if new_count > 0 and page == 1:
        return "take_new"
    if reread_total != snapshot_total:
        return "announce_change"
    return "update_rows"


# --- "Actualizar menciones" outcome (QUA-152) ------------------------------------------

REFRESHING_NOTICE: Final = "Actualizando las menciones del periodo…"
REFRESH_FAILED_NOTICE: Final = "No se pudieron actualizar las menciones. Inténtalo de nuevo."
USAGE_PAUSED_NOTICE: Final = (
    "Se pausó la actualización para no agotar el límite de consultas de la red social. "
    "Los datos guardados se conservan. Vuelve a pulsar Actualizar en unos minutos."
)
# A run that started but has not reported for this long is considered dead: opening
# the screen unlocks the button. Longer than any bounded run. (Today Reflex keeps state in
# memory — no REFLEX_REDIS_URL in production — so a restart already clears the flag; this
# bound is what keeps the button usable if shared state is ever enabled.)
REFRESH_MAX_RUN_SECONDS: Final = 30 * 60


def refresh_still_running(
    *, is_refreshing: bool, alive_run: int, current_run: int, started_at: float, now: float
) -> bool:
    """Whether a refresh run is genuinely in flight when the screen is (re)opened: its
    background step started for the CURRENT run and it is not older than the longest
    possible run. Otherwise the button must be unlocked — the background step never
    started (the tab closed after the click) or died (the process restarted)."""
    return (
        is_refreshing
        and alive_run == current_run
        and 0 <= now - started_at < REFRESH_MAX_RUN_SECONDS
    )


THROTTLED_NOTICE: Final = (
    "La red social limitó las consultas, así que no se actualizaron todas las menciones. "
    "Los datos guardados se conservan. Vuelve a pulsar Actualizar en unos minutos."
)


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
    usage_paused: bool = False,
    planning_failed: bool = False,
    credential_failed: int = 0,
    removed: int = 0,
    restored: int = 0,
) -> RefreshOutcome:
    """Never says "done" while anything of the scope is still pending: a mention the
    network refused, or one left for a later run (per-run cap, throttling, usage pause),
    keeps the notice in warning tone with what to do next.

    `in_scope` excludes the `removed` mentions: the network no longer gives their content,
    so they left the list. That is not pending work — only announced, never a warning;
    neither is a removed mention that answered again (`restored`)."""
    if planning_failed:
        return stopped_outcome(REFRESH_FAILED_NOTICE, removed=removed, restored=restored)
    note = changes_note(removed=removed, restored=restored)
    if failed == 0 and not_attempted == 0 and credential_failed == 0:
        if in_scope == 0:
            if note:
                return RefreshOutcome(note, "ok")
            return RefreshOutcome("No hay menciones en este periodo para actualizar.", "info")
        noun = "la mención" if in_scope == 1 else f"las {in_scope} menciones"
        message = f"Se actualizaron {noun} del periodo."
        return RefreshOutcome(f"{message} {note}" if note else message, "ok")
    current = refreshed + already_fresh
    parts = [f"Se actualizaron {current} de {in_scope} menciones."]
    if note:
        parts.append(note)
    if failed:
        parts.append(
            "1 no se pudo leer en la red social (puede que ya no exista o que no haya "
            "respondido) y conserva sus datos."
            if failed == 1
            else f"{failed} no se pudieron leer en la red social (puede que ya no existan o "
            "que no hayan respondido) y conservan sus datos."
        )
    if credential_failed:
        verb = "no se pudo" if credential_failed == 1 else "no se pudieron"
        parts.append(
            f"{credential_failed} {verb} leer porque no se pudo acceder a la cuenta "
            "conectada; si se repite, revísala en Conexiones."
        )
    if not_attempted:
        if rate_limited:
            reason = "la red social limitó las consultas"
        elif usage_paused:
            reason = "se pausó para no agotar el límite de consultas de la red social"
        else:
            reason = "se alcanzó el límite de esta actualización"
        parts.append(
            f"1 quedó pendiente porque {reason}."
            if not_attempted == 1
            else f"{not_attempted} quedaron pendientes porque {reason}."
        )
    parts.append("Vuelve a pulsar Actualizar para continuar.")
    return RefreshOutcome(" ".join(parts), "warn")


def stopped_outcome(notice: str, *, removed: int = 0, restored: int = 0) -> RefreshOutcome:
    """A run that stopped before its outcome (throttled, paused, failed): the warning,
    after what the run did change in the list — rows never vanish unexplained."""
    note = changes_note(removed=removed, restored=restored)
    return RefreshOutcome(f"{note} {notice}" if note else notice, "warn")


def changes_note(*, removed: int = 0, restored: int = 0) -> str:
    """What left or came back to the list in this run; '' for nothing."""
    parts = []
    if removed == 1:
        parts.append("1 mención ya no está disponible en la red social y se quitó de la lista.")
    elif removed > 1:
        parts.append(
            f"{removed} menciones ya no están disponibles en la red social y se quitaron "
            "de la lista."
        )
    if restored == 1:
        parts.append("1 mención volvió a estar disponible y se muestra de nuevo.")
    elif restored > 1:
        parts.append(f"{restored} menciones volvieron a estar disponibles y se muestran de nuevo.")
    return " ".join(parts)
