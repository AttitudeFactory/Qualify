"""Tests for `TrendingState` (QUA-113, Fase 1) — the "Tendencias e inspiración"
panel's own state, split out of `StoriesState`. Every test below that existed before
the split was MOVED here from `test_stories_state.py` unchanged in intent (only the
state class it targets changed); the tests in the first section are new and pin the
one explicit link the panel keeps with a publish flow — the account Meta's
`ig_audio` lookup runs against.

**Why `_run_audio_search` is only exercised with `_session_tenant_id` stubbed:** the
real one calls `self.get_state(AuthState)`, which needs a live `EventContext` — the
same documented gap `test_stories_state.py`/`test_publishing_state.py` explain.
"""

from __future__ import annotations

import inspect
from uuid import UUID

import pytest
from qualify_api.referentes.scrapecreators_client import ScrapeCreatorsError

from . import scrapecreators_trending
from . import trending_state as trending_state_module
from .trending_state import TrendingState

_TENANT = UUID("00000000-0000-0000-0000-00000000aaaa")
_CONN_A = "00000000-0000-0000-0000-0000000000a1"
_CONN_B = "00000000-0000-0000-0000-0000000000b2"

# ----------------------------------------------------------------------------------
# The account behind Meta's audio lookup (set by the active publish flow)
# ----------------------------------------------------------------------------------


def test_set_audio_connection_records_the_account() -> None:
    state = TrendingState()

    state.set_audio_connection(_CONN_A)

    assert state.audio_connection_id == _CONN_A


def test_set_audio_connection_clears_the_previous_accounts_meta_suggestion() -> None:
    """A trending-audio list fetched for account A must never silently survive a
    switch to account B — including whatever search query was typed for it. (Was
    `test_selecting_a_new_connection_clears_the_previous_trend_suggestion` on
    `StoriesState` before the split.)"""
    state = TrendingState()
    state.trend_options = ["placeholder"]  # type: ignore[list-item]
    state.trend_expanded = True
    state.audio_search_query = "some query"
    state.selected_trend_audio_id = "a1"
    state.selected_trend_audio_title = "Cancion"

    state.set_audio_connection(_CONN_B)

    assert state.trend_options == []
    assert state.trend_expanded is False
    assert state.audio_search_query == ""
    assert state.selected_trend_audio_id == ""
    assert state.selected_trend_audio_title == ""


def test_set_audio_connection_does_not_clear_scrapecreators_trending_lists() -> None:
    """Unlike Meta's `trend_options` (tied to the account's credentials),
    ScrapeCreators trending discovery is account-independent (QUA-107) — switching
    accounts must leave it untouched."""
    state = TrendingState()
    state.tiktok_trending = ["placeholder"]  # type: ignore[list-item]
    state.instagram_trending = ["placeholder"]  # type: ignore[list-item]

    state.set_audio_connection(_CONN_B)

    assert state.tiktok_trending == ["placeholder"]
    assert state.instagram_trending == ["placeholder"]


def test_release_audio_connection_mirrors_the_pre_split_post_publish_reset() -> None:
    """After a successful Story publish, `StoriesState` used to clear the account and
    the selected audio but leave the shown Meta list in place. The split keeps that
    exactly: the account goes, the selection goes, the list stays."""
    state = TrendingState()
    state.set_audio_connection(_CONN_A)
    state.trend_options = ["shown"]  # type: ignore[list-item]
    state.trend_expanded = True
    state.select_trend_audio("a1", "Cancion")

    state.release_audio_connection()

    assert state.audio_connection_id == ""
    assert state.selected_trend_audio_id == ""
    assert state.selected_trend_audio_title == ""
    assert state.trend_options == ["shown"]
    assert state.trend_expanded is True


def test_follow_connection_keeps_everything_when_the_account_is_the_same() -> None:
    """QUA-113: switching flow where both flows use the same account must not throw
    away the Meta list the operator is looking at."""
    state = TrendingState()
    state.set_audio_connection(_CONN_A)
    state.trend_options = ["shown"]  # type: ignore[list-item]
    state.trend_expanded = True
    state.select_trend_audio("a1", "Cancion")

    state.follow_connection(_CONN_A)

    assert state.trend_options == ["shown"]
    assert state.trend_expanded is True
    assert state.selected_trend_audio_id == "a1"


def test_follow_connection_drops_the_meta_list_for_a_different_account() -> None:
    state = TrendingState()
    state.set_audio_connection(_CONN_A)
    state.trend_options = ["shown"]  # type: ignore[list-item]
    state.tiktok_trending = ["kept"]  # type: ignore[list-item]

    state.follow_connection(_CONN_B)

    assert state.audio_connection_id == _CONN_B
    assert state.trend_options == []
    assert state.tiktok_trending == ["kept"]


def test_follow_connection_to_no_account_disables_the_meta_lookup() -> None:
    state = TrendingState()
    state.set_audio_connection(_CONN_A)

    state.follow_connection("")

    assert state.audio_connection_id == ""


def test_selection_setters_are_plain_synchronous() -> None:
    state = TrendingState()

    state.select_trend_audio("a1", "Cancion")
    assert state.selected_trend_audio_id == "a1"
    assert state.selected_trend_audio_title == "Cancion"

    state.clear_trend_audio()
    assert state.selected_trend_audio_id == ""
    assert state.selected_trend_audio_title == ""


def _stub_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_session_tenant_id(self: TrendingState) -> UUID:
        return _TENANT

    monkeypatch.setattr(TrendingState, "_session_tenant_id", fake_session_tenant_id)


@pytest.mark.asyncio
async def test_run_audio_search_is_a_no_op_without_an_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_tenant(monkeypatch)
    calls: list[object] = []

    async def fake_suggest(**kwargs: object) -> list[object]:
        calls.append(kwargs)
        return []

    monkeypatch.setattr(trending_state_module, "_suggest_trend_audio", fake_suggest)
    state = TrendingState()

    await state._run_audio_search("")

    assert calls == []
    assert state.is_loading_trend is False


@pytest.mark.asyncio
async def test_run_audio_search_uses_the_account_the_active_flow_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_tenant(monkeypatch)
    calls: list[dict[str, object]] = []

    async def fake_suggest(**kwargs: object) -> list[str]:
        calls.append(kwargs)
        return [f"opt-{i}" for i in range(15)]

    monkeypatch.setattr(trending_state_module, "_suggest_trend_audio", fake_suggest)
    state = TrendingState()
    state.set_audio_connection(_CONN_A)

    await state._run_audio_search("bad bunny")

    assert calls == [
        {"tenant_id": _TENANT, "connection_id": UUID(_CONN_A), "search_query": "bad bunny"}
    ]
    assert len(state.trend_options) == trending_state_module._MAX_TREND_AUDIO_OPTIONS
    assert state.trend_expanded is True
    assert state.is_loading_trend is False


@pytest.mark.asyncio
async def test_run_audio_search_drops_a_result_that_arrives_after_the_account_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With more than one flow able to set the account, Meta's answer for account A
    can land after the operator already switched to B — it must not be shown under
    B's account."""
    _stub_tenant(monkeypatch)
    state = TrendingState()

    async def fake_suggest(**kwargs: object) -> list[str]:
        state.set_audio_connection(_CONN_B)  # the switch happens mid-request
        return ["for-account-a"]

    monkeypatch.setattr(trending_state_module, "_suggest_trend_audio", fake_suggest)
    state.set_audio_connection(_CONN_A)

    await state._run_audio_search("")

    assert state.trend_options == []
    assert state.is_loading_trend is False
    assert state.audio_connection_id == _CONN_B


# ----------------------------------------------------------------------------------
# Moved from test_stories_state.py (QUA-106 V1 / QUA-107 behavior, unchanged)
# ----------------------------------------------------------------------------------


def test_close_trend_audio_collapses_without_clearing_the_cached_list() -> None:
    state = TrendingState()
    state.trend_options = ["cached"]  # type: ignore[list-item]
    state.trend_expanded = True

    state.close_trend_audio()

    assert state.trend_expanded is False
    assert state.trend_options == ["cached"]


def test_toggle_audio_preview_plays_a_new_track() -> None:
    state = TrendingState()

    state.toggle_audio_preview("a1", "https://example.test/a1.mp3")

    assert state.playing_audio_id == "a1"
    assert state.playing_audio_url == "https://example.test/a1.mp3"
    assert state.is_audio_playing is True


def test_toggle_audio_preview_pauses_the_currently_playing_track() -> None:
    state = TrendingState()
    state.toggle_audio_preview("a1", "https://example.test/a1.mp3")

    state.toggle_audio_preview("a1", "https://example.test/a1.mp3")

    assert state.is_audio_playing is False
    assert state.playing_audio_id == "a1"


def test_toggle_audio_preview_switches_track_without_needing_a_pause_first() -> None:
    state = TrendingState()
    state.toggle_audio_preview("a1", "https://example.test/a1.mp3")

    state.toggle_audio_preview("a2", "https://example.test/a2.mp3")

    assert state.playing_audio_id == "a2"
    assert state.playing_audio_url == "https://example.test/a2.mp3"
    assert state.is_audio_playing is True


def test_audio_preview_stopped_resets_the_playing_flag_without_clearing_the_track() -> None:
    state = TrendingState()
    state.toggle_audio_preview("a1", "https://example.test/a1.mp3")

    state.audio_preview_stopped()

    assert state.is_audio_playing is False
    assert state.playing_audio_id == "a1"


def test_selecting_trend_audio_never_touches_the_playing_audio_state() -> None:
    state = TrendingState()
    state.toggle_audio_preview("a1", "https://example.test/a1.mp3")

    state.select_trend_audio("a2", "Otra cancion")

    assert state.playing_audio_id == "a1"
    assert state.is_audio_playing is True
    assert state.selected_trend_audio_id == "a2"


def test_a_new_trend_selection_replaces_any_previous_one_regardless_of_source() -> None:
    """`selected_trend_audio_id`/`_title` are purely a display choice in this
    session's Reflex state (QUA-106 V1 redesign — there is no row left to persist it
    on) — selecting a TikTok song after a Meta suggestion (or vice versa) simply
    replaces the previous display value."""
    state = TrendingState()
    state.select_trend_audio("meta-1", "Meta Song")
    assert state.selected_trend_audio_id == "meta-1"

    state.select_trend_audio("tiktok-1", "TikTok Song")
    assert state.selected_trend_audio_id == "tiktok-1"
    assert state.selected_trend_audio_title == "TikTok Song"


def _video(**overrides: object) -> scrapecreators_trending.TrendingVideo:
    defaults: dict[str, object] = {
        "source": "tiktok",
        "id": "1",
        "caption": "a caption",
        "author_handle": "someone",
        "author_display_name": "Someone",
        "likes": 10,
        "comments": 2,
        "plays": 100,
        "created_at": None,
        "permalink": "https://example.com/1",
        "thumbnail_url": "",
        "music_id": "m1",
        "music_title": "a song",
        "rank": 0,
    }
    defaults.update(overrides)
    return scrapecreators_trending.TrendingVideo(**defaults)


@pytest.mark.asyncio
async def test_discover_tiktok_trending_populates_state_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = TrendingState()
    monkeypatch.setattr(
        trending_state_module.scrapecreators_trending,
        "fetch_tiktok_trending_feed",
        lambda: (_video(),),
    )

    await TrendingState.discover_tiktok_trending.fn(state)

    assert len(state.tiktok_trending) == 1
    assert state.tiktok_trending[0].external_id == "1"
    assert state.tiktok_trending[0].music_id == "m1"
    assert state.is_loading_tiktok_trending is False
    assert state.tiktok_trending_error == ""
    assert state.tiktok_trending_expanded is True


@pytest.mark.asyncio
async def test_discover_tiktok_trending_degrades_to_empty_list_on_vendor_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = TrendingState()
    state.tiktok_trending = ["stale"]  # type: ignore[list-item]

    def boom() -> tuple[scrapecreators_trending.TrendingVideo, ...]:
        raise ScrapeCreatorsError("vendor down")

    monkeypatch.setattr(
        trending_state_module.scrapecreators_trending, "fetch_tiktok_trending_feed", boom
    )

    await TrendingState.discover_tiktok_trending.fn(state)

    assert state.tiktok_trending == []
    assert state.is_loading_tiktok_trending is False


def test_toggle_tiktok_trending_fetches_on_the_first_click() -> None:
    state = TrendingState()

    result = state.toggle_tiktok_trending()

    assert result is TrendingState.discover_tiktok_trending
    assert state.tiktok_trending_expanded is False  # the fetch itself sets it, not this


def test_toggle_tiktok_trending_collapses_and_re_expands_without_refetching() -> None:
    """Follow-up ("cómo cierro esto"): once data is cached, the SAME button toggles
    visibility instantly — never a second vendor call, never a `discover_*`
    dispatch."""
    state = TrendingState()
    state.tiktok_trending = ["cached"]  # type: ignore[list-item]
    state.tiktok_trending_expanded = True

    collapse_result = state.toggle_tiktok_trending()
    assert collapse_result is None
    assert state.tiktok_trending_expanded is False
    assert state.tiktok_trending == ["cached"]  # untouched, still cached

    expand_result = state.toggle_tiktok_trending()
    assert expand_result is None
    assert state.tiktok_trending_expanded is True
    assert state.tiktok_trending == ["cached"]


@pytest.mark.asyncio
async def test_discover_instagram_trending_populates_state_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = TrendingState()
    reel = _video(source="instagram", id="r1", music_id="", music_title="")
    monkeypatch.setattr(
        trending_state_module.scrapecreators_trending,
        "fetch_instagram_trending_reels",
        lambda: (reel,),
    )

    await TrendingState.discover_instagram_trending.fn(state)

    assert len(state.instagram_trending) == 1
    assert state.instagram_trending[0].external_id == "r1"
    assert state.instagram_trending[0].has_music is False
    assert state.is_loading_instagram_trending is False
    assert state.instagram_trending_expanded is True


@pytest.mark.asyncio
async def test_discover_instagram_trending_degrades_to_empty_list_on_vendor_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = TrendingState()
    state.instagram_trending = ["stale"]  # type: ignore[list-item]

    def boom() -> tuple[scrapecreators_trending.TrendingVideo, ...]:
        raise ScrapeCreatorsError("vendor down")

    monkeypatch.setattr(
        trending_state_module.scrapecreators_trending, "fetch_instagram_trending_reels", boom
    )

    await TrendingState.discover_instagram_trending.fn(state)

    assert state.instagram_trending == []
    assert state.is_loading_instagram_trending is False


def test_toggle_instagram_trending_fetches_on_the_first_click() -> None:
    state = TrendingState()

    result = state.toggle_instagram_trending()

    assert result is TrendingState.discover_instagram_trending


def test_toggle_instagram_trending_collapses_and_re_expands_without_refetching() -> None:
    state = TrendingState()
    state.instagram_trending = ["cached"]  # type: ignore[list-item]
    state.instagram_trending_expanded = True

    collapse_result = state.toggle_instagram_trending()
    assert collapse_result is None
    assert state.instagram_trending_expanded is False
    assert state.instagram_trending == ["cached"]


@pytest.mark.asyncio
async def test_expand_song_populates_song_detail_with_trending_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detail = scrapecreators_trending.SongDetail(
        id="s1",
        title="Cancion Viral",
        author="Artista",
        user_count=100,
        recommend_status=50,
        preview_url="https://example.test/preview.mp3",
    )
    monkeypatch.setattr(
        trending_state_module.scrapecreators_trending,
        "fetch_tiktok_song",
        lambda *, clip_id: detail,
    )
    state = TrendingState()

    await TrendingState.expand_song.fn(state, "s1", "fallback title")

    assert state.expanded_song_id == "s1"
    assert state.song_detail is not None
    assert state.song_detail.audio_id == "s1"
    assert state.song_detail.title == "Cancion Viral"
    assert state.song_detail.user_count == 100
    assert state.song_detail.has_user_count is True
    assert state.song_detail.recommend_status == 50
    assert state.song_detail.has_recommend_status is True
    assert state.song_detail.preview_url == "https://example.test/preview.mp3"
    assert state.song_detail.has_preview is True
    assert state.is_loading_song_detail is False


@pytest.mark.asyncio
async def test_expand_song_without_trending_signals_leaves_them_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detail = scrapecreators_trending.SongDetail(
        id="s1", title="t", author="a", user_count=None, recommend_status=None
    )
    monkeypatch.setattr(
        trending_state_module.scrapecreators_trending,
        "fetch_tiktok_song",
        lambda *, clip_id: detail,
    )
    state = TrendingState()

    await TrendingState.expand_song.fn(state, "s1", "fallback title")

    assert state.song_detail.has_user_count is False
    assert state.song_detail.has_recommend_status is False


@pytest.mark.asyncio
async def test_expand_song_degrades_without_blocking_on_vendor_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*, clip_id: str) -> scrapecreators_trending.SongDetail:
        raise ScrapeCreatorsError("vendor down")

    monkeypatch.setattr(trending_state_module.scrapecreators_trending, "fetch_tiktok_song", boom)
    state = TrendingState()

    await TrendingState.expand_song.fn(state, "s1", "fallback title")

    assert state.song_detail is None
    assert state.is_loading_song_detail is False


@pytest.mark.asyncio
async def test_selecting_an_enriched_song_reuses_the_shared_selection_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detail = scrapecreators_trending.SongDetail(
        id="s1", title="Cancion Viral", author="Artista", user_count=10, recommend_status=90
    )
    monkeypatch.setattr(
        trending_state_module.scrapecreators_trending,
        "fetch_tiktok_song",
        lambda *, clip_id: detail,
    )
    state = TrendingState()

    await TrendingState.expand_song.fn(state, "s1", "fallback")
    state.select_trend_audio(state.song_detail.audio_id, state.song_detail.title)

    assert state.selected_trend_audio_id == "s1"
    assert state.selected_trend_audio_title == "Cancion Viral"


def test_trending_discovery_handlers_take_no_tenant_or_connection_params() -> None:
    for handler in (
        TrendingState.discover_tiktok_trending.fn,
        TrendingState.discover_instagram_trending.fn,
        TrendingState.expand_song.fn,
    ):
        params = inspect.signature(handler).parameters
        assert "tenant_id" not in params
        assert "connection_id" not in params
        source = inspect.getsource(handler)
        assert "_session_tenant_id" not in source
        assert "get_state" not in source


def test_suggest_audio_caps_trend_options_at_the_ui_presentation_limit() -> None:
    """The cap lives in the shared `_run_audio_search` helper (QUA-107 follow-up:
    `suggest_audio`/`search_audio`/`search_song_on_meta` all delegate to it), so
    every one of those three handlers inherits it — not just `suggest_audio`."""
    source = inspect.getsource(TrendingState._run_audio_search)
    assert "options[:_MAX_TREND_AUDIO_OPTIONS]" in source


def test_run_audio_search_expands_the_list_on_a_successful_lookup() -> None:
    """Follow-up ("que también se pueda cerrar"): a successful lookup re-opens the
    list — same `_run_audio_search` helper every trend-audio entry point shares, so
    `suggest_audio`/`search_audio`/`search_song_on_meta` all inherit it."""
    source = inspect.getsource(TrendingState._run_audio_search)
    assert "self.trend_expanded = True" in source


def test_max_trend_audio_options_is_ten() -> None:
    assert trending_state_module._MAX_TREND_AUDIO_OPTIONS == 10


def test_suggest_audio_search_audio_and_search_song_delegate_to_the_shared_helper() -> None:
    """Structural pin: one search implementation, three entry points — `suggest_audio`
    (no query), `search_audio` (whatever is typed), `search_song_on_meta` (a TikTok
    candidate's title). None reimplements the tenant/connection resolution or the
    presentation cap."""
    suggest_source = inspect.getsource(TrendingState.suggest_audio.fn)
    assert 'await self._run_audio_search("")' in suggest_source

    search_source = inspect.getsource(TrendingState.search_audio.fn)
    assert "await self._run_audio_search(query)" in search_source

    search_song_source = inspect.getsource(TrendingState.search_song_on_meta.fn)
    assert "await self._run_audio_search(title)" in search_song_source
    assert "self.audio_search_query = title" in search_song_source


def test_set_audio_search_query_is_plain_synchronous() -> None:
    state = TrendingState()

    state.set_audio_search_query("some song")

    assert state.audio_search_query == "some song"
