"""The owner's competitors in «Ideas para tus reels» — the screen of RF-05 (m-25119465,
under m-24872324; decision 5 of `docs/epica-filtrado-reels.md`). Pure — no database, no
network — so every row, every state and every sentence is tested offline
(`Qualify/test_reels_competitors_vm.py`).

From RF-02's filter bar, «Tus competidores» opens a drawer (option A, Deivid
2026-11-25; it replaced the ticket's panel «Elige cuáles 6 competidores leemos cada
lunes», which pushed the ideas down) — one row per
account the brand marked «Compite contigo» (`competencia`), ticked when the Monday run
reads it. With nothing chosen, the first 6 of the list are the ticked ones
(`reels.competitor_accounts`). A competitor outside the 6 has «Ver sus reels ahora»: a
read at once, queued by `competitors.read_now` and paid by the reels-worker, inside the
business's daily cap. Its state after the press — reading, done, a limit, a failure —
shows under the row, in the words of `qualify_api.referentes.competitors`.

Opening the panel and ticking a row never pay: they read and write the brand's own labels.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from qualify_api.referentes import competitors as rivals
from qualify_api.referentes.reels import NETWORK_LABELS, CompetitorAccount

from .reels_filters_vm import account_key, parse_account_key

#: The panel's title and the button (exact, ticket m-25119465).
#: Option A, chosen by Deivid on 2026-11-25 after seeing the panel live (it pushed the
#: ideas down): the panel moves into a drawer opened from the filter bar, and its title
#: replaces the ticket's «Elige cuáles 6 competidores leemos cada lunes».
PICKER_TITLE = "Tus competidores"
READ_NOW = rivals.READ_NOW_BUTTON
#: The bar's button on a phone (option A, Deivid 2026-11-26: short only if needed so
#: nothing is alone on a line); its accessible name still starts «Tus competidores».
PICKER_SHORT = "Competidores"
#: What the panel says under its title (Deivid, option A).
PICKER_BODY = (
    "Marca hasta 6: cada lunes te traemos sus reels nuevos. Para ver ya los de otro, "
    "pulsa «Ver sus reels ahora»."
)
#: m-25142823 (Deivid, 2026-11-27): the panel lives in «Negocios parecidos al tuyo», one
#: line under the board — what it does, and the button that opens it.
SECTION_BODY = "Marca hasta 6 para que cada lunes te traigamos sus reels nuevos."
OPENER_LABEL = "Elegir competidores"
#: The line with no competitor yet (Deivid, 2026-11-27: always in view).
SECTION_EMPTY = "Aún no tienes competidores. Márcalos abajo con «Compite contigo» o elígelos aquí."
#: Inside the panel: a competitor taken back to the board's «sin clasificar», and the
#: board's other accounts, each with «Compite contigo» (the board's own words).
REMOVE_LABEL = "Quitar"
#: «Quitar» is only its × in the row (Deivid, 2026-11-27): its name says it in full.
REMOVE_NAME = "Quitar a {account} de tus competidores"
ADD_TITLE = "Agregar competidores"
ADD_BUTTON = "Compite contigo"
NO_CANDIDATES = (
    "No hay más cuentas para elegir. Busca negocios parecidos al tuyo en esta misma sección."
)
#: Each candidate's place on the board, in its words.
BUCKET_WORDS = {"": "Sin clasificar", "referente": "Te inspira", "detractor": "No va contigo"}
#: How many are ticked: «3 de 6 marcados».
PICKED_COUNT = "{n} de " + str(rivals.MAX_WEEKLY) + " marcados"
#: The opener's `title` (m-25142823): how many are read on Monday, or that a read is on.
BUTTON_LABEL = "Tus competidores: {n} de " + str(rivals.MAX_WEEKLY) + " los revisamos cada lunes"
BUTTON_LABEL_READING = "Tus competidores: estamos leyendo sus reels"
#: A manual read ended while the drawer was closed (a toast; open, the row says it).
#: RF-13 (m-25120327): the list has no «Más reels revisados» heading any more.
TOAST_DONE = "Listo: los reels de {account} ya están en tus ideas."
TOAST_FAILED = "No pudimos leer los reels de {account}. Inténtalo de nuevo en unos minutos."
#: More than 6 ticked (exact, `competitors.TOO_MANY_TEXT`).
TOO_MANY = rivals.TOO_MANY_TEXT
#: Unticking the last one (an empty choice would mean «the first 6» again).
KEEP_ONE = "Deja marcado al menos un competidor."
#: The choice could not be saved (Postgres down).
SAVE_FAILED = "No pudimos guardar tu elección. Inténtalo de nuevo."
#: «Ver sus reels ahora» could not be asked for (Postgres down): the read's own failure.
READ_FAILED = rivals.FAILED_TEXT
#: The row of an account the Monday run reads.
WEEKLY_DETAIL = "Lo revisamos cada lunes"

#: A row's state after «Ver sus reels ahora», and the tone its line is painted in.
STATE_TONES = {
    rivals.STATE_READING: "info",
    rivals.STATE_DONE: "ok",
    rivals.STATE_LIMIT: "warn",
    rivals.STATE_FAILED: "error",
}


@dataclass(frozen=True)
class ReadState:
    """A row's state after «Ver sus reels ahora» (`competitors.ReadNow`, in plain strings)."""

    state: str
    message: str


def read_state(answer: rivals.ReadNow) -> ReadState:
    return ReadState(answer.state, answer.message)


def rows(
    accounts: Sequence[CompetitorAccount], states: Mapping[str, ReadState] | None = None
) -> list[dict[str, str]]:
    """One row per competitor, in the owner's order: `{"key", "label", "detail",
    "weekly", "state", "message", "tone"}` — «@rival» over «Instagram · Lo revisamos cada
    lunes»; `weekly` = "1" when the Monday run reads it (no «Ver sus reels ahora» then);
    `state`/`message`/`tone` = today's manual read, "" when none."""
    found = states or {}
    out = []
    for account in accounts:
        key = account_key(account.network, account.handle)
        network = NETWORK_LABELS.get(account.network, account.network)
        read = found.get(key)
        out.append(
            {
                "key": key,
                "label": f"@{account.handle}",
                "detail": f"{network} · {WEEKLY_DETAIL}" if account.weekly else network,
                "weekly": "1" if account.weekly else "",
                "state": read.state if read else "",
                "message": read.message if read else "",
                "tone": STATE_TONES.get(read.state, "") if read else "",
            }
        )
    return out


def with_answer(
    table: Sequence[Mapping[str, str]], key: str, answer: ReadState | None
) -> list[dict[str, str]]:
    """`table` with the press's `answer` on `key`'s row: it is the newest word on that
    account — a press the cap refused queues no read, so only its answer can tell the
    owner why nothing happens, even over an earlier read of the day that failed."""
    out = [dict(row) for row in table]
    if answer is None:
        return out
    for row in out:
        if row["key"] == key:
            row.update(
                state=answer.state,
                message=answer.message,
                tone=STATE_TONES.get(answer.state, ""),
            )
    return out


def ended(before: Mapping[str, str], table: Iterable[Mapping[str, str]]) -> list[tuple[str, str]]:
    """The manual reads that were reading (`before`: key → state) and are not any more,
    as `(tone, sentence)` toasts: «ok» with `TOAST_DONE`, «error» with `TOAST_FAILED`."""
    out = []
    for row in table:
        if before.get(row["key"]) != rivals.STATE_READING:
            continue
        state = row.get("state", "")
        if state == rivals.STATE_READING:
            continue
        if state == rivals.STATE_DONE:
            out.append(("ok", TOAST_DONE.format(account=row["label"])))
        elif state == rivals.STATE_LIMIT and row.get("message"):
            # stopped by the cap: «try again in a few minutes» would be wrong today
            out.append(("warn", row["message"]))
        else:
            out.append(("error", TOAST_FAILED.format(account=row["label"])))
    return out


def button_label(table: Iterable[Mapping[str, str]]) -> str:
    """The opener's `title` (`BUTTON_LABEL` / `BUTTON_LABEL_READING`)."""
    rows_ = list(table)
    if reading(rows_):
        return BUTTON_LABEL_READING
    return BUTTON_LABEL.format(n=sum(1 for row in rows_ if row.get("weekly")))


def picked_count(table: Iterable[Mapping[str, str]]) -> str:
    """«3 de 6»: how many rows the Monday run reads."""
    return PICKED_COUNT.format(n=sum(1 for row in table if row.get("weekly")))


def reading(table: Iterable[Mapping[str, str]]) -> bool:
    """Some manual read is still queued or running (the screen asks again later)."""
    return any(row.get("state") == rivals.STATE_READING for row in table)


@dataclass(frozen=True)
class Toggle:
    """What ticking a row asks for: the new choice to save, or why it is refused."""

    picks: tuple[tuple[str, str], ...] = ()
    error: str = ""


def toggle(table: Sequence[Mapping[str, str]], key: str) -> Toggle | None:
    """Tick or untick `key`, starting from the rows the Monday run reads now (with nothing
    chosen, the first 6): the new choice, `TOO_MANY` past 6, or None for a key that is
    not a row (a stale browser)."""
    keys = [row["key"] for row in table]
    if key not in keys:
        return None
    weekly = [row["key"] for row in table if row.get("weekly")]
    if key in weekly:
        chosen = [k for k in weekly if k != key]
        if not chosen:  # an empty choice means «the first 6»: it would tick them back
            return Toggle(error=KEEP_ONE)
    elif len(weekly) >= rivals.MAX_WEEKLY:
        return Toggle(error=TOO_MANY)
    else:
        chosen = [k for k in keys if k in weekly or k == key]  # the list's order
    picks = tuple(pair for pair in (parse_account_key(k) for k in chosen) if pair)
    return Toggle(picks=picks)


__all__ = [
    "BUTTON_LABEL",
    "BUTTON_LABEL_READING",
    "KEEP_ONE",
    "ADD_BUTTON",
    "ADD_TITLE",
    "BUCKET_WORDS",
    "NO_CANDIDATES",
    "OPENER_LABEL",
    "REMOVE_LABEL",
    "REMOVE_NAME",
    "PICKED_COUNT",
    "PICKER_BODY",
    "PICKER_SHORT",
    "PICKER_TITLE",
    "READ_FAILED",
    "READ_NOW",
    "SAVE_FAILED",
    "SECTION_BODY",
    "SECTION_EMPTY",
    "STATE_TONES",
    "TOAST_DONE",
    "TOAST_FAILED",
    "TOO_MANY",
    "WEEKLY_DETAIL",
    "ReadState",
    "Toggle",
    "button_label",
    "ended",
    "picked_count",
    "read_state",
    "reading",
    "rows",
    "toggle",
    "with_answer",
]
