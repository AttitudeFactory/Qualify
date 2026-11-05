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
from types import SimpleNamespace
from uuid import UUID

import pytest
from qualify_api.creators.metrics import (
    CompareEntry,
    MetricValue,
    ReelRead,
    SnapshotFacts,
    build_sheet,
    compare,
)

from .creators_vm import (
    MISSING,
    build_card_vm,
    build_comparison_vm,
    build_sheet_vm,
    compare_url,
    days_between,
    display_handle,
    duration_text,
    filter_cards,
    format_count,
    format_percent,
    freshness_text,
    metric_text,
    mobile_pages,
    page_counter,
    parse_ids,
    pick_button,
    pick_reason,
    pick_url,
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
    assert vm.collab_sentence == "1 de sus últimos 12 reels son colaboraciones pagadas."
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
            SimpleNamespace(
                tracked_id=A, handle="a", read_at=NOW, stale=False, measurable_in_window=10
            ),
            SimpleNamespace(
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
    assert "las mismas fechas para todos" in vm.intro


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
