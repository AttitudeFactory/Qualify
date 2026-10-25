"""Commercial intent on the Interacciones screen (m-24789644, PR 4b) — network-free, no
database: the provider's projection, the intent filter's mapping and the automatic
analysis that replaced the "Ordenar por prioridad" button (m-24852204).

Pins:
1. Each comment carries its intent signal under `CURRENT_INTENT_VERSION`, read ONCE per
   page (`current_signals`), never per comment and never for an empty page.
2. Chips come highest confidence first; a class the committed reliability report does not
   back is still shown, flagged `reliable=False` (the page marks it «no fiable»).
3. «Requiere atención comercial» passes `CURRENT_INTENT_VERSION` down to the SAME
   paginated read; "ALL" passes `None` (no intent filter at all).
4. `analyze_comments_now` runs `comment_analysis.analyze_after_sync` (the one runner) for
   the session's tenant and only reports whether anything new landed.
5. Every successful sync chains `InboxState.analyze_new_comments` after its own refresh;
   that handler is silent (no toast, no error), guarded, and re-reads only when needed.
   No button and no copy about sorting remain.
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
from qualify_api.comment_analysis import ConnectionAnalysisReport
from qualify_api.intent import (
    CURRENT_INTENT_VERSION,
    IntentClass,
    IntentSignal,
)
from qualify_api.sentiment.repository import AnalyzedComment

from . import inbox_page, inbox_provider
from .inbox_state import FILTER_ALL, FILTER_COMMERCIAL, InboxState
from .inbox_vm import CommentVM, IntentChipVM

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
# m-24852204 — prioritization is automatic: chained after every sync, no button
# --------------------------------------------------------------------------------------


def test_analyze_comments_now_runs_the_one_runner_for_the_session_tenant() -> None:
    captured: dict[str, object] = {}

    def _fake(**kwargs: object) -> ConnectionAnalysisReport:
        captured.update(kwargs)
        return ConnectionAnalysisReport(sentiment_new=2, intent_new=2, followups_opened=1)

    with _patched(analyze_after_sync=_fake):
        changed = asyncio.run(
            inbox_provider.analyze_comments_now(tenant_id=_TENANT, connection_id=_CONNECTION)
        )
    assert captured == {"tenant_id": _TENANT, "connection_id": _CONNECTION}
    assert changed is True


def test_analyze_comments_now_reports_nothing_new_when_the_models_are_missing() -> None:
    """No model and no key: the runner skips both halves silently — the screen does not
    even re-read, and nothing is shown."""

    def _skipped(**_kwargs: object) -> ConnectionAnalysisReport:
        return ConnectionAnalysisReport(
            sentiment_skipped="unavailable", intent_skipped="unavailable"
        )

    with _patched(analyze_after_sync=_skipped):
        assert (
            asyncio.run(
                inbox_provider.analyze_comments_now(tenant_id=_TENANT, connection_id=_CONNECTION)
            )
            is False
        )


def test_a_successful_sync_chains_the_analysis_after_its_own_refresh() -> None:
    source = inspect.getsource(InboxState.sync_comments.fn)
    assert source.count("InboxState.analyze_new_comments") == 2  # on /inbox, and off it
    refresh = source.index("await self._refresh_after_write(tenant_id, connection_id)")
    assert source.index("InboxState.analyze_new_comments") > refresh
    # The sync pass itself never waits for the models.
    assert "analyze_comments_now(" not in source


@pytest.mark.asyncio
async def test_the_analysis_ignores_a_second_trigger_while_one_runs() -> None:
    state = InboxState()
    state.is_analyzing_comments = True
    await InboxState.analyze_new_comments.fn(state)
    assert state.is_analyzing_comments is True


def test_the_analysis_is_silent_resets_in_a_finally_and_rereads_only_when_needed() -> None:
    source = inspect.getsource(InboxState.analyze_new_comments.fn)
    assert "rx.toast" not in source and "_error =" not in source
    assert "sync_now(" not in source
    assert source.count("self.is_analyzing_comments = False") == 1
    refresh = source.index("await self._refresh_after_write(tenant_id, connection_id)")
    assert refresh > source.index("if not changed:")
    assert refresh > source.index("still_same_account = self.selected_connection_id")
    # UX review: new buyers reach the «Quieren comprar» count without a reload.
    assert source.index("return ResponderState.load_counts") > refresh


def test_there_is_no_prioritize_button_nor_copy_about_it() -> None:
    page_source = inspect.getsource(inbox_page)
    assert not hasattr(inbox_page, "_prioritize_button")
    assert not hasattr(inbox_page, "_prioritize_error_block")
    assert "Ordenando" not in page_source
    assert '"Ordenar por prioridad"' not in page_source
    for name in ("analyze_sentiment", "analyze_intent", "prioritize_error", "is_prioritizing"):
        assert not hasattr(InboxState, name), name


# --------------------------------------------------------------------------------------
# set_intent_filter
# --------------------------------------------------------------------------------------


def test_the_intent_filter_is_part_of_every_comment_read_and_its_race_guard() -> None:
    for handler in (
        InboxState._load_thread_comments_first_page,
        InboxState.load_more_thread_comments.fn,
    ):
        source = inspect.getsource(handler)
        assert "intent_filter=intent_filter" in source
        assert "intent_filter == self.intent_filter" in source
    assert "self.intent_filter = FILTER_ALL" in inspect.getsource(InboxState._open_detail)
