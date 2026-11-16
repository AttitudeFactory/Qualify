"""m-25040496 — «Es una historia» on a piece's own page, offline: who may be marked, what
undoing sets, the provider's one call to `update_post`, the state's refresh and its
words, and the control on the piece's page. After the change the gallery reads the
piece as a historia (label, «Historias», share file)."""

from __future__ import annotations

import inspect
import json
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from . import creative_pages
from . import story_mark_provider as provider
from . import story_mark_state as state_module
from .planner_vm import build_post_option
from .story_mark_provider import StoryMarkRefused, set_story, story_mark_of
from .story_mark_state import StoryMarkState
from .story_mark_vm import (
    REASON_OTHER,
    REASON_PURGED,
    REASON_SCHEDULED,
    REASON_SEVERAL_FILES,
    REASON_TOO_LONG,
    StoryMarkVM,
    marked_toast,
    story_mark,
    target_category,
    undo_category,
    unmarked_toast,
)

TENANT = UUID("a0000000-0000-4000-8000-000025040496")
DRAFT = UUID("20000000-0000-4000-8000-000025040496")


def _mark(**kw: Any) -> StoryMarkVM:
    params: dict[str, Any] = {
        "category": "galeria",
        "media_types": ("IMAGE",),
        "has_outputs": False,
        "has_live_event": False,
        "purged": False,
        "video_too_long": False,
    }
    params.update(kw)
    return story_mark(**params)


# -- the rule --------------------------------------------------------------------------


def test_one_image_or_one_video_may_be_marked_in_any_state() -> None:
    assert _mark().can_change and not _mark().is_story
    assert _mark(category="reel", media_types=("VIDEO",)).can_change
    assert _mark(category="story").is_story and _mark(category="story").can_change


@pytest.mark.parametrize(
    ("kw", "reason"),
    [
        ({"media_types": ("IMAGE", "IMAGE")}, REASON_SEVERAL_FILES),  # a carousel
        ({"media_types": ()}, REASON_SEVERAL_FILES),  # no file read
        ({"has_live_event": True}, REASON_SCHEDULED),  # on the calendar: never changed
        ({"purged": True}, REASON_PURGED),
        ({"category": "tiktok_video", "media_types": ("VIDEO",)}, REASON_OTHER),
        ({"media_types": ("VIDEO",), "video_too_long": True}, REASON_TOO_LONG),
    ],
)
def test_what_may_not_change_says_why(kw: dict[str, Any], reason: str) -> None:
    mark = _mark(**kw)
    assert mark.shown and not mark.can_change and mark.reason == reason


def test_a_too_long_historia_can_still_be_unmarked() -> None:
    mark = _mark(category="story", media_types=("VIDEO",), video_too_long=True)
    assert mark.can_change and target_category(mark, story=False) == "reel"


def test_a_template_package_never_shows_the_switch() -> None:
    assert not _mark(has_outputs=True).shown


def test_undo_goes_back_to_the_pieces_shape() -> None:
    assert undo_category(("IMAGE",)) == "galeria"
    assert undo_category(("VIDEO",)) == "reel"
    assert target_category(_mark(category="story"), story=False) == "galeria"
    assert target_category(_mark(), story=True) == "story"
    assert target_category(_mark(), story=False) is None  # already so
    assert target_category(_mark(has_live_event=True), story=True) is None


# -- the provider ----------------------------------------------------------------------


def _summary(**kw: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "category": "galeria",
        "media_types": ("IMAGE",),
        "outputs": (),
        "has_live_event": False,
        "retention_state": "",
        "video_seconds": None,
        "approval": SimpleNamespace(value="approved"),
    }
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    box: dict[str, Any] = {"post": _summary(), "calls": [], "events": []}

    class Reader:
        def get(self, *, tenant_id: UUID, post_id: UUID) -> Any:
            return box["post"]

    class Service:
        def update_post(self, **kw: Any) -> None:
            box["calls"].append(kw)
            box["post"] = _summary(**{**vars(box["post"]), "category": kw["category"]})

    monkeypatch.setattr(provider, "_reader", Reader)
    monkeypatch.setattr(provider, "_service", Service)
    monkeypatch.setattr(
        provider,
        "_events",
        lambda _t, _d: [SimpleNamespace(status=status) for status in box["events"]],
    )
    return box


@pytest.mark.parametrize(
    ("statuses", "blocked"),
    [
        (["scheduled"], True),  # overdue too: it can be moved to another day
        (["publishing"], True),
        (["failed"], False),  # terminal: never goes out again
        (["cancelled", "published"], False),
    ],
)
def test_an_event_that_may_still_go_out_blocks_the_change(
    db: dict, statuses: list[str], blocked: bool
) -> None:
    db["events"] = statuses
    mark = provider.story_mark_info(TENANT, DRAFT)
    assert mark.can_change is not blocked
    assert (mark.reason == REASON_SCHEDULED) is blocked


def test_a_piece_gone_or_now_a_package_is_refused_with_words(db: dict) -> None:
    db["post"] = None
    with pytest.raises(StoryMarkRefused) as gone:
        set_story(TENANT, DRAFT, story=True)
    assert gone.value.reason == REASON_OTHER
    db["post"] = _summary(outputs=(SimpleNamespace(port="story"),))
    with pytest.raises(StoryMarkRefused) as package:
        set_story(TENANT, DRAFT, story=False)
    assert package.value.reason == REASON_OTHER
    assert StoryMarkRefused("").reason == REASON_OTHER
    assert db["calls"] == []


def test_marking_calls_update_post_with_story_and_returns_the_new_mark(db: dict) -> None:
    mark = set_story(TENANT, DRAFT, story=True)
    assert db["calls"] == [{"tenant_id": TENANT, "draft_id": DRAFT, "category": "story"}]
    assert mark.is_story


def test_unmarking_a_video_sets_reel(db: dict) -> None:
    db["post"] = _summary(category="story", media_types=("VIDEO",))
    assert not set_story(TENANT, DRAFT, story=False).is_story
    assert db["calls"][-1]["category"] == "reel"


def test_already_so_writes_nothing_and_a_refusal_writes_nothing(db: dict) -> None:
    db["post"] = _summary(category="story")
    set_story(TENANT, DRAFT, story=True)
    db["post"] = _summary(has_live_event=True)
    with pytest.raises(StoryMarkRefused) as refused:
        set_story(TENANT, DRAFT, story=True)
    assert refused.value.reason == REASON_SCHEDULED
    assert db["calls"] == []


def test_a_purged_piece_reads_as_purged() -> None:
    assert story_mark_of(_summary(retention_state="purged")).reason == REASON_PURGED
    assert not story_mark_of(None).shown


# -- after the change, the gallery sees a historia --------------------------------------


def test_a_marked_piece_is_a_historia_in_the_gallery() -> None:
    card = build_post_option(
        post_id=str(DRAFT),
        title="Shawarma",
        caption_excerpt="",
        thumbnail_url="/r2media/tok",
        category="story",
        approval="approved",
        detail_href=f"/drafts/{DRAFT}",
        is_publishable=True,
        unpublishable_reason="",
        gallery_state="schedulable",
        media_types=("IMAGE",),
    )
    assert card.is_story and card.story_share_url == "/r2media/tok"


# -- the state -------------------------------------------------------------------------


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    box: dict[str, Any] = {"story": False, "refuse": "", "writes": 0}

    async def tenant(self: StoryMarkState) -> UUID:
        return TENANT

    def info(tenant_id: UUID, draft: UUID) -> StoryMarkVM:
        return _mark(category="story" if box["story"] else "galeria")

    def write(tenant_id: UUID, draft: UUID, *, story: bool) -> StoryMarkVM:
        if box["refuse"]:
            raise StoryMarkRefused(box["refuse"])
        box["story"], box["writes"] = story, box["writes"] + 1
        return info(tenant_id, draft)

    monkeypatch.setattr(StoryMarkState, "_tenant", tenant)
    monkeypatch.setattr(state_module, "story_mark_info", info)
    monkeypatch.setattr(state_module, "set_story", write)
    return box


async def _drain(gen: Any) -> list[Any]:
    return [e async for e in gen]


async def test_the_switch_marks_unmarks_and_refreshes(backend: dict[str, Any]) -> None:
    state = StoryMarkState()
    await StoryMarkState.load_for.fn(state, str(DRAFT))
    assert state.loaded and state.shown and state.can_change and not state.is_story
    events = await _drain(StoryMarkState.set_story.fn(state, True))
    text = json.dumps(str(events), ensure_ascii=False)
    assert state.is_story and backend["story"]
    assert "Por aprobar › Historias" in text  # `_mark` is not approved
    events = await _drain(StoryMarkState.set_story.fn(state, False))
    text = json.dumps(str(events), ensure_ascii=False)
    assert not state.is_story and "vuelve a ser una publicación" in text
    await _drain(StoryMarkState.set_story.fn(state, False))  # already so: no write
    assert backend["writes"] == 2


async def test_a_piece_that_vanished_mid_change_says_so_and_never_crashes(
    backend: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    state = StoryMarkState()
    await StoryMarkState.load_for.fn(state, str(DRAFT))
    monkeypatch.setattr(state_module, "set_story", lambda *_a, **_k: StoryMarkVM())
    assert await _drain(StoryMarkState.set_story.fn(state, True)) == []
    assert state.error == REASON_OTHER and not state.busy


def test_the_toasts_say_where_and_what() -> None:
    assert marked_toast(approved=True).endswith("Aprobados › Historias.")
    assert marked_toast(approved=False).endswith("Por aprobar › Historias.")
    assert unmarked_toast("galeria") == "Listo: vuelve a ser una publicación."
    assert unmarked_toast("reel") == "Listo: vuelve a ser un reel."


def test_the_switch_is_described_by_its_reason() -> None:
    from . import story_mark_ui

    source = inspect.getsource(story_mark_ui.story_mark_control)
    assert '"aria-describedby": _NOTE_ID' in source and "id=_NOTE_ID" in source


async def test_a_refusal_is_said_and_changes_nothing(backend: dict[str, Any]) -> None:
    state = StoryMarkState()
    await StoryMarkState.load_for.fn(state, str(DRAFT))
    backend["refuse"] = REASON_SCHEDULED
    assert await _drain(StoryMarkState.set_story.fn(state, True)) == []
    assert state.error == REASON_SCHEDULED and not state.is_story and not state.busy


def test_the_switch_is_on_the_pieces_page() -> None:
    source = inspect.getsource(creative_pages)
    assert source.count("story_mark_control(") == 2  # both layouts of the piece's page
