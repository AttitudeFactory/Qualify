"""m-24842984 (PUBLICAR-2, UX epic m-24842956): approve or turn down a publication from its
panel in Tu semana.

- A publication «En revisión» shows «No la quiero» (outlined red) and «Aprobar» (solid),
  under «Nada sale sin tu aprobación. Si la apruebas, sale el {día} a las {hora}».
- «Aprobar» is the gallery's approval (first version that passes the brand rules); the
  panel is read again in place and says when it goes out.
- Approving publishes nothing (N13): only the creative approval runs; the event keeps its
  day and hour and the calendar worker takes it then.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from uuid import UUID

import pytest

from . import planner_drawer, planner_provider, planner_state
from .planner_state import PlannerState
from .planner_vm import (
    APPROVED_CHECK_TOAST,
    AUTO_PUBLISH_ACTIVE,
    AUTO_PUBLISH_NO_CONNECTION,
    REVIEW_EDIT_LINK,
    REVIEW_EDIT_NOTE,
    REVIEW_NOTHING_WITHOUT_YOU,
    EventDetailVM,
    approved_line,
    approved_toast,
    review_line,
)

_TENANT = UUID("a0000000-0000-4000-8000-000000000001")
_POST = UUID("b0000000-0000-4000-8000-000000000002")
_EVENT = "c0000000-0000-4000-8000-000000000003"


# --- the words -----------------------------------------------------------------------


def test_review_line_says_nothing_goes_out_without_you_and_when_it_would() -> None:
    assert review_line("2026-09-28", "15:00") == (
        "Nada sale sin tu aprobación. Si la apruebas, sale el lunes 28 de septiembre "
        "a las 3:00 p. m."
    )
    assert review_line("2026-10-01", "13:30").endswith(
        "sale el jueves 1 de octubre a la 1:30 p. m."
    )


def test_review_line_promises_no_hour_that_is_gone_or_unknown() -> None:
    assert review_line("2026-09-28", "15:00", expired=True) == REVIEW_NOTHING_WITHOUT_YOU
    assert review_line("", "") == REVIEW_NOTHING_WITHOUT_YOU


def test_approved_line_is_unchanged_by_the_shared_phrase() -> None:
    assert approved_line("2026-09-28", "15:00") == (
        "Aprobada por ti: sale el lunes 28 de septiembre a las 3:00 p. m."
    )
    assert approved_line("nope", "15:00") == ""


def test_the_panel_vm_carries_its_review_line() -> None:
    detail = EventDetailVM(local_date="2026-09-28", local_time="15:00", can_reject_post=True)
    assert detail.review_line.startswith(
        "Nada sale sin tu aprobación. Si la apruebas, sale el lunes"
    )
    expired = EventDetailVM(local_date="2026-09-28", local_time="15:00", expired=True)
    assert expired.review_line == REVIEW_NOTHING_WITHOUT_YOU


def _approved(**kw: object) -> EventDetailVM:
    base: dict[str, object] = {
        "local_date": "2026-09-28",
        "local_time": "15:00",
        "approval_tone": "ok",
        "status_tone": "info",
    }
    base.update(kw)
    return EventDetailVM(**base)  # type: ignore[arg-type]


def test_approved_toast_says_when_only_when_it_really_goes_out() -> None:
    assert approved_toast(_approved(), AUTO_PUBLISH_ACTIVE) == (
        "Aprobada por ti: sale el lunes 28 de septiembre a las 3:00 p. m."
    )
    # no account, not ready, expired: never a promise the worker will not keep
    assert approved_toast(_approved(), AUTO_PUBLISH_NO_CONNECTION) == APPROVED_CHECK_TOAST
    assert approved_toast(_approved(approval_tone="warn"), AUTO_PUBLISH_ACTIVE) == (
        APPROVED_CHECK_TOAST
    )
    assert approved_toast(_approved(expired=True), AUTO_PUBLISH_ACTIVE) == APPROVED_CHECK_TOAST


def test_new_strings_are_plain_spanish() -> None:
    for text in (
        REVIEW_NOTHING_WITHOUT_YOU,
        APPROVED_CHECK_TOAST,
        review_line("2026-09-28", "9:00"),
    ):
        for word in ("POST", "post", "feed", "Feed", "publicamos por ti", "automátic"):
            assert word not in text


# --- the panel -----------------------------------------------------------------------


def test_the_footer_offers_aprobar_and_no_la_quiero_for_a_publication_in_review() -> None:
    footer = inspect.getsource(planner_drawer._detail_footer)
    assert '"Aprobar"' in footer and '"No la quiero"' in footer
    assert "PlannerState.approve_post_from_detail" in footer
    assert "PlannerState.reject_post_from_detail" in footer
    assert "PlannerState.review_busy" in footer  # no double tap
    body = inspect.getsource(planner_drawer._detail_body)
    assert "d.review_line" in body
    # the drawer renders with both
    assert "Aprobar" in str(planner_drawer._detail_footer())


# --- the provider: the gallery's approval, nothing that publishes ----------------------


class _OnlyGet:
    """A planner service that only reads: any other call (schedule, publish…) fails."""

    def get(self, *, tenant_id: UUID, event_id: UUID) -> object:
        assert tenant_id == _TENANT and str(event_id) == _EVENT
        return SimpleNamespace(event=SimpleNamespace(post_id=_POST))

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"approving must not call PlannerService.{name}")


def _variant(variant_id: str, *, passed: bool) -> SimpleNamespace:
    return SimpleNamespace(variant_id=variant_id, passed=passed)


@pytest.fixture
def provider(monkeypatch):
    from . import creative_provider

    calls: list[tuple[UUID, UUID, UUID, UUID]] = []
    drafts: dict[str, object] = {}
    monkeypatch.setattr(planner_provider, "production_planner_service", lambda: _OnlyGet())
    monkeypatch.setattr(planner_provider, "acting_user_id", lambda tenant_id: _TENANT)
    monkeypatch.setattr(creative_provider, "draft_detail", lambda t, d: drafts.get("draft"))
    monkeypatch.setattr(
        creative_provider,
        "approve_draft",
        lambda t, d, v, u: calls.append((t, d, v, u)),
    )
    return calls, drafts


def test_approve_post_approves_the_first_version_that_passes(provider) -> None:
    calls, drafts = provider
    first_ok = "d0000000-0000-4000-8000-000000000005"
    drafts["draft"] = SimpleNamespace(
        variants=(
            _variant("d0000000-0000-4000-8000-000000000004", passed=False),
            _variant(first_ok, passed=True),
        )
    )
    planner_provider.approve_post(_TENANT, _EVENT)
    assert calls == [(_TENANT, _POST, UUID(first_ok), _TENANT)]


def test_approve_post_with_no_passing_version_says_what_to_do(provider) -> None:
    calls, drafts = provider
    drafts["draft"] = SimpleNamespace(variants=(_variant(str(_POST), passed=False),))
    with pytest.raises(planner_provider.NoPassingVariant) as err:
        planner_provider.approve_post(_TENANT, _EVENT)
    assert calls == []
    assert planner_provider.approve_error_message(err.value).startswith(
        "Ninguna versión cumple las reglas de tu marca"
    )


def test_approve_post_blocked_by_a_price_says_what_to_correct(provider, monkeypatch) -> None:
    from qualify_api.creative.service import ApprovalBlocked

    from . import creative_provider

    _calls, drafts = provider
    drafts["draft"] = SimpleNamespace(variants=(_variant(str(_POST), passed=True),))

    def blocked(*_args: object) -> None:
        raise ApprovalBlocked("El precio no es el del catálogo: corrígelo.")

    monkeypatch.setattr(creative_provider, "approve_draft", blocked)
    with pytest.raises(planner_provider.PriceBlocked) as err:
        planner_provider.approve_post(_TENANT, _EVENT)
    assert planner_provider.approve_error_message(err.value) == (
        "El precio no es el del catálogo: corrígelo."
    )


def test_approve_post_of_a_missing_publication(provider) -> None:
    with pytest.raises(planner_provider.UnknownPost):
        planner_provider.approve_post(_TENANT, _EVENT)


def test_approve_error_messages_speak_of_approving() -> None:
    from qualify_api.creative.service import ApprovalBlocked

    blocked = ApprovalBlocked("El precio no es el del catálogo: corrígelo.")
    assert planner_provider.approve_error_message(blocked) == blocked.detail
    moved = planner_provider.CreativeInvalidTransition("approved", "approve")
    assert "no se puede aprobar" in planner_provider.approve_error_message(moved)


def test_the_gallery_and_tu_semana_share_the_no_version_wording() -> None:
    from . import gallery_state

    assert gallery_state._NO_PASSING_VARIANT == planner_provider.NO_PASSING_VARIANT_MESSAGE


# --- the event: approve, read the panel again in place, toast, refresh the week --------


def _panel_state(monkeypatch, *, approve=None, detail=None) -> tuple[PlannerState, list[str]]:
    approved: list[str] = []

    async def fake_tenant(self):
        return _TENANT

    def fake_approve(tenant_id: UUID, event_id: str) -> None:
        if isinstance(approve, Exception):
            raise approve
        approved.append(event_id)

    def fake_detail(tenant_id: UUID, event_id: str, view_tz: str) -> EventDetailVM:
        if isinstance(detail, Exception):
            raise detail
        return detail

    monkeypatch.setattr(PlannerState, "_tenant", fake_tenant)
    monkeypatch.setattr(planner_state, "approve_post", fake_approve)
    monkeypatch.setattr(planner_state, "event_detail", fake_detail)
    state = PlannerState()
    state.detail = EventDetailVM(
        event_id=_EVENT,
        local_date="2026-09-28",
        local_time="15:00",
        approval_label="En revisión",
        approval_tone="warn",
        can_reject_post=True,
    )
    state.auto_publish = AUTO_PUBLISH_ACTIVE
    return state, approved


async def test_aprobar_turns_the_panel_approved_in_place_and_says_when(monkeypatch) -> None:
    after = _approved(event_id=_EVENT, approval_label="Listo para publicar")
    state, approved = _panel_state(monkeypatch, detail=after)

    events = [e async for e in PlannerState.approve_post_from_detail.fn(state)]

    assert approved == [_EVENT]
    assert state.detail.approval_label == "Listo para publicar"  # no reload, no skeleton
    assert state.detail.can_reject_post is False
    assert state.detail_loading is False and state.review_busy is False
    assert "Aprobada por ti: sale el lunes 28 de septiembre a las 3:00 p. m." in str(events[0])
    assert events[-1] is PlannerState.load  # the week shows it approved too


async def test_aprobar_that_cannot_go_out_yet_does_not_promise_the_hour(monkeypatch) -> None:
    after = _approved(event_id=_EVENT, approval_tone="warn")  # approved, not ready
    state, _ = _panel_state(monkeypatch, detail=after)
    events = [e async for e in PlannerState.approve_post_from_detail.fn(state)]
    assert APPROVED_CHECK_TOAST in str(events[0])
    assert "sale el" not in str(events[0])


async def test_aprobar_refused_says_why_and_changes_nothing(monkeypatch) -> None:
    state, approved = _panel_state(
        monkeypatch, approve=planner_provider.NoPassingVariant(str(_POST))
    )
    events = [e async for e in PlannerState.approve_post_from_detail.fn(state)]
    assert approved == []
    assert len(events) == 1
    assert "Ninguna versión cumple las reglas de tu marca" in str(events[0])
    assert state.detail.approval_label == "En revisión" and state.review_busy is False


async def test_aprobar_with_an_unreadable_panel_still_refreshes(monkeypatch) -> None:
    state, approved = _panel_state(monkeypatch, detail=RuntimeError("db down"))
    events = [e async for e in PlannerState.approve_post_from_detail.fn(state)]
    assert approved == [_EVENT]
    assert APPROVED_CHECK_TOAST in str(events[0])
    assert events[-1] is PlannerState.load


async def test_a_second_tap_while_busy_does_nothing(monkeypatch) -> None:
    state, approved = _panel_state(monkeypatch, detail=_approved(event_id=_EVENT))
    state.review_busy = True
    events = [e async for e in PlannerState.approve_post_from_detail.fn(state)]
    assert events == [] and approved == []


# --- UX review (m-24842984) ------------------------------------------------------------


def test_review_line_promises_no_hour_while_something_is_missing() -> None:
    assert (
        review_line("2026-09-28", "15:00", publish_note="Falta la foto.")
        == REVIEW_NOTHING_WITHOUT_YOU
    )
    missing = EventDetailVM(
        local_date="2026-09-28", local_time="15:00", publish_note="Falta el video."
    )
    assert missing.review_line == REVIEW_NOTHING_WITHOUT_YOU


def test_the_review_hour_shows_only_when_an_account_can_publish() -> None:
    body = inspect.getsource(planner_drawer._detail_body)
    assert "PlannerState.auto_publish == AUTO_PUBLISH_ACTIVE" in body
    assert "callout(REVIEW_NOTHING_WITHOUT_YOU" in body


def test_aprobar_comes_before_no_la_quiero() -> None:
    footer = inspect.getsource(planner_drawer._detail_footer)
    assert footer.index('"Aprobar"') < footer.index('"No la quiero"')


def test_panel_buttons_are_at_least_44px_tall() -> None:
    from pathlib import Path

    css = (Path(__file__).resolve().parent.parent / "assets" / "qualify-planner.css").read_text()
    assert ".q-panel-actions .rt-Button { width: 100%; min-height: 44px; }" in css


def test_the_check_toast_points_up_the_same_panel() -> None:
    assert APPROVED_CHECK_TOAST == (
        "Publicación aprobada. Aquí arriba te decimos qué falta para que salga."
    )


async def test_no_passing_version_stays_on_the_panel_with_a_way_out(monkeypatch) -> None:
    state, _ = _panel_state(monkeypatch, approve=planner_provider.NoPassingVariant(str(_POST)))
    _ = [e async for e in PlannerState.approve_post_from_detail.fn(state)]
    assert state.review_error == REVIEW_EDIT_NOTE
    body = inspect.getsource(planner_drawer._detail_body)
    assert "PlannerState.review_error" in body and "REVIEW_EDIT_LINK" in body
    assert REVIEW_EDIT_LINK == "Ir a Por aprobar ›"


async def test_a_blocked_price_stays_on_the_panel_in_the_guards_words(monkeypatch) -> None:
    blocked = planner_provider.PriceBlocked("El precio no es el del catálogo.")
    state, _ = _panel_state(monkeypatch, approve=blocked)
    _ = [e async for e in PlannerState.approve_post_from_detail.fn(state)]
    assert state.review_error == "El precio no es el del catálogo."


async def test_a_refusal_not_about_the_text_leaves_no_panel_note(monkeypatch) -> None:
    state, _ = _panel_state(monkeypatch, approve=planner_provider.UnknownPost(str(_POST)))
    _ = [e async for e in PlannerState.approve_post_from_detail.fn(state)]
    assert state.review_error == ""
