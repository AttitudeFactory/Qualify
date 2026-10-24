"""ATENDER-4b (m-24848533) on the screen: a draft for a question or a complaint says what
it answers, a complaint asks «Revísala antes de aprobar» and unlocks by a tick OR by an
edit, the comment card can find its own draft, and every «Responder aquí» refusal is
said in the owner's words. Offline: no Reflex app, no DB."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from qualify_api.replies.repository import DraftRecord
from qualify_api.replies.service import RegenerationRefused

from . import replies_state
from . import replies_vm as vm

_ZONE = ZoneInfo("America/Bogota")
_CREATED = datetime(2026, 10, 23, 19, 30, tzinfo=UTC)
_TEXT = "Lamentamos lo que pasó. Escríbenos por mensaje privado y lo revisamos contigo."


def _record(*, kind: str | None, reasons: list[str], message_id: UUID | None = None) -> DraftRecord:
    grounding: dict[str, Any] = {
        "business_name": "Polette",
        "products": [],
        "prices_withheld": True,
        "review_reasons": reasons,
    }
    if kind is not None:
        grounding["triage"] = {
            "kind": kind,
            "sentiment": "neg",
            "needs_reply": True,
            "model_id": "claude-haiku-5-5",
            "prompt_version": "atender4a.1",
            "cost_usd": 0.00002,
        }
    return DraftRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        connection_id=uuid4(),
        message_id=message_id or uuid4(),
        source_id="1789",
        sentiment_result_id=None,
        sentiment_label="NEG",
        gate_reason="ok",
        generator_version="atender4a.2:claude-haiku-5-5",
        generated_text=_TEXT,
        final_text=None,
        status="proposed",
        comment_text="llegó frío el pedido",
        created_at=_CREATED,
        decided_at=None,
        decided_by_user_id=None,
        sent_at=None,
        external_reply_id=None,
        send_error_code=None,
        settled_at=None,
        grounding=grounding,
        needs_review=bool(reasons),
        cost_usd=Decimal("0.0002"),
    )


def test_a_complaint_draft_says_queja_and_needs_review() -> None:
    message_id = uuid4()
    draft = vm.build_draft_vm(
        _record(kind="complaint", reasons=["complaint"], message_id=message_id), zone=_ZONE
    )
    assert draft.comment_kind == "complaint" and draft.comment_kind_label == "Queja"
    # Grounded, but not a sale: no «Quiere comprar», no catalog block.
    assert draft.is_commercial is False
    assert draft.needs_review is True
    assert draft.review_reasons == [vm.COMPLAINT_REVIEW_LABEL]
    assert draft.review_by_edit_ok is True
    assert draft.message_id == str(message_id)


@pytest.mark.parametrize(("kind", "label"), [("question", "Pregunta"), ("praise", "Te felicita")])
def test_questions_and_praise_say_what_they_answer(kind: str, label: str) -> None:
    draft = vm.build_draft_vm(_record(kind=kind, reasons=[]), zone=_ZONE)
    assert draft.comment_kind_label == label
    assert draft.needs_review is False and draft.review_by_edit_ok is False


def test_a_commercial_draft_is_unchanged() -> None:
    draft = vm.build_draft_vm(_record(kind=None, reasons=[]), zone=_ZONE)
    assert draft.is_commercial is True and draft.comment_kind_label == ""


def test_a_complaint_goes_after_a_tick_or_an_edit_but_not_untouched() -> None:
    draft = vm.build_draft_vm(_record(kind="complaint", reasons=["complaint"]), zone=_ZONE)
    blocked = vm.send_block_reason([draft], draft.id, [])
    assert blocked == vm.REVIEW_CONFIRM_REQUIRED
    # Opening «Editar» and sending it untouched (or only re-spaced) is not a review.
    assert vm.send_block_reason([draft], draft.id, [], edited_text="  " + _TEXT + " ") == blocked
    assert vm.send_block_reason([draft], draft.id, [draft.id]) == ""
    edited = "Qué pena lo del pedido. Escríbenos por mensaje privado y lo vemos."
    assert vm.send_block_reason([draft], draft.id, [], edited_text=edited) == ""


def test_an_edit_does_not_clear_other_blocking_reasons() -> None:
    draft = vm.build_draft_vm(
        _record(kind="complaint", reasons=["complaint", "price_token"]), zone=_ZONE
    )
    assert draft.review_by_edit_ok is False
    assert (
        vm.send_block_reason([draft], draft.id, [], edited_text="otro texto")
        == vm.REVIEW_CONFIRM_REQUIRED
    )


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("the comment is no longer available on Instagram", "ya no está en Instagram"),
        ("a person already approved a private message (Fase C followup)", "mensaje privado"),
        ("triage says 'complaint' but ... run «Ordenar por prioridad» first", "Intenta de nuevo"),
        ("sentiment 'NEG' is not 'POS' and no current commercial intent", "Escríbele en privado"),
    ],
)
def test_reply_here_refusals_are_in_the_owners_words(reason: str, expected: str) -> None:
    message = vm.reply_here_error_message(RegenerationRefused(reason))
    assert expected in message
    assert not re.search(r"\b(POS|NEG|triage|gate|intent|DM|post)\b", message)


def test_reply_here_unexpected_failure_says_try_again() -> None:
    assert "Intenta de nuevo" in vm.reply_here_error_message(RuntimeError("boom"))


def test_new_copy_never_says_qualify_sends_on_its_own() -> None:
    for text in (
        vm.COMPLAINT_REVIEW_LABEL,
        vm.REPLY_HERE_LABEL,
        vm.REPLY_HERE_READY,
        *vm.COMMENT_KIND_LABELS.values(),
    ):
        assert not re.search(r"\b(post|feed|lead|engagement|autom[aá]tic)", text, re.I)
        assert "enviamos" not in text.lower() and "respondemos" not in text.lower()


def test_the_state_lists_the_comments_with_a_waiting_draft() -> None:
    drafts = [vm.build_draft_vm(_record(kind="question", reasons=[]), zone=_ZONE) for _ in range(2)]
    state_cls = replies_state.RepliesState
    computed = state_cls.computed_vars["draft_message_ids"]
    fake = type("S", (), {"drafts": drafts})()
    assert computed.fget(fake) == [d.message_id for d in drafts]


def test_reply_here_never_sends_the_owner_to_sort_first() -> None:
    message = vm.reply_here_error_message(
        RegenerationRefused("triage says 'question' but ... run «Ordenar por prioridad» first")
    )
    assert "Ordenar" not in message


def test_an_other_comment_gets_no_kind_label_so_the_tone_shows() -> None:
    assert "other" not in vm.COMMENT_KIND_LABELS
    assert vm.build_draft_vm(_record(kind="other", reasons=[]), zone=_ZONE).comment_kind_label == ""


def test_the_complaint_note_does_not_promise_what_the_draft_says() -> None:
    assert "no promete nada" not in vm.COMPLAINT_REVIEW_LABEL
    assert "Fíjate que no prometa nada" in vm.COMPLAINT_REVIEW_LABEL


def _analyzed(label: str | None) -> Any:
    from qualify_api.sentiment.repository import AnalyzedComment

    return AnalyzedComment(
        message_id=uuid4(),
        source_id="1789",
        text="¿abren el domingo?",
        author_username="ana",
        posted_at=_CREATED,
        external_thread_id="t",
        label=label,
        score=0.9 if label else None,
    )


def test_reply_here_shows_only_where_it_can_deliver() -> None:
    from . import inbox_provider

    # Setting off: only a positive (or commercial) comment offers «Responder aquí» (N3).
    assert inbox_provider._to_comment_vm(_analyzed("POS")).can_reply_here is True
    assert inbox_provider._to_comment_vm(_analyzed("NEG")).can_reply_here is False
    assert inbox_provider._to_comment_vm(_analyzed(None)).can_reply_here is False
    # Setting on for this business: every comment does.
    assert inbox_provider._to_comment_vm(_analyzed("NEG"), any_comment=True).can_reply_here
