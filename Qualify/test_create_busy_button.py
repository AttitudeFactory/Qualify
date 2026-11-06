"""m-24971284: «Crear» says the piece is being created — the kit's ring and «Creando tu
publicación…» on a button that cannot be pressed twice — from the press until the result
shows, and goes back to «Crear» on every refusal."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import reflex as rx
from qualify_api.creative.creations import NotEnoughCreations
from sqlalchemy.exc import SQLAlchemyError

from . import campaign_provider as cp
from . import creative_state as module
from .creative_state import CreativeState
from .creative_vm import CREATING_LABEL
from .test_generator_campaign import _Proxy
from .ui import steps


def _last_step() -> CreativeState:
    state = CreativeState()
    state.choose_category("script")
    state.brief_topic = "La smash doble cayendo en cámara lenta"
    state.product_confirmed = True
    state.go_to_view(str(len(state.gen_views) - 1))
    assert state.gen_is_last_view
    return state


def _session(monkeypatch: pytest.MonkeyPatch) -> None:
    ids = (uuid4(), uuid4(), uuid4())

    async def session_ids(self: CreativeState) -> tuple[UUID, UUID, UUID]:
        return ids

    async def refresh(self: CreativeState, tenant_id: UUID, brand_id: UUID) -> None:
        return None

    monkeypatch.setattr(CreativeState, "_session_ids", session_ids)
    monkeypatch.setattr(CreativeState, "_refresh_creations", refresh)
    monkeypatch.setattr(module, "brand_campaign_options", lambda *a: [])


async def _press_crear(state: CreativeState) -> list[object]:
    return [event async for event in CreativeState.submit_generator_form.fn(_Proxy(state))]


def test_the_primary_reads_crear_then_creating() -> None:
    state = _last_step()
    assert state.create_primary_label == "Crear" and not state.create_primary_busy
    state.is_submitting = True
    assert state.create_primary_label == CREATING_LABEL == "Creando tu publicación…"
    assert state.create_primary_busy and state.create_primary_disabled


async def test_crear_stays_busy_until_the_result_shows(monkeypatch: pytest.MonkeyPatch) -> None:
    """The draft exists before the campaign is applied: «Crear» must not come back in
    that gap (it was pressable again there before this ticket)."""
    _session(monkeypatch)
    draft_id = uuid4()
    seen: list[tuple[bool, bool, str]] = []
    state = _last_step()

    def create(*args: object, **kwargs: object) -> UUID:
        seen.append((state.is_submitting, state.create_primary_busy, state.create_primary_label))
        return draft_id

    def apply(*args: object, **kwargs: object) -> None:
        seen.append((state.is_submitting, state.create_primary_busy, state.create_primary_label))

    monkeypatch.setattr(module, "submit_brief", create)
    monkeypatch.setattr(module, "apply_post_choice", apply)
    state.set_gen_campaign(cp.NEW_CAMPAIGN)
    state.set_gen_campaign_new_name("Navidad")
    await _press_crear(state)
    assert seen == [(True, True, CREATING_LABEL)] * 2
    assert state.generator_view == "result" and state.gen_draft_id == str(draft_id)
    assert not state.is_submitting and not state.create_primary_busy


@pytest.mark.parametrize(
    "error",
    [SQLAlchemyError("db down"), NotEnoughCreations(weight=2, left=1), ValueError("no")],
    ids=["db-error", "price-guard", "invalid"],
)
async def test_a_refusal_puts_crear_back(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    _session(monkeypatch)

    def refuse(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(module, "submit_brief", refuse)
    state = _last_step()
    await _press_crear(state)
    assert not state.is_submitting and state.create_primary_label == "Crear"
    assert state.create_error  # the reason, beside the form
    assert state.generator_view != "result"


async def test_a_failure_after_the_draft_still_clears_the_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session(monkeypatch)
    monkeypatch.setattr(module, "submit_brief", lambda *a, **kw: uuid4())

    async def boom(self: CreativeState, draft_id: UUID, campaign: object) -> None:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(CreativeState, "_assign_gen_campaign", boom)
    state = _last_step()
    with pytest.raises(RuntimeError):
        await _press_crear(state)
    assert not state.is_submitting


async def test_a_second_press_while_busy_creates_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session(monkeypatch)
    calls: list[object] = []
    monkeypatch.setattr(module, "submit_brief", lambda *a, **kw: calls.append(1))
    state = _last_step()
    state.is_submitting = True
    assert await _press_crear(state) == []
    assert calls == []


# -- the view ---------------------------------------------------------------------------


class _Busy(rx.State):
    busy: bool = False


def test_the_foot_shows_the_kits_ring_only_when_busy_is_wired() -> None:
    busy = str(
        steps.step_foot(
            "Crear", step=5, on_primary=rx.console_log("x"), primary_busy=_Busy.busy
        ).render()
    )
    assert "q-spinner" in busy and "aria-busy" in busy.replace("ariaBusy", "aria-busy")
    plain = str(steps.step_foot("Siguiente", step=2, on_primary=rx.console_log("x")).render())
    assert "q-spinner" not in plain


def test_atras_hides_while_busy_and_the_busy_primary_keeps_its_accent() -> None:
    """UX review m-24971284: no «Atrás» while the piece is being created (the result
    shows on its own), and the "not valid yet" grey does not apply to a busy primary."""
    from pathlib import Path

    foot = str(
        steps.step_foot(
            "Crear",
            step=5,
            on_primary=rx.console_log("x"),
            on_back=rx.console_log("back"),
            primary_busy=_Busy.busy,
        ).render()
    )
    assert "Atr" in foot and "busy" in foot.split("Atr")[0]  # «Atrás» sits under the flag
    css = (Path(__file__).resolve().parents[1] / "assets" / "qualify.css").read_text()
    assert ':is(:disabled, [data-disabled]):not([aria-busy="true"])' in css


def test_the_generator_wires_the_busy_primary() -> None:
    from .content_generator import _generator_frame

    rendered = str(_generator_frame().render())
    assert "create_primary_busy" in rendered and "q-spinner" in rendered
