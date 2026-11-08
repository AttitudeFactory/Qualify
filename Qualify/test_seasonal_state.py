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
PHOTO = UUID("40000000-0000-4000-8000-000000976896")
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
    #: m-24976893: the IA quote (per video, total for 3) or why it is off
    per_video: Decimal = Decimal("0.05")
    ai_off: str = ""
    spent: Decimal = Decimal("0")
    plan_refusals: list[BaseException] = field(default_factory=list)
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

    def plan(  # noqa: ANN201
        self,
        tenant_id,  # noqa: ANN001
        brand_id,  # noqa: ANN001
        key,  # noqa: ANN001
        label,  # noqa: ANN001
        mode,  # noqa: ANN001
        user,  # noqa: ANN001
        accepted_total_usd=None,  # noqa: ANN001
        accepted_draft_ids=None,  # noqa: ANN001
    ):
        self.calls.append(("plan", (key, label, mode)))
        if accepted_total_usd is not None:
            self.calls.append(("accepted_total", accepted_total_usd))
        if accepted_draft_ids is not None:
            self.calls.append(("accepted_drafts", [str(d) for d in accepted_draft_ids]))
        if self.plan_refusals:
            raise self.plan_refusals.pop(0)
        if self.refuse:
            raise self.refuse

    def approve(self, tenant_id, brand_id, ids, user):  # noqa: ANN001, ANN201
        self.calls.append(("approve", sorted(str(i) for i in ids)))
        for rows in self.rows.values():
            for r in rows:
                if r.id in ids:
                    r.status = "approved"

    def another(self, tenant_id, brand_id, media_id, user, accepted_cost_usd=None):  # noqa: ANN001, ANN201
        self.calls.append(("another", str(media_id)))
        if accepted_cost_usd is not None:
            self.calls.append(("accepted_cost", accepted_cost_usd))

    def archive(self, tenant_id, brand_id, key):  # noqa: ANN001, ANN201
        self.archived.add(key)
        self.calls.append(("archive", key))

    def restore(self, tenant_id, brand_id, key):  # noqa: ANN001, ANN201
        self.archived.discard(key)
        self.calls.append(("restore", key))

    #: the photos the quote animates (their draft ids go back to `plan_batch`)
    photo_ids: list[str] = field(default_factory=lambda: [str(uuid4()) for _ in range(3)])

    def ai_quote(self, tenant_id: UUID, brand_id: UUID) -> Any:
        from .seasonal_provider import AiPhoto, AiQuote

        if self.ai_off:
            return AiQuote(unavailable=self.ai_off)
        photos = tuple(
            AiPhoto(id=pid, title=f"Foto {i}", src=f"/r2media/p{i}")
            for i, pid in enumerate(self.photo_ids)
        )
        return AiQuote(
            per_video_usd=self.per_video,
            total_usd=self.per_video * len(photos),
            videos=len(photos),
            photos=photos,
        )

    def month_ai_total(self, tenant_id: UUID, brand_id: UUID) -> Decimal:
        return self.spent

    def ai_video_price(self, tenant_id: UUID, brand_id: UUID) -> Decimal | None:
        """ONE video's price for «Pedir otro»; None while «Con IA» is off."""
        return None if self.ai_off else self.per_video

    def reason_texts(self) -> dict[str, str]:
        """The library's own words (`whatsapp.seasonal.REASON_TEXT`, vendor_expired…)."""
        from qualify_api.whatsapp.seasonal import REASON_TEXT

        return dict(REASON_TEXT)

    def batch_counts(self, mode: str) -> tuple[int, int]:
        return (6, 4)

    def preview_src(self, tenant_id, brand_id, row) -> str:  # noqa: ANN001
        return f"/r2seasonal/{row.id}"

    def acting_user(self, tenant_id: UUID) -> None:
        return None

    calendar_fails: bool = False

    def calendar(self, tenant_id: UUID, n: int = 3) -> tuple[list[Any], date]:
        """The backend's calendar (m-24976896): its names, keys and dates."""
        if self.calendar_fails:
            raise RuntimeError("db down")
        from qualify_api.whatsapp.seasons import next_seasons

        today = date(2026, 10, 10)
        return next_seasons("VE", today, n), today


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
    await SeasonalState.quote_ai.fn(state)  # what `load` chains (the IA quote)


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
    assert upcoming_occasions(date(2026, 10, 1), "VE", 1)[0].label == "Noche de brujas 2026"


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
    events = await _drain(SeasonalState.create.fn(state))
    assert gw.calls[-1] == ("plan", (state.occasions[0].key, state.occasions[0].label, MODE_FREE))
    assert not state.flow_open and "Por aprobar" in json.dumps(str(events), ensure_ascii=False)


async def test_ia_off_by_config_says_so_and_cannot_be_chosen(gw: FakeGateway) -> None:
    gw.ai_off = "Pronto podrás crear videos con inteligencia artificial."
    state = SeasonalState()
    await _load(state)
    state.open_flow()
    await SeasonalState.quote_ai.fn(state)
    state.choose_mode(MODE_AI)
    assert state.mode == MODE_FREE and not state.ai_ready
    assert state.ai_unavailable == "Pronto podrás crear videos con inteligencia artificial."


async def test_ia_shows_the_photos_and_passes_the_confirmed_total(gw: FakeGateway) -> None:
    state = SeasonalState()
    await _load(state)
    state.open_flow()
    await SeasonalState.quote_ai.fn(state)
    state.flow_next()
    state.choose_mode(MODE_AI)
    assert state.mode == MODE_AI and state.flow_can_next
    state.flow_next()
    assert state.flow_title == "¿Qué fotos animamos?"
    assert [p.title for p in state.ai_photos] == ["Foto 0", "Foto 1", "Foto 2"]
    assert state.ai_photos_line == "Elegimos tus 3 fotos aprobadas más recientes."
    assert state.ai_total_line == "Total: unos US$0,15"
    assert state.create_label == "Crear los videos · unos US$0,15"
    await _drain(SeasonalState.create.fn(state))
    assert ("accepted_total", Decimal("0.15")) in gw.calls and not state.flow_open
    assert ("accepted_drafts", gw.photo_ids) in gw.calls  # exactly the photos shown


async def test_changed_photos_requote_and_show_the_new_ones(gw: FakeGateway) -> None:
    from qualify_api.whatsapp.seasonal import SelectionChanged

    state = SeasonalState()
    await _load(state)
    state.open_flow()
    await SeasonalState.quote_ai.fn(state)
    state.flow_next()
    state.choose_mode(MODE_AI)
    state.flow_next()
    gw.plan_refusals = [SelectionChanged()]
    gw.photo_ids = [str(uuid4()), str(uuid4())]  # a piece was unapproved meanwhile
    await _drain(SeasonalState.create.fn(state))
    assert state.flow_open and state.flow_error == (
        "Tus fotos aprobadas cambiaron: ahora animaríamos estas. ¿Seguimos?"
    )
    assert [p.id for p in state.ai_photos] == gw.photo_ids
    assert state.ai_photos_line == "Elegimos tus 2 fotos aprobadas más recientes."
    await _drain(SeasonalState.create.fn(state))
    assert gw.calls[-1] == ("accepted_drafts", gw.photo_ids)


async def test_a_price_change_requotes_and_asks_again(gw: FakeGateway) -> None:
    from qualify_api.whatsapp.seasonal import CostNotConfirmed

    state = SeasonalState()
    await _load(state)
    state.open_flow()
    await SeasonalState.quote_ai.fn(state)
    state.flow_next()
    state.choose_mode(MODE_AI)
    state.flow_next()
    gw.plan_refusals = [CostNotConfirmed()]
    gw.per_video = Decimal("0.06")  # the price moved meanwhile
    await _drain(SeasonalState.create.fn(state))
    assert state.flow_open
    assert state.flow_error == "El precio cambió: ahora son unos US$0,18. ¿Seguimos?"
    assert state.create_label == "Crear los videos · unos US$0,18"
    await _drain(SeasonalState.create.fn(state))
    assert ("accepted_total", Decimal("0.18")) in gw.calls[-2:] and not state.flow_open


async def test_no_photo_to_animate_is_said(gw: FakeGateway) -> None:
    from qualify_api.whatsapp.seasonal import NoPhotoToAnimate

    gw.ai_off = NoPhotoToAnimate().message
    state = SeasonalState()
    await _load(state)
    assert state.ai_unavailable == "Para crear videos con IA necesitas al menos una foto aprobada."


async def test_budget_cap_and_the_month_spend(gw: FakeGateway) -> None:
    gw.spent = Decimal("0.45")
    gw.rows["navidad-2026"].append(
        Row(uuid4(), "video", "failed", fail_reason="budget_cap", cost_usd=Decimal("0"))
    )
    state = SeasonalState()
    await _load(state)
    assert state.month_spend == "Este mes llevas US$0,45 en videos con IA."
    capped = [i for i in state.to_review[0].pieces if i.fail_text.startswith("Esta pieza")]
    assert capped[0].fail_text == "Esta pieza superaría tu tope de gasto."
    gw.spent = Decimal("0")
    await _load(state)
    assert state.month_spend == ""


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
    # the library's own words for `too_large` (REASON_TEXT) win over ours
    assert heavy.heavy and heavy.fail_text == "Salió muy pesado para WhatsApp. Puedes pedir otro."
    pending = next(i for i in season.pieces if i.preparing)
    assert pending.size_label == ""  # no weight while it is prepared
    await _drain(SeasonalState.approve.fn(state, pending.id))
    assert gw.calls == []  # a piece still being prepared is never approved

    state.ask_approve_ready("navidad-2026")
    assert state.confirm_question.startswith("Vas a aprobar 2 stickers y videos de «Navidad 2026»")
    # a refresh while the question is open brings a third ready piece: it is NOT approved
    gw.rows["navidad-2026"][2].status = "ready"
    await state._refresh(TENANT, state._gen, quiet=True)
    await _drain(SeasonalState.approve_ready.fn(state))
    ready = sorted(str(r.id) for r in gw.rows["navidad-2026"][:2])
    assert gw.calls == [("approve", ready)] and state.confirm_season == ""


async def test_another_with_ia_asks_first_and_passes_its_cost(gw: FakeGateway) -> None:
    paid = Row(uuid4(), "video", "ready")
    paid.recipe = "ai-seedance"  # type: ignore[attr-defined]
    gw.rows["navidad-2026"].append(paid)
    state = SeasonalState()
    await _load(state)
    await _drain(SeasonalState.another.fn(state, str(paid.id)))
    assert gw.calls == [] and state.confirm_another == str(paid.id)
    assert state.another_question == "Pedir otro cuesta unos US$0,05. ¿Lo creamos?"
    await _drain(SeasonalState.another.fn(state, str(paid.id)))
    assert gw.calls == [("another", str(paid.id)), ("accepted_cost", Decimal("0.05"))]


async def test_the_redo_price_does_not_depend_on_the_batch_quote(gw: FakeGateway) -> None:
    """Review of 61115356: no photo left to animate (the batch quote is off) still lets
    «Pedir otro» on an IA video say its price; with «Con IA» off it is not offered."""
    from qualify_api.whatsapp.seasonal import NoPhotoToAnimate

    paid = Row(uuid4(), "video", "failed", fail_reason="vendor_expired")
    paid.recipe = "ai-seedance"  # type: ignore[attr-defined]
    gw.rows["navidad-2026"].append(paid)
    state = SeasonalState()
    await _load(state)
    item = next(i for i in state.to_review[0].pieces if i.id == str(paid.id))
    assert item.fail_text == "La IA no alcanzó a crear el video y no se cobró. Puedes pedir otro."
    gw_quote_off = NoPhotoToAnimate().message
    state.ai_unavailable = gw_quote_off  # the batch quote says no photo
    assert state.ai_redo_cost == "US$0,05"
    await _drain(SeasonalState.another.fn(state, str(paid.id)))
    assert state.another_question == "Pedir otro cuesta unos US$0,05. ¿Lo creamos?"

    gw.ai_off = "Pronto podrás crear videos con inteligencia artificial."
    await _load(state)
    assert state.ai_redo_cost == ""
    state.cancel_confirm()
    await _drain(SeasonalState.another.fn(state, str(paid.id)))
    assert state.confirm_another == "" and gw.calls == []  # not offered, nothing called


async def test_a_quote_that_lands_after_a_business_switch_is_dropped(
    gw: FakeGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = SeasonalState()
    await _load(state)
    state.ai_photos, state._ai_total_usd = [], ""
    real = gw.ai_quote

    def slow_quote(tenant_id: UUID, brand_id: UUID) -> Any:
        state._brand = str(uuid4())  # the owner switched business while it was read
        return real(tenant_id, brand_id)

    monkeypatch.setattr(gw, "ai_quote", slow_quote)
    await SeasonalState.quote_ai.fn(state)
    assert state.ai_photos == [] and state._ai_total_usd == "" and not state.ai_quoting


async def test_two_quotes_never_overlap(gw: FakeGateway) -> None:
    state = SeasonalState()
    await _load(state)
    calls: list[int] = []
    real = gw.ai_quote

    def counted(tenant_id: UUID, brand_id: UUID) -> Any:
        calls.append(1)
        return real(tenant_id, brand_id)

    gw.ai_quote = counted  # type: ignore[method-assign]
    state.ai_quoting = True  # one is in flight (the flow's, or the re-quote in «Crear»)
    await SeasonalState.quote_ai.fn(state)
    assert calls == []


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


async def test_two_quick_taps_on_another_call_once(gw: FakeGateway) -> None:
    import asyncio

    state = SeasonalState()
    await _load(state)
    ready = state.to_review[0].pieces[0]
    await asyncio.gather(
        _drain(SeasonalState.another.fn(state, ready.id)),
        _drain(SeasonalState.another.fn(state, ready.id)),
    )
    assert [c for c in gw.calls if c[0] == "another"] == [("another", ready.id)]


async def test_ia_off_and_its_backend_words(gw: FakeGateway) -> None:
    class ModeNotAvailable(Exception):
        message = "Pronto podrás crear videos con inteligencia artificial."

    gw.refuse = ModeNotAvailable()
    state = SeasonalState()
    await _load(state)
    state.open_flow()
    state.flow_step = 3
    state.mode = MODE_AI  # forced: if it ever reaches the backend, its words show
    await _drain(SeasonalState.create.fn(state))
    assert state.flow_error == "Pronto podrás crear videos con inteligencia artificial."


def test_the_production_gateway_signs_previews_for_this_business(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review of f205f48b: the PRODUCTION class, with the real signature, reaches the
    business-bound signer (never the generic `r2_media` one)."""
    import inspect

    from . import seasonal_media
    from .seasonal_provider import ProductionSeasonalGateway, SeasonalGateway

    calls: list[tuple[Any, ...]] = []

    def issue(tenant: UUID, brand: UUID, key: str, **_k: Any) -> str:
        calls.append((tenant, brand, key))
        return "/r2seasonal/t"

    monkeypatch.setattr(seasonal_media, "issue_seasonal_view_path", issue)
    row = Row(uuid4(), "sticker", "ready", object_key="seasonal/x.webp")
    assert ProductionSeasonalGateway().preview_src(TENANT, BRAND, row) == "/r2seasonal/t"
    assert calls == [(TENANT, BRAND, "seasonal/x.webp")]
    for name, member in inspect.getmembers(SeasonalGateway, inspect.isfunction):
        if name.startswith("_"):
            continue
        real = getattr(ProductionSeasonalGateway, name)
        assert inspect.signature(real) == inspect.signature(member), name


async def test_step_one_comes_from_the_backend_calendar(gw: FakeGateway) -> None:
    state = SeasonalState()
    await _load(state)
    state.open_flow()
    first = state.occasions[0]
    assert first.label == "Noche de brujas 2026" and first.line == "faltan 3 semanas"
    assert state.occasion_key == first.key  # the next season, preselected
    assert [o.key for o in state.occasions][-2:] == ["todo-el-ano", "otra"]


async def test_the_client_list_only_when_the_calendar_read_fails(gw: FakeGateway) -> None:
    gw.calendar_fails = True
    state = SeasonalState()
    await _load(state)
    assert not state._calendar_ok and state.error == ""  # the screen still works
    state.open_flow()
    assert state.occasions[0].key == upcoming_occasions(date.today(), "CO", 1)[0].key


async def test_the_week_notice_opens_the_flow_on_its_season(
    gw: FakeGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace
    from unittest.mock import PropertyMock, patch

    state = SeasonalState()
    await _load(state)
    key = state.calendar[1].key
    router = SimpleNamespace(
        url=SimpleNamespace(query_parameters={"crear": "temporada", "temporada": key})
    )
    with patch.object(SeasonalState, "router", new_callable=PropertyMock, return_value=router):
        state.open_from_query()
    assert state.flow_open and state.occasion_key == key and state.flow_step == 2


async def test_a_transient_calendar_failure_keeps_the_last_good_one(gw: FakeGateway) -> None:
    state = SeasonalState()
    await _load(state)
    good = list(state.calendar)
    assert state._calendar_ok and good
    gw.calendar_fails = True
    await state._refresh(TENANT, state._gen, quiet=True)  # the 5 s refresh
    assert state._calendar_ok and state.calendar == good
    state.open_flow()
    assert state.occasions[0].label == "Noche de brujas 2026"  # still the backend's


def test_the_production_gateway_quotes_and_passes_the_confirmed_amounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """m-24976893 through the PRODUCTION class over a fake service: the quote is the
    backend's, `ModeNotAvailable` comes back in its words, and the confirmed total / cost
    reach `plan_batch` / `request_another` untouched."""
    from qualify_api.whatsapp.seasonal import BatchQuote, ModeNotAvailable, QuotedPhoto

    from .seasonal_provider import ProductionSeasonalGateway

    class Service:
        def __init__(self) -> None:
            self.calls: list[tuple[str, Any]] = []
            self.off = False

        def quote_batch(self, tenant_id: UUID, brand_id: UUID, mode: str) -> BatchQuote:
            if self.off:
                raise ModeNotAvailable()
            return BatchQuote(
                mode,
                6,
                4,
                3,
                Decimal("0.05"),
                Decimal("0.15"),
                photos=(QuotedPhoto(PHOTO, "Shawarma mixto", f"t/{TENANT}/pieces/{PHOTO}/0.jpg"),),
            )

        def plan_batch(self, **kw: Any) -> list[Any]:
            self.calls.append(
                ("plan", kw["mode"], kw["accepted_total_usd"], kw["accepted_draft_ids"])
            )
            return []

        def request_another(self, **kw: Any) -> Any:
            self.calls.append(("another", kw["accepted_cost_usd"]))

        def ai_video_price_usd(self) -> Decimal:
            if self.off:
                raise ModeNotAvailable()
            return Decimal("0.05")

    service = Service()
    gw = ProductionSeasonalGateway(service)
    # the real `r2_media` signer over an in-memory Redis: a `t/{tenant}/…` thumbnail key
    from qualify_api.publishing.media_token import MediaTokenStore

    from . import r2_media

    class Redis:
        def __init__(self) -> None:
            self.data: dict[str, str] = {}

        def set(self, name: str, value: str, *, ex: int | None = None) -> bool:
            self.data[name] = value
            return True

        def get(self, name: str) -> str | None:
            return self.data.get(name)

    monkeypatch.setattr(r2_media, "_token_store", lambda: MediaTokenStore(Redis()))
    quote = gw.ai_quote(TENANT, BRAND)
    assert (quote.per_video_usd, quote.total_usd, quote.videos) == (
        Decimal("0.05"),
        Decimal("0.15"),
        3,
    )
    assert [(p.id, p.title) for p in quote.photos] == [(str(PHOTO), "Shawarma mixto")]
    assert quote.photos[0].src.startswith("/r2media/")  # signed through the token store
    assert gw.ai_video_price(TENANT, BRAND) == Decimal("0.05")
    service.off = True
    assert gw.ai_quote(TENANT, BRAND).unavailable == (
        "Pronto podrás crear videos con inteligencia artificial."
    )
    gw.plan(TENANT, BRAND, "navidad-2026", "Navidad 2026", "ai", None, Decimal("0.15"), [PHOTO])
    gw.another(TENANT, BRAND, uuid4(), None, Decimal("0.05"))
    assert service.calls == [
        ("plan", "ai", Decimal("0.15"), [PHOTO]),
        ("another", Decimal("0.05")),
    ]
    assert gw.reason_texts()["budget_cap"] == "Esta pieza superaría tu tope de gasto."
