"""m-24921091: the TikTok view models, states' pure parts and copy — offline, no Reflex
runtime, no database."""

from __future__ import annotations

import dataclasses
import inspect
import re

import pytest

from . import tiktok_vm as vm
from .connections_state import ConnectionsState
from .tiktok_state import TikTokConnectionsState, TikTokDraftState

# --- the account card ------------------------------------------------------------------


def _account(**kw: object) -> vm.TikTokAccountVM:
    base: dict[str, object] = {
        "connection_id": "c-1",
        "display_name": "Bianki Shawarma",
        "status": "active",
        "granted_scopes": ("user.info.basic", "video.upload"),
        "reconnect_reason": None,
        "access_notice": "",
    }
    return vm.build_account_vm(**{**base, **kw})  # type: ignore[arg-type]


def test_a_working_account_can_send_and_shows_no_problem() -> None:
    account = _account()
    assert account.can_send and account.problem == ""
    assert account.name == "Bianki Shawarma"


def test_the_account_vm_carries_no_credential_field() -> None:
    names = {f.name for f in dataclasses.fields(vm.TikTokAccountVM)}
    assert names == {"id", "name", "status", "problem", "notice", "can_send", "permission_missing"}
    assert not any(word in " ".join(names) for word in ("token", "secret", "cipher", "key"))


def test_without_the_upload_permission_it_cannot_send_and_says_why() -> None:
    account = _account(granted_scopes=("user.info.basic",))
    assert not account.can_send and account.problem == vm.PERMISSION_PROBLEM
    degraded = _account(status="degraded", reconnect_reason="permission_missing")
    assert not degraded.can_send and degraded.problem == vm.PERMISSION_PROBLEM
    assert account.permission_missing and degraded.permission_missing
    assert not _account(status="degraded").permission_missing


@pytest.mark.parametrize(
    ("status", "problem"),
    [("degraded", vm.DISCONNECTED_PROBLEM), ("revoked", vm.REVOKED_PROBLEM)],
)
def test_a_broken_account_says_to_reconnect(status: str, problem: str) -> None:
    account = _account(status=status)
    assert not account.can_send and account.problem == problem
    assert "Volver a conectar" in account.problem


def test_missing_display_name_falls_back_to_plain_words() -> None:
    assert _account(display_name=None).name == vm.FALLBACK_NAME
    assert _account(display_name="   ").name == vm.FALLBACK_NAME


def test_development_notice_only_on_a_live_account() -> None:
    assert _account(access_notice="aviso").notice == "aviso"
    assert _account(status="revoked", access_notice="aviso").notice == ""


def test_first_sendable_skips_accounts_that_cannot_receive() -> None:
    broken = _account(connection_id="a", status="degraded")
    working = _account(connection_id="b")
    assert vm.first_sendable([broken, working]) is working
    assert vm.first_sendable([broken]) is None


def test_copy_matches_the_backend_sentences() -> None:
    from qualify_api.connections.tiktok_service import (
        NOTICE_DEVELOPMENT,
        NOTICE_PERMISSION_MISSING,
        tiktok_access_notice,
    )
    from qualify_api.publishing.tiktok_drafts import IN_INBOX_TEXT, failure_text

    assert vm.PERMISSION_PROBLEM == NOTICE_PERMISSION_MISSING
    assert vm.DEVELOPMENT_NOTICE == NOTICE_DEVELOPMENT == tiktok_access_notice("development")
    assert tiktok_access_notice("live") == ""
    assert vm.DRAFT_IN_INBOX == IN_INBOX_TEXT
    assert vm.DRAFT_FAILED_DEFAULT == failure_text(None)


def test_backend_vocabulary_is_the_one_the_vm_speaks() -> None:
    from qualify_api.connections.tiktok_service import PLATFORM, UPLOAD_SCOPE
    from qualify_api.publishing import tiktok_drafts as drafts

    assert (vm.PLATFORM, vm.UPLOAD_SCOPE) == (PLATFORM, UPLOAD_SCOPE)
    for name in ("PENDING", "UPLOADING", "PROCESSING", "IN_INBOX", "FAILED"):
        assert getattr(vm, f"STATUS_{name}") == getattr(drafts, f"STATUS_{name}")


# --- the connect round trip ------------------------------------------------------------


def test_every_route_outcome_has_a_notice() -> None:
    from qualify_api.connections.service import ConnectOutcome

    tiktok_outcomes = {"active", "degraded", "permission_missing", "account_access_required"}
    assert tiktok_outcomes <= {str(o) for o in ConnectOutcome}
    assert set(vm.CONNECT_RESULT_NOTICES) == tiktok_outcomes | {"denied", "invalid_state"}
    assert vm.connect_result_notice("junk<script>") == ("", "info")


def test_tiktok_state_reads_only_its_own_callback() -> None:
    state = TikTokConnectionsState()
    state.apply_connect_result({"connect": "active", "platform": "tiktok"})
    assert state.connected_ok and state.connect_notice
    state.apply_connect_result({"connect": "denied", "platform": "tiktok"})
    assert not state.connected_ok and state.connect_notice_tone == "info"
    state.apply_connect_result({"connect": "active"})  # Meta's callback
    assert not state.connected_ok and state.connect_notice == ""


def test_meta_state_ignores_a_tiktok_callback_but_keeps_the_origin() -> None:
    state = ConnectionsState()
    state.return_to = "/drafts/abc"
    state.apply_connect_result({"connect": "active", "platform": "tiktok"})
    # no «Instagram conectado» for a TikTok account …
    assert not state.connected_ok and state.connect_notice == ""
    # … but «Seguir donde estabas» still goes back to the piece
    assert state.return_to == "/drafts/abc"
    state.apply_connect_result({"connect": "active"})
    assert state.connected_ok


# --- the draft card --------------------------------------------------------------------


@pytest.mark.parametrize("status", ["pending", "uploading", "processing"])
def test_a_draft_on_its_way_is_in_progress(status: str) -> None:
    draft = vm.build_draft_vm(draft_id="d", status=status)
    assert draft.in_progress and not draft.done and not draft.failed
    assert draft.message == vm.DRAFT_SENDING and draft.label == "Enviando…"


def test_a_landed_draft_tells_the_owner_to_finish_in_tiktok() -> None:
    draft = vm.build_draft_vm(draft_id="d", status="in_inbox")
    assert draft.done and not draft.in_progress and draft.tone == "ok"
    assert "TikTok" in draft.message and "notificación" in draft.message


def test_copy_never_says_the_video_lands_in_the_drafts_folder() -> None:
    """`video.upload` arrives as a notification in the TikTok app, not in «Borradores»;
    no sentence the owner reads says «borradores»."""
    assert [text for text in _client_strings() if "borradores" in text.lower()] == []


def test_a_failed_draft_keeps_the_backend_reason() -> None:
    draft = vm.build_draft_vm(draft_id="d", status="failed", message="Tienes varios borradores.")
    assert draft.failed and draft.message == "Tienes varios borradores."
    refused = vm.refused_vm("La publicación no está aprobada.")
    assert refused.failed and refused.status == vm.STATUS_REFUSED and refused.draft_id == ""
    assert vm.refused_vm("").message == vm.DRAFT_SEND_FAILED


def test_target_prefers_the_reel_port_and_refuses_non_videos() -> None:
    ports = [("feed", ("IMAGE",)), ("feed-video", ("VIDEO",)), ("reel", ("VIDEO",))]
    assert vm.pick_target(ports, ()) == vm.TikTokTarget(True, "reel")
    assert vm.pick_target([("square-video", ("VIDEO",))], ()) == vm.TikTokTarget(
        True, "square-video"
    )
    assert vm.pick_target([("feed", ("IMAGE",))], ("VIDEO",)) == vm.NOT_A_TARGET
    assert vm.pick_target([], ("VIDEO",)) == vm.TikTokTarget(True, "")
    assert vm.pick_target([], ("IMAGE",)) == vm.NOT_A_TARGET
    assert vm.pick_target([], ("VIDEO", "VIDEO")) == vm.NOT_A_TARGET  # a carousel


def test_a_piece_made_for_tiktok_is_marked_but_never_makes_an_image_eligible() -> None:
    assert vm.pick_target([], ("VIDEO",), "tiktok_video") == vm.TikTokTarget(True, "", True)
    assert vm.pick_target([("reel", ("VIDEO",))], (), "tiktok_video").tiktok_only
    assert not vm.pick_target([], ("VIDEO",), "reel").tiktok_only
    assert vm.pick_target([], ("IMAGE",), "tiktok_video") == vm.NOT_A_TARGET
    assert (vm.DRAFT_TITLE_TIKTOK, vm.DRAFT_TITLE) == (
        "Llévalo a TikTok",
        "Llévalo también a TikTok",
    )


def test_next_attempt_only_moves_after_a_failure() -> None:
    assert vm.next_attempt(0) == 1  # same key: a resend returns the draft already sent
    assert vm.next_attempt(2) == 3
    assert vm.next_attempt(-1) == 1


def test_polling_is_bounded() -> None:
    assert vm.POLL_SECONDS * vm.POLL_MAX_READS <= 90


def test_draft_card_shows_only_for_a_loaded_eligible_piece() -> None:
    state = TikTokDraftState()
    assert not state.show_card
    state.loaded, state.eligible = True, True
    assert not state.show_card  # neither connectable nor connected
    state.available = True
    assert state.show_card  # invites to connect
    state.available, state.account_id = False, "c-1"
    assert state.show_card and state.can_send
    state.eligible = False
    assert not state.show_card


def test_draft_card_cannot_send_twice_while_one_is_on_its_way() -> None:
    state = TikTokDraftState()
    state.account_id = "c-1"
    state.draft = vm.build_draft_vm(draft_id="d", status="processing")
    assert not state.can_send
    state.draft = vm.build_draft_vm(draft_id="d", status="failed")
    assert state.can_send
    state.sending = True
    assert not state.can_send


def test_connect_link_comes_back_to_the_piece() -> None:
    from .connections_vm import safe_return_path

    state = TikTokDraftState()
    state.post_id = "6f1c2f8e-0000-4000-8000-000000000001"
    href = state.connect_href
    assert href.startswith("/connections?volver=/drafts/")
    assert safe_return_path(href.split("volver=", 1)[1]) == f"/drafts/{state.post_id}"


@pytest.mark.asyncio
async def test_send_ignores_a_double_click() -> None:
    state = TikTokDraftState()
    state.account_id = "c-1"
    state.sending = True
    async for _ in TikTokDraftState.send.fn(state):
        pass
    assert state.sending and state.error == ""


# --- the video final is not ready yet (m-24945954) -------------------------------------

_POST = "6f1c2f8e-0000-4000-8000-000000000001"
_TENANT = "6f1c2f8e-0000-4000-8000-0000000000aa"
_USER = "6f1c2f8e-0000-4000-8000-0000000000bb"
_ACCOUNT = "6f1c2f8e-0000-4000-8000-0000000000cc"


def test_final_wait_reasons_are_the_backend_gate_s() -> None:
    """The card waits on exactly the reasons `send_tiktok_draft` refuses a preview with,
    and words them from the same `draft_mode` states the piece's video notice uses."""
    from qualify_api.creative import draft_mode
    from qualify_api.planner.post_reader import UnpublishableReason as R

    from . import creative_vm

    assert vm.REASON_DRAFT_PENDING == R.MEDIA_DRAFT_PENDING.value
    assert vm.REASON_FINAL_UNCONFIRMED == R.MEDIA_FINAL_UNCONFIRMED.value
    assert vm.VIDEO_RENDERING == draft_mode.DRAFT_RENDERING == creative_vm.VIDEO_RENDERING
    assert (
        vm.VIDEO_FINAL_SCHEDULED
        == draft_mode.DRAFT_FINAL_SCHEDULED
        == creative_vm.VIDEO_FINAL_SCHEDULED
    )
    assert vm.VIDEO_FINAL_READY == draft_mode.DRAFT_FINAL_READY == creative_vm.VIDEO_FINAL_READY


def test_final_review_note_and_card_agree_on_tomorrow_morning() -> None:
    """The nightly lane: the card says the same «mañana temprano» as the video notice."""
    from .final_review_vm import FINAL_SCHEDULED_NOTE

    assert vm.FINAL_WAIT_TOMORROW.startswith(FINAL_SCHEDULED_NOTE)


@pytest.mark.parametrize(
    ("reason", "video_state", "note", "review"),
    [
        (vm.REASON_DRAFT_PENDING, "final_scheduled", vm.FINAL_WAIT_TOMORROW, False),
        (vm.REASON_DRAFT_PENDING, "rendering", vm.FINAL_WAIT_RENDERING, False),
        (vm.REASON_DRAFT_PENDING, "failed", vm.FINAL_WAIT_NOTE, False),
        (vm.REASON_DRAFT_PENDING, "", vm.FINAL_WAIT_NOTE, False),
        (vm.REASON_DRAFT_PENDING, "final_ready", vm.FINAL_WAIT_CONFIRM, True),
        (vm.REASON_FINAL_UNCONFIRMED, "final_ready", vm.FINAL_WAIT_CONFIRM, True),
        (vm.REASON_FINAL_UNCONFIRMED, "", vm.FINAL_WAIT_CONFIRM, True),
    ],
)
def test_a_preview_waits_and_says_when(
    reason: str, video_state: str, note: str, review: bool
) -> None:
    wait = vm.final_wait_vm(reason, video_state)
    assert wait.waiting and wait.note == note and wait.review is review
    assert "TikTok" in wait.note


@pytest.mark.parametrize("reason", ["", "not_approved", "media_not_in_r2", "no_media"])
def test_only_a_preview_makes_the_card_wait(reason: str) -> None:
    """Any other refusal is left to the send, which names it; a ready video sends."""
    assert vm.final_wait_vm(reason, "final_scheduled") == vm.FINAL_OK


def test_a_preview_refusal_is_told_apart_from_a_real_one() -> None:
    preview = vm.refused_vm("Este video todavía es una vista previa.", vm.REASON_DRAFT_PENDING)
    assert preview.reason == vm.REASON_DRAFT_PENDING and vm.is_final_wait_refusal(preview)
    assert not vm.is_final_wait_refusal(vm.refused_vm("x", "needs_reconnect"))
    assert not vm.is_final_wait_refusal(vm.build_draft_vm(draft_id="d", status="failed"))


def test_the_review_link_is_the_piece_s_own() -> None:
    assert vm.final_review_href(_POST) == f"/planner?revisar=videos&pieza={_POST}"


def test_no_send_while_the_final_is_not_ready() -> None:
    state = TikTokDraftState()
    state.account_id = "c-1"
    assert state.can_send
    state.final_wait = vm.final_wait_vm(vm.REASON_DRAFT_PENDING, "final_scheduled")
    assert not state.can_send
    state.post_id = _POST
    assert state.review_href == vm.final_review_href(_POST)


def _session(monkeypatch: pytest.MonkeyPatch) -> None:
    from .auth_state import AuthState

    auth = AuthState()
    auth.session_tenant_id = _TENANT
    auth._session_user_id = _USER

    async def get_state(_self: object, state_cls: type) -> object:
        assert state_cls is AuthState
        return auth

    monkeypatch.setattr(TikTokDraftState, "get_state", get_state)


@pytest.mark.asyncio
async def test_send_does_nothing_while_waiting_for_the_final(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from . import tiktok_state

    def boom(*_a: object, **_k: object) -> object:
        raise AssertionError("nothing may be sent")

    monkeypatch.setattr(tiktok_state, "failed_attempts", boom)
    monkeypatch.setattr(tiktok_state, "send_to_tiktok_drafts", boom)
    state = TikTokDraftState()
    state.account_id, state.post_id = _ACCOUNT, _POST
    state.final_wait = vm.final_wait_vm(vm.REASON_DRAFT_PENDING, "rendering")
    async for _ in TikTokDraftState.send.fn(state):
        pass
    assert not state.sending and state.draft == vm.NO_DRAFT


@pytest.mark.asyncio
async def test_a_preview_refused_at_send_waits_instead_of_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The card was stale (the final went back to being made): no «No se envió»."""
    from . import tiktok_state

    _session(monkeypatch)
    monkeypatch.setattr(tiktok_state, "failed_attempts", lambda *_a: 0)

    async def refused(**_k: object) -> vm.TikTokDraftVM:
        return vm.refused_vm("Este video todavía es una vista previa.", vm.REASON_DRAFT_PENDING)

    monkeypatch.setattr(tiktok_state, "send_to_tiktok_drafts", refused)
    monkeypatch.setattr(
        tiktok_state,
        "tiktok_final_wait",
        lambda *_a: vm.final_wait_vm(vm.REASON_DRAFT_PENDING, "final_scheduled"),
    )
    state = TikTokDraftState()
    state.account_id, state.post_id = _ACCOUNT, _POST
    async for _ in TikTokDraftState.send.fn(state):
        pass
    assert state.draft == vm.NO_DRAFT and state.error == ""
    assert state.final_wait.waiting and state.final_wait.note == vm.FINAL_WAIT_TOMORROW
    assert not state.can_send


@pytest.mark.asyncio
async def test_a_real_refusal_still_shows(monkeypatch: pytest.MonkeyPatch) -> None:
    from . import tiktok_state

    _session(monkeypatch)
    monkeypatch.setattr(tiktok_state, "failed_attempts", lambda *_a: 0)

    async def refused(**_k: object) -> vm.TikTokDraftVM:
        return vm.refused_vm("Hay que volver a conectar tu cuenta de TikTok.", "needs_reconnect")

    monkeypatch.setattr(tiktok_state, "send_to_tiktok_drafts", refused)
    state = TikTokDraftState()
    state.account_id, state.post_id = _ACCOUNT, _POST
    async for _ in TikTokDraftState.send.fn(state):
        pass
    assert state.draft.status == vm.STATUS_REFUSED and not state.final_wait.waiting


@pytest.mark.asyncio
async def test_once_the_final_is_ready_the_preview_refusal_is_cleared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`check_final` (after approving, and when the final lands on screen): the button
    comes back as the normal «Enviar a TikTok», not «Intentar de nuevo»."""
    from . import tiktok_state

    _session(monkeypatch)
    answers = [vm.final_wait_vm(vm.REASON_DRAFT_PENDING, "rendering"), vm.FINAL_OK]
    seen: list[tuple[object, ...]] = []

    def gate(*args: object) -> vm.FinalWaitVM:
        seen.append(args)
        return answers.pop(0)

    monkeypatch.setattr(tiktok_state, "tiktok_final_wait", gate)
    state = TikTokDraftState()
    state.loaded, state.eligible = True, True
    state.account_id, state.post_id, state.output_port = _ACCOUNT, _POST, "reel"
    state.draft = vm.refused_vm("vista previa", vm.REASON_DRAFT_PENDING)
    await TikTokDraftState.check_final.fn(state)
    assert state.final_wait.waiting and not state.can_send
    assert state.draft == vm.NO_DRAFT
    await TikTokDraftState.check_final.fn(state)
    assert not state.final_wait.waiting and state.can_send
    assert state.draft == vm.NO_DRAFT and not state.draft.failed
    assert [str(a[1]) for a in seen] == [_POST, _POST] and seen[0][2] == "reel"


@pytest.mark.asyncio
async def test_check_final_leaves_a_sent_draft_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    from . import tiktok_state

    _session(monkeypatch)
    monkeypatch.setattr(tiktok_state, "tiktok_final_wait", lambda *_a: vm.FINAL_OK)
    state = TikTokDraftState()
    state.loaded, state.eligible, state.post_id = True, True, _POST
    sent = vm.build_draft_vm(draft_id="d", status="in_inbox")
    state.draft = sent
    await TikTokDraftState.check_final.fn(state)
    assert state.draft == sent


@pytest.mark.asyncio
async def test_check_final_is_quiet_before_the_card_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from . import tiktok_state

    def boom(*_a: object) -> object:
        raise AssertionError("no read before the card is loaded")

    monkeypatch.setattr(tiktok_state, "tiktok_final_wait", boom)
    state = TikTokDraftState()
    await TikTokDraftState.check_final.fn(state)
    assert not state.final_wait.waiting


@pytest.mark.parametrize(
    ("reason", "waiting"),
    [("media_draft_pending", True), ("media_final_unconfirmed", True), ("not_approved", False)],
)
def test_provider_waits_on_the_gate_s_preview_reasons(
    monkeypatch: pytest.MonkeyPatch, reason: str, waiting: bool
) -> None:
    from uuid import UUID

    from qualify_api.planner import composition
    from qualify_api.planner.post_reader import NotPublishable, UnpublishableReason
    from qualify_api.planner.publishable import DESTINATION_TIKTOK

    from . import creative_provider, tiktok_provider
    from .creative_vm import video_draft_vm

    calls: list[dict[str, object]] = []

    class Reader:
        def get_publishable(self, **kw: object) -> NotPublishable:
            calls.append(kw)
            return NotPublishable(post_id=UUID(_POST), reason=UnpublishableReason(reason))

    monkeypatch.setattr(composition, "production_post_reader", Reader)
    monkeypatch.setattr(
        creative_provider,
        "final_video_state",
        lambda *_a: video_draft_vm("final_scheduled", None, approved=True),
    )
    wait = tiktok_provider.tiktok_final_wait(UUID(_TENANT), UUID(_POST), "reel")
    assert wait.waiting is waiting
    assert calls[0]["destination"] == DESTINATION_TIKTOK and calls[0]["output_port"] == "reel"
    if reason == "media_draft_pending":
        assert wait.note == vm.FINAL_WAIT_TOMORROW


def test_the_card_asks_the_same_gate_the_send_does() -> None:
    """`tiktok_final_wait` reads `get_publishable` with the TikTok destination — the
    rule `TikTokDraftService.send_to_inbox` refuses with — never a copy of it."""
    from . import tiktok_provider

    source = inspect.getsource(tiktok_provider.tiktok_final_wait)
    assert "get_publishable(" in source and "DESTINATION_TIKTOK" in source


# --- copy rules (qualify-copy-es / qualify-ux §3) -------------------------------------

_BANNED = re.compile(
    r"\b(post|posteo|draft|story|feed|inbox|upload|token|scope|API|OAuth|schedul\w*|"
    r"programad\w*|programar)\b",
    re.IGNORECASE,
)


def _client_strings() -> list[str]:
    strings = [
        value
        for name, value in vars(vm).items()
        if name.isupper() and isinstance(value, str) and " " in value
    ]
    strings += [message for message, _tone in vm.CONNECT_RESULT_NOTICES.values()]
    strings += [label for label, _tone in vm.DRAFT_PILLS.values()]
    return strings


def test_client_copy_has_no_english_or_technical_words() -> None:
    offenders = [text for text in _client_strings() if _BANNED.search(text)]
    assert offenders == []


def test_copy_never_promises_qualify_publishes_on_tiktok() -> None:
    """The owner publishes in the TikTok app; Qualify never says it does (copy-es §6)."""
    promise = re.compile(r"\b(publicamos|publicaremos|se publica\w*|publicará\w*|saldrá)\b")
    assert [text for text in _client_strings() if promise.search(text.lower())] == []


def test_states_never_touch_the_planner() -> None:
    """No TikTok scheduling anywhere (ADR 23c): the states never call the Planificador."""
    from . import tiktok_provider, tiktok_state

    for module in (tiktok_state, tiktok_provider):
        source = inspect.getsource(module)
        assert "schedule(" not in source and "calendar_event" not in source
