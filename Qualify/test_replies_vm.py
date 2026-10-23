"""Tests for `replies_vm` and `replies_provider.pending_drafts` (m-24789645, Fase B PR 3):
the reason → Spanish mapping, the sources (never a price), the intent chips, the
needs-review send gate and the «Regenerar» error copy. Offline: no Reflex app, no DB."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from qualify_api.intent import IntentClass, IntentSignal
from qualify_api.replies.repository import DraftRecord
from qualify_api.replies.service import RegenerationRefused, UnknownDraft

from . import replies_provider
from . import replies_vm as vm

_ZONE = ZoneInfo("America/Bogota")
_CREATED = datetime(2026, 10, 23, 19, 30, tzinfo=UTC)

#: Every code `qualify_api.replies.public_drafts.review_reasons` can record.
_ALL_CODES = (
    "model_unsupported",
    "price_token",
    "empty_catalog",
    "price_unknown",
    *(f"unvalidated:{c}" for c in ("availability", "store", "location", "hours")),
    *(f"unreliable:{c.value}" for c in IntentClass if c is not IntentClass.GENERAL),
)


def _record(
    *,
    grounding: dict[str, Any] | None = None,
    needs_review: bool = False,
    unsupported_claims: tuple[str, ...] = (),
    sentiment_label: str = "POS",
    message_id: UUID | None = None,
) -> DraftRecord:
    return DraftRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        connection_id=uuid4(),
        message_id=message_id or uuid4(),
        source_id="1789",
        sentiment_result_id=None,
        sentiment_label=sentiment_label,
        gate_reason="ok",
        generator_version="m24789645.1:claude-haiku-5-5",
        generated_text="¡Hola! Te escribimos por mensaje privado.",
        final_text=None,
        status="proposed",
        comment_text="¿Cuánto cuesta el combo?",
        created_at=_CREATED,
        decided_at=None,
        decided_by_user_id=None,
        sent_at=None,
        external_reply_id=None,
        send_error_code=None,
        settled_at=None,
        grounding=grounding,
        needs_review=needs_review,
        unsupported_claims=unsupported_claims,
        cost_usd=Decimal("0.0012") if grounding is not None else None,
    )


def _product(name: str, updated_at: str | None = "2026-10-12T15:00:00+00:00") -> dict[str, Any]:
    return {
        "product_id": str(uuid4()),
        "name": name,
        "price": "$12.000",
        "price_amount": "12000",
        "currency": "COP",
        "category": "Combos",
        "updated_at": updated_at,
    }


def _signal(message_id: UUID, classes: dict[IntentClass, float]) -> IntentSignal:
    return IntentSignal(
        comment_id=message_id,
        source_id="1789",
        classes=classes,
        detector_version="d1",
        pipeline_version="p1",
        model_id="claude-haiku-5-5",
    )


# -- reason → Spanish ---------------------------------------------------------------------


@pytest.mark.parametrize("code", _ALL_CODES)
def test_every_known_reason_has_its_own_plain_spanish_line(code: str) -> None:
    label = vm.review_reason_label(code)
    assert label and label != vm.REVIEW_REASON_FALLBACK
    assert code not in label
    # No internal vocabulary or English reaches the owner.
    assert not re.search(r"\b(token|model|catalog|unreliable|unvalidated|DM|price)\b", label)


def test_price_token_says_no_prices_in_public() -> None:
    label = vm.review_reason_label("price_token")
    assert "menciona un precio" in label and "en público no damos precios" in label
    # It says what to do next.
    assert "«Editar»" in label and "«Regenerar»" in label


@pytest.mark.parametrize(
    ("created", "expected"),
    [
        (0, "Revisamos tus comentarios: no hay ninguno nuevo que responder."),
        (1, "Listo: 1 respuesta nueva para revisar."),
        (4, "Listo: 4 respuestas nuevas para revisar."),
    ],
)
def test_generation_toast_says_what_is_waiting(created: int, expected: str) -> None:
    assert vm.generation_message(created) == expected


def test_unreliable_reason_names_the_class_in_spanish() -> None:
    assert "«precio»" in vm.review_reason_label("unreliable:price")
    assert "«otra consulta comercial»" in vm.review_reason_label("unreliable:other_commercial")


@pytest.mark.parametrize(
    "code",
    ["", "   ", "something_new", "unvalidated:", "unvalidated:teleport", "unreliable:x", "a:b"],
)
def test_unknown_codes_fall_back_gracefully(code: str) -> None:
    assert vm.review_reason_label(code) == vm.REVIEW_REASON_FALLBACK


def test_unvalidated_class_known_to_intent_but_not_listed_still_reads_well() -> None:
    label = vm.review_reason_label("unvalidated:variants")
    assert label.startswith("Preguntan por variantes")


def test_reason_labels_keep_order_and_drop_repeats() -> None:
    labels = vm.review_reason_labels(["price_token", "weird", "price_token", "other"])
    assert labels == [
        vm.review_reason_label("price_token"),
        vm.REVIEW_REASON_FALLBACK,
    ]


# -- the card's view model ----------------------------------------------------------------


def test_a_sentiment_era_draft_keeps_its_old_shape() -> None:
    draft = vm.build_draft_vm(_record(), zone=_ZONE)
    assert draft.is_commercial is False
    assert draft.needs_review is False
    assert draft.review_reasons == []
    assert draft.sources_count == 0 and draft.sources_head == [] and draft.sources_rest == []
    assert draft.intent_chips == []
    assert draft.sentiment_label == "POS"
    assert draft.source_id == "1789"


def test_dates_are_spanish_in_the_tenant_zone() -> None:
    draft = vm.build_draft_vm(_record(), zone=_ZONE)
    assert draft.created_at == "23 oct 2026, 14:30"


def test_sources_show_name_and_update_date_but_never_a_price() -> None:
    grounding = {
        "business_name": "Bianki",
        "products": [_product("Combo Vecino"), _product("Shawarma mixto", None)],
        "prices_withheld": True,
        "review_reasons": [],
    }
    draft = vm.build_draft_vm(_record(grounding=grounding), zone=_ZONE)
    assert draft.is_commercial is True
    assert [s.name for s in draft.sources_head] == ["Combo Vecino", "Shawarma mixto"]
    assert draft.sources_head[0].updated_label == "actualizado el 12 oct 2026"
    assert draft.sources_head[1].updated_label == ""
    rendered = repr(draft)
    assert "12.000" not in rendered and "12000" not in rendered and "COP" not in rendered


def test_long_source_lists_fold_after_three() -> None:
    names = [f"Producto {i}" for i in range(5)]
    grounding = {"products": [_product(n) for n in names], "review_reasons": []}
    draft = vm.build_draft_vm(_record(grounding=grounding), zone=_ZONE)
    assert draft.sources_count == 5
    assert [s.name for s in draft.sources_head] == names[:3]
    assert [s.name for s in draft.sources_rest] == names[3:]
    assert draft.sources_more_label == "Ver 2 productos más"


def test_one_extra_source_is_singular() -> None:
    grounding = {"products": [_product(f"P{i}") for i in range(4)], "review_reasons": []}
    assert vm.build_draft_vm(_record(grounding=grounding), zone=_ZONE).sources_more_label == (
        "Ver 1 producto más"
    )


def test_old_or_malformed_grounding_records_still_render() -> None:
    grounding = {"products": [{"name": "Gorra"}, {"name": "  "}, {}], "review_reasons": "x"}
    draft = vm.build_draft_vm(_record(grounding=grounding), zone=_ZONE)
    assert [s.name for s in draft.sources_head] == ["Gorra"]
    assert draft.review_reasons == []


def test_needs_review_shows_every_reason_and_the_unsupported_claims() -> None:
    grounding = {"products": [], "review_reasons": ["model_unsupported", "empty_catalog"]}
    draft = vm.build_draft_vm(
        _record(grounding=grounding, needs_review=True, unsupported_claims=("Envío gratis", " ")),
        zone=_ZONE,
    )
    assert draft.needs_review is True
    assert draft.review_reasons == [
        vm.review_reason_label("model_unsupported"),
        vm.review_reason_label("empty_catalog"),
    ]
    assert draft.unsupported_claims == vm.UNSUPPORTED_PREFIX + "Envío gratis"


def test_needs_review_without_a_recorded_reason_still_explains_itself() -> None:
    draft = vm.build_draft_vm(_record(grounding={"products": []}, needs_review=True), zone=_ZONE)
    assert draft.review_reasons == [vm.REVIEW_REASON_FALLBACK]


def test_a_recorded_reason_forces_review_even_without_the_flag() -> None:
    grounding = {"products": [], "review_reasons": ["price_token"]}
    draft = vm.build_draft_vm(_record(grounding=grounding, needs_review=False), zone=_ZONE)
    assert draft.needs_review is True


def test_commercial_drafts_get_intent_chips_with_reliability() -> None:
    message_id = uuid4()
    signal = _signal(message_id, {IntentClass.PRICE: 0.9, IntentClass.HOURS: 0.6})
    draft = vm.build_draft_vm(
        _record(grounding={"products": []}, message_id=message_id),
        zone=_ZONE,
        signal=signal,
        reliable={IntentClass.PRICE: True},
    )
    assert [(c.label, c.commercial, c.reliable) for c in draft.intent_chips] == [
        ("Precio", True, True),
        ("Horario", True, False),
    ]


def test_sentiment_era_drafts_never_get_chips() -> None:
    message_id = uuid4()
    signal = _signal(message_id, {IntentClass.PRICE: 0.9})
    draft = vm.build_draft_vm(_record(message_id=message_id), zone=_ZONE, signal=signal)
    assert draft.intent_chips == []


# -- the needs-review send gate -----------------------------------------------------------


def _vm(*, needs_review: bool) -> vm.DraftVM:
    grounding = {"products": [], "review_reasons": ["price_token"] if needs_review else []}
    return vm.build_draft_vm(_record(grounding=grounding, needs_review=needs_review), zone=_ZONE)


def test_a_draft_that_needs_review_is_not_sent_until_ticked() -> None:
    draft = _vm(needs_review=True)
    assert vm.send_block_reason([draft], draft.id, []) == vm.REVIEW_CONFIRM_REQUIRED
    assert vm.send_block_reason([draft], draft.id, ["another-draft"]) == (
        vm.REVIEW_CONFIRM_REQUIRED
    )
    assert vm.send_block_reason([draft], draft.id, [draft.id]) == ""


def test_a_clean_draft_needs_no_tick() -> None:
    draft = _vm(needs_review=False)
    assert vm.send_block_reason([draft], draft.id, []) == ""


def test_a_draft_no_longer_on_screen_is_refused() -> None:
    assert vm.send_block_reason([_vm(needs_review=False)], "gone", []) == vm.STALE_DRAFT


# -- «Regenerar» errors --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (RegenerationRefused("the comment is no longer available on Instagram"), "Instagram"),
        (
            RegenerationRefused(
                "a person already approved a private message (Fase C followup) for this "
                "comment — it is answered by DM, not publicly"
            ),
            "mensaje privado",
        ),
        (RegenerationRefused("draft x was decided meanwhile"), "ya se envió o se descartó"),
        (RegenerationRefused("sentiment 'NEG' is not 'POS' and no current"), "ya no necesita"),
        (UnknownDraft("x"), "Ya no encontramos"),
        (ValueError("draft x is 'sent'; only 'proposed' regenerates"), "ya se envió"),
        (RuntimeError("boom"), "Intenta de nuevo"),
    ],
)
def test_regenerate_errors_tell_the_owner_what_to_do(exc: Exception, expected: str) -> None:
    message = vm.regenerate_error_message(exc)
    assert expected in message
    # Never the internal reason or an English word from it.
    assert not re.search(r"\b(draft|comment|sentiment|proposed|POS|DM)\b", message)


# -- provider: the queue ------------------------------------------------------------------


def test_pending_drafts_reads_signals_only_for_commercial_drafts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commercial_msg = uuid4()
    old = _record()
    commercial = _record(grounding={"products": [_product("Combo")]}, message_id=commercial_msg)
    asked: list[list[UUID]] = []

    def fake_signals(*, tenant_id: UUID, message_ids: list[UUID]) -> dict[UUID, IntentSignal]:
        asked.append(list(message_ids))
        return {commercial_msg: _signal(commercial_msg, {IntentClass.PRODUCT: 0.8})}

    monkeypatch.setattr(replies_provider, "_list_pending_drafts", lambda **_: (old, commercial))
    monkeypatch.setattr(replies_provider, "_current_signals", fake_signals)
    monkeypatch.setattr(
        replies_provider, "class_reliability", lambda _v: {IntentClass.PRODUCT: True}
    )
    monkeypatch.setattr(replies_provider, "_tenant_zone", lambda _t: _ZONE)

    drafts = replies_provider.pending_drafts(tenant_id=uuid4(), connection_id=uuid4())

    assert asked == [[commercial_msg]]
    assert drafts[0].intent_chips == [] and drafts[0].is_commercial is False
    assert [(c.label, c.reliable) for c in drafts[1].intent_chips] == [("Producto", True)]


def test_pending_drafts_without_commercial_drafts_skips_the_intent_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(**_: object) -> dict[UUID, IntentSignal]:
        raise AssertionError("no commercial draft, no intent read")

    monkeypatch.setattr(replies_provider, "_list_pending_drafts", lambda **_: (_record(),))
    monkeypatch.setattr(replies_provider, "_current_signals", boom)
    monkeypatch.setattr(replies_provider, "_tenant_zone", lambda _t: _ZONE)

    drafts = replies_provider.pending_drafts(tenant_id=uuid4(), connection_id=uuid4())
    assert len(drafts) == 1


def test_regenerate_draft_passes_the_acting_user_and_returns_the_new_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    new = _record(grounding={"products": []})
    calls: list[dict[str, UUID]] = []

    def fake(**kwargs: UUID) -> DraftRecord:
        calls.append(kwargs)
        return new

    monkeypatch.setattr(replies_provider, "_regenerate_draft", fake)
    tenant, draft, user = uuid4(), uuid4(), uuid4()
    assert replies_provider.regenerate_draft(tenant_id=tenant, draft_id=draft, user_id=user) == (
        str(new.id)
    )
    assert calls == [{"tenant_id": tenant, "draft_id": draft, "user_id": user}]
