"""m-24976895 — «Stickers y videos de tu marca» offline: the calendar and the words, the
three-step flow and its defaults, the IA cost line, approvals (nothing by default, only
`ready`, «Aprobar los listos» with its question), «Pedir otro» with IA asking first, late
reads dropped, archive with «Deshacer», logout reset and no autoplay."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_api.whatsapp.seasonal import NothingToMake

from . import seasonal_state as state_module
from .seasonal_provider import SeasonRow
from .seasonal_state import SeasonalState
from .seasonal_vm import (
    MISSING_MATERIAL,
    MODE_AI,
    MODE_FREE,
    OTHER_KEY,
    approve_ready_question,
    build_season,
    occasion_choices,
    upcoming_occasions,
    usd_label,
)

TENANT = UUID("a0000000-0000-4000-8000-000000976896")
BRAND = UUID("c0000000-0000-4000-8000-000000976896")


@dataclass
class Row:
    id: UUID
    kind: str
    status: str
    season_key: str = "navidad-2026"
    bytes: int | None = 320 * 1024
    cost_usd: Decimal = Decimal("0")
    fail_reason: str | None = None
    object_key: str | None = "k"


@dataclass
class FakeGateway:
    rows: dict[str, list[Row]] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    archived: set[str] = field(default_factory=set)
    cost: Decimal | None = Decimal("0.048")
    calls: list[tuple[str, Any]] = field(default_factory=list)
    refuse: BaseException | None = None

    def brand(self, tenant_id: UUID) -> UUID:
        return BRAND

    def country(self, tenant_id: UUID) -> str:
        return "CO"

    def seasons(self, tenant_id: UUID, brand_id: UUID) -> list[SeasonRow]:
        return [SeasonRow(k, self.labels[k], k in self.archived) for k in self.rows]

    def season_items(self, tenant_id: UUID, brand_id: UUID, key: str) -> list[Row]:
        return self.rows[key]

    def plan(self, tenant_id, brand_id, key, label, mode, user):  # noqa: ANN001, ANN201
        self.calls.append(("plan", (key, label, mode)))
        if self.refuse:
            raise self.refuse

    def approve(self, tenant_id, brand_id, ids, user):  # noqa: ANN001, ANN201
        self.calls.append(("approve", sorted(str(i) for i in ids)))
        for rows in self.rows.values():
            for r in rows:
                if r.id in ids:
                    r.status = "approved"

    def another(self, tenant_id, brand_id, media_id, user):  # noqa: ANN001, ANN201
        self.calls.append(("another", str(media_id)))

    def archive(self, tenant_id, brand_id, key):  # noqa: ANN001, ANN201
        self.archived.add(key)
        self.calls.append(("archive", key))

    def restore(self, tenant_id, brand_id, key):  # noqa: ANN001, ANN201
        self.archived.discard(key)
        self.calls.append(("restore", key))

    def ai_video_cost_usd(self) -> Decimal | None:
        return self.cost

    def batch_counts(self, mode: str) -> tuple[int, int]:
        return (6, 4)

    def preview_src(self, tenant_id, brand_id, row) -> str:  # noqa: ANN001
        return f"/r2seasonal/{row.id}"

    def acting_user(self, tenant_id: UUID) -> None:
        return None


@pytest.fixture
def gw(monkeypatch: pytest.MonkeyPatch) -> FakeGateway:
    fake = FakeGateway(
        rows={
            "navidad-2026": [
                Row(uuid4(), "sticker", "ready"),
                Row(uuid4(), "sticker", "ready"),
                Row(uuid4(), "video", "pending"),
                Row(uuid4(), "video", "failed", fail_reason="too_large"),
            ]
        },
        labels={"navidad-2026": "Navidad 2026"},
    )
    monkeypatch.setattr(state_module, "gateway", lambda: fake)

    async def tenant(self: SeasonalState) -> UUID:
        return TENANT

    monkeypatch.setattr(SeasonalState, "_tenant", tenant)
    return fake


async def _drain(gen: Any) -> list[Any]:
    return [e async for e in gen]


async def _load(state: SeasonalState) -> None:
    await _drain(SeasonalState.load.fn(state))


# --- words and rules ------------------------------------------------------------------


def test_the_calendar_preselects_the_next_season() -> None:
    nov = date(2026, 11, 8)
    first = upcoming_occasions(nov, "CO", 1)[0]
    assert (first.key, first.label, first.line) == (
        "navidad-2026",
        "Navidad 2026",
        "faltan 6 semanas",
    )
    keys = [o.key for o in occasion_choices(nov, "CO")]
    assert keys[-2:] == ["todo-el-ano", "otra"] and len(keys) == 4
    assert upcoming_occasions(date(2026, 2, 1), "VE", 1)[0].label == "San Valentín 2026"
    assert upcoming_occasions(date(2026, 9, 1), "CO", 1)[0].label == "Amor y Amistad 2026"


def test_money_and_counts() -> None:
    assert usd_label(Decimal("0.048")) == "US$0,05" and usd_label(None) == ""
    assert usd_label(Decimal("0.001")) == "menos de US$0,01"
    assert approve_ready_question(7, "Navidad 2026") == (
        "Vas a aprobar 7 stickers y videos de «Navidad 2026». "
        "Desde ahí los puedes mandar en tus chats."
    )
    season = build_season("k", "Navidad 2026", False, FakeGateway().rows.get("x", []))
    assert season.progress_label == "Navidad 2026"


# --- the flow -----------------------------------------------------------------------------


async def test_three_steps_with_the_defaults_then_create(gw: FakeGateway) -> None:
    state = SeasonalState()
    await _load(state)
    state.open_flow()
    assert (state.flow_step, state.flow_title) == (1, "¿Para qué ocasión?")
    assert state.occasion_key == state.occasions[0].key  # the coming season, chosen
    state.flow_next()
    assert state.flow_title == "¿Cómo lo creamos?" and state.mode == MODE_FREE  # never IA
    assert state.ai_title == "Crear con IA · unos US$0,05 por video"
    state.flow_next()
    assert state.flow_title == "Revisa y crea"
    assert state.review_line.startswith("Vamos a preparar 6 stickers y 4 videos para «")
    assert state.create_label == "Crear"
    state.flow_back()
    state.choose_mode(MODE_AI)
    state.flow_next()
    assert state.create_label == "Crear el video · unos US$0,05"
    events = await _drain(SeasonalState.create.fn(state))
    assert gw.calls[-1] == ("plan", (state.occasions[0].key, state.occasions[0].label, MODE_AI))
    assert not state.flow_open and "Por aprobar" in json.dumps(str(events), ensure_ascii=False)


async def test_ia_is_not_offered_without_a_price(gw: FakeGateway) -> None:
    gw.cost = None
    state = SeasonalState()
    await _load(state)
    state.open_flow()
    state.choose_mode(MODE_AI)
    assert state.mode == MODE_FREE and state.ai_title == "Crear con IA"


async def test_other_occasion_needs_its_name_and_caps_it(gw: FakeGateway) -> None:
    state = SeasonalState()
    await _load(state)
    state.open_flow()
    state.choose_occasion(OTHER_KEY)
    state.flow_next()
    assert state.flow_step == 1 and state.flow_error == "Escribe el nombre de la ocasión."
    state.set_other_name("Aniversario del local y muchas cosas más")
    assert len(state.other_name) == 24 and state.other_count == "24/24"
    state.flow_next()
    assert state.flow_step == 2


async def test_nothing_to_make_shows_both_ways(gw: FakeGateway) -> None:
    gw.refuse = NothingToMake()
    state = SeasonalState()
    await _load(state)
    state.open_flow()
    state.flow_next()
    state.flow_next()
    await _drain(SeasonalState.create.fn(state))
    assert state.flow_open and state.flow_missing and state.flow_error == MISSING_MATERIAL


# --- Por aprobar ---------------------------------------------------------------------------


async def test_nothing_approved_by_default_and_only_ready_can_be(gw: FakeGateway) -> None:
    state = SeasonalState()
    await _load(state)
    season = state.to_review[0]
    assert season.progress_label == "Navidad 2026 · 2 de 4 listos"
    assert not any(i.approved for i in season.pieces) and season.ready_count == 2
    heavy = next(i for i in season.pieces if i.failed)
    assert heavy.heavy and heavy.fail_text == "Salió muy pesado para WhatsApp. Pide otro."
    pending = next(i for i in season.pieces if i.preparing)
    await _drain(SeasonalState.approve.fn(state, pending.id))
    assert gw.calls == []  # a piece still being prepared is never approved

    state.ask_approve_ready("navidad-2026")
    assert state.confirm_question.startswith("Vas a aprobar 2 stickers y videos de «Navidad 2026»")
    await _drain(SeasonalState.approve_ready.fn(state))
    ready = sorted(str(r.id) for r in gw.rows["navidad-2026"][:2])
    assert gw.calls == [("approve", ready)] and state.confirm_season == ""


async def test_another_with_ia_asks_first(gw: FakeGateway) -> None:
    paid = Row(uuid4(), "video", "ready", cost_usd=Decimal("0.05"))
    gw.rows["navidad-2026"].append(paid)
    state = SeasonalState()
    await _load(state)
    await _drain(SeasonalState.another.fn(state, str(paid.id)))
    assert gw.calls == [] and state.confirm_another == str(paid.id)
    assert state.another_question == "Pedir otro cuesta unos US$0,05. ¿Lo creamos?"
    await _drain(SeasonalState.another.fn(state, str(paid.id)))
    assert gw.calls == [("another", str(paid.id))]


async def test_a_late_read_is_dropped(gw: FakeGateway) -> None:
    state = SeasonalState()
    state._gen = 5
    assert await state._refresh(TENANT, 4, quiet=False) is False
    assert state.seasons == [] and not state.loaded


async def test_archive_leaves_the_chat_with_undo(gw: FakeGateway) -> None:
    state = SeasonalState()
    await _load(state)
    events = await _drain(SeasonalState.archive.fn(state, "navidad-2026"))
    text = json.dumps(str(events), ensure_ascii=False)
    assert "«Navidad 2026» ya no aparece en tus chats" in text and "Deshacer" in text
    assert state.archived[0].key == "navidad-2026" and state.library == []
    await _drain(SeasonalState.restore.fn(state, "navidad-2026"))
    assert gw.calls[-1] == ("restore", "navidad-2026") and state.library


def test_logout_resets_it_and_nothing_autoplays() -> None:
    from .auth_state import business_state_classes
    from .creative_pages import drafts_index
    from .seasonal_ui import brand_section

    assert SeasonalState in business_state_classes()
    for rendered in (str(drafts_index()), str(brand_section())):
        assert "autoPlay" not in rendered and "autoplay" not in rendered.lower()
    page = str(brand_section())
    for text in ("Stickers y videos de tu marca", "Crear para esta temporada", "Archivar"):
        assert text in page or json.dumps(text)[1:-1] in page, text


async def test_a_fourth_another_is_refused_in_the_services_words(
    gw: FakeGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qualify_api.whatsapp.seasonal import AttemptsExhausted

    def refuse(*_a: Any) -> None:
        raise AttemptsExhausted()

    monkeypatch.setattr(gw, "another", refuse)
    state = SeasonalState()
    await _load(state)
    failed = next(i for i in state.to_review[0].pieces if i.failed)
    await _drain(SeasonalState.another.fn(state, failed.id))  # «Pedir otro» on a failure
    assert state.action_error == "Ya pediste otro tres veces para esta pieza."
