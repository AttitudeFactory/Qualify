"""Tests for the Brand Kit draft/finalized split (request 2026-09-08).

The split: `CreativeState`'s `kit_*` fields ARE the in-session draft — there is no
separate draft table, on purpose (see `_kit_draft_loaded`'s own comment in
`creative_state.py`). `load_brand` used to re-fetch and overwrite them on every
`/brand/manual`/`/brand/connect` `on_load`, which fires on far more than a fresh
visit (a refresh, "Atrás" back out and in, navigating to another screen and back) —
silently discarding whatever the operator had just typed. `_kit_draft_loaded` makes
that fetch-and-apply run exactly once per session; `AuthState.logout` (tested in
`test_auth_state.py`) is what actually clears the draft, by resetting the whole state.

**Why `_session_ids` is monkeypatched rather than exercised for real:** it calls
`self.get_state(AuthState)`, which needs a live Reflex `EventContext` and raises
`LookupError` on a standalone-constructed state — the same pre-existing gap
`test_publishing_state.py`'s own module docstring documents ("no test anywhere in this
repo drives a `rx.State` through its full event-dispatch machinery"). Replacing
`_session_ids` (a plain method, not an `@rx.event`) with a canned coroutine sidesteps
that entirely, so `load_brand` runs for real from that point on — this is a stronger
test than source-inspection alone, not a workaround of last resort. It has to be
patched on the CLASS (`monkeypatch.setattr(CreativeState, ...)`), not the instance:
`rx.State.__setattr__` rejects assigning any name that is not a declared var/backend
var, and a plain private method is neither.
"""

from __future__ import annotations

from uuid import UUID

from . import creative_state as creative_state_module
from .creative_state import CreativeState
from .creative_vm import CopyVariantVM, DraftVM, GapVM, KitFormVM, ReadinessVM
from .pending_state import PendingState

_TENANT_ID = UUID("a0000000-0000-4000-8000-000000000001")
_BRAND_ID = UUID("b0000000-0000-4000-8000-000000000001")
_USER_ID = UUID("c0000000-0000-4000-8000-000000000001")

_READY = ReadinessVM(
    has_kit=True,
    completeness_pct=100,
    has_active_voice=False,
    can_distill=True,
    can_generate=False,
    gaps=(),
)
_NOT_READY = ReadinessVM(
    has_kit=True,
    completeness_pct=40,
    has_active_voice=False,
    can_distill=False,
    can_generate=False,
    gaps=(
        GapVM(
            key="do_examples",
            label="Ejemplos de voz",
            fix_route="/brand/manual",
            fix_label="Completar",
        ),
    ),
)


async def _fake_session_ids(self: CreativeState) -> tuple[UUID, UUID, UUID]:
    return (_TENANT_ID, _BRAND_ID, _USER_ID)


def _state(monkeypatch) -> CreativeState:
    """A standalone `CreativeState` with `_session_ids` faked out — see module
    docstring for why. Patched on the CLASS, not the instance: `rx.State.__setattr__`
    rejects assigning any name that is not a declared var/backend var, `_session_ids`
    (a plain private method, not a state var) included — `monkeypatch.setattr(
    CreativeState, ...)` goes through plain `type.__setattr__` instead, which has no
    such restriction. Every test wires its own `brand_readiness`/`load_kit_form`
    stand-ins via monkeypatch too; this only removes the `get_state(AuthState)` step."""
    monkeypatch.setattr(CreativeState, "_session_ids", _fake_session_ids)
    return CreativeState()


def _stub_provider(monkeypatch, *, form: KitFormVM | None, readiness: ReadinessVM = _READY):
    """Replace the two blocking provider calls `load_brand` makes with counters, so a
    test can assert not just the RESULT but whether the fetch itself was skipped —
    the whole point of `_kit_draft_loaded` is to avoid the DB round-trip, not just to
    avoid applying its result."""
    calls = {"readiness": 0, "load_kit_form": 0}

    def fake_readiness(tenant_id, brand_id):
        calls["readiness"] += 1
        return readiness

    def fake_load_kit_form(tenant_id, brand_id):
        calls["load_kit_form"] += 1
        return form

    monkeypatch.setattr(creative_state_module, "brand_readiness", fake_readiness)
    monkeypatch.setattr(creative_state_module, "load_kit_form", fake_load_kit_form)
    return calls


async def test_load_brand_applies_the_form_on_the_first_call(monkeypatch) -> None:
    form = KitFormVM(positioning="Café de especialidad", audience="Oficinistas del centro")
    calls = _stub_provider(monkeypatch, form=form)
    state = _state(monkeypatch)

    await CreativeState.load_brand.fn(state)

    assert state.kit_positioning == "Café de especialidad"
    assert state.kit_audience == "Oficinistas del centro"
    assert state.readiness == _READY
    assert state._kit_draft_loaded is True
    assert calls["load_kit_form"] == 1


async def test_load_brand_does_not_overwrite_an_in_session_draft_on_a_second_call(
    monkeypatch,
) -> None:
    """The exact bug report (2026-09-08): type into a step, leave the wizard, come
    back — `on_load` fires `load_brand` again. Simulated here as two calls in the same
    state instance, the second with the operator's own unsaved edit already in place."""
    form = KitFormVM(positioning="Café de especialidad")
    calls = _stub_provider(monkeypatch, form=form)
    state = _state(monkeypatch)
    await CreativeState.load_brand.fn(state)

    state.kit_positioning = "Texto que el operador está escribiendo ahora mismo"
    await CreativeState.load_brand.fn(state)

    assert state.kit_positioning == "Texto que el operador está escribiendo ahora mismo"
    assert calls["load_kit_form"] == 1, (
        "the DB form must not even be re-fetched, let alone reapplied"
    )


async def test_load_brand_still_refreshes_readiness_on_a_second_call(monkeypatch) -> None:
    """`readiness` is a derived read, not draft data — it should stay live even once
    the kit fields themselves are frozen for the session."""
    _stub_provider(monkeypatch, form=KitFormVM(), readiness=_NOT_READY)
    state = _state(monkeypatch)
    await CreativeState.load_brand.fn(state)
    assert state.readiness == _NOT_READY

    calls_after = _stub_provider(monkeypatch, form=KitFormVM(), readiness=_READY)
    await CreativeState.load_brand.fn(state)

    assert state.readiness == _READY
    assert calls_after["readiness"] == 1
    assert calls_after["load_kit_form"] == 0


async def test_load_brand_error_leaves_the_draft_flag_unset_for_a_retry(monkeypatch) -> None:
    """A failed load must be retryable on the NEXT `on_load` (e.g. re-entering the
    page), not permanently mistaken for "already loaded" with nothing in state."""

    def raise_db_error(tenant_id, brand_id):
        from sqlalchemy.exc import SQLAlchemyError

        raise SQLAlchemyError("connection refused")

    monkeypatch.setattr(creative_state_module, "brand_readiness", raise_db_error)
    state = _state(monkeypatch)

    await CreativeState.load_brand.fn(state)

    assert state._kit_draft_loaded is False
    assert state.kit_error != ""
    assert state.kit_loading is False


async def test_load_brand_with_no_saved_kit_still_marks_the_session_loaded(monkeypatch) -> None:
    """A brand-new brand has no `brand_kits` row yet (`load_kit_form` returns None) —
    that is a valid "loaded, nothing to load" outcome, not an error, and must still
    flip the flag so the operator's very first keystrokes are not immediately wiped
    by the next `on_load`."""
    _stub_provider(monkeypatch, form=None)
    state = _state(monkeypatch)

    await CreativeState.load_brand.fn(state)

    assert state._kit_draft_loaded is True
    assert state.kit_positioning == ""


# --- draft review: the copy is read-only until "Editar" (request 2026-09-30) ----------


def _review_state(monkeypatch) -> CreativeState:
    variant = CopyVariantVM(
        variant_id="v1",
        ordinal=0,
        label="Variante 1",
        hook="Gancho guardado",
        caption="Caption guardado",
        hashtags_text="#a",
        cta="Pide ya",
        ads_primary_text="",
        ads_headline="",
        ads_description="",
        has_ads=False,
        passed=True,
        failure_labels=(),
        was_edited=False,
        rendered_caption="Caption guardado",
    )
    state = _state(monkeypatch)
    state.draft = DraftVM(
        draft_id="d1",
        status="generated",
        status_label="Por revisar",
        status_tone="warn",
        variants=(variant,),
        can_approve=True,
        can_reject=True,
        can_regenerate=True,
    )
    state.select_variant("v1")
    return state


def test_the_copy_starts_read_only_and_editar_unlocks_it(monkeypatch) -> None:
    state = _review_state(monkeypatch)
    assert state.edit_mode is False
    assert state.can_approve_now  # nothing unsaved
    state.start_edit()
    assert state.edit_mode is True
    assert not state.can_approve_now  # never approve over unsaved edits


def test_cancelar_restores_the_saved_copy_and_locks_the_fields(monkeypatch) -> None:
    state = _review_state(monkeypatch)
    state.start_edit()
    state.set_edit_caption("Algo que no quiero guardar")
    state.cancel_edit()
    assert state.edit_mode is False
    assert state.edit_caption == "Caption guardado"


def test_switching_variant_leaves_edit_mode(monkeypatch) -> None:
    state = _review_state(monkeypatch)
    state.start_edit()
    state.select_variant("v1")
    assert state.edit_mode is False


def test_the_review_editor_adds_and_removes_hashtags_and_uses_a_cta(monkeypatch) -> None:
    state = _state(monkeypatch)
    state.edit_caption = "Promo de hamburguesas dobles este viernes"
    state.edit_hashtags = "#promo"
    assert "hamburguesas" in state.hashtag_suggestions
    state.add_hashtag("hamburguesas")
    assert state.edit_hashtag_chips == ["promo", "hamburguesas"]
    assert "hamburguesas" not in state.hashtag_suggestions
    state.edit_hashtag_query = "#Viernes"
    state.add_typed_hashtag()
    assert state.edit_hashtags == "#promo #hamburguesas #viernes"
    assert state.edit_hashtag_query == ""
    state.remove_hashtag("promo")
    assert state.edit_hashtag_chips == ["hamburguesas", "viernes"]
    assert state.hashtag_count_label == "2/30"
    # Several calls to action, kept as one list in the `cta` field.
    state.edit_cta = ""
    state.add_cta("Escríbenos por DM")
    state.edit_cta_query = "Reserva por WhatsApp"
    state.add_typed_cta()
    state.add_cta("Escríbenos por DM")  # once only
    assert state.cta_chips == ["Escríbenos por DM", "Reserva por WhatsApp"]
    assert state.edit_cta == "Escríbenos por DM · Reserva por WhatsApp"
    assert "Escríbenos por DM" not in state.cta_suggestions
    state.remove_cta("Escríbenos por DM")
    assert state.cta_chips == ["Reserva por WhatsApp"]


def test_ai_hashtag_ideas_are_grouped_and_hide_once_chosen(monkeypatch) -> None:
    from .creative_vm import HashtagIdeaVM

    state = _state(monkeypatch)
    state.ai_hashtags = [
        HashtagIdeaVM(tag="postres", kind="popular", reason="Amplio"),
        HashtagIdeaVM(tag="heladoartesanal", kind="nicho", reason="El tema"),
        HashtagIdeaVM(tag="caracas", kind="marca", reason="El lugar"),
    ]
    assert [h.tag for h in state.ai_popular] == ["postres"]
    assert [h.tag for h in state.ai_niche] == ["heladoartesanal"]
    assert [h.tag for h in state.ai_brand] == ["caracas"]
    state.add_hashtag("postres")
    assert state.ai_popular == [] and state.ai_pending_count == 2
    state.add_all_ai_hashtags()
    assert state.edit_hashtag_chips == ["postres", "heladoartesanal", "caracas"]


def test_caption_rules_show_under_the_caption(monkeypatch) -> None:
    state = _state(monkeypatch)
    state.edit_blocking = [
        "El caption tiene 23 caracteres y tu marca pide al menos 80: agrega 57 más.",
        "Falta la palabra obligatoria «ofertas».",
    ]
    assert len(state.caption_blocking) == 1 and len(state.other_blocking) == 1


def test_rejecting_asks_first_and_only_the_confirmation_discards(monkeypatch) -> None:
    state = _state(monkeypatch)
    state.ask_reject(False)
    assert state.reject_confirm == "reject"
    state.set_reject_confirm_open(False)  # «Volver»: nothing discarded
    assert state.reject_confirm == ""
    state.ask_reject(True)
    assert state.reject_confirm == "regenerate"
    event = state.confirm_reject()
    assert state.reject_confirm == ""
    assert event.handler.fn.__name__ == "reject_current"
    assert "true" in str(event.args).lower()


# --- after approving: «Aprobada. Todavía no se publica.» (m-24842978) ------------------

_DRAFT_UUID = UUID("d0000000-0000-4000-8000-000000000001")


def _approved_vm(draft: DraftVM) -> DraftVM:
    return DraftVM(
        draft_id=str(_DRAFT_UUID),
        status="approved",
        status_label="Aprobado",
        status_tone="grass",
        variants=draft.variants,
    )


_VARIANT_UUID = "e0000000-0000-4000-8000-000000000001"


def _approvable_state(monkeypatch) -> CreativeState:
    """`_review_state`, with a real variant id: `approve_selected` parses it as a UUID."""
    from dataclasses import replace

    state = _review_state(monkeypatch)
    variant = replace(state.draft.variants[0], variant_id=_VARIANT_UUID)
    state.draft = replace(state.draft, variants=(variant,))
    state.select_variant(_VARIANT_UUID)
    return state


def _gallery_with(*, schedulable: bool, note: str = ""):
    """What `load_gallery` would read right after approving: this publication, either
    ready to be given a day and time or «aprobada pero no lista»."""
    from .planner_provider import GalleryData
    from .planner_vm import build_post_option

    post = build_post_option(
        post_id=str(_DRAFT_UUID),
        title="Promo",
        caption_excerpt="",
        thumbnail_url="",
        category="galeria",
        approval="approved",
        detail_href=f"/drafts/{_DRAFT_UUID}",
        is_publishable=schedulable,
        unpublishable_reason=note,
        gallery_state="schedulable" if schedulable else "needs_action",
    )
    return GalleryData(posts=[post])


async def _approve(monkeypatch, state: CreativeState, *, gallery=None) -> list:
    monkeypatch.setattr(CreativeState, "_route_draft_id", lambda self: _DRAFT_UUID)
    monkeypatch.setattr(
        creative_state_module,
        "approve_draft",
        lambda tenant_id, draft_id, variant_id, user_id: _approved_vm(state.draft),
    )
    data = gallery if gallery is not None else _gallery_with(schedulable=True)
    monkeypatch.setattr(creative_state_module, "load_gallery", lambda tenant_id: data)
    events = [event async for event in CreativeState.approve_selected.fn(state)]
    # m-24842963: the menu's recount rides along; these tests read the toast
    return [e for e in events if e is not PendingState.refresh_now]


async def test_approved_but_not_ready_says_what_is_missing_and_offers_no_dead_end(
    monkeypatch,
) -> None:
    state = _approvable_state(monkeypatch)
    note = "Conecta una cuenta de Instagram para publicarla."
    events = await _approve(monkeypatch, state, gallery=_gallery_with(schedulable=False, note=note))

    assert state.show_approved_next is True
    assert state.approved_ready is False
    assert state.approved_note == note
    toast = str(events[-1])
    assert "Publicación aprobada. Revisa lo que falta antes de elegir cuándo sale." in toast
    assert "Ahora elige" not in toast


async def test_an_unreadable_readiness_still_offers_the_way_to_tu_semana(monkeypatch) -> None:
    state = _approvable_state(monkeypatch)

    def boom(tenant_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(CreativeState, "_route_draft_id", lambda self: _DRAFT_UUID)
    monkeypatch.setattr(
        creative_state_module,
        "approve_draft",
        lambda tenant_id, draft_id, variant_id, user_id: _approved_vm(state.draft),
    )
    monkeypatch.setattr(creative_state_module, "load_gallery", boom)
    events = [event async for event in CreativeState.approve_selected.fn(state)]
    events = [e for e in events if e is not PendingState.refresh_now]  # m-24842963

    assert state.show_approved_next is True and state.approved_ready is True
    assert "Publicación aprobada. Ahora elige cuándo sale." in str(events[-1])


async def test_approving_shows_the_next_step_and_a_toast_that_says_it_is_not_out(
    monkeypatch,
) -> None:
    state = _approvable_state(monkeypatch)
    assert state.show_approved_next is False

    events = await _approve(monkeypatch, state)

    assert state.just_approved is True
    assert state.show_approved_next is True
    toast = str(events[-1])
    assert "Publicación aprobada. Ahora elige cuándo sale." in toast
    assert "POST aprobado" not in toast


async def test_elegir_dia_y_hora_opens_tu_semana_on_this_publication(monkeypatch) -> None:
    state = _approvable_state(monkeypatch)
    await _approve(monkeypatch, state)

    event = state.go_schedule()

    assert f"/planner?post={_DRAFT_UUID}" in str(event)


async def test_publicar_ahora_opens_tu_semana_on_ahora(monkeypatch) -> None:
    # m-24842985: the soft «Publicar ahora» opens the same drawer with «Ahora» chosen;
    # the owner still taps «Programar» there.
    state = _approvable_state(monkeypatch)
    await _approve(monkeypatch, state)

    event = state.go_publish_now()

    assert f"/planner?post={_DRAFT_UUID}&cuando=ahora" in str(event)


async def test_the_card_goes_away_once_the_draft_is_back_in_review(monkeypatch) -> None:
    state = _approvable_state(monkeypatch)
    await _approve(monkeypatch, state)
    # saving an edit sends an approved draft back to review
    state.draft = DraftVM(
        draft_id=str(_DRAFT_UUID),
        status="generated",
        status_label="Por revisar",
        status_tone="warn",
        can_approve=True,
    )
    assert state.show_approved_next is False


def test_crear_otra_publicacion_goes_to_create_and_clears_the_card(monkeypatch) -> None:
    state = _review_state(monkeypatch)
    state.just_approved = True
    event = state.go_create_another()
    assert state.just_approved is False
    assert "/create" in str(event)


def test_the_old_approved_toast_is_gone_from_the_review_screen() -> None:
    from pathlib import Path

    source = Path(creative_state_module.__file__).read_text(encoding="utf-8")
    assert "POST aprobado" not in source


def test_the_review_screen_swaps_the_decision_for_the_approved_card() -> None:
    import json

    from . import creative_pages

    rendered = str(creative_pages._decision_bar())
    for text in (
        "Aprobada. Todavía no se publica.",
        "Elige el día y la hora en que sale.",
        "Elegir día y hora",
        "Crear otra publicación",
        "Revisa lo que falta antes de elegir cuándo sale.",
        "Te quedas con esta versión. Después eliges el día y la hora en que sale.",
        "show_approved_next",
        "approved_can_schedule",
        "approved_hold_note",
    ):
        # the compiled JSX escapes non-ASCII («í» → «í»)
        assert json.dumps(text)[1:-1] in rendered, text
    # N12: ≥ 44 px tap targets on a phone — both card buttons and the three decisions
    assert rendered.count("2.75rem") >= 5


def test_the_gallery_card_offers_the_same_name_as_the_approved_card() -> None:
    import json

    from . import creative_pages
    from .planner_vm import CARD_STATES
    from .test_campaigns_ui import _PostVar

    rendered = str(creative_pages._gallery_card(_PostVar))
    # m-24842981: the card's one main button comes from its state's view-model
    assert CARD_STATES["ready"].action_label == creative_pages.APPROVED_SCHEDULE
    assert "card_action_label" in rendered
    assert '"Programar"' not in rendered and json.dumps("Programar") not in rendered


async def test_approving_a_draft_whose_final_renders_holds_the_day_and_time(
    monkeypatch,
) -> None:
    """m-24820142 over m-24842978: approving a Seedance 2.5 draft orders its 1080p
    final; until it lands the publication cannot be scheduled (MEDIA_DRAFT_PENDING), so
    the toast says the final is being made, the card offers no «Elegir día y hora» and
    says why, and the final poll starts. When the final lands, the card asks again and
    offers the way."""
    from dataclasses import replace

    from .creative_vm import FINAL_READY_TEXT, FINAL_RENDERING_NOTE, video_draft_vm

    state = _approvable_state(monkeypatch)
    monkeypatch.setattr(CreativeState, "_route_draft_id", lambda self: _DRAFT_UUID)
    rendering = video_draft_vm("rendering", None)
    monkeypatch.setattr(
        creative_state_module,
        "approve_draft",
        lambda tenant_id, draft_id, variant_id, user_id: replace(
            _approved_vm(state.draft), video_draft=rendering
        ),
    )
    pending = _gallery_with(schedulable=False, note="El video es todavía un borrador.")
    monkeypatch.setattr(creative_state_module, "load_gallery", lambda tenant_id: pending)
    events = [event async for event in CreativeState.approve_selected.fn(state)]

    toast = str(events[0])
    assert "Estamos preparando el video en alta calidad" in toast
    assert "Ahora elige" not in toast and "Revisa lo que falta" not in toast
    assert events[-1] is CreativeState.poll_final
    assert state._final_polling_id == str(_DRAFT_UUID)
    assert state.show_approved_next is True
    assert state.approved_can_schedule is False
    assert state.approved_hold_note == FINAL_RENDERING_NOTE

    # the final lands while the page watches: Tu semana's reader now says it can go out
    final = replace(state.draft, video_draft=video_draft_vm("final", None))
    monkeypatch.setattr(creative_state_module, "_FINAL_POLL_SECONDS", 0)
    monkeypatch.setattr(creative_state_module, "final_video_state", lambda t, d: final.video_draft)
    monkeypatch.setattr(creative_state_module, "draft_detail", lambda t, d: final)
    ready = _gallery_with(schedulable=True)
    monkeypatch.setattr(creative_state_module, "load_gallery", lambda tenant_id: ready)
    events = [e async for e in CreativeState.poll_final.fn(state)]

    assert len(events) == 1 and FINAL_READY_TEXT in str(events[0])
    assert state.approved_can_schedule is True and state.approved_hold_note == ""


async def test_approving_a_draft_whose_final_could_not_be_ordered_says_so(
    monkeypatch,
) -> None:
    from dataclasses import replace

    from .creative_vm import FINAL_FAILED_NOTE, video_draft_vm

    state = _approvable_state(monkeypatch)
    monkeypatch.setattr(CreativeState, "_route_draft_id", lambda self: _DRAFT_UUID)
    failed = video_draft_vm("failed", None, "x", approved=True)
    monkeypatch.setattr(
        creative_state_module,
        "approve_draft",
        lambda tenant_id, draft_id, variant_id, user_id: replace(
            _approved_vm(state.draft), video_draft=failed
        ),
    )
    ready = _gallery_with(schedulable=True)
    monkeypatch.setattr(creative_state_module, "load_gallery", lambda tenant_id: ready)
    events = [event async for event in CreativeState.approve_selected.fn(state)]
    events = [e for e in events if e is not PendingState.refresh_now]  # m-24842963

    assert len(events) == 1 and "Puedes reintentarlo" in str(events[0])
    assert state.approved_ready is True  # the grid alone would offer the way …
    assert state.approved_can_schedule is False  # … but the failed final holds it back
    assert state.approved_hold_note == FINAL_FAILED_NOTE


# -- the 1080p final poll (m-24820142, review 2026-10-23) ------------------------------


def _video(state: str, *, rendering: bool = False):  # noqa: ANN202
    from .creative_vm import VideoDraftVM

    return VideoDraftVM(state, "", "info", "", rendering=rendering)


def _final_vm(draft_id: str, state: str, *, rendering: bool = False):  # noqa: ANN202
    from types import SimpleNamespace

    return SimpleNamespace(draft_id=draft_id, video_draft=_video(state, rendering=rendering))


def _polling(monkeypatch, piece: str, states: list) -> tuple[CreativeState, list, list]:  # noqa: ANN001
    """A state showing `piece` (its final rendering) and polling it; the light reads
    answer `states` in turn (the last one repeats); returns (state, light reads, full
    reloads)."""
    state = _state(monkeypatch)
    state.draft = _final_vm(piece, "rendering", rendering=True)
    state._final_polling_id = piece
    monkeypatch.setattr(creative_state_module, "_FINAL_POLL_SECONDS", 0)
    light: list = []
    full: list = []

    def fake_state(tenant_id, draft_id):  # noqa: ANN001, ANN202
        light.append(draft_id)
        return states[min(len(light), len(states)) - 1]

    def fake_detail(tenant_id, draft_id):  # noqa: ANN001, ANN202
        full.append(draft_id)
        return _final_vm(piece, light and states[min(len(light), len(states)) - 1].state)

    monkeypatch.setattr(creative_state_module, "final_video_state", fake_state)
    monkeypatch.setattr(creative_state_module, "draft_detail", fake_detail)
    # when the final lands the «Aprobada» card asks Tu semana's reader again (m-24842978)
    monkeypatch.setattr(
        creative_state_module, "load_gallery", lambda tenant_id: _gallery_with(schedulable=True)
    )
    return state, light, full


async def test_a_final_poll_stops_when_another_piece_takes_the_slot(monkeypatch) -> None:
    """A stale poll (its piece no longer owns `_final_polling_id`) stops without a
    toast and leaves the new owner's slot alone."""
    piece_a, piece_b = str(UUID(int=10)), str(UUID(int=11))
    rendering = _video("rendering", rendering=True)
    state, light, _ = _polling(monkeypatch, piece_a, [rendering])
    real_sleep = creative_state_module.asyncio.sleep

    async def sleep(seconds: float) -> None:
        if light:  # after the first look: the operator opened B, whose final renders
            state._final_polling_id = piece_b
        await real_sleep(0)

    monkeypatch.setattr(creative_state_module.asyncio, "sleep", sleep)
    events = [e async for e in CreativeState.poll_final.fn(state)]

    assert events == [] and len(light) == 1
    assert state._final_polling_id == piece_b


async def test_a_final_poll_stops_when_another_piece_is_opened(monkeypatch) -> None:
    """Review round 3: the operator opened a piece WITHOUT a final of its own (nothing
    took the slot): the poll for the old one stops on its next tick, says nothing on
    the new piece's page, and frees the slot."""
    piece_a, piece_b = str(UUID(int=13)), str(UUID(int=14))
    state, light, full = _polling(monkeypatch, piece_a, [_video("final")])
    state.draft = _final_vm(piece_b, "")  # B is on screen now

    events = [e async for e in CreativeState.poll_final.fn(state)]

    assert events == [] and light == [] and full == []
    assert state._final_polling_id == ""
    assert state.draft.draft_id == piece_b  # the page's piece is left alone


async def test_a_final_poll_toasts_and_frees_its_slot_when_the_final_lands(monkeypatch) -> None:
    piece = str(UUID(int=12))
    state, _, full = _polling(monkeypatch, piece, [_video("final")])
    events = [e async for e in CreativeState.poll_final.fn(state)]
    assert len(events) == 1 and state._final_polling_id == ""
    assert len(full) == 1 and state.draft.video_draft.state == "final"


async def test_a_final_poll_never_touches_the_edits_in_progress(monkeypatch) -> None:
    """Review round 3: the poll refreshes the video, never what the operator is typing
    nor the AI hashtag suggestions."""
    from .creative_vm import HashtagIdeaVM

    piece = str(UUID(int=15))
    state, _, full = _polling(monkeypatch, piece, [_video("final")])
    state.edit_mode = True
    state.edit_caption = "Lo que estoy escribiendo"
    state.edit_hook = "Mi gancho"
    state.edit_hashtags = "#helado"
    state.ai_hashtags = [HashtagIdeaVM(tag="postres", kind="popular", reason="Amplio")]

    events = [e async for e in CreativeState.poll_final.fn(state)]

    assert len(events) == 1 and len(full) == 1
    assert state.edit_caption == "Lo que estoy escribiendo" and state.edit_hook == "Mi gancho"
    assert state.edit_hashtags == "#helado" and [h.tag for h in state.ai_hashtags] == ["postres"]


async def test_a_final_poll_reads_the_whole_piece_only_when_its_state_changes(
    monkeypatch,
) -> None:
    """Review round 3: every tick is a light read; the whole piece only when the
    draft-video state moved (and once more when the final lands)."""
    piece = str(UUID(int=16))
    rendering = _video("rendering", rendering=True)
    state, light, full = _polling(
        monkeypatch, piece, [rendering, rendering, rendering, _video("final")]
    )

    events = [e async for e in CreativeState.poll_final.fn(state)]

    assert len(light) == 4 and len(full) == 1 and len(events) == 1


async def test_a_final_poll_outlasts_the_stale_threshold_and_shows_retry(monkeypatch) -> None:
    """Review round 3: the poll window is longer than the stale threshold (one source
    of truth), so a final left half-made turns retryable while the page still watches;
    and when the window ends while it still renders, the last tick refreshes the piece
    — the screen shows what is true without a reload."""
    from qualify_api.creative.draft_mode import FINAL_STALE_SECONDS

    assert creative_state_module._FINAL_POLL_BUDGET_SECONDS > FINAL_STALE_SECONDS

    piece = str(UUID(int=17))
    rendering = _video("rendering", rendering=True)
    state, light, full = _polling(monkeypatch, piece, [rendering])
    monkeypatch.setattr(creative_state_module, "_FINAL_POLL_BUDGET_SECONDS", 0)

    events = [e async for e in CreativeState.poll_final.fn(state)]

    assert events == [] and len(light) == 1 and len(full) == 1  # the last look reloads
    assert state._final_polling_id == ""

    # the stale final shows as failed on the light read: reloaded, toasted, «Reintentar»
    state, _, full = _polling(monkeypatch, piece, [_video("failed")])
    events = [e async for e in CreativeState.poll_final.fn(state)]
    assert len(events) == 1 and len(full) == 1 and "reintentarlo" in str(events[0])


def test_the_final_polls_light_read_is_the_screens_own_state(monkeypatch) -> None:
    """`final_video_state` turns the draft row and its draft videos into the same
    `VideoDraftVM` the full read gives — an approved piece whose final was never
    ordered shows «Reintentar» — and None when the piece is gone."""
    import time
    from types import SimpleNamespace

    from . import creative_provider

    rendering = {"draft": {"status": "rendering", "rendering_at": time.time()}}
    answers = {
        UUID(int=20): ("approved", (rendering,)),
        UUID(int=21): ("approved", ({"draft": {"status": "draft"}},)),
    }
    service = SimpleNamespace(
        video_drafts_state=lambda *, tenant_id, draft_id: answers.get(draft_id)
    )
    monkeypatch.setattr(creative_provider, "production_content_service", lambda: service)

    assert creative_provider.final_video_state(_TENANT_ID, UUID(int=20)).rendering
    never_ordered = creative_provider.final_video_state(_TENANT_ID, UUID(int=21))
    assert never_ordered.can_retry and never_ordered.state == "failed"
    assert creative_provider.final_video_state(_TENANT_ID, UUID(int=22)) is None
