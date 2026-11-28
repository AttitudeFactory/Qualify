"""RF-02 (m-25119460) and RF-02b (m-25119463): the filter bar of «Ideas para tus reels»,
offline — the exact words, what each axis offers, the two sides (inspiring / competitors,
never mixed), what the owner's choice becomes for RF-01's read, and the message that
replaces an empty list."""

from __future__ import annotations

import re

import pytest
from qualify_api.referentes.reviewed_reels import ReelFilters

from . import reels_filters_vm as vm

ACCOUNTS = {
    "instagram:foodie": "referente",
    "tiktok:rival": "competencia",
    "instagram:abc": "referente",
}
#: What the bar sends with nothing narrowed: the inspiring side only (never both).
INSPIRING = ReelFilters.of(kinds=["referente"])
#: «País»'s options of a business in Cúcuta, Colombia.
PLACES = vm.region_options("Colombia", "Cúcuta")


def test_the_bar_says_exactly_what_the_ticket_says() -> None:
    # Deivid, 2026-11-27: no «Tipo de cuenta» chip — the side button switches instead
    assert [vm.AXIS_LABELS[a] for a in vm.AXES] == ["Canal", "Cuenta", "Duración", "País"]
    assert vm.AXIS_KIND not in vm.AXES
    assert [label for _, label in vm.NETWORK_OPTIONS] == ["Instagram", "TikTok"]
    assert [label for _, label in vm.DURATION_OPTIONS] == [
        "Menos de 15 segundos",
        "De 15 a 30 segundos",
        "De 30 a 60 segundos",
        "Más de 60 segundos",
    ]
    assert vm.RESET_LABEL == "Restablecer filtros"
    assert vm.EMPTY_FILTERED == "No hay reels con estos filtros. Prueba quitando alguno."
    # RF-13 (Deivid, 2026-11-25): one list with no heading, 16 at a time, «Ver más»
    assert vm.MORE_BUTTON == "Ver más" and vm.LIST_PAGE == 16
    for gone in ("MORE_TITLE", "MORE_BODY", "IDEAS_NONE_FILTERED", "niche_line"):
        assert not hasattr(vm, gone), gone


def _cards(n: int) -> list[dict[str, str]]:
    return [{"key": f"instagram:M{i}"} for i in range(n)]


def test_the_first_page_is_the_ideas_then_the_reviewed_reels_up_to_16() -> None:
    """RF-13: 6 ideas leave room for 10 reviewed reels; «Ver más» reads from the 11th."""
    page = vm.first_page(6, _cards(16), has_more=True)
    assert [c["key"] for c in page.more] == [f"instagram:M{i}" for i in range(10)]
    assert page.has_more and page.next_offset == 10
    short = vm.first_page(6, _cards(4), has_more=False)
    assert (len(short.more), short.has_more, short.next_offset) == (4, False, 4)
    exact = vm.first_page(6, _cards(10), has_more=False)
    assert (len(exact.more), exact.has_more) == (10, False)
    none = vm.first_page(0, _cards(16), has_more=True)
    assert (len(none.more), none.has_more, none.next_offset) == (16, True, 16)
    full = vm.first_page(16, _cards(3), has_more=False)
    assert (full.more, full.has_more, full.next_offset) == ([], True, 0)
    assert vm.first_page(16, [], has_more=False).has_more is False


# --------------------------------------------------------------------------------------
# the two sides (Deivid, 2026-11-27)
# --------------------------------------------------------------------------------------


def test_the_screen_opens_on_the_inspiring_side_and_never_mixes() -> None:
    """Default: the inspiring accounts; an unknown side is that one; no «Todos»."""
    assert vm.NO_CHOICE.kind == "referente"
    assert vm.FilterChoice.of(kind="").kind == "referente"
    assert vm.FilterChoice.of(kind="detractor").kind == "referente"
    assert vm.NO_CHOICE.to_filters() == INSPIRING
    rivals = vm.FilterChoice.of(kind="competencia")
    assert rivals.to_filters() == ReelFilters.of(kinds=["competencia"])
    # decision 1 of the epic: «Competidores» = accounts marked `competencia`; no detractors
    assert dict(vm.KIND_OPTIONS) == {"referente": "Inspiradores", "competencia": "Competidores"}


def test_the_side_is_not_a_filter() -> None:
    """Not counted in «Filtros · N», not offered to «Restablecer filtros», kept by it."""
    rivals = vm.FilterChoice.of(kind="competencia")
    assert not rivals.active
    assert vm.filters_button(rivals) == ("Filtros", "Filtros: ninguno activo")
    on = vm.FilterChoice.of(kind="competencia", network="tiktok", region=vm.REGION_LOCAL)
    assert vm.cleared(on) == rivals  # every filter off, same side


def test_the_side_button_says_where_it_goes() -> None:
    """«Competidores» on the inspiring side, «Inspiraciones» on the competitors' side; the
    accessible name says the action and contains the face; `other` keeps the width."""
    there = vm.side_button(vm.NO_CHOICE)
    assert there == {
        "face": "Competidores",
        "name": "Ver reels de tus competidores",
        "other": "Inspiraciones",
    }
    back = vm.side_button(vm.FilterChoice.of(kind="competencia"))
    assert back == {
        "face": "Inspiraciones",
        "name": "Volver a los reels de tus inspiraciones",
        "other": "Competidores",
    }
    for texts in (there, back):
        assert texts["face"].lower() in texts["name"].lower()


def test_switching_side_keeps_the_filters_and_drops_the_other_sides_accounts() -> None:
    mine = vm.FilterChoice.of(network="instagram", accounts=["instagram:foodie"])
    rivals = vm.switch_side(mine, ACCOUNTS)
    assert (rivals.kind, rivals.network, rivals.accounts) == ("competencia", "instagram", ())
    rival = vm.toggle_account(rivals, "tiktok:rival")
    back = vm.switch_side(rival, ACCOUNTS)
    assert (back.kind, back.accounts) == ("referente", ())


def test_cuenta_offers_only_the_side_on_screen() -> None:
    every = vm.account_options({**ACCOUNTS, "instagram:hater": "detractor"})
    assert every == [
        {
            "key": "instagram:abc",
            "label": "@abc",
            "detail": "Instagram · Te inspira",
            "kind": "referente",
        },
        {
            "key": "instagram:foodie",
            "label": "@foodie",
            "detail": "Instagram · Te inspira",
            "kind": "referente",
        },
        {
            "key": "tiktok:rival",
            "label": "@rival",
            "detail": "TikTok · Compite contigo",
            "kind": "competencia",
        },
    ]
    assert [o["key"] for o in vm.side_options(every, "referente")] == [
        "instagram:abc",
        "instagram:foodie",
    ]
    assert [o["key"] for o in vm.side_options(every, "competencia")] == ["tiktok:rival"]
    assert vm.accounts_by_key({("instagram", "foodie"): "referente"}) == {
        "instagram:foodie": "referente"
    }
    # an account of the other side (or gone) leaves the choice
    choice = vm.FilterChoice.of(accounts=["instagram:foodie", "tiktok:rival", "instagram:gone"])
    assert vm.known_accounts(choice, ACCOUNTS).accounts == ("instagram:foodie",)
    assert vm.known_accounts(vm.NO_CHOICE, ACCOUNTS) is vm.NO_CHOICE


def test_the_competitors_side_says_why_it_is_empty() -> None:
    """Their reels not read yet: said, with the way back to the inspiring side; none
    marked: how to mark them, in «Negocios parecidos al tuyo»."""
    rivals = vm.FilterChoice.of(kind="competencia")
    assert vm.only_competitors(rivals) and not vm.only_competitors(vm.NO_CHOICE)
    message = vm.empty_message(rivals, ACCOUNTS, ideas=0, more=0)
    assert message.kind == vm.EMPTY_COMPETITORS
    assert message.title == "Aún no revisamos los reels de tus competidores"
    assert message.action == "Ver cuentas que te inspiran"
    none_marked = {"instagram:foodie": "referente"}
    message = vm.empty_message(rivals, none_marked, ideas=0, more=0)
    assert message.kind == vm.EMPTY_NO_COMPETITORS and message.action == "Elegir competidores"
    assert "Tus competidores" in message.body and "dentro de tu marca" in message.body
    # a filter that leaves their (read) reels out says so — never «Aún no revisamos…»
    for narrowed in (
        vm.FilterChoice.of(kind="competencia", region=vm.REGION_LOCAL),
        vm.FilterChoice.of(kind="competencia", duration="gte60"),
    ):
        message = vm.empty_message(narrowed, ACCOUNTS, ideas=0, more=0)
        assert (message.kind, message.body) == (vm.EMPTY_FILTERS, vm.EMPTY_FILTERED)


# --------------------------------------------------------------------------------------
# the chips
# --------------------------------------------------------------------------------------


def test_a_chip_says_one_short_word_inside_its_full_name() -> None:
    """RF-13 (Deivid, 2026-11-26, measured at 375 px): no filter → the short name; a
    filter → its value, shorter for «Duración», the place itself for «País»; the
    accessible name keeps the long words and always contains the visible one (WCAG 2.5.3)."""
    none = vm.NO_CHOICE
    assert vm.phone_chip(vm.AXIS_NETWORK, none) == ("Canal", "Canal: Todos")
    insta = vm.FilterChoice.of(network="instagram")
    assert vm.phone_chip(vm.AXIS_NETWORK, insta) == ("Instagram", "Canal: Instagram")
    short = vm.FilterChoice.of(duration="lt15")
    assert vm.phone_chip(vm.AXIS_DURATION, short) == (
        "< 15 s",
        "Duración: < 15 s (menos de 15 segundos)",
    )
    assert [vm.CHIP_VALUES[vm.AXIS_DURATION][v] for v, _ in vm.DURATION_OPTIONS] == [
        "< 15 s",
        "15–30 s",
        "30–60 s",
        "> 60 s",
    ]
    assert vm.value_label(vm.AXIS_DURATION, short) == "Menos de 15 segundos"
    local = vm.FilterChoice.of(region=vm.REGION_LOCAL)
    for axis in vm.AXES:
        for choice in (none, insta, short, local):
            face, name = vm.phone_chip(axis, choice, places=PLACES)
            assert face.lower() in name.lower(), (axis, face, name)
            assert face not in ("Competidores", "Inspiraciones")  # the side button's words


def test_the_filters_button_counts_the_axes_on() -> None:
    """«Filtros» / «Filtros · N», named in words; several accounts are ONE axis."""
    assert vm.filters_button(vm.NO_CHOICE) == ("Filtros", "Filtros: ninguno activo")
    one = vm.FilterChoice.of(network="tiktok")
    assert vm.filters_button(one) == ("Filtros · 1", "Filtros: 1 activo")
    accounts = vm.FilterChoice.of(accounts=["instagram:a", "tiktok:b"])
    assert vm.active_count(accounts) == 1
    every = vm.FilterChoice.of(
        network="instagram",
        duration="lt15",
        accounts=["instagram:a"],
        region=vm.REGION_COUNTRY,
    )
    assert vm.active_count(every) == 4
    assert vm.filters_button(every) == ("Filtros · 4", "Filtros: 4 activos")


def test_every_single_choice_axis_starts_with_all() -> None:
    assert vm.single_options(vm.AXIS_NETWORK)[0] == {"value": "", "label": "Todos"}
    assert vm.single_options(vm.AXIS_DURATION)[0] == {"value": "", "label": "Todas"}
    assert [o["value"] for o in vm.single_options(vm.AXIS_DURATION)] == [
        "",
        "lt15",
        "15_30",
        "30_60",
        "gte60",
    ]


def test_by_default_nothing_is_narrowed() -> None:
    assert not vm.NO_CHOICE.active
    assert [c["value"] for c in vm.chips(vm.NO_CHOICE, places=PLACES)] == [
        "Todos",
        "Todas",
        "Todas",
        "Todos",
    ]
    assert all(c["on"] == "" for c in vm.chips(vm.NO_CHOICE))


def test_the_choice_becomes_rf01_filters() -> None:
    choice = vm.FilterChoice.of(
        network="tiktok",
        kind="competencia",
        duration="15_30",
        accounts=["tiktok:rival", "instagram:foodie"],
    )
    assert choice.active
    assert choice.to_filters() == ReelFilters.of(
        networks=["tiktok"],
        kinds=["competencia"],
        accounts=[("tiktok", "rival"), ("instagram", "foodie")],
        durations=["15_30"],
    )


def test_a_value_the_bar_does_not_offer_means_all() -> None:
    """A stale browser can never send a filter RF-01 would refuse."""
    choice = vm.FilterChoice.of(
        network="youtube",
        kind="detractor",
        duration="90",
        accounts=["otro:x", "bad", "tiktok:"],
        region="CO",  # the old country codes are not values any more
    )
    assert choice == vm.NO_CHOICE
    assert choice.to_filters() == INSPIRING


def test_axes_change_one_at_a_time_and_accounts_toggle() -> None:
    choice = vm.set_axis(vm.NO_CHOICE, vm.AXIS_NETWORK, "instagram")
    choice = vm.set_axis(choice, vm.AXIS_DURATION, "lt15")
    assert (choice.network, choice.kind, choice.duration) == ("instagram", "referente", "lt15")
    choice = vm.toggle_account(choice, "instagram:foodie")
    choice = vm.toggle_account(choice, "instagram:abc")
    assert choice.accounts == ("instagram:foodie", "instagram:abc")
    choice = vm.toggle_account(choice, "instagram:foodie")
    assert choice.accounts == ("instagram:abc",)
    assert vm.clear_accounts(choice).accounts == ()
    assert vm.set_axis(choice, vm.AXIS_NETWORK, "").network == ""
    assert vm.set_axis(choice, vm.AXIS_KIND, "competencia") == choice  # the side button's
    assert vm.set_axis(choice, "objective", "sell") == choice  # RF-11's, not here
    local = vm.set_axis(choice, vm.AXIS_REGION, vm.REGION_LOCAL)
    assert (local.region, local.network, local.accounts) == (
        "local",
        "instagram",
        ("instagram:abc",),
    )
    assert vm.toggle_account(local, "instagram:foodie").region == "local"
    assert vm.set_axis(local, vm.AXIS_REGION, "").region == ""


def test_the_chips_say_what_each_axis_is_set_to() -> None:
    options = vm.side_options(vm.account_options(ACCOUNTS), "referente")
    one = vm.FilterChoice.of(network="instagram", accounts=["instagram:abc"])
    assert {c["axis"]: c["value"] for c in vm.chips(one, options, PLACES)} == {
        "network": "Instagram",
        "account": "@abc",
        "duration": "Todas",
        "region": "Todos",
    }
    two = vm.toggle_account(one, "instagram:foodie")
    assert vm.value_label(vm.AXIS_ACCOUNT, two, options) == "2 cuentas"
    assert [c["on"] for c in vm.chips(two, options, PLACES)] == ["1", "1", "", ""]


def test_other_filters_that_leave_nothing_say_the_tickets_sentence() -> None:
    choice = vm.FilterChoice.of(duration="gte60")
    message = vm.empty_message(choice, ACCOUNTS, ideas=0, more=0)
    assert (message.kind, message.body) == (vm.EMPTY_FILTERS, vm.EMPTY_FILTERED)
    assert vm.empty_message(choice, ACCOUNTS, ideas=1, more=0).kind == vm.EMPTY_NONE
    assert vm.empty_message(choice, ACCOUNTS, ideas=0, more=3).kind == vm.EMPTY_NONE
    left = vm.empty_message(vm.NO_CHOICE, ACCOUNTS, ideas=0, more=0)
    assert (left.kind, left.action) == (vm.EMPTY_NO_IDEAS, "Elegir cuentas")  # no dead end


# --------------------------------------------------------------------------------------
# RF-02b «País» (Deivid, 2026-11-27): «Todas», «Tu país», «Locales»
# --------------------------------------------------------------------------------------


def test_pais_offers_todas_tu_pais_and_locales() -> None:
    assert vm.AXIS_LABELS[vm.AXIS_REGION] == "País"
    assert vm.CHIP_LABELS[vm.AXIS_REGION] == "País"
    assert PLACES == [
        {"value": "", "label": "Todos", "detail": ""},
        {"value": "pais", "label": "Tu país", "detail": "Colombia"},
        {"value": "local", "label": "Locales", "detail": "Cúcuta"},
    ]


def test_pais_shows_only_what_the_business_has() -> None:
    """No city: no «Locales»; no country: no «Tu país»; neither: «Todas» alone (the screen
    then draws no «País» at all)."""
    assert [o["value"] for o in vm.region_options("Uruguay", "")] == ["", "pais"]
    assert [o["value"] for o in vm.region_options("", "Cúcuta")] == ["", "local"]
    assert [o["value"] for o in vm.region_options("", "  ")] == [""]
    # a «País» value the business does not offer goes back to «Todas»
    local = vm.FilterChoice.of(region=vm.REGION_LOCAL)
    assert vm.offered_region(local, vm.region_options("Uruguay", "")).region == ""
    assert vm.offered_region(local, PLACES) is local


def test_tu_pais_and_locales_become_rf01_filters() -> None:
    """«Tu país» narrows to the business's country, «Locales» to its city; «Todas» — or a
    place the business does not have — narrows nothing."""
    country = vm.FilterChoice.of(region=vm.REGION_COUNTRY)
    assert country.active
    assert country.to_filters(country="CO", city="Cúcuta") == ReelFilters.of(
        kinds=["referente"], regions=["CO"]
    )
    local = vm.FilterChoice.of(region=vm.REGION_LOCAL, network="tiktok")
    assert local.to_filters(country="CO", city="Cúcuta") == ReelFilters.of(
        kinds=["referente"], networks=["tiktok"], city="cucuta"
    )
    assert vm.NO_CHOICE.to_filters(country="CO", city="Cúcuta") == INSPIRING
    assert country.to_filters() == INSPIRING  # no country known: no narrowing
    assert local.to_filters(country="CO") == ReelFilters.of(
        kinds=["referente"], networks=["tiktok"]
    )


def test_the_pais_chip_names_the_place() -> None:
    country = vm.FilterChoice.of(region=vm.REGION_COUNTRY)
    local = vm.FilterChoice.of(region=vm.REGION_LOCAL)
    assert vm.value_label(vm.AXIS_REGION, vm.NO_CHOICE, places=PLACES) == "Todos"
    assert vm.value_label(vm.AXIS_REGION, country, places=PLACES) == "Colombia"
    assert vm.phone_chip(vm.AXIS_REGION, vm.NO_CHOICE, places=PLACES) == ("País", "País: Todos")
    assert vm.phone_chip(vm.AXIS_REGION, local, places=PLACES) == ("Cúcuta", "País: Cúcuta")
    assert [c["on"] for c in vm.chips(local, places=PLACES)] == ["", "", "", "1"]
    assert vm.filters_button(local) == ("Filtros · 1", "Filtros: 1 activo")


#: Words a client must not read (`qualify-copy-es`, `qualify-ux`'s banned list).
_ANGLICISMS = re.compile(
    r"\b(reset|filter|filters|post|feed|inbox|creator|creators|brand|kit|trending|"
    r"insights|likes?|sort|ok|tap|click|scroll|fitness)\b",
    re.IGNORECASE,
)


#: Every sentence or label of the module a client reads (the `AXIS_*` / `EMPTY_*` keys
#: are identifiers, never shown).
_COPY = sorted(
    value
    for name, value in vars(vm).items()
    if name.isupper() and isinstance(value, str) and not name.startswith(("AXIS_", "EMPTY_"))
) + [
    label
    for _, label in (
        *vm.NETWORK_OPTIONS,
        *vm.KIND_OPTIONS,
        *vm.DURATION_OPTIONS,
        *vm.REGION_OPTIONS,
    )
]


@pytest.mark.parametrize("text", _COPY)
def test_the_copy_is_plain_spanish(text: str) -> None:
    assert not _ANGLICISMS.search(text), text
