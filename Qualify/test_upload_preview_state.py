"""ED-09 (m-25026643; ADR 50 D-E2): coming back to the editor, its preview plays the 480p
copy of the owner's own uploaded video; «Cortar» is still judged with the ORIGINAL's size;
a copy that failed for good shows a friendly notice and the original plays. Offline: the
service's read (`previews_for`) is a fake; the `/r2media` door is the real one on a token
double, as in `test_clip_editor_state.py`."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from qualify_api.creative.upload_previews import UploadPreview, preview_key

from . import clip_editor_vm, r2_media
from . import creative_state as creative_state_module
from . import upload_preview_state as ups
from .creative_state import CreativeState

TENANT = UUID("a0000000-0000-4000-8000-0000000e0919")
VIDEO = f"t/{TENANT}/uploads/abc_iphone.MOV"
COPY = preview_key(TENANT, VIDEO)

#: The real read, taken before the autouse fixture swaps it for «play the original».
CHOOSE = ups.choose_play

BLURRY = "Al ponerlo vertical, tu video se vería borroso. Sube el video original desde tu teléfono."


def _preview(status: str, **fields: Any) -> UploadPreview:
    return UploadPreview(source_key=VIDEO, status=status, preview_key=COPY, **fields)


@pytest.fixture
def read(monkeypatch: pytest.MonkeyPatch) -> dict[str, UploadPreview]:
    """What `previews_for` answers (`{}` = not a previewable key)."""
    rows: dict[str, UploadPreview] = {}
    monkeypatch.setattr(ups, "choose_play", CHOOSE)
    monkeypatch.setattr(
        ups, "previews_for", lambda _t, keys: {k: rows[k] for k in keys if k in rows}
    )
    return rows


# -- what plays ---------------------------------------------------------------------------


def test_a_made_copy_plays_with_the_originals_size(read) -> None:
    read[VIDEO] = _preview("done", source_width=2160, source_height=3840)
    assert ups.choose_play(TENANT, VIDEO) == ups.PlayChoice(COPY, 2160, 3840)


def test_a_copy_without_the_originals_size_is_not_played(read) -> None:
    read[VIDEO] = _preview("done")
    assert ups.choose_play(TENANT, VIDEO) == ups.PlayChoice(VIDEO)


@pytest.mark.parametrize(("status", "ask"), [("none", True), ("queued", False), ("running", False)])
def test_until_the_copy_is_made_the_original_plays_without_a_notice(read, status, ask) -> None:
    read[VIDEO] = _preview(status)
    # never asked for (a video picked from elsewhere, an upload whose request was lost):
    # asked now
    assert ups.choose_play(TENANT, VIDEO) == ups.PlayChoice(VIDEO, ask=ask)


def test_a_copy_failed_for_good_plays_the_original_with_the_notice(read) -> None:
    read[VIDEO] = _preview("failed", error_code="unreadable")
    assert ups.choose_play(TENANT, VIDEO) == ups.PlayChoice(VIDEO, failed=True)
    # a failure of the machine, not of the file: no notice, and the copy is asked again
    read[VIDEO] = _preview("failed", error_code="attempts_exhausted", transient_failures=1)
    assert ups.choose_play(TENANT, VIDEO) == ups.PlayChoice(VIDEO, ask=True)
    # …until it failed that way too often: for good, the notice, never asked again
    read[VIDEO] = _preview("failed", error_code="attempts_exhausted", transient_failures=2)
    assert ups.choose_play(TENANT, VIDEO) == ups.PlayChoice(VIDEO, failed=True)


def test_a_key_that_is_not_an_upload_plays_as_is(read) -> None:
    gallery = f"gallery/{TENANT}/m1/video.mp4"
    assert ups.choose_play(TENANT, gallery) == ups.PlayChoice(gallery)


def test_a_failed_read_plays_the_original(monkeypatch, caplog) -> None:
    def down(*_a: Any) -> dict[str, UploadPreview]:
        raise RuntimeError("db down")

    monkeypatch.setattr(ups, "previews_for", down)
    assert CHOOSE(TENANT, VIDEO) == ups.PlayChoice(VIDEO)
    assert "upload preview not read" in caplog.text


def test_the_original_size_wins_only_when_known() -> None:
    sizes = {VIDEO: [2160, 3840], "x": [0, 0]}
    assert ups.original_size(sizes, VIDEO, 270, 480) == (2160, 3840)
    assert ups.original_size(sizes, "x", 270, 480) == (270, 480)
    assert ups.original_size(sizes, "y", 1080, 1920) == (1080, 1920)


def test_the_notice_text() -> None:
    assert ups.NOTICE_TEXT == (
        "Tu video puede tardar un poco en verse aquí. El video final no cambia."
    )
    assert ups.upload_preview_notice() is not None  # builds on the real states' Vars


@pytest.mark.parametrize(
    ("failed", "playable", "broken", "broken_key", "shown"),
    [
        (VIDEO, True, False, "", True),
        ("", True, False, "", False),  # the copy did not fail
        ("other", True, False, "", False),  # another video's
        (VIDEO, False, False, "", False),  # not playable: the preview says it cannot show it
        (VIDEO, True, True, VIDEO, False),  # broken: PREVIEW_UNAVAILABLE says it already
        (VIDEO, True, True, "other", True),  # an older video's break does not count
    ],
)
def test_the_notice_never_repeats_preview_unavailable(
    failed, playable, broken, broken_key, shown
) -> None:
    assert bool(ups.notice_condition(failed, VIDEO, playable, broken, broken_key)) is shown


# -- the editor ----------------------------------------------------------------------------


class _Tokens:
    def __init__(self) -> None:
        self.asked: list[str] = []

    def issue(self, *, tenant_id: UUID, object_key: str, **_kw: Any) -> str:
        self.asked.append(object_key)
        return f"tok-{len(self.asked)}"


@pytest.fixture
def editor(monkeypatch: pytest.MonkeyPatch, read) -> tuple[CreativeState, _Tokens, Any]:
    monkeypatch.setattr(clip_editor_vm, "CLIP_EDITOR_ON", True)
    tokens = _Tokens()

    def issue(tenant_id: UUID, key: str, media_type: str) -> str:
        return r2_media.issue_view_path(tenant_id, key, media_type, store=tokens)

    async def tenant(_self: CreativeState) -> UUID:
        return TENANT

    notice = ups.UploadPreviewState()
    asked: list[str] = []
    monkeypatch.setattr(
        ups.upload_preview_provider, "ask_for_preview", lambda _t, _b, k: asked.append(k)
    )
    tokens.copies_asked = asked  # type: ignore[attr-defined]

    async def get_state(_self: Any, wanted: type) -> Any:
        assert wanted is ups.UploadPreviewState
        return notice

    monkeypatch.setattr(creative_state_module, "issue_view_path", issue)
    monkeypatch.setattr(CreativeState, "_clip_preview_tenant", tenant)
    monkeypatch.setattr(CreativeState, "get_state", get_state)
    state = CreativeState()
    state.gen_category = "clip"
    state.brief_kind = "clip"
    state.clip_videos = [{"key": VIDEO, "name": "iphone.MOV", "source": "upload"}]
    return state, tokens, notice


async def test_a_4k_original_shown_from_its_480p_copy_is_not_called_blurry(editor, read) -> None:
    state, tokens, notice = editor
    read[VIDEO] = _preview("done", source_width=2160, source_height=3840)
    await CreativeState.resolve_clip_preview.fn(state)
    assert tokens.asked == [COPY]  # the preview plays the copy
    assert state.clip_preview_for == VIDEO and state.clip_preview_url.startswith("/r2media/")
    # the browser measures the copy: 270×480
    CreativeState.report_clip_source.fn(state, VIDEO, 12.0, 270, 480)
    assert (state.clip_source_width, state.clip_source_height) == (2160, 3840)
    assert state.clip_cut_check == ["", ""]
    assert notice.failed_key == ""
    # the piece is still made from the original: the copy never reaches the recipe
    assert COPY not in str(state._clip_edit_media()) and COPY not in str(state.clip_videos)


async def test_the_same_small_size_from_the_original_is_still_called_blurry(editor, read) -> None:
    state, tokens, _notice = editor
    read[VIDEO] = _preview("queued")
    await CreativeState.resolve_clip_preview.fn(state)
    assert tokens.asked == [VIDEO]  # no copy yet: the original plays
    CreativeState.report_clip_source.fn(state, VIDEO, 12.0, 270, 480)
    assert (state.clip_source_width, state.clip_source_height) == (270, 480)
    assert state.clip_cut_check == ["", BLURRY]


async def test_a_copy_failed_for_good_shows_the_notice_and_plays_the_original(editor, read) -> None:
    state, tokens, notice = editor
    read[VIDEO] = _preview("failed", error_code="unreadable")
    await CreativeState.resolve_clip_preview.fn(state)
    assert tokens.asked == [VIDEO]
    assert state.clip_edit_video_playable  # the owner keeps building the piece
    assert notice.failed_key == VIDEO
    # later the copy is there (a new version): the notice goes away
    read[VIDEO] = _preview("done", source_width=1080, source_height=1920)
    state.clip_preview_for = ""
    await CreativeState.resolve_clip_preview.fn(state)
    assert tokens.asked[-1] == COPY and notice.failed_key == ""


async def test_a_broken_notice_state_never_breaks_the_preview(editor, read, monkeypatch) -> None:
    state, tokens, _notice = editor

    async def no_state(_self: Any, _wanted: type) -> Any:
        raise RuntimeError("no substate")

    monkeypatch.setattr(CreativeState, "get_state", no_state)
    read[VIDEO] = _preview("failed", error_code="unreadable")
    await CreativeState.resolve_clip_preview.fn(state)
    assert tokens.asked == [VIDEO] and state.clip_edit_video_playable


async def test_opening_a_video_never_asked_for_asks_for_its_copy(editor, read) -> None:
    state, tokens, notice = editor
    read[VIDEO] = _preview("none")
    await CreativeState.resolve_clip_preview.fn(state)
    assert tokens.asked == [VIDEO] and tokens.copies_asked == [VIDEO]
    # made by now: played, nothing asked again
    read[VIDEO] = _preview("done", source_width=1080, source_height=1920)
    state.clip_preview_for = ""
    await CreativeState.resolve_clip_preview.fn(state)
    assert tokens.asked[-1] == COPY and tokens.copies_asked == [VIDEO]


async def test_a_copy_that_dies_in_the_browser_is_renewed_as_the_original(editor, read) -> None:
    state, tokens, _notice = editor
    read[VIDEO] = _preview("done", source_width=2160, source_height=3840)
    await CreativeState.resolve_clip_preview.fn(state)
    assert tokens.asked == [COPY]
    CreativeState.report_clip_source.fn(state, VIDEO, -1.0, 0, 0)  # the copy does not play
    assert state.clip_preview_for == ""  # renewal asked
    await CreativeState.resolve_clip_preview.fn(state)
    assert tokens.asked == [COPY, VIDEO]  # the original this time
    assert not state.clip_source_broken and state.clip_edit_video_playable
    # it plays: the browser's own size is what «Cortar» judges now
    CreativeState.report_clip_source.fn(state, VIDEO, 12.0, 2160, 3840)
    assert (state.clip_source_width, state.clip_source_height) == (2160, 3840)
    assert state._clip_copy_sizes == {}
