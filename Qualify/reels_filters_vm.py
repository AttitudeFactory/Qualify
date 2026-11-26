"""The filter bar of «Ideas para tus reels» — RF-02 of the reels-filter epic (m-25119460,
under m-24872324; decisions in `docs/epica-filtrado-reels.md`). Pure — no database, no
network — so every label, every option and every empty message is tested offline
(`Qualify/test_reels_filters_vm.py`).

What the owner narrows, as TikTok Creative Center's Top Ads bar does: «Canal» (Instagram /
TikTok), «Tipo de cuenta» (inspiradores = `referente`, competidores = `competencia`),
«Cuenta» (one or several, from the accounts the brand labelled — `ReviewedReels.accounts`)
and «Duración» (four buckets), plus «Restablecer filtros». Default: nothing narrowed.

Filtering only reads what is stored (`reviewed_reels.reviewed_reels`, RF-01): it never
calls ScrapeCreators nor the model. Region and niche wait for RF-02b; «me gusta», dates,
search by product, «ordenar por» and detractors are out (decision 2 and 3 of the epic).

`FilterChoice` is what the screen's state holds (plain strings, so it can live in Reflex
state); `to_filters` turns it into RF-01's validated `ReelFilters`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from qualify_api.referentes.reviewed_reels import (
    DURATION_15_30,
    DURATION_30_60,
    DURATION_OVER_60,
    DURATION_UNDER_15,
    KIND_COMPETENCIA,
    KIND_REFERENTE,
    NETWORKS,
    ReelFilters,
)

# --------------------------------------------------------------------------------------
# the copy (exact, ticket m-25119460)
# --------------------------------------------------------------------------------------

AXIS_NETWORK = "network"
AXIS_KIND = "kind"
AXIS_ACCOUNT = "account"
AXIS_DURATION = "duration"
AXES = (AXIS_NETWORK, AXIS_KIND, AXIS_ACCOUNT, AXIS_DURATION)

NETWORK_LABEL = "Canal"
KIND_LABEL = "Tipo de cuenta"
ACCOUNT_LABEL = "Cuenta"
DURATION_LABEL = "Duración"
AXIS_LABELS = {
    AXIS_NETWORK: NETWORK_LABEL,
    AXIS_KIND: KIND_LABEL,
    AXIS_ACCOUNT: ACCOUNT_LABEL,
    AXIS_DURATION: DURATION_LABEL,
}
#: RF-13, option A (Deivid 2026-11-26): on a phone a chip with no filter shows only this
#: short name («Tipo», not «Tipo de cuenta»), and a chip with a filter only its value —
#: so 2 or 3 chips fit on a line. The full «Tipo de cuenta: Todos» stays in its
#: accessible name and its `title`.
CHIP_LABELS = {
    AXIS_NETWORK: NETWORK_LABEL,
    AXIS_KIND: "Tipo",
    AXIS_ACCOUNT: ACCOUNT_LABEL,
    AXIS_DURATION: DURATION_LABEL,
}
RESET_LABEL = "Restablecer filtros"

#: What an axis says when nothing is narrowed on it. «Todos» / «Todas» agree with the
#: axis' noun («Canal», «Tipo de cuenta» / «Cuenta», «Duración»).
ALL_MASCULINE = "Todos"
ALL_FEMININE = "Todas"
ALL_LABELS = {
    AXIS_NETWORK: ALL_MASCULINE,
    AXIS_KIND: ALL_MASCULINE,
    AXIS_ACCOUNT: ALL_FEMININE,
    AXIS_DURATION: ALL_FEMININE,
}

NETWORK_OPTIONS: tuple[tuple[str, str], ...] = (("instagram", "Instagram"), ("tiktok", "TikTok"))
KIND_OPTIONS: tuple[tuple[str, str], ...] = (
    (KIND_REFERENTE, "Inspiradores"),
    (KIND_COMPETENCIA, "Competidores"),
)
DURATION_OPTIONS: tuple[tuple[str, str], ...] = (
    (DURATION_UNDER_15, "Menos de 15 segundos"),
    (DURATION_15_30, "De 15 a 30 segundos"),
    (DURATION_30_60, "De 30 a 60 segundos"),
    (DURATION_OVER_60, "Más de 60 segundos"),
)
_NETWORK_NAMES = dict(NETWORK_OPTIONS)
_KIND_NAMES = dict(KIND_OPTIONS)
_DURATION_NAMES = dict(DURATION_OPTIONS)

#: The bar's accessible name, and the phone sheet's head (drafted here, for the UX check).
BAR_LABEL = "Filtrar reels"
#: Closes the phone sheet of «Cuenta», where several can be chosen.
DONE_LABEL = "Listo"
#: «Cuenta» with no labelled account to offer.
NO_ACCOUNTS_OPTION = "Aún no elegiste cuentas. Hazlo en «Negocios parecidos al tuyo»."
#: «Cuenta» when several are chosen: «3 cuentas».
SOME_ACCOUNTS = "{n} cuentas"
#: Each account's kind in «Cuenta», in the singular words of «Negocios parecidos al tuyo»
#: (`creative_wizard_pages.BUCKETS`; UX review 6).
ACCOUNT_KIND_WORDS = {KIND_REFERENTE: "Te inspira", KIND_COMPETENCIA: "Compite contigo"}

#: Nothing left with the chosen filters (exact, ticket m-25119460).
EMPTY_FILTERED = "No hay reels con estos filtros. Prueba quitando alguno."
#: Only competitors chosen, and none of their reels read yet (UX review 3: no promise
#: without a date): nothing is read yet, and the way on is the inspiring accounts.
COMPETITORS_EMPTY_TITLE = "Aún no revisamos los reels de tus competidores"
COMPETITORS_EMPTY_BODY = "Mientras tanto, mira las ideas de las cuentas que te inspiran."
COMPETITORS_EMPTY_ACTION = "Ver cuentas que te inspiran"
#: Only competitors chosen, and the brand marked none (UX review 4: the board's words).
NO_COMPETITORS_TITLE = "Aún no elegiste a tus competidores"
NO_COMPETITORS_BODY = (
    "Ponlos en «Compite contigo», dentro de «Negocios parecidos al tuyo». Cuando "
    "revisemos sus reels, los verás aquí."
)
NO_COMPETITORS_ACTION = "Elegir competidores"
#: The run's ideas left out with no filter on (an idea's account now marked «No va
#: contigo»; UX review 2: never a dead end — with «Elegir cuentas» when nothing is left).
NO_IDEAS_LEFT = (
    "Ya no quedan ideas de las cuentas que elegiste. Suma otras cuentas que te inspiren "
    "para tener más ideas."
)
NO_IDEAS_LEFT_ACTION = "Elegir cuentas"
#: RF-13 (m-25120327, Deivid 2026-11-25): one list under the bar — the ideas first, then
#: the other reels the check kept, with no heading over either — `LIST_PAGE` at a time;
#: «Ver más» brings the next `LIST_PAGE`. Only the ideas keep «Hacer uno parecido».
LIST_PAGE = 16
MORE_BUTTON = "Ver más"
#: Where an idea has «Hacer uno parecido», a reviewed reel says why it has not (ux-designer
#: on RF-13, approved by Deivid 2026-11-26).
MORE_ONLY_LOOK = "Este es solo para inspirarte: no se puede hacer uno parecido."
#: Filters on and no idea left that can be made again (same review): over the list; the
#: way back is «Restablecer filtros», already in the bar.
NO_IDEAS_FILTERED = (
    "Con estos filtros no queda ninguna idea para hacer uno parecido. Quita alguno para verlas."
)
MORE_BUSY = "Cargando…"
#: A reel of the second list could not be read (Postgres down while paging).
MORE_ERROR = "No pudimos traer más reels. Inténtalo de nuevo."
#: A card of the second list whose picture is no longer available (its CDN link lives
#: ~4 days and only the ideas keep a copy): the placeholder says it, never a broken image.
COVER_GONE = "La imagen ya no está disponible"

#: Which empty message is on screen (`FilterResult.empty`).
EMPTY_NONE = ""
EMPTY_FILTERS = "filters"
EMPTY_COMPETITORS = "competitors"
EMPTY_NO_COMPETITORS = "no_competitors"
EMPTY_NO_IDEAS = "no_ideas"


# --------------------------------------------------------------------------------------
# what the owner chose
# --------------------------------------------------------------------------------------


def account_key(network: str, handle: str) -> str:
    """The option value of one account: «instagram:foodie»."""
    return f"{network}:{handle}"


def parse_account_key(key: str) -> tuple[str, str] | None:
    """`(network, handle)` of an option value; None when it is not one."""
    network, sep, handle = key.partition(":")
    if not sep or network not in NETWORKS or not handle:
        return None
    return network, handle


@dataclass(frozen=True)
class FilterChoice:
    """The bar's values as the state holds them: "" = «Todos» on that axis; `accounts`
    are `account_key` values, in the order they were chosen."""

    network: str = ""
    kind: str = ""
    duration: str = ""
    accounts: tuple[str, ...] = ()

    @classmethod
    def of(
        cls,
        *,
        network: str = "",
        kind: str = "",
        duration: str = "",
        accounts: Sequence[str] = (),
    ) -> FilterChoice:
        """Keep only values the bar offers: an unknown one means «Todos» (a stale browser
        can never send a filter RF-01 would refuse)."""
        return cls(
            network=network if network in _NETWORK_NAMES else "",
            kind=kind if kind in _KIND_NAMES else "",
            duration=duration if duration in _DURATION_NAMES else "",
            accounts=tuple(dict.fromkeys(a for a in accounts if parse_account_key(a))),
        )

    @property
    def active(self) -> bool:
        return bool(self.network or self.kind or self.duration or self.accounts)

    def to_filters(self) -> ReelFilters:
        """RF-01's validated filters; empty axes narrow nothing."""
        pairs = [pair for pair in (parse_account_key(a) for a in self.accounts) if pair]
        return ReelFilters.of(
            networks=[self.network] if self.network else None,
            kinds=[self.kind] if self.kind else None,
            accounts=pairs,
            durations=[self.duration] if self.duration else None,
        )


NO_CHOICE = FilterChoice()


def set_axis(choice: FilterChoice, axis: str, value: str) -> FilterChoice:
    """`choice` with one single-choice axis set to `value` ("" = «Todos»)."""
    if axis == AXIS_NETWORK:
        return FilterChoice.of(
            network=value, kind=choice.kind, duration=choice.duration, accounts=choice.accounts
        )
    if axis == AXIS_KIND:
        return FilterChoice.of(
            network=choice.network, kind=value, duration=choice.duration, accounts=choice.accounts
        )
    if axis == AXIS_DURATION:
        return FilterChoice.of(
            network=choice.network, kind=choice.kind, duration=value, accounts=choice.accounts
        )
    return choice


def toggle_account(choice: FilterChoice, key: str) -> FilterChoice:
    """`choice` with the account `key` added, or removed when it was chosen."""
    accounts = (
        tuple(a for a in choice.accounts if a != key)
        if key in choice.accounts
        else (*choice.accounts, key)
    )
    return FilterChoice.of(
        network=choice.network, kind=choice.kind, duration=choice.duration, accounts=accounts
    )


def clear_accounts(choice: FilterChoice) -> FilterChoice:
    return FilterChoice.of(network=choice.network, kind=choice.kind, duration=choice.duration)


def accounts_by_key(accounts: Mapping[tuple[str, str], str]) -> dict[str, str]:
    """RF-01's `ReviewedReels.accounts` (`(network, handle) → kind`) keyed by
    `account_key`, the shape the state can hold."""
    return {account_key(network, handle): kind for (network, handle), kind in accounts.items()}


def known_accounts(choice: FilterChoice, accounts: Mapping[str, str]) -> FilterChoice:
    """`choice` without the accounts the brand no longer offers (unlabelled, or now a
    detractor): a filter on an account that is gone would leave a list empty for no
    reason the owner can see. `accounts` is `accounts_by_key`'s."""
    kept = tuple(a for a in choice.accounts if a in accounts)
    if kept == choice.accounts:
        return choice
    return FilterChoice.of(
        network=choice.network, kind=choice.kind, duration=choice.duration, accounts=kept
    )


# --------------------------------------------------------------------------------------
# what the bar shows
# --------------------------------------------------------------------------------------


def account_options(accounts: Mapping[str, str]) -> list[dict[str, str]]:
    """The «Cuenta» options (`accounts` is `accounts_by_key`'s): inspiradores first, then
    competidores, each by handle — `{"key", "label", "detail"}`, «@foodie» over
    «Instagram · Te inspira»."""
    order = {KIND_REFERENTE: 0, KIND_COMPETENCIA: 1}
    rows = []
    for key, kind in accounts.items():
        pair = parse_account_key(key)
        if pair is not None and kind in _KIND_NAMES:
            rows.append((order[kind], pair[1], pair[0], key, kind))
    return [
        {
            "key": key,
            "label": f"@{handle}",
            "detail": f"{_NETWORK_NAMES[network]} · {ACCOUNT_KIND_WORDS[kind]}",
        }
        for _, handle, network, key, kind in sorted(rows)
    ]


def single_options(axis: str) -> list[dict[str, str]]:
    """A single-choice axis' options, «Todos»/«Todas» first: `{"value", "label"}`."""
    options = {
        AXIS_NETWORK: NETWORK_OPTIONS,
        AXIS_KIND: KIND_OPTIONS,
        AXIS_DURATION: DURATION_OPTIONS,
    }.get(axis, ())
    return [{"value": "", "label": ALL_LABELS[axis]}] + [
        {"value": value, "label": label} for value, label in options
    ]


def value_label(axis: str, choice: FilterChoice, options: Sequence[dict[str, str]] = ()) -> str:
    """What an axis is set to, in words: «Todos», «Instagram», «@foodie», «3 cuentas»."""
    if axis == AXIS_NETWORK:
        return _NETWORK_NAMES.get(choice.network, ALL_LABELS[axis])
    if axis == AXIS_KIND:
        return _KIND_NAMES.get(choice.kind, ALL_LABELS[axis])
    if axis == AXIS_DURATION:
        return _DURATION_NAMES.get(choice.duration, ALL_LABELS[axis])
    if axis == AXIS_ACCOUNT:
        if not choice.accounts:
            return ALL_LABELS[axis]
        if len(choice.accounts) == 1:
            labels = {o["key"]: o["label"] for o in options}
            pair = parse_account_key(choice.accounts[0])
            return labels.get(choice.accounts[0], f"@{pair[1]}" if pair else "")
        return SOME_ACCOUNTS.format(n=len(choice.accounts))
    return ""


def chips(choice: FilterChoice, options: Sequence[dict[str, str]] = ()) -> list[dict[str, str]]:
    """One chip per axis, in the bar's order: `{"axis", "label", "value", "on"}` —
    «Canal» over «Todos»; `on` = "1" when the axis narrows something."""
    on = {
        AXIS_NETWORK: bool(choice.network),
        AXIS_KIND: bool(choice.kind),
        AXIS_ACCOUNT: bool(choice.accounts),
        AXIS_DURATION: bool(choice.duration),
    }
    return [
        {
            "axis": axis,
            "label": AXIS_LABELS[axis],
            "value": value_label(axis, choice, options),
            "on": "1" if on[axis] else "",
        }
        for axis in AXES
    ]


# --------------------------------------------------------------------------------------
# the lists under the bar
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FirstPage:
    """The reviewed reels that fill the first `LIST_PAGE` after the ideas, whether more
    exist, and the offset «Ver más» reads from next."""

    more: list[dict[str, str]]
    has_more: bool
    next_offset: int


def first_page(
    ideas: int,
    more: Sequence[dict[str, str]],
    *,
    has_more: bool,
    page: int = LIST_PAGE,
) -> FirstPage:
    """RF-13: the first page of the one list is `ideas` ideas and then as many reviewed
    reels (`more`, read from offset 0, at least `page` of them) as fit in `page`; what
    is left over waits for «Ver más», which reads `page` more from `next_offset`."""
    room = max(0, page - max(0, ideas))
    shown = list(more[:room])
    return FirstPage(shown, has_more or len(more) > room, len(shown))


def only_competitors(choice: FilterChoice, accounts: Mapping[str, str]) -> bool:
    """The filters reach competitor accounts only: «Competidores» chosen, or every chosen
    account is a `competencia` one (`accounts` is `accounts_by_key`'s)."""
    if choice.kind == KIND_COMPETENCIA:
        return True
    if not choice.accounts:
        return False
    return all(accounts.get(a) == KIND_COMPETENCIA for a in choice.accounts)


@dataclass(frozen=True)
class EmptyMessage:
    """What the screen says instead of a mute list: `kind` is one of `EMPTY_*`."""

    kind: str = EMPTY_NONE
    title: str = ""
    body: str = ""
    #: Its one button ("" for none): «Negocios parecidos al tuyo», or «Inspiradores».
    action: str = ""


def empty_message(
    choice: FilterChoice,
    accounts: Mapping[str, str],
    *,
    ideas: int,
    more: int,
) -> EmptyMessage:
    """The message when nothing is left to show (`ideas` and `more` are what the filtered
    read returned). Competitors first: until their reels are read (RF-05), a filter on them is
    empty by design and is told so — and, when the brand marked none, how to mark them."""
    if ideas or more:
        return EmptyMessage()
    if only_competitors(choice, accounts):
        if KIND_COMPETENCIA not in accounts.values():
            return EmptyMessage(
                EMPTY_NO_COMPETITORS,
                NO_COMPETITORS_TITLE,
                NO_COMPETITORS_BODY,
                NO_COMPETITORS_ACTION,
            )
        return EmptyMessage(
            EMPTY_COMPETITORS,
            COMPETITORS_EMPTY_TITLE,
            COMPETITORS_EMPTY_BODY,
            COMPETITORS_EMPTY_ACTION,
        )
    if choice.active:
        return EmptyMessage(EMPTY_FILTERS, "", EMPTY_FILTERED)
    return EmptyMessage(EMPTY_NO_IDEAS, "", NO_IDEAS_LEFT, NO_IDEAS_LEFT_ACTION)


__all__ = [
    "ACCOUNT_KIND_WORDS",
    "ACCOUNT_LABEL",
    "ALL_FEMININE",
    "ALL_LABELS",
    "ALL_MASCULINE",
    "AXES",
    "AXIS_ACCOUNT",
    "AXIS_DURATION",
    "AXIS_KIND",
    "AXIS_LABELS",
    "CHIP_LABELS",
    "AXIS_NETWORK",
    "BAR_LABEL",
    "COMPETITORS_EMPTY_ACTION",
    "COMPETITORS_EMPTY_BODY",
    "COMPETITORS_EMPTY_TITLE",
    "COVER_GONE",
    "DONE_LABEL",
    "DURATION_LABEL",
    "DURATION_OPTIONS",
    "EMPTY_COMPETITORS",
    "EMPTY_FILTERED",
    "EMPTY_FILTERS",
    "EMPTY_NONE",
    "EMPTY_NO_COMPETITORS",
    "EMPTY_NO_IDEAS",
    "KIND_LABEL",
    "KIND_OPTIONS",
    "LIST_PAGE",
    "MORE_BUSY",
    "MORE_BUTTON",
    "MORE_ERROR",
    "MORE_ONLY_LOOK",
    "NETWORK_LABEL",
    "NETWORK_OPTIONS",
    "NO_ACCOUNTS_OPTION",
    "NO_CHOICE",
    "NO_COMPETITORS_ACTION",
    "NO_COMPETITORS_BODY",
    "NO_COMPETITORS_TITLE",
    "NO_IDEAS_FILTERED",
    "NO_IDEAS_LEFT",
    "NO_IDEAS_LEFT_ACTION",
    "RESET_LABEL",
    "SOME_ACCOUNTS",
    "EmptyMessage",
    "FirstPage",
    "FilterChoice",
    "account_key",
    "account_options",
    "accounts_by_key",
    "chips",
    "clear_accounts",
    "empty_message",
    "first_page",
    "known_accounts",
    "only_competitors",
    "parse_account_key",
    "set_axis",
    "single_options",
    "toggle_account",
    "value_label",
]
