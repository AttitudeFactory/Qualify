"""Creadores' view models (m-24946129, m-24946132) — `creators_vm.py`.

The sheet and the comparison are built from the backend's own pure functions
(`qualify_api.creators.metrics.build_sheet` / `compare`, design §9), so these tests pin
the screen against the real §10.3 dataclasses, not a copy of them.

Pins (docs/ux-creadores.md §2-3, §7 «Pruebas que conviene dejar»):
1. Numbers in the owner's format: «8.300», «12,4 mil», «1,2 millones», «4,1 %».
2. «Sin dato» is never shown as 0, and a real 0 (no paid collaborations) is said.
3. «Mejor» comes only from the server's `best`, ties included, never on a «Sin dato»;
   no summed score, no overall winner.
4. Comparar takes 2 to 4 ids: junk and repeats are dropped from the URL.
5. Two columns per phone screen; an odd last one sits next to the first.
6. Every refresh outcome is a sentence with what to do next — never credits.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest
from qualify_api.creators.metrics import (
    ComparedCreator,
    CompareEntry,
    MetricValue,
    ReelRead,
    SnapshotFacts,
    build_sheet,
    compare,
)

from .creators_vm import (
    EMPTY_RATE,
    MISSING,
    amount_input_text,
    build_card_vm,
    build_comparison_vm,
    build_rate_vm,
    build_sheet_vm,
    compare_url,
    cost_per_thousand_text,
    count_of,
    days_between,
    display_handle,
    duration_text,
    filter_cards,
    format_count,
    format_percent,
    format_range,
    freshness_text,
    handle_wrap,
    known_currency,
    measured_text,
    metric_text,
    mobile_pages,
    money_text,
    notes_counter,
    page_counter,
    parse_ids,
    pick_button,
    pick_reason,
    pick_url,
    rate_error_text,
    rate_url,
    refresh_outcome_vm,
)

NOW = datetime(2026, 11, 4, 15, 0, tzinfo=UTC)
A = UUID("a1000000-0000-4000-8000-000000000001")
B = UUID("b2000000-0000-4000-8000-000000000002")
C = UUID("c3000000-0000-4000-8000-000000000003")


def _reel(
    i: int,
    *,
    days_ago: float,
    views: int | None = 1000,
    likes: int | None = 40,
    comments: int | None = 2,
    duration: float = 20.0,
    paid: bool = False,
    coauthors: tuple[str, ...] | None = (),
) -> ReelRead:
    return ReelRead(
        reel_id=f"r{i}",
        url=f"https://www.instagram.com/reel/r{i}/",
        taken_at=NOW - timedelta(days=days_ago),
        duration_s=duration,
        views=views,
        likes=likes,
        comments=comments,
        counts_hidden=views is None,
        is_paid_partnership=paid,
        coauthors=coauthors,
        sound_id="s1",
        sound_title="Audio original",
        sound_is_original=True,
    )


def _snapshot(handle: str, *, followers: int | None, days_old: int = 0, n: int = 12):
    return SnapshotFacts(
        snapshot_id=UUID(int=hash(handle) & ((1 << 64) - 1)),
        network="instagram",
        handle=handle,
        read_at=NOW - timedelta(days=days_old),
        status="ok",
        followers=followers,
        full_name="",
        reels_read=n,
    )


def _reels(base_views: int, n: int = 12, *, offset_days: int = 0) -> list[ReelRead]:
    out = []
    for i in range(n):
        views = base_views * (5 if i == 3 else 1) + i * 10
        out.append(_reel(i, days_ago=4 + offset_days + i * 3, views=views, paid=i == 0))
    return out


# --- 1. numbers ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (0, "0"),
        (8300, "8.300"),
        (9999, "9.999"),
        (12_400, "12,4 mil"),
        (48_100, "48,1 mil"),
        (100_000, "100 mil"),
        (999_960, "1 millón"),
        (1_234_567, "1,2 millones"),
        (None, MISSING),
    ],
)
def test_counts_read_like_the_owner_writes_them(value: int | None, text: str) -> None:
    assert format_count(value) == text


def test_percent_has_a_comma_and_a_space() -> None:
    assert format_percent(0.041) == "4,1 %"
    assert format_percent(0.67, 0) == "67 %"
    assert format_percent(1.13, 0) == "113 %"
    assert format_percent(None) == MISSING


def test_freshness_in_words() -> None:
    assert freshness_text(0) == "Datos de hoy"
    assert freshness_text(1) == "Datos de ayer"
    assert freshness_text(9) == "Datos de hace 9 días"
    assert days_between(NOW - timedelta(days=3), NOW) == 3


def test_a_duration_band_is_said_in_words() -> None:
    assert duration_text("≤15 s") == "hasta 15 s"
    assert duration_text("16–30 s") == "de 16 a 30 s"
    assert duration_text(">90 s") == "más de 90 s"


def test_display_handle_accepts_what_the_owner_pastes() -> None:
    assert display_handle("@ComeConMaria") == "@comeconmaria"
    assert display_handle("comeconmaria") == "@comeconmaria"
    assert display_handle("https://www.instagram.com/comeconmaria/?igsh=abc") == "@comeconmaria"


# --- 2. «Sin dato», never 0 ----------------------------------------------------------


@pytest.mark.parametrize(
    "key", ["followers", "median_views", "views_per_follower", "engagement_rate", "standout_share"]
)
@pytest.mark.parametrize("status", ["insufficient", "unknown"])
def test_a_metric_without_data_is_sin_dato_never_zero(key: str, status: str) -> None:
    text = metric_text(key, MetricValue(key, None, status, 2))
    assert text == MISSING
    assert "0" not in text


def test_a_real_zero_of_paid_collaborations_is_said_as_none() -> None:
    assert metric_text("paid_partnerships", MetricValue("paid_partnerships", 0, "ok", 30)) == (
        "Ninguna declarada"
    )
    assert metric_text("paid_partnerships", MetricValue("paid_partnerships", 4, "ok", 30)) == (
        "4 de 30"
    )


def test_the_sheet_shows_sin_dato_for_hidden_followers_and_few_reels() -> None:
    reels = [_reel(i, days_ago=5 + i) for i in range(2)]  # 2 measurable < MIN_SAMPLE
    sheet = build_sheet(A, _snapshot("maria", followers=None, n=2), reels, now=NOW)
    vm = build_sheet_vm(sheet, now=NOW)
    by_key = {s.key: s for s in vm.stats}
    for key in ("median_views", "followers", "views_per_follower", "engagement_rate"):
        assert by_key[key].value == MISSING
        assert by_key[key].missing
        assert by_key[key].hint == "Instagram no lo muestra para esta cuenta"
    assert vm.few_reels.startswith("Solo encontramos 2 reels")


def test_the_sheet_in_words() -> None:
    sheet = build_sheet(A, _snapshot("maria", followers=12_400), _reels(8000), now=NOW)
    vm = build_sheet_vm(sheet, now=NOW)
    by_key = {s.key: s for s in vm.stats}
    assert by_key["followers"].value == "12,4 mil"
    assert by_key["median_views"].label == "Vistas típicas por reel"
    assert by_key["median_views"].hint == "Lo que suele ver un reel suyo"
    assert vm.handle == "@maria"
    assert vm.freshness == "Datos de hoy"
    assert vm.profile_url == "https://www.instagram.com/maria/"
    assert vm.standout_sentence.startswith("1 de sus últimos 12 reels tuvieron más del doble")
    assert vm.standout_reels[0].lift.endswith("veces lo normal")
    assert vm.collab_sentence == "1 de sus últimos 12 reels es una publicación pagada."
    assert vm.trust.startswith("Contamos sus últimos 12 reels, del ")
    assert not vm.stale and vm.stale_message == ""


def test_a_stale_sheet_asks_to_update_before_deciding() -> None:
    sheet = build_sheet(A, _snapshot("maria", followers=900, days_old=9), _reels(800), now=NOW)
    vm = build_sheet_vm(sheet, now=NOW)
    assert vm.stale
    assert vm.freshness == "Datos de hace 9 días"
    assert vm.stale_message == "Estos números son de hace 9 días. Actualízalos antes de decidir."


# --- 3. Comparar: «Mejor» from the server, never a total -----------------------------


def _comparison(stale_b: bool = False):
    entries = [
        CompareEntry(A, _snapshot("maria", followers=12_400), _reels(8000)),
        CompareEntry(
            B, _snapshot("ruta", followers=None, days_old=21 if stale_b else 0), _reels(9000)
        ),
        CompareEntry(C, _snapshot("tachira", followers=6900), _reels(7000)),
    ]
    return compare(entries, now=NOW)


def test_mejor_follows_the_server_and_never_lands_on_sin_dato() -> None:
    raw = _comparison()
    vm = build_comparison_vm(raw, now=NOW)
    rows = {r.key: r for r in vm.rows}
    for row in raw.rows:
        cells = rows[row.key].cells
        marked = {i for i, cell in enumerate(cells) if cell.best}
        assert marked <= set(row.best)
        for cell in cells:
            if cell.missing:
                assert not cell.best
    # followers do not highlight; B has none and says so
    assert not any(c.best for c in rows["followers"].cells)
    assert rows["followers"].cells[1].text == MISSING
    assert rows["median_views"].cells[1].best
    assert "mejor de los 3" in rows["median_views"].cells[1].spoken


def test_rows_that_carry_mejor_come_first_and_there_is_no_total() -> None:
    vm = build_comparison_vm(_comparison(), now=NOW)
    keys = [r.key for r in vm.rows]
    assert keys[:4] == ["median_views", "views_per_follower", "engagement_rate", "standout_share"]
    labels = " ".join(r.label.lower() for r in vm.rows)
    for word in ("total", "puntaje", "ganador"):
        assert word not in labels


def test_ties_mark_every_tied_creator() -> None:
    value = MetricValue("median_views", 5000, "ok", 10)
    raw = SimpleNamespace(
        creators=(
            ComparedCreator(
                tracked_id=A, handle="a", read_at=NOW, stale=False, measurable_in_window=10
            ),
            ComparedCreator(
                tracked_id=B, handle="b", read_at=NOW, stale=False, measurable_in_window=10
            ),
        ),
        window_from=NOW - timedelta(days=60),
        window_to=NOW - timedelta(days=3),
        rows=(
            SimpleNamespace(
                key="median_views", values=(value, value), best=(0, 1), highlights=True
            ),
        ),
        warnings=(),
        reels_per_creator=10,
    )
    vm = build_comparison_vm(raw, now=NOW)
    assert [c.best for c in vm.rows[0].cells] == [True, True]


def test_a_stale_creator_gets_the_warning_with_its_button() -> None:
    vm = build_comparison_vm(_comparison(stale_b=True), now=NOW)
    assert vm.stale_ids == [str(B)]
    assert vm.stale_message == (
        "Los datos de @ruta son de hace 21 días. Actualízalos para comparar parejo."
    )
    assert vm.stale_button == "Actualizar @ruta"
    assert vm.columns[1].stale


def test_columns_can_be_removed_only_above_two_and_link_back_to_the_list() -> None:
    vm = build_comparison_vm(_comparison(), now=NOW)
    assert all(c.remove_href for c in vm.columns)
    assert vm.columns[0].remove_href == compare_url([str(B), str(C)])
    assert vm.add_href == pick_url([str(A), str(B), str(C)])
    assert vm.intro.startswith("Comparamos los últimos ")


# --- 4. the ids of the URL -------------------------------------------------------------


def test_parse_ids_drops_junk_and_repeats() -> None:
    assert parse_ids(f"{A},nope,{A},{B}") == [str(A), str(B)]
    assert parse_ids("@maria,juan") == []
    assert parse_ids(None) == []
    five = ",".join(str(UUID(int=i + 1)) for i in range(5))
    assert len(parse_ids(five)) == 5  # still visible as «more than 4»


def test_the_pick_foot_says_why_it_waits() -> None:
    assert pick_reason(0) == "Elige al menos 2 más"
    assert pick_reason(1) == "Elige al menos uno más"
    assert pick_reason(2) == ""
    assert pick_button(3) == "Comparar 3 creadores"


# --- 5. two per phone screen -----------------------------------------------------------


def test_two_columns_per_phone_screen() -> None:
    assert mobile_pages(2) == [[0, 1]]
    assert mobile_pages(3) == [[0, 1], [2, 0]]
    assert mobile_pages(4) == [[0, 1], [2, 3]]
    assert page_counter(0, mobile_pages(3), 3) == "1–2 de 3"
    assert page_counter(1, mobile_pages(3), 3) == "1 y 3 de 3"


# --- 6. outcomes in words ----------------------------------------------------------------


@pytest.mark.parametrize(
    "status", ["missing", "private", "busy", "cap_reached", "blocked", "error", "weird"]
)
def test_every_outcome_is_a_sentence_without_team_words(status: str) -> None:
    outcome = refresh_outcome_vm(status, "maria")
    assert not outcome.done
    assert outcome.message
    lowered = outcome.message.lower()
    for word in ("crédito", "credito", "api", "scrap", "error", "404", "402", "vendor"):
        assert word not in lowered
    if status in ("missing", "private"):
        assert "@maria" in outcome.message


def test_read_and_fresh_open_the_sheet() -> None:
    assert refresh_outcome_vm("read", "x").done
    assert refresh_outcome_vm("fresh", "x").done


# --- the list ---------------------------------------------------------------------------


def _card(**kw):
    tracked = SimpleNamespace(
        id=kw.pop("id", A),
        handle=kw.pop("handle", "maria"),
        refresh_state=kw.pop("refresh_state", "ok"),
        refresh_error=kw.pop("refresh_error", None),
        created_at=NOW,
    )
    base = {
        "tracked": tracked,
        "full_name": "María Valentina",
        "avatar_url": "",
        "followers": 12_400,
        "median_views": MetricValue("median_views", 8300, "ok", 30),
        "engagement_rate": MetricValue("engagement_rate", 0.041, "ok", 30),
        "read_at": NOW - timedelta(days=3),
        "stale": False,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_a_list_card_in_words() -> None:
    vm = build_card_vm(_card(), now=NOW)
    assert vm.state == "ready"
    assert vm.followers == "12,4 mil seguidores"
    assert vm.median_views == "8.300 vistas típicas por reel"
    assert vm.freshness == "Datos de hace 3 días"
    assert vm.href == f"/creadores/{A}"
    assert vm.initials == "MV"


def test_list_card_states() -> None:
    working = build_card_vm(_card(read_at=None, refresh_state="reading"), now=NOW)
    assert working.state == "working"
    failed = build_card_vm(
        _card(read_at=None, refresh_state="failed", refresh_error="private"), now=NOW
    )
    assert failed.state == "failed"
    assert "privada" in failed.problem
    unknown = build_card_vm(
        _card(median_views=MetricValue("median_views", None, "unknown", 0), followers=None), now=NOW
    )
    assert unknown.median_views == "Vistas típicas por reel: sin dato"
    assert unknown.followers == "Seguidores: sin dato"


def test_search_by_name_or_handle() -> None:
    cards = [
        build_card_vm(_card(), now=NOW),
        build_card_vm(_card(id=B, handle="ruta", full_name="Ruta"), now=NOW),
    ]
    assert [c.handle for c in filter_cards(cards, "@rut")] == ["@ruta"]
    assert [c.handle for c in filter_cards(cards, "valentina")] == ["@maria"]
    assert len(filter_cards(cards, "")) == 2


# --- review fixes 2026-11-04 -------------------------------------------------------------


def test_millions_take_de_before_the_noun() -> None:
    assert count_of(7_200_000, "vistas") == "7,2 millones de vistas"
    assert count_of(1_000_000, "seguidores") == "1 millón de seguidores"
    assert count_of(12_400, "seguidores") == "12,4 mil seguidores"
    card = build_card_vm(
        _card(followers=32_500_000, median_views=MetricValue("median_views", 7_200_000, "ok", 30)),
        now=NOW,
    )
    assert card.followers == "32,5 millones de seguidores"
    assert card.median_views == "7,2 millones de vistas típicas por reel"


def test_a_range_writes_the_year_only_when_it_crosses_one() -> None:
    assert format_range(datetime(2026, 8, 2), datetime(2026, 11, 1)) == (
        "del 2 de agosto al 1 de noviembre"
    )
    assert format_range(datetime(2025, 12, 20), datetime(2026, 1, 3)) == (
        "del 20 de diciembre de 2025 al 3 de enero de 2026"
    )


def test_one_reel_is_singular() -> None:
    reels = [_reel(0, days_ago=5)]
    sheet = build_sheet(A, _snapshot("maria", followers=10, n=1), reels, now=NOW)
    vm = build_sheet_vm(sheet, now=NOW)
    assert vm.few_reels.startswith("Solo encontramos 1 reel.")
    assert "1 reels" not in vm.trust
    assert measured_text(1, None, None) == "Medido en su último reel"


def test_the_cap_promises_neither_tomorrow_nor_a_plan() -> None:
    message = refresh_outcome_vm("cap_reached", "x").message
    assert message == "Llegaste al límite de revisiones por ahora. Vuelve a intentarlo más tarde."


def test_a_read_stuck_in_reading_offers_a_retry() -> None:
    """The backend's `refresh_stuck` decides; the row then says what to do."""
    stuck = build_card_vm(_card(read_at=None, refresh_state="reading"), now=NOW, stuck=True)
    assert stuck.state == "failed"
    assert "Inténtalo de nuevo" in stuck.problem
    alive = build_card_vm(_card(read_at=None, refresh_state="reading"), now=NOW)
    assert alive.state == "working"


def test_paid_and_coauthors_have_their_own_names() -> None:
    raw = _comparison()
    vm = build_comparison_vm(raw, now=NOW)
    assert {r.key: r.label for r in vm.rows}["paid_partnerships"] == "Publicaciones pagadas"
    sheet = build_sheet(A, _snapshot("maria", followers=10), _reels(800), now=NOW)
    words = build_sheet_vm(sheet, now=NOW)
    assert "marca" not in words.collab_sentence + words.coauthor_sentence


def test_comparar_uses_the_same_last_n_reels_and_never_blames_posting_little() -> None:
    raw = _comparison()
    vm = build_comparison_vm(raw, now=NOW)
    n = raw.reels_per_creator
    assert n >= 3
    assert vm.intro.startswith(f"Comparamos los últimos {n} reels de cada uno.")
    text = " ".join([vm.intro, *(c.measured for c in vm.columns)])
    assert "publica poco" not in text
    for column, creator in zip(vm.columns, raw.creators, strict=True):
        assert column.measured.startswith(f"Medido en sus últimos {creator.reels_used} reels")
    assert vm.columns[0].freshness_short == "hoy"


def test_a_creator_with_few_reels_is_flagged_not_blanked() -> None:
    raw = _comparison()
    creators = tuple(
        SimpleNamespace(**{**c.__dict__, "few_reels": i == 1}) for i, c in enumerate(raw.creators)
    )
    vm = build_comparison_vm(SimpleNamespace(**{**raw.__dict__, "creators": creators}), now=NOW)
    assert [c.few_note for c in vm.columns] == ["", "Pocos reels para comparar", ""]
    warned = SimpleNamespace(**{**raw.__dict__, "warnings": (f"few_reels:{C}",)})
    assert build_comparison_vm(warned, now=NOW).columns[2].few_note == "Pocos reels para comparar"


def test_handles_break_after_dots_and_underscores() -> None:
    assert handle_wrap("@pilla.no_saurio") == "@pilla.\u200bno_\u200bsaurio"


# --- «Lo que cobra» (m-24955847) ----------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "currency", "home", "expected"),
    [
        (Decimal("150000"), "COP", "cop", "150.000 pesos"),  # the business's own pesos
        (Decimal("150000"), "COP", "uyu", "150.000 pesos colombianos"),
        (Decimal("2500"), "UYU", "uyu", "2.500 pesos"),
        (Decimal("2500"), "UYU", "cop", "2.500 pesos uruguayos"),
        (Decimal("150"), "USD", "usd", "150 dólares"),
        (Decimal("1"), "USD", "cop", "1 dólar"),
        (Decimal("1"), "COP", "usd", "1 peso colombiano"),
        (Decimal("1500.50"), "USD", "cop", "1.500,50 dólares"),
        (Decimal("1500.00"), "VES", "ves", "1.500 bolívares"),
        (Decimal("1200000"), "cop", None, "1.200.000 pesos colombianos"),
        (None, "COP", "cop", ""),
    ],
)
def test_money_in_the_owners_words(amount, currency, home, expected) -> None:
    assert money_text(amount, currency, home=home) == expected


def test_the_amount_goes_back_to_the_field_as_it_is_read() -> None:
    assert amount_input_text(Decimal("150000")) == "150.000"
    assert amount_input_text(Decimal("1500.5")) == "1.500,50"
    assert amount_input_text(None) == ""


def _rated(**kw):
    base = {
        "rate_notes": "",
        "rate_from": None,
        "rate_currency": None,
        "rate_updated_at": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_a_rate_in_words_keeps_its_line_breaks() -> None:
    vm = build_rate_vm(
        _rated(
            rate_notes="1 reel, 150.000\nPaquete de 3 reels, 380.000",
            rate_from=Decimal("150000"),
            rate_currency="COP",
            rate_updated_at=datetime(NOW.year, 11, 5, 15, tzinfo=UTC),
        ),
        now=NOW,
        home="cop",
    )
    assert vm.has_rate
    assert vm.from_text == "Desde 150.000 pesos"
    assert vm.notes == "1 reel, 150.000\nPaquete de 3 reels, 380.000"
    assert vm.updated == "Anotado el 5 de noviembre"
    assert vm.amount_input == "150.000"
    assert vm.currency == "cop"


def test_a_price_of_zero_is_said_as_working_for_products() -> None:
    vm = build_rate_vm(_rated(rate_from=Decimal("0"), rate_currency="COP"), now=NOW, home="cop")
    assert vm.from_text == "Trabaja a cambio de productos"
    assert vm.amount_input == "0"


def test_nothing_written_is_the_empty_state_never_zero() -> None:
    assert build_rate_vm(_rated(), now=NOW) == EMPTY_RATE
    assert build_rate_vm(SimpleNamespace(), now=NOW) == EMPTY_RATE  # an older backend
    only_text = build_rate_vm(_rated(rate_notes="Cobra por canje"), now=NOW)
    assert only_text.has_rate and only_text.from_text == ""
    assert only_text.currency == ""


def test_the_list_card_says_desde_only_with_a_price() -> None:
    priced = _card()
    priced.tracked.rate_from = Decimal("380000")
    priced.tracked.rate_currency = "COP"
    assert build_card_vm(priced, now=NOW, home="cop").rate_from == "Desde 380.000 pesos"
    assert build_card_vm(priced, now=NOW, home="ves").rate_from == (
        "Desde 380.000 pesos colombianos"
    )
    assert build_card_vm(_card(), now=NOW).rate_from == ""


@pytest.mark.parametrize(
    ("reason", "field_name", "sentence"),
    [
        ("not_a_number", "amount", "Escribe solo el número, por ejemplo 150.000."),
        ("negative", "amount", "El precio no puede ser negativo."),
        ("too_large", "amount", "Es demasiado grande; revisa los ceros."),
        ("notes_too_long", "notes", "Acorta el texto: caben hasta 1.000 letras."),
        ("currency_required", "amount", "Elige la moneda de su precio."),
        (
            "cents_not_allowed",
            "amount",
            "Los pesos no llevan centavos. Revisa el número; por ejemplo, 150.500.",
        ),
        ("whatever", "", "No pudimos guardar lo que cobra. Vuelve a intentarlo en un momento."),
    ],
)
def test_every_refused_rate_says_what_to_do(reason, field_name, sentence) -> None:
    assert rate_error_text(reason) == (field_name, sentence)


def test_a_currency_written_in_the_amount_that_disagrees_is_named() -> None:
    assert rate_error_text("currency_mismatch", typed="usd", chosen="cop") == (
        "amount",
        "Escribiste dólares pero elegiste pesos colombianos. Cambia la moneda o escribe "
        "solo el número.",
    )


def test_the_counter_and_the_currency_choice() -> None:
    assert notes_counter("x" * 1200) == "1.200 de 1.000 letras"
    assert notes_counter("  hola  \n") == "4 de 1.000 letras"  # edges do not count
    assert known_currency("UYU") == "uyu"
    assert known_currency("EUR") == "cop"
    assert known_currency("", "ves") == "ves"


def test_the_drawer_has_its_own_address() -> None:
    assert rate_url(A) == f"/creadores/{A}?flujo=tarifa&paso=1"


def _priced(raw, rates):
    creators = tuple(
        SimpleNamespace(**{**c.__dict__, **rate})
        for c, rate in zip(raw.creators, rates, strict=True)
    )
    return SimpleNamespace(**{**raw.__dict__, "creators": creators})


def test_comparar_marks_the_lowest_price_from_the_server() -> None:
    raw = _priced(
        _comparison(),
        [
            {
                "rate_from": Decimal("150000"),
                "rate_currency": "COP",
                "rate_notes": "1 reel",
                "cost_per_thousand_views": Decimal("18072.29"),
                "lowest_rate": True,
                "lowest_cost_per_thousand": False,
            },
            {
                "rate_from": Decimal("200000"),
                "rate_currency": "COP",
                "rate_notes": "x" * 200,
                "cost_per_thousand_views": Decimal("15000"),
                "lowest_rate": False,
                "lowest_cost_per_thousand": True,
            },
            {},  # nothing written
        ],
    )
    vm = build_comparison_vm(raw, now=NOW, home="cop")
    rows = {r.key: r for r in vm.rows}
    keys = [r.key for r in vm.rows]
    assert keys[4:6] == ["rate_from", "cost_per_thousand"]
    assert keys[-1] == "rate_notes"

    price = rows["rate_from"]
    assert price.label == "Cobra desde"
    assert [c.text for c in price.cells] == ["150.000 pesos", "200.000 pesos", "Sin anotar"]
    assert [c.best for c in price.cells] == [True, False, False]
    assert "el más bajo de los 3" in price.cells[0].spoken
    assert price.cells[0].kind == "money"
    assert price.cells[2].add_href == f"/creadores/{C}?flujo=tarifa&paso=1"
    assert price.cells[2].add_label == "Anotar lo que cobra"
    assert price.cells[0].add_href == ""

    cost = rows["cost_per_thousand"]
    assert cost.label == "Por cada mil vistas (aprox.)"
    assert cost.hint == "Su precio más bajo entre las vistas que suele tener un reel suyo."
    assert cost.help.startswith("Es un cálculo aproximado.")
    assert "personas" not in f"{cost.label} {cost.hint} {cost.help}"
    assert [c.text for c in cost.cells] == ["18.072 pesos", "15.000 pesos", MISSING]
    assert [c.best for c in cost.cells] == [False, True, False]

    notes = rows["rate_notes"]
    assert [c.text for c in notes.cells][2] == "Sin anotar"
    assert [c.long for c in notes.cells] == [False, True, False]
    assert vm.mixed_note == ""
    # the phone columns carry the same cells
    assert vm.mobile[0].figures[4].text == "150.000 pesos"
    assert vm.mobile[0].figures[4].best
    assert vm.mobile[2].figures[4].add_label == "Anotar lo que cobra"


def test_notes_without_a_price_ask_for_the_price() -> None:
    raw = _priced(_comparison(), [{"rate_notes": "Cobra por paquetes"}, {}, {}])
    price = next(r for r in build_comparison_vm(raw, now=NOW).rows if r.key == "rate_from")
    assert price.cells[0].text == "Falta su precio más bajo"
    assert price.cells[0].add_label == "Anotar su precio más bajo"
    assert price.cells[0].missing
    assert (price.cells[1].text, price.cells[1].add_label) == ("Sin anotar", "Anotar lo que cobra")


def test_a_creator_who_works_for_products_on_comparar() -> None:
    raw = _priced(
        _comparison(),
        [
            {"rate_from": Decimal("0"), "rate_currency": "COP"},
            {"rate_from": Decimal("150000"), "rate_currency": "COP"},
            {},
        ],
    )
    rows = {r.key: r for r in build_comparison_vm(raw, now=NOW, home="cop").rows}
    first = rows["rate_from"].cells[0]
    assert first.text == "Trabaja a cambio de productos"
    assert not first.missing and not first.best and first.add_href == ""
    assert rows["cost_per_thousand"].cells[0].text == MISSING


def test_mixed_currencies_are_said_and_never_converted() -> None:
    raw = _priced(
        _comparison(),
        [
            {"rate_from": Decimal("150000"), "rate_currency": "COP"},
            {"rate_from": Decimal("3000"), "rate_currency": "UYU"},
            {"rate_from": Decimal("40"), "rate_currency": "USD"},
        ],
    )
    raw.mixed_currencies = True
    vm = build_comparison_vm(raw, now=NOW, home="uyu")
    price = next(r for r in vm.rows if r.key == "rate_from")
    assert [c.text for c in price.cells] == [
        "150.000 pesos colombianos",
        "3.000 pesos",  # the business's own
        "40 dólares",
    ]
    assert not any(c.best for c in price.cells)
    assert vm.mixed_note == (
        "Hay precios en monedas distintas; solo comparamos los que están en la misma moneda."
    )


def test_a_small_cost_per_thousand_keeps_its_cents() -> None:
    assert cost_per_thousand_text(Decimal("0.85"), "USD") == "0,85 dólares"
    assert cost_per_thousand_text(Decimal("18.07"), "USD") == "18,07 dólares"
    assert cost_per_thousand_text(Decimal("180.4"), "USD") == "180 dólares"
    assert cost_per_thousand_text(None, "USD") == MISSING
