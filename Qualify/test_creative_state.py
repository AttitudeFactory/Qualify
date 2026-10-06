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
