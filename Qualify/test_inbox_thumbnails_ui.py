"""m-24852202: the publication cards and the reply drafts show the picture kept in R2
first, Meta's live one next, and the icon only with neither."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from qualify_api.sentiment.repository import ReelSummary

from . import inbox_page, inbox_provider, replies_provider
from .inbox_vm import CandidateMediaVM

_TENANT = UUID("a2520000-0000-4000-8000-000000000001")
_CONNECTION = UUID("c2520000-0000-4000-8000-000000000001")
_NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
_KEY = f"t/{_TENANT}/inbox/thumbs/{_CONNECTION}/r"


def _summary(thumbnail_key: str | None) -> ReelSummary:
    return ReelSummary(
        thread_id=UUID(int=7),
        external_thread_id="r",
        last_message_at=_NOW - timedelta(days=30),
        total=1,
        positive=1,
        neutral=0,
        negative=0,
        not_analyzed=0,
        is_monitored=True,
        media_posted_at=_NOW - timedelta(days=30),
        thumbnail_key=thumbnail_key,
        thumbnail_content_type="image/jpeg" if thumbnail_key else None,
    )


def _candidate() -> CandidateMediaVM:
    return CandidateMediaVM(
        external_media_id="r",
        posted_at="",
        is_monitored=True,
        caption="",
        permalink="",
        thumbnail_url="https://cdn/live.jpg",
    )


def _page(monkeypatch: pytest.MonkeyPatch, summary: ReelSummary, candidates):
    monkeypatch.setattr(inbox_provider, "_list_reel_summaries", lambda **_: (summary,))
    items, _, _ = inbox_provider.reel_summaries_page(
        tenant_id=_TENANT, connection_id=_CONNECTION, cursor=None, candidates=candidates, now=_NOW
    )
    return items[0]


def test_a_stored_picture_wins_over_the_live_one(monkeypatch: pytest.MonkeyPatch) -> None:
    issued: list[tuple] = []

    def fake_issue(tenant_id, key, media_type, content_type=None):
        issued.append((tenant_id, key, content_type))
        return "/r2media/tok"

    monkeypatch.setattr(inbox_provider, "issue_view_path", fake_issue)
    vm = _page(monkeypatch, _summary(_KEY), [_candidate()])
    assert vm.thumbnail_url == "/r2media/tok"
    assert issued == [(_TENANT, _KEY, "image/jpeg")]


def test_without_a_stored_picture_the_live_one_then_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(inbox_provider, "issue_view_path", lambda *a, **k: "/r2media/never")
    assert _page(monkeypatch, _summary(None), [_candidate()]).thumbnail_url == (
        "https://cdn/live.jpg"
    )
    assert _page(monkeypatch, _summary(None), []).thumbnail_url == ""


def test_a_view_path_failure_falls_back_instead_of_breaking_the_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def down(*_a, **_k):
        raise ConnectionError("redis down")

    monkeypatch.setattr(inbox_provider, "issue_view_path", down)
    assert _page(monkeypatch, _summary(_KEY), [_candidate()]).thumbnail_url == (
        "https://cdn/live.jpg"
    )


def test_drafts_use_the_stored_picture(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inbox_provider, "issue_view_path", lambda *a, **k: "/r2media/d")
    source = inspect.getsource(replies_provider.build_queue)
    assert "stored_thumbnail_path(" in source and "media_thumbnail_key" in source
    assert inbox_provider.stored_thumbnail_path(_TENANT, _KEY, "image/jpeg") == "/r2media/d"
    assert inbox_provider.stored_thumbnail_path(None, _KEY, "image/jpeg") == ""
    assert inbox_provider.stored_thumbnail_path(_TENANT, "", None) == ""


def test_the_cards_resolve_r2_paths_and_keep_the_icon_when_empty() -> None:
    reel = inspect.getsource(inbox_page._reel_thumbnail)
    assert "viewable_src(reel.thumbnail_url)" in reel
    assert 'has=reel.thumbnail_url != ""' in reel
