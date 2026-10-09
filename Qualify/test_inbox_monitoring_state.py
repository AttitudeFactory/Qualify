"""QUA-149 phase 3: the Contenido badge shows the EFFECTIVE monitoring state the backend
applies — from the shared 14-day rule over the persisted publication date, never from
`is_monitored` alone — and the persisted caption survives the window.

One chain per scenario: backend (`InboxRepository.list_media_to_sync`, what the sync
really processes) → provider (`reel_summaries_page`) → VM (`monitoring_state`) → the
label the page renders for that state."""

from __future__ import annotations

import contextlib
import inspect
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from qualify_api.inbox.monitoring import MONITORING_WINDOW, MediaMetadata
from qualify_api.inbox.repository import MemoryInboxRepository
from qualify_api.sentiment.repository import ReelSummary

from . import inbox_page, inbox_provider
from .inbox_vm import (
    MONITORING_ACTIVE,
    MONITORING_EXPIRED,
    MONITORING_INACTIVE,
    MONITORING_PENDING,
    CandidateMediaVM,
)

_TENANT = UUID("a1490000-0000-4000-8000-000000000001")
_CONNECTION = UUID("c1490000-0000-4000-8000-000000000001")
_NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)

# The label the page shows for each state (`inbox_page._reel_monitoring_badge`).
_LABELS = {
    MONITORING_ACTIVE: "Monitoreado",
    MONITORING_PENDING: "Monitoreado · fecha por verificar",
    MONITORING_EXPIRED: "No monitoreado · vencido",
    MONITORING_INACTIVE: "No monitoreado",
}


@contextlib.contextmanager
def _patched(**replacements: Callable[..., object]) -> Iterator[None]:
    originals = {name: getattr(inbox_provider, name) for name in replacements}
    for name, value in replacements.items():
        setattr(inbox_provider, name, value)
    try:
        yield
    finally:
        for name, value in originals.items():
            setattr(inbox_provider, name, value)


def _summary(
    media_id: str,
    *,
    is_monitored: bool,
    posted_at: datetime | None,
    caption: str | None = None,
    permalink: str | None = None,
) -> ReelSummary:
    return ReelSummary(
        thread_id=UUID(int=abs(hash(media_id)) % (1 << 64)),
        external_thread_id=media_id,
        last_message_at=_NOW - timedelta(days=1),
        total=2,
        positive=1,
        neutral=0,
        negative=0,
        not_analyzed=1,
        is_monitored=is_monitored,
        media_posted_at=posted_at,
        caption=caption,
        permalink=permalink,
    )


def _page(*summaries: ReelSummary, candidates: list[CandidateMediaVM] | None = None):
    with _patched(_list_reel_summaries=lambda **kwargs: summaries):
        items, _cursor, _more = inbox_provider.reel_summaries_page(
            tenant_id=_TENANT,
            connection_id=_CONNECTION,
            cursor=None,
            candidates=candidates or [],
            now=_NOW,
        )
    return {item.external_thread_id: item for item in items}


# (media id, is_monitored, posted_at, expected state, synced by the backend?)
_SCENARIOS = [
    ("active", True, _NOW - timedelta(days=3), MONITORING_ACTIVE, True),
    ("edge", True, _NOW - MONITORING_WINDOW, MONITORING_ACTIVE, True),
    ("expired", True, _NOW - MONITORING_WINDOW - timedelta(seconds=1), MONITORING_EXPIRED, False),
    ("off", False, _NOW - timedelta(days=3), MONITORING_INACTIVE, False),
    ("off-old", False, _NOW - timedelta(days=40), MONITORING_INACTIVE, False),
    ("legacy", True, None, MONITORING_PENDING, True),
]


@pytest.mark.parametrize(("media_id", "monitored", "posted_at", "state", "synced"), _SCENARIOS)
def test_backend_provider_vm_and_label_agree(
    media_id: str, monitored: bool, posted_at: datetime | None, state: str, synced: bool
) -> None:
    # Backend: what the sync really processes for this row.
    repo = MemoryInboxRepository()
    repo.set_media_monitored(
        tenant_id=_TENANT,
        connection_id=_CONNECTION,
        external_media_id=media_id,
        monitored=monitored,
        metadata=None if posted_at is None else MediaMetadata(posted_at=posted_at),
        fetched_at=None if posted_at is None else _NOW,
    )
    to_sync = repo.list_media_to_sync(tenant_id=_TENANT, connection_id=_CONNECTION, now=_NOW)
    assert (media_id in {m.external_media_id for m in to_sync}) is synced

    # Provider + VM.
    vm = _page(_summary(media_id, is_monitored=monitored, posted_at=posted_at))[media_id]
    assert vm.monitoring_state == state

    # The label: "Monitoreado…" exactly when the backend still syncs it.
    assert _LABELS[vm.monitoring_state].startswith("Monitoreado") is synced


def test_an_expired_reel_keeps_its_persisted_caption_without_any_candidate() -> None:
    items = _page(
        _summary(
            "old",
            is_monitored=True,
            posted_at=_NOW - timedelta(days=30),
            caption="Promo de septiembre",
            permalink="https://www.instagram.com/reel/old/",
        ),
        candidates=[],  # long gone from Meta's 14-day listing
    )
    vm = items["old"]
    assert vm.monitoring_state == MONITORING_EXPIRED
    assert vm.caption == "Promo de septiembre"
    assert vm.permalink == "https://www.instagram.com/reel/old/"
    assert vm.thumbnail_url == ""  # not stored: the page falls back to its generic icon
    assert vm.total == 2  # comment history still counted


def test_the_persisted_caption_wins_over_the_live_candidate() -> None:
    candidate = CandidateMediaVM(
        external_media_id="r",
        posted_at="08 oct 2026, 10:00",
        is_monitored=True,
        caption="caption en vivo",
        permalink="https://live/r",
        thumbnail_url="https://cdn/r.jpg",
    )
    vm = _page(
        _summary("r", is_monitored=True, posted_at=_NOW - timedelta(days=1), caption="guardado"),
        candidates=[candidate],
    )["r"]
    assert vm.caption == "guardado"
    assert vm.permalink == "https://live/r"  # nothing persisted: live fallback
    assert vm.thumbnail_url == "https://cdn/r.jpg"


def test_a_legacy_reel_falls_back_to_the_live_caption_while_pending() -> None:
    candidate = CandidateMediaVM(
        external_media_id="legacy",
        posted_at="08 oct 2026, 10:00",
        is_monitored=True,
        caption="caption en vivo",
        permalink="https://live/legacy",
        thumbnail_url="",
    )
    vm = _page(
        _summary("legacy", is_monitored=True, posted_at=None),
        candidates=[candidate],
    )["legacy"]
    assert vm.monitoring_state == MONITORING_PENDING
    assert vm.caption == "caption en vivo"


def test_a_manually_disabled_reel_reads_no_monitoreado_and_keeps_its_caption() -> None:
    vm = _page(
        _summary("off", is_monitored=False, posted_at=_NOW - timedelta(days=2), caption="hola"),
    )["off"]
    assert vm.monitoring_state == MONITORING_INACTIVE
    assert vm.caption == "hola"


def test_the_page_matches_on_the_effective_state_with_the_four_labels() -> None:
    source = inspect.getsource(inbox_page._reel_monitoring_badge)
    assert "reel.monitoring_state" in source
    assert "reel.is_monitored" not in source  # never the raw flag alone
    for label in _LABELS.values():
        assert f'"{label}"' in source
    assert "No monitoreado · histórico" not in inspect.getsource(inbox_page)


def test_the_provider_reuses_the_shared_rule_and_compares_no_dates() -> None:
    source = inspect.getsource(inbox_provider._monitoring_state)
    assert "effective_state(" in source
    assert "MONITORING_WINDOW" not in inspect.getsource(inbox_provider)
    assert "timedelta" not in inspect.getsource(inbox_provider)
