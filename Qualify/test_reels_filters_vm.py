"""RF-02 (m-25119460): the filter bar of «Ideas para tus reels», offline — the exact
words of the ticket, what each axis offers, what the owner's choice becomes for RF-01's
read, and the message that replaces an empty list."""

from __future__ import annotations

import re

import pytest
from qualify_api.referentes.reviewed_reels import NO_FILTERS, ReelFilters

from . import reels_filters_vm as vm

ACCOUNTS = {
    "instagram:foodie": "referente",
    "tiktok:rival": "competencia",
    "instagram:abc": "referente",
}


def test_the_bar_says_exactly_what_the_ticket_says() -> None:
    assert [vm.AXIS_LABELS[a] for a in vm.AXES] == ["Canal", "Tipo de cuenta", "Cuenta", "Duración"]
    assert [label for _, label in vm.NETWORK_OPTIONS] == ["Instagram", "TikTok"]
    assert [label for _, label in vm.KIND_OPTIONS] == ["Inspiradores", "Competidores"]
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
    for gone in ("MORE_TITLE", "MORE_BODY", "IDEAS_NONE_FILTERED"):
        assert not hasattr(vm, gone), gone


def _cards(n: int) -> list[dict[str, str]]:
    return [{"key": f"instagram:M{i}"} for i in range(n)]


def test_the_first_page_is_the_ideas_then_the_reviewed_reels_up_to_16() -> None:
    """RF-13: 6 ideas leave room for 10 reviewed reels; «Ver más» reads from the 11th."""
    page = vm.first_page(6, _cards(16), has_more=True)
    assert [c["key"] for c in page.more] == [f"instagram:M{i}" for i in range(10)]
    assert page.has_more and page.next_offset == 10
    # fewer reviewed reels than the room: all of them, and nothing more to see
    short = vm.first_page(6, _cards(4), has_more=False)
    assert (len(short.more), short.has_more, short.next_offset) == (4, False, 4)
    # exactly the room: nothing left over unless the read said so
    exact = vm.first_page(6, _cards(10), has_more=False)
    assert (len(exact.more), exact.has_more) == (10, False)
    # no idea left by the filters: 16 reviewed reels
    none = vm.first_page(0, _cards(16), has_more=True)
    assert (len(none.more), none.has_more, none.next_offset) == (16, True, 16)
    # a page full of ideas: the reviewed reels all wait for «Ver más», from the start
    full = vm.first_page(16, _cards(3), has_more=False)
    assert (full.more, full.has_more, full.next_offset) == ([], True, 0)
    assert vm.first_page(16, [], has_more=False).has_more is False


def test_inspiradores_and_competidores_are_the_labelled_kinds() -> None:
    """Decision 1 of the epic: «Competidores» = accounts marked `competencia`; no
    detractors anywhere in the bar (decision 3)."""
    assert dict(vm.KIND_OPTIONS) == {"referente": "Inspiradores", "competencia": "Competidores"}
    assert "detractor" not in str(vm.single_options(vm.AXIS_KIND))


def test_a_phone_chip_says_one_short_word_inside_its_full_name() -> None:
    """RF-13 (Deivid, 2026-11-26, measured at 375 px): no filter → the short name; a
    filter → its value, shorter for «Tipo» and «Duración»; the accessible name keeps the
    long words and always contains the visible one (WCAG 2.5.3)."""
    none = vm.NO_CHOICE
    assert vm.phone_chip(vm.AXIS_KIND, none) == ("Tipo", "Tipo de cuenta: Todos")
    assert vm.phone_chip(vm.AXIS_NETWORK, none) == ("Canal", "Canal: Todos")
    insta = vm.FilterChoice.of(network="instagram")
    assert vm.phone_chip(vm.AXIS_NETWORK, insta) == ("Instagram", "Canal: Instagram")
    rivals = vm.FilterChoice.of(kind="competencia")
    assert vm.phone_chip(vm.AXIS_KIND, rivals) == (
        "Compiten contigo",
        "Tipo de cuenta: Compiten contigo (competidores)",
    )
    assert vm.phone_chip(vm.AXIS_KIND, vm.FilterChoice.of(kind="referente"))[0] == "Te inspiran"
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
    # the sheet and the desktop keep the long words
    assert vm.value_label(vm.AXIS_DURATION, short) == "Menos de 15 segundos"
    assert vm.value_label(vm.AXIS_KIND, rivals) == "Competidores"
    # «Competidores» is never a chip's face (the «Competidores» button sits beside it)
    for axis in vm.AXES:
        for choice in (none, insta, rivals, short):
            face, name = vm.phone_chip(axis, choice)
            assert face.lower() in name.lower(), (axis, face, name)
            assert face != "Competidores"


def test_every_single_choice_axis_starts_with_all() -> None:
    assert vm.single_options(vm.AXIS_NETWORK)[0] == {"value": "", "label": "Todos"}
    assert vm.single_options(vm.AXIS_KIND)[0] == {"value": "", "label": "Todos"}
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
    assert vm.NO_CHOICE.to_filters() == NO_FILTERS
    assert [c["value"] for c in vm.chips(vm.NO_CHOICE)] == ["Todos", "Todos", "Todas", "Todas"]
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
        network="youtube", kind="detractor", duration="90", accounts=["otro:x", "bad", "tiktok:"]
    )
    assert choice == vm.NO_CHOICE
    assert choice.to_filters() == NO_FILTERS


def test_axes_change_one_at_a_time_and_accounts_toggle() -> None:
    choice = vm.set_axis(vm.NO_CHOICE, vm.AXIS_NETWORK, "instagram")
    choice = vm.set_axis(choice, vm.AXIS_DURATION, "lt15")
    assert (choice.network, choice.kind, choice.duration) == ("instagram", "", "lt15")
    choice = vm.toggle_account(choice, "instagram:foodie")
    choice = vm.toggle_account(choice, "tiktok:rival")
    assert choice.accounts == ("instagram:foodie", "tiktok:rival")
    choice = vm.toggle_account(choice, "instagram:foodie")
    assert choice.accounts == ("tiktok:rival",)
    assert vm.clear_accounts(choice).accounts == ()
    assert vm.set_axis(choice, vm.AXIS_NETWORK, "").network == ""
    assert vm.set_axis(choice, "region", "co") == choice  # RF-02b's, not here


def test_the_chips_say_what_each_axis_is_set_to() -> None:
    options = vm.account_options(ACCOUNTS)
    one = vm.FilterChoice.of(network="instagram", kind="referente", accounts=["instagram:abc"])
    assert {c["axis"]: c["value"] for c in vm.chips(one, options)} == {
        "network": "Instagram",
        "kind": "Inspiradores",
        "account": "@abc",
        "duration": "Todas",
    }
    two = vm.toggle_account(one, "instagram:foodie")
    assert vm.value_label(vm.AXIS_ACCOUNT, two, options) == "2 cuentas"
    assert [c["on"] for c in vm.chips(two, options)] == ["1", "1", "1", ""]


def test_the_account_options_are_the_labelled_ones_inspiradores_first() -> None:
    assert vm.account_options({**ACCOUNTS, "instagram:hater": "detractor"}) == [
        {"key": "instagram:abc", "label": "@abc", "detail": "Instagram · Te inspira"},
        {"key": "instagram:foodie", "label": "@foodie", "detail": "Instagram · Te inspira"},
        {"key": "tiktok:rival", "label": "@rival", "detail": "TikTok · Compite contigo"},
    ]
    assert vm.accounts_by_key({("instagram", "foodie"): "referente"}) == {
        "instagram:foodie": "referente"
    }


def test_an_account_the_brand_no_longer_offers_leaves_the_choice() -> None:
    choice = vm.FilterChoice.of(accounts=["instagram:foodie", "instagram:gone"])
    assert vm.known_accounts(choice, ACCOUNTS).accounts == ("instagram:foodie",)
    assert vm.known_accounts(vm.NO_CHOICE, ACCOUNTS) is vm.NO_CHOICE


def test_competitors_empty_is_said_never_a_mute_list() -> None:
    """Before RF-05 no reel of a `competencia` account is read: that filter is empty by
    design, and the owner is told so — and how to mark competitors when there are none."""
    only_kind = vm.FilterChoice.of(kind="competencia")
    only_account = vm.FilterChoice.of(accounts=["tiktok:rival"])
    for choice in (only_kind, only_account):
        assert vm.only_competitors(choice, ACCOUNTS)
        message = vm.empty_message(choice, ACCOUNTS, ideas=0, more=0)
        assert message.kind == vm.EMPTY_COMPETITORS
        assert message.title == "Aún no revisamos los reels de tus competidores"
        assert message.action == "Ver cuentas que te inspiran"
    none_marked = {"instagram:foodie": "referente"}
    message = vm.empty_message(only_kind, none_marked, ideas=0, more=0)
    assert message.kind == vm.EMPTY_NO_COMPETITORS and message.action == "Elegir competidores"
    # an inspirador account among the chosen ones is not «only competitors»
    mixed = vm.FilterChoice.of(accounts=["tiktok:rival", "instagram:foodie"])
    assert not vm.only_competitors(mixed, ACCOUNTS)


def test_other_filters_that_leave_nothing_say_the_tickets_sentence() -> None:
    choice = vm.FilterChoice.of(duration="gte60")
    message = vm.empty_message(choice, ACCOUNTS, ideas=0, more=0)
    assert (message.kind, message.body) == (vm.EMPTY_FILTERS, vm.EMPTY_FILTERED)
    assert vm.empty_message(choice, ACCOUNTS, ideas=1, more=0).kind == vm.EMPTY_NONE
    assert vm.empty_message(choice, ACCOUNTS, ideas=0, more=3).kind == vm.EMPTY_NONE
    left = vm.empty_message(vm.NO_CHOICE, ACCOUNTS, ideas=0, more=0)
    assert (left.kind, left.action) == (vm.EMPTY_NO_IDEAS, "Elegir cuentas")  # no dead end


#: Words a client must not read (`qualify-copy-es`, `qualify-ux`'s banned list).
_ANGLICISMS = re.compile(
    r"\b(reset|filter|filters|post|feed|inbox|creator|creators|brand|kit|trending|"
    r"insights|likes?|sort|ok|tap|click|scroll)\b",
    re.IGNORECASE,
)


#: Every sentence or label of the module a client reads (the `AXIS_*` / `EMPTY_*` keys
#: are identifiers, never shown).
_COPY = sorted(
    value
    for name, value in vars(vm).items()
    if name.isupper() and isinstance(value, str) and not name.startswith(("AXIS_", "EMPTY_"))
) + [label for _, label in (*vm.NETWORK_OPTIONS, *vm.KIND_OPTIONS, *vm.DURATION_OPTIONS)]


@pytest.mark.parametrize("text", _COPY)
def test_the_copy_is_plain_spanish(text: str) -> None:
    assert not _ANGLICISMS.search(text), text
