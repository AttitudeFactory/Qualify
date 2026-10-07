"""QUA-118 Phase 4: the POST gallery (`/drafts`) — derived states on the shared card
view-model, filters, the gallery state, and the calendar's drag & drop. No Reflex
runtime beyond state objects, no database."""

from __future__ import annotations

from qualify_api.planner.gallery import GalleryState as DerivedState

from .gallery_state import GalleryState
from .planner_state import MODE_ASSIGN, PlannerState
from .planner_vm import (
    GALLERY_FILTER_ALL,
    GALLERY_LABELS,
    GALLERY_STATE_FILTERS,
    STEP_WHEN,
    CategoryOptionVM,
    ConnectionChoiceVM,
    build_post_option,
    category_options,
    filter_posts,
)


def _post(post_id: str, *, state: str = "schedulable", category: str = "galeria", **kw: object):
    params: dict[str, object] = {
        "post_id": post_id,
        "title": "Promo " + post_id,
        "caption_excerpt": "",
        "thumbnail_url": "",
        "category": category,
        "approval": "approved" if state in ("schedulable", "used") else "pending",
        "detail_href": "/drafts/" + post_id,
        "is_publishable": state in ("schedulable", "used"),
        "unpublishable_reason": "",
        "gallery_state": state,
    }
    params.update(kw)
    return build_post_option(**params)  # type: ignore[arg-type]


# --- the card's derived state and history --------------------------------------------


def test_gallery_labels_are_the_five_post_states_and_none_of_the_event_words() -> None:
    assert {s.value for s in DerivedState} == set(GALLERY_LABELS)
    words = {label for label, _tone in GALLERY_LABELS.values()}
    assert words == {"Borrador", "Por completar", "Listo", "Usado", "Desechado"}
    assert words.isdisjoint({"Programado", "Pendiente", "Publicado", "Vencido", "Fallido"})
    assert [value for value, _label in GALLERY_STATE_FILTERS] == list(GALLERY_LABELS)


def test_the_card_carries_state_word_tone_and_history_badges() -> None:
    post = _post("p1", state="schedulable", times_published=3, has_live_event=True)
    assert (post.gallery_label, post.gallery_tone) == ("Listo", "ok")
    assert post.used_count == 3 and post.in_calendar is True  # Listo + Usado ×3 + En calendario
    used = _post("p2", state="used", times_published=1)
    assert (used.gallery_label, used.gallery_tone) == ("Usado", "info")
    draft = _post("p3", state="draft", approval="not_ready", is_publishable=False)
    assert (draft.gallery_label, draft.gallery_tone) == ("Borrador", "neutral")
    assert not draft.schedulable
    unknown = _post("p4", state="")
    assert (unknown.gallery_label, unknown.gallery_tone) == ("", "neutral")


def test_the_media_label_names_medium_and_format() -> None:
    assert _post("a", category="reel", video_url="/r2media/x").media_label == "Video · Reel 9:16"
    assert _post("b", category="galeria").media_label == "Imagen · Galería 1:1"
    assert _post("c", category="story").media_label == "Imagen · Historia 9:16"
    assert _post("d", category="").media_label == "Imagen · Publicación 4:5"


# --- filters --------------------------------------------------------------------------


def test_filter_posts_by_state_and_category() -> None:
    posts = [
        _post("a", state="schedulable", category="reel"),
        _post("b", state="draft", category="galeria"),
        _post("c", state="used", category="reel"),
        _post("d", state="discarded", category="story"),
    ]
    assert [p.post_id for p in filter_posts(posts, state=GALLERY_FILTER_ALL, category="")] == [
        "a",
        "b",
        "c",
        "d",
    ]
    assert [p.post_id for p in filter_posts(posts, state="used", category="all")] == ["c"]
    assert [p.post_id for p in filter_posts(posts, state="all", category="reel")] == ["a", "c"]
    assert [p.post_id for p in filter_posts(posts, state="draft", category="reel")] == []
    assert category_options(posts) == [
        CategoryOptionVM(value="reel", label="Reel"),
        CategoryOptionVM(value="galeria", label="Galería"),
        CategoryOptionVM(value="story", label="Story"),
    ]


def test_gallery_state_filters_count_and_clear() -> None:
    state = GalleryState()
    state.posts = [
        _post("a", state="schedulable", category="reel"),
        _post("b", state="schedulable", category="galeria"),
        _post("c", state="discarded", category="reel"),
    ]
    assert state.total_count == 3 and state.visible_count == 3 and not state.is_filtered
    assert state.state_counts["all"] == 3
    assert state.state_counts["schedulable"] == 2 and state.state_counts["discarded"] == 1
    assert state.state_counts["draft"] == 0
    state.set_state_filter("schedulable")
    state.set_category_filter("reel")
    assert [p.post_id for p in state.visible] == ["a"] and state.is_filtered
    state.set_state_filter("nonsense")  # unknown → all
    assert state.state_filter == GALLERY_FILTER_ALL
    state.clear_filters()
    assert state.visible_count == 3 and not state.is_filtered


def test_assign_from_the_gallery_hands_the_post_to_the_planner_drawer() -> None:
    event = GalleryState().assign("p9")
    assert "/planner?post=p9" in str(event.args)


# --- drag & drop into a calendar cell ------------------------------------------------


def _planner() -> PlannerState:
    state = PlannerState()
    state.connections = [ConnectionChoiceVM(id="c1", label="@bianki", platform="instagram")]
    state.monday_iso = "2026-09-21"
    state.today_iso = "2026-09-23"
    state.schedulable = [_post("p1")]
    return state


def test_dropping_a_card_on_a_cell_opens_the_drawer_prefilled_and_creates_nothing() -> None:
    state = _planner()
    state.start_drag("p1")
    assert state.dragging
    state.drop_on_slot("2026-09-25", 15)
    assert not state.dragging and state.form_open
    assert state.form_mode == MODE_ASSIGN
    [item] = state.plan_items
    assert item.post_id == "p1" and (item.date, item.time) == ("2026-09-25", "15:00")
    assert state.form_step == STEP_WHEN  # the POST is chosen: straight to its programming
    assert item.connection_ids == ["c1"]


def test_a_drop_on_a_past_day_or_without_a_drag_does_nothing() -> None:
    state = _planner()
    state.drop_on_slot("2026-09-25", 9)  # nothing being dragged
    assert not state.form_open
    state.start_drag("p1")
    state.drop_on_slot("2026-09-22", 9)  # yesterday
    assert not state.form_open and not state.dragging
    state.start_drag("p1")
    state.end_drag()  # released outside any cell
    assert not state.dragging and not state.form_open


# --- QUA-118 v2 polish: order and quick review ------------------------------------------


def test_the_gallery_shows_ready_posts_first_and_history_last() -> None:
    from .gallery_state import sort_for_gallery

    posts = [
        _post("a", state="discarded"),
        _post("b", state="needs_action"),
        _post("c", state="schedulable"),
        _post("d", state="used"),
        _post("e", state="schedulable"),
    ]
    assert [p.post_id for p in sort_for_gallery(posts)] == ["c", "e", "b", "d", "a"]


def test_only_a_post_waiting_for_review_offers_approve_and_reject() -> None:
    assert _post("a", state="needs_action", lifecycle_status="generated").can_review
    assert not _post("b", state="schedulable", lifecycle_status="approved").can_review
    assert not _post("c", state="discarded", lifecycle_status="rejected").can_review


def test_rejecting_from_a_card_asks_first() -> None:
    state = GalleryState()
    state.ask_reject_post("p1", "Promo p1")
    assert (state.reject_post_id, state.reject_post_title) == ("p1", "Promo p1")
    state.set_reject_post_open(False)  # «Volver»
    assert state.reject_post_id == "" and state.reject_post_title == ""
