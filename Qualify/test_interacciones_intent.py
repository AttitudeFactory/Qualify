"""Commercial intent on the Interacciones screen (m-24789644, PR 4b) — network-free, no
database: the provider's projection, the intent filter's mapping, the "Analizar
intención" transport and the state handler's shape.

Pins:
1. Each comment carries its intent signal under `CURRENT_INTENT_VERSION`, read ONCE per
   page (`current_signals`), never per comment and never for an empty page.
2. Chips come highest confidence first; a class the committed reliability report does not
   back is still shown, flagged `reliable=False` (the page marks it «no fiable»).
3. «Requiere atención comercial» passes `CURRENT_INTENT_VERSION` down to the SAME
   paginated read; "ALL" passes `None` (no intent filter at all).
4. `analyze_intent_now` runs `analyze_pending_intents` (the one intent engine), forwards
   the session's tenant, projects every count, and propagates its typed refusals.
5. `InboxState.analyze_intent` has the same guard / `finally` / success-only refresh
   shape as `analyze_sentiment`, maps each failure to its own message, and is
   independent of sync and of sentiment analysis.
"""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID

import pytest
from qualify_api.intent import (
    CURRENT_INTENT_VERSION,
    IntentAnalysisSummary,
    IntentClass,
    IntentModelUnavailable,
    IntentSignal,
    UnknownIntentConnection,
)
from qualify_api.sentiment.repository import AnalyzedComment

from . import inbox_page, inbox_provider, inbox_state
from .inbox_state import FILTER_ALL, FILTER_COMMERCIAL, InboxState
from .inbox_vm import CommentVM, IntentAnalysisSummaryVM, IntentChipVM
from .test_inbox_state import _error_constant_by_exception

_TENANT = UUID("a0000000-0000-4000-8000-0000000000b1")
_CONNECTION = UUID("c0000000-0000-4000-8000-0000000000b1")
_THREAD = UUID("d0000000-0000-4000-8000-0000000000b1")
_PRICE_Q = UUID("e0000000-0000-4000-8000-000000000001")
_PRAISE = UUID("e0000000-0000-4000-8000-000000000002")
_PENDING = UUID("e0000000-0000-4000-8000-000000000003")


@contextmanager
def _patched(**replacements: object) -> Iterator[None]:
    originals = {name: getattr(inbox_provider, name) for name in replacements}
    for name, value in replacements.items():
        setattr(inbox_provider, name, value)
    try:
        yield
    finally:
        for name, value in originals.items():
            setattr(inbox_provider, name, value)


def _comment(message_id: UUID, text: str) -> AnalyzedComment:
    return AnalyzedComment(
        message_id=message_id,
        source_id=f"src-{message_id.int}",
        text=text,
        author_username="cliente",
        posted_at=datetime(2026, 10, 20, 10, 0, tzinfo=UTC),
        external_thread_id="media-1",
        label=None,
        score=None,
    )


def _signal(message_id: UUID, classes: dict[IntentClass, float]) -> IntentSignal:
    return IntentSignal(
        comment_id=message_id,
        source_id=f"src-{message_id.int}",
        classes=classes,
        detector_version=CURRENT_INTENT_VERSION.detector_version,
        pipeline_version=CURRENT_INTENT_VERSION.pipeline_version,
        model_id=CURRENT_INTENT_VERSION.model_id,
        model_revision=CURRENT_INTENT_VERSION.model_revision,
    )


def _page(**kwargs: object) -> list[CommentVM]:
    defaults: dict[str, object] = {
        "tenant_id": _TENANT,
        "connection_id": _CONNECTION,
        "thread_id": _THREAD,
        "sentiment_filter": "ALL",
        "search": "",
        "cursor": None,
    }
    defaults.update(kwargs)
    items, _cursor, _has_more = inbox_provider.thread_comments_page(**defaults)
    return items


# --------------------------------------------------------------------------------------
# VM boundary
# --------------------------------------------------------------------------------------


def test_intent_chip_vm_carries_only_display_fields() -> None:
    """Whitelist: the chip is a label and two flags — never a confidence, a model id or
    any raw signal payload."""
    assert {f.name: f.type for f in dataclasses.fields(IntentChipVM)} == {
        "label": "str",
        "commercial": "bool",
        "reliable": "bool",
    }


def test_comment_vm_defaults_to_not_analyzed_for_intent() -> None:
    vm = CommentVM(
        message_id="m",
        text="t",
        author_username="",
        posted_at="",
        external_thread_id="",
        sentiment_label="",
        score_display="",
    )
    assert vm.intent_analyzed is False
    assert vm.intent_chips == []


# --------------------------------------------------------------------------------------
# thread_comments_page — intent decoration
# --------------------------------------------------------------------------------------


def test_each_comment_carries_its_intent_and_unreliable_classes_are_flagged() -> None:
    calls: list[list[UUID]] = []

    def _signals(*, tenant_id: UUID, message_ids: list[UUID]) -> dict[UUID, IntentSignal]:
        assert tenant_id == _TENANT
        calls.append(list(message_ids))
        return {
            _PRICE_Q: _signal(_PRICE_Q, {IntentClass.PRICE: 0.6, IntentClass.HOURS: 0.9}),
            _PRAISE: _signal(_PRAISE, {IntentClass.GENERAL: 0.95}),
        }

    reliability = {c: False for c in IntentClass} | {
        IntentClass.PRICE: True,
        IntentClass.GENERAL: True,
    }
    with _patched(
        _list_comments_for_thread=lambda **kw: (
            _comment(_PRICE_Q, "¿precio y horario?"),
            _comment(_PRAISE, "hermoso"),
            _comment(_PENDING, "¿tienen talla S?"),
        ),
        _current_signals=_signals,
        class_reliability=lambda detector_version: reliability,
    ):
        price_q, praise, pending = _page()

    assert calls == [[_PRICE_Q, _PRAISE, _PENDING]], "one read for the whole page"
    assert price_q.intent_analyzed is True
    assert price_q.intent_chips == [
        IntentChipVM(label="Horario", commercial=True, reliable=False),  # 0.9 first
        IntentChipVM(label="Precio", commercial=True, reliable=True),
    ]
    assert praise.intent_chips == [
        IntentChipVM(label="Comentario general", commercial=False, reliable=True)
    ]
    assert pending.intent_analyzed is False
    assert pending.intent_chips == []


def test_an_empty_page_never_reads_intent() -> None:
    def _boom(**kwargs: object) -> dict:
        raise AssertionError("current_signals must not run for an empty page")

    with _patched(_list_comments_for_thread=lambda **kw: (), _current_signals=_boom):
        assert _page() == []


def test_the_committed_reliability_report_backs_what_the_page_shows() -> None:
    """Not a stub: the real report for the current version (PR 3b's test-split
    measurement) — price is reliable, hours is not, so a page would mark hours."""
    reliable = inbox_provider.class_reliability(CURRENT_INTENT_VERSION.detector_version)
    assert reliable[IntentClass.PRICE] is True
    assert reliable[IntentClass.HOURS] is False


# --------------------------------------------------------------------------------------
# thread_comments_page — «Requiere atención comercial»
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("intent_filter", "expected"),
    [
        (FILTER_COMMERCIAL, CURRENT_INTENT_VERSION),
        (FILTER_ALL, None),
        ("", None),
    ],
)
def test_the_intent_filter_narrows_the_same_paginated_read(
    intent_filter: str, expected: object
) -> None:
    captured: dict[str, object] = {}

    def _capture(**kwargs: object) -> tuple[AnalyzedComment, ...]:
        captured.update(kwargs)
        return ()

    with _patched(_list_comments_for_thread=_capture):
        _page(intent_filter=intent_filter, sentiment_filter="NEG", search="precio")

    assert captured["commercial_intent"] == expected
    # The other filters ride along untouched: the filters combine.
    assert captured["sentiment_filter"] == "NEG"
    assert captured["search"] == "precio"


def test_the_page_offers_the_commercial_filter() -> None:
    assert (FILTER_COMMERCIAL, "Quieren comprar") in inbox_page._INTENT_FILTER_OPTIONS
    assert "InboxState.set_intent_filter" in inspect.getsource(inbox_page._intent_filter_select)


# --------------------------------------------------------------------------------------
# analyze_intent_now
# --------------------------------------------------------------------------------------


def test_analyze_intent_now_forwards_the_session_tenant_and_projects() -> None:
    captured: dict[str, object] = {}

    def _fake(**kwargs: object) -> IntentAnalysisSummary:
        captured.update(kwargs)
        return IntentAnalysisSummary(
            comments_checked=6, new_results=4, skipped_empty=1, unclassified=1
        )

    async def _opened(tenant_id: UUID, connection_id: UUID) -> int:
        captured["opened_for"] = (tenant_id, connection_id)
        return 2

    with _patched(analyze_pending_intents=_fake, _open_followups=_opened):
        result = asyncio.run(
            inbox_provider.analyze_intent_now(tenant_id=_TENANT, connection_id=_CONNECTION)
        )
    assert captured == {
        "tenant_id": _TENANT,
        "connection_id": _CONNECTION,
        # m-24789646 (B1): the analysis then opens the commercial queries.
        "opened_for": (_TENANT, _CONNECTION),
    }
    assert result == IntentAnalysisSummaryVM(
        comments_checked=6, new_results=4, skipped_empty=1, unclassified=1, followups_opened=2
    )


@pytest.mark.parametrize("exc", [UnknownIntentConnection("x"), IntentModelUnavailable("no key")])
def test_analyze_intent_now_propagates_its_typed_refusals(exc: Exception) -> None:
    def _raise(**kwargs: object) -> IntentAnalysisSummary:
        raise exc

    with _patched(analyze_pending_intents=_raise), pytest.raises(type(exc)):
        asyncio.run(inbox_provider.analyze_intent_now(tenant_id=_TENANT, connection_id=_CONNECTION))


# --------------------------------------------------------------------------------------
# InboxState.analyze_intent / set_intent_filter
# --------------------------------------------------------------------------------------


def test_can_analyze_intent_needs_a_connection_and_no_pass_in_flight() -> None:
    state = InboxState()
    state.selected_connection_id = ""
    assert state.can_analyze_intent is False
    state.selected_connection_id = "c-1"
    state.is_analyzing_intent = True
    assert state.can_analyze_intent is False
    state.is_analyzing_intent = False
    assert state.can_analyze_intent is True


@pytest.mark.asyncio
async def test_analyze_intent_ignores_a_double_click() -> None:
    state = InboxState()
    state.is_analyzing_intent = True
    state.analyze_intent_error = "estado previo"
    await InboxState.analyze_intent.fn(state)
    assert state.is_analyzing_intent is True
    assert state.analyze_intent_error == "estado previo"


def test_analyze_intent_maps_each_failure_to_its_own_message() -> None:
    mapping = _error_constant_by_exception(InboxState.analyze_intent.fn, "analyze_intent_error")
    assert mapping == {
        "UnknownIntentConnection": "_UNKNOWN_CONNECTION",
        "IntentModelUnavailable": "_ANALYZE_INTENT_UNAVAILABLE",
        "Exception": "_ANALYZE_INTENT_FAILED",
    }


def test_analyze_intent_resets_its_flag_in_a_finally_and_refreshes_only_on_success() -> None:
    source = inspect.getsource(InboxState.analyze_intent.fn)
    assert source.count("self.is_analyzing_intent = False") == 2
    refresh = source.index("await self._refresh_after_write(tenant_id, connection_id)")
    assert refresh > source.rindex("self.is_analyzing_intent = False")
    assert "_SESSION_EXPIRED if tenant_id is None else _NO_CONNECTION_SELECTED" in source


def test_analyze_intent_is_independent_of_sync_and_sentiment() -> None:
    source = inspect.getsource(InboxState.analyze_intent.fn)
    for fragment in (
        "sync_now(",
        "analyze_sentiment_now(",
        "self.is_syncing",
        "self.is_analyzing =",
    ):
        assert fragment not in source, fragment
    for handler in (InboxState.analyze_sentiment.fn, InboxState.sync_comments.fn):
        assert "analyze_intent_now(" not in inspect.getsource(handler)


def test_the_intent_filter_is_part_of_every_comment_read_and_its_race_guard() -> None:
    for handler in (
        InboxState._load_thread_comments_first_page,
        InboxState.load_more_thread_comments.fn,
    ):
        source = inspect.getsource(handler)
        assert "intent_filter=intent_filter" in source
        assert "intent_filter == self.intent_filter" in source
    assert "self.intent_filter = FILTER_ALL" in inspect.getsource(InboxState._open_detail)


@pytest.mark.parametrize(
    ("summary", "expected"),
    [
        (
            IntentAnalysisSummaryVM(
                comments_checked=0, new_results=0, skipped_empty=0, unclassified=0
            ),
            "No hay comentarios nuevos para ordenar.",
        ),
        (
            IntentAnalysisSummaryVM(
                comments_checked=5, new_results=5, skipped_empty=0, unclassified=0
            ),
            "Listo: ordenamos 5 comentarios.",
        ),
        (
            IntentAnalysisSummaryVM(
                comments_checked=5, new_results=3, skipped_empty=1, unclassified=1
            ),
            "Listo: ordenamos 3 comentarios. 1 quedó sin revisar: lo intentamos de nuevo"
            " la próxima vez.",
        ),
    ],
)
def test_the_toast_says_what_happened(summary: IntentAnalysisSummaryVM, expected: str) -> None:
    assert inbox_state._intent_result_message(summary) == expected
