"""QUA-118 Phase 4: the POST gallery (`/drafts`) — derived states on the shared card
view-model, filters, the gallery state, and the calendar's drag & drop. No Reflex
runtime beyond state objects, no database."""

from __future__ import annotations

import ast
import textwrap

from qualify_api.planner.gallery import GalleryState as DerivedState

from .gallery_state import GalleryState
from .planner_state import MODE_ASSIGN, PlannerState
from .planner_vm import (
    CARD_ACTION_REVIEW,
    CARD_ACTION_SCHEDULE,
    CARD_ACTION_VIEW,
    CARD_STATES,
    GALLERY_FILTER_ALL,
    GALLERY_LABELS,
    GALLERY_STATE_FILTERS,
    STEP_WHEN,
    CategoryOptionVM,
    ConnectionChoiceVM,
    build_post_option,
    card_state,
    category_options,
    filter_posts,
    history_help,
    history_word,
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
    assert words == {"Creándose", "Le falta algo", "Lista para programar", "Ya salió", "Descartada"}
    assert words.isdisjoint({"Programado", "Pendiente", "Publicado", "Vencido", "Fallido"})
    # m-24842981: the filters are the card's states — «Por revisar» split out first
    assert [label for _value, label in GALLERY_STATE_FILTERS] == [
        "Por revisar",
        "Le falta algo",
        "Lista para programar",
        "Ya salió",
        "Descartada",
        "Creándose",
    ]


def test_the_card_carries_state_word_tone_and_history_badges() -> None:
    post = _post("p1", state="schedulable", times_published=3, has_live_event=True)
    assert (post.gallery_label, post.gallery_tone) == ("Lista para programar", "ok")
    assert post.used_count == 3 and post.in_calendar is True
    used = _post("p2", state="used", times_published=1)
    assert (used.gallery_label, used.gallery_tone) == ("Ya salió", "info")
    draft = _post("p3", state="draft", approval="not_ready", is_publishable=False)
    assert (draft.gallery_label, draft.gallery_tone) == ("Creándose", "neutral")
    assert not draft.schedulable
    unknown = _post("p4", state="")
    assert (unknown.gallery_label, unknown.gallery_tone) == ("", "neutral")
    assert unknown.card_state == ""


# --- m-24842981 (CREAR-3): the state in words and ONE main button per card --------------


def test_each_card_state_has_its_words_and_its_one_main_button() -> None:
    cases = {
        "review": _post("a", state="needs_action", lifecycle_status="generated"),
        "missing": _post(
            "b", state="needs_action", approval="approved", lifecycle_status="approved"
        ),
        "ready": _post("c", state="schedulable"),
        "used": _post("d", state="used", times_published=1),
        "discarded": _post("e", state="discarded", approval="rejected"),
        "drafting": _post("f", state="draft", approval="not_ready", lifecycle_status="drafting"),
    }
    seen = {
        key: (p.card_state, p.card_label, p.card_action, p.card_action_label)
        for key, p in cases.items()
    }
    assert seen == {
        "review": ("review", "Por revisar", CARD_ACTION_REVIEW, "Revisar"),
        "missing": ("missing", "Le falta algo", CARD_ACTION_REVIEW, "Ver qué falta"),
        "ready": ("ready", "Lista para programar", CARD_ACTION_SCHEDULE, "Elegir día y hora"),
        "used": ("used", "Ya salió", CARD_ACTION_VIEW, "Ver"),
        "discarded": ("discarded", "Descartada", CARD_ACTION_VIEW, "Ver"),
        "drafting": ("drafting", "Creándose", CARD_ACTION_VIEW, "Ver"),
    }
    # the drawer's pill prints the same words as the card
    assert cases["review"].gallery_label == "Por revisar"


def test_waiting_for_review_wins_over_what_else_is_missing() -> None:
    assert card_state("needs_action", waiting_review=True) == CARD_STATES["review"]
    assert card_state("needs_action", waiting_review=False) == CARD_STATES["missing"]
    assert card_state("schedulable", waiting_review=True) == CARD_STATES["ready"]
    assert card_state("nonsense", waiting_review=False) is None


def test_history_word_and_its_visible_help() -> None:
    assert (history_word(0), history_help(0)) == (
        "Por probar",
        "Todavía no ha salido en tus redes.",
    )
    assert (history_word(1), history_help(1)) == ("Por probar", "Salió 1 vez en tus redes.")
    assert (history_word(3), history_help(3)) == (
        "Ya probada",
        "Ya salió 3 veces en tus redes: se puede repetir sin problema.",
    )
    post = _post("a", state="schedulable", times_published=3)
    assert (post.history_word, post.history_help) == (history_word(3), history_help(3))


def test_the_gallery_card_prints_no_cold_hot_or_evergreen_and_no_title_only_help() -> None:
    """m-24842981: no visible «Cold», «Hot» nor «evergreen» on «Por aprobar» and its
    publication page, and the help is not in a `title=` attribute."""
    import inspect

    from . import creative_pages

    sources = [
        inspect.getsource(fn)
        for fn in (
            creative_pages._gallery_state_badge,
            creative_pages._card_main_button,
            creative_pages._gallery_card,
            creative_pages._history_line,
            creative_pages.drafts_index,
        )
    ]
    strings = [
        node.value
        for src in sources
        for node in ast.walk(ast.parse(textwrap.dedent(src)))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    # "cold" / "hot" in lower case are the temperature keys (class names, comparisons)
    for s in strings:
        tokens = s.replace("·", " ").split()
        assert "Cold" not in tokens and "Hot" not in tokens, s
        assert "evergreen" not in s.lower(), s
    for src in sources:
        tree = ast.parse(textwrap.dedent(src))
        assert not any(isinstance(k, ast.keyword) and k.arg == "title" for k in ast.walk(tree))
    words = {label for _key, label in GALLERY_STATE_FILTERS}
    words |= {s.action_label for s in CARD_STATES.values()}
    assert not any(w in " ".join(words) for w in ("Cold", "Hot", "evergreen", "POST"))


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
    assert [p.post_id for p in filter_posts(posts, state="drafting", category="reel")] == []
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
    assert state.state_counts["ready"] == 2 and state.state_counts["discarded"] == 1
    assert state.state_counts["drafting"] == 0 and state.state_counts["review"] == 0
    state.set_state_filter("ready")
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


def test_every_screen_that_approves_a_draft_says_why_a_price_blocks_it() -> None:
    """Ticket 24803289: the content service refuses a variations piece whose copy quotes
    a price that is not the catalog's (`ApprovalBlocked`). Every screen that approves
    through `approve_draft` — the POST's page and the gallery card — must show that
    reason, not a generic error (the gallery card did, before this test)."""
    import ast
    from pathlib import Path

    here = Path(__file__).parent
    callers = []
    for path in sorted(here.glob("*.py")):
        if path.name.startswith("test_") or path.name == "creative_provider.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
            if "approve_draft" not in names:
                continue
            handled = {
                h.type.id
                for h in ast.walk(fn)
                if isinstance(h, ast.ExceptHandler) and isinstance(h.type, ast.Name)
            }
            callers.append((path.name, fn.name, "ApprovalBlocked" in handled))
    assert {(f, n) for f, n, _ in callers} >= {
        ("creative_state.py", "approve_selected"),
        ("gallery_state.py", "quick_approve"),
    }
    assert all(ok for _, _, ok in callers), callers


# --- «Aprobar» on a card says it is not out yet (m-24842978) ----------------------------

_QA_POST_ID = "d0000000-0000-4000-8000-000000000002"


async def _quick_approve(monkeypatch, gallery) -> tuple[GalleryState, list, list]:
    """Run «Aprobar» on a card with the backend faked: `gallery` is what the grid reads
    right after approving (a `GalleryData`, or an exception to raise)."""
    from uuid import UUID

    from . import gallery_state as gallery_state_module
    from .creative_vm import CopyVariantVM, DraftVM

    variant = CopyVariantVM(
        variant_id="e0000000-0000-4000-8000-000000000002",
        ordinal=0,
        label="Variante 1",
        hook="Gancho",
        caption="Texto",
        hashtags_text="",
        cta="",
        ads_primary_text="",
        ads_headline="",
        ads_description="",
        has_ads=False,
        passed=True,
        failure_labels=(),
        was_edited=False,
        rendered_caption="Texto",
    )
    draft = DraftVM(
        draft_id=_QA_POST_ID,
        status="generated",
        status_label="Por revisar",
        status_tone="warn",
        variants=(variant,),
        can_approve=True,
    )

    async def fake_tenant(self):
        return UUID("a0000000-0000-4000-8000-000000000001")

    def fake_load_gallery(tenant_id):
        if isinstance(gallery, Exception):
            raise gallery
        return gallery

    approved: list[UUID] = []
    monkeypatch.setattr(GalleryState, "_tenant", fake_tenant)
    monkeypatch.setattr(gallery_state_module, "acting_user_id", lambda tenant_id: tenant_id)
    monkeypatch.setattr(gallery_state_module, "draft_detail", lambda tenant_id, draft_id: draft)
    monkeypatch.setattr(
        gallery_state_module,
        "approve_draft",
        lambda tenant_id, draft_id, variant_id, user_id: approved.append(draft_id),
    )
    monkeypatch.setattr(gallery_state_module, "load_gallery", fake_load_gallery)

    state = GalleryState()
    events = [e async for e in GalleryState.quick_approve.fn(state, _QA_POST_ID)]
    return state, events, approved


def _gallery(*, schedulable: bool, note: str = ""):
    from .planner_provider import GalleryData

    if schedulable:
        return GalleryData(posts=[_post(_QA_POST_ID, state="schedulable")])
    # «aprobada pero no lista»: approved, but the evaluator says it cannot go out yet
    post = _post(
        _QA_POST_ID,
        state="needs_action",
        approval="approved",
        is_publishable=False,
        unpublishable_reason=note,
    )
    return GalleryData(posts=[post])


async def test_quick_approve_toast_says_not_out_yet_and_offers_elegir_dia_y_hora(
    monkeypatch,
) -> None:
    from uuid import UUID

    from . import gallery_state as gallery_state_module
    from .creative_state import APPROVED_TOAST as DRAFT_PAGE_TOAST

    state, events, approved = await _quick_approve(monkeypatch, _gallery(schedulable=True))

    assert approved == [UUID(_QA_POST_ID)]
    assert [p.post_id for p in state.posts] == [_QA_POST_ID]  # the grid is fresh
    assert gallery_state_module.APPROVED_TOAST == DRAFT_PAGE_TOAST  # one wording, both places
    toast = str(events[0])
    assert "Publicación aprobada. Ahora elige cuándo sale." in toast
    # the action button, wired to Tu semana's drawer on this publication
    assert "label='Elegir día y hora'" in toast and '["onClick"]' in toast
    assert f"/planner?post={_QA_POST_ID}" in toast
    assert "POST aprobado" not in toast
    assert len(events) == 1  # no second read of the grid


async def test_quick_approve_of_a_not_ready_publication_offers_no_dead_end(monkeypatch) -> None:
    gallery = _gallery(schedulable=False, note="Conecta una cuenta de Instagram.")
    state, events, _ = await _quick_approve(monkeypatch, gallery)

    assert state.posts[0].readiness_note == "Conecta una cuenta de Instagram."
    toast = str(events[0])
    assert "Publicación aprobada. Revisa lo que falta antes de elegir cuándo sale." in toast
    assert "Elegir d" not in toast and "/planner" not in toast


async def test_quick_approve_with_an_unreadable_grid_still_offers_the_way(monkeypatch) -> None:
    _state, events, _ = await _quick_approve(monkeypatch, RuntimeError("db down"))

    # the approval stands, so the way to Tu semana is offered (it is the real gate) …
    assert f"/planner?post={_QA_POST_ID}" in str(events[0])
    # … and the grid is read again by `load`, which shows its own error if it fails
    assert events[-1] is GalleryState.load


def test_schedule_readiness_reads_the_publication_from_the_grid() -> None:
    from .gallery_state import schedule_readiness

    ready = _post("p1", state="schedulable")
    not_ready = _post(
        "p2",
        state="needs_action",
        approval="approved",
        is_publishable=False,
        unpublishable_reason="Falta la foto.",
    )
    assert schedule_readiness([ready, not_ready], "p1") == (True, "")
    assert schedule_readiness([ready, not_ready], "p2") == (False, "Falta la foto.")
    # not in the grid: Tu semana stays the gate and says why itself
    assert schedule_readiness([], "p3") == (True, "")


def test_gallery_review_errors_speak_of_the_publication() -> None:
    from . import gallery_state as gallery_state_module

    for text in (gallery_state_module._REVIEW_FAILED, gallery_state_module._NO_PASSING_VARIANT):
        assert "POST" not in text and "variante" not in text
