"""Saved comments and persistent access notices, offline (m-24854867)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
import reflex as rx
from qualify_api.connections.runtime_health import ConnectionRuntimeState
from qualify_api.inbox import CommentsAuthExpired, CommentsReadError

from . import inbox_page, inbox_provider, inbox_state
from .inbox_access import InboxAccessVM, InboxConnectionVM, access_moment, access_notice
from .inbox_state import InboxState
from .inbox_vm import ReelSummaryVM, SyncSummaryVM

TENANT = UUID("11111111-1111-4111-8111-111111111111")
CONNECTION = UUID("22222222-2222-4222-8222-222222222222")


def notice(
    status: str = "degraded", cause: str = "auth_expired", failures: int = 0
) -> InboxAccessVM:
    return access_notice(
        status=status, cause=cause, account="@cafe", since="el martes 3:40 p. m.", failures=failures
    )


@pytest.mark.parametrize("cause", ["auth_expired", "missing_credential", ""])
def test_disconnected_copy_is_literal(cause: str) -> None:
    vm = notice(cause=cause)
    assert vm.title == "Instagram de @cafe se desconectó"
    assert vm.detail == (
        "No llegan comentarios nuevos desde el martes 3:40 p. m. Los que ya tenías siguen aquí."
    )
    assert vm.needs_reconnect


def test_permission_and_revoked_copy_is_literal() -> None:
    vm = notice(cause="permission_missing")
    assert vm.title == "Falta un paso para ver los comentarios de @cafe"
    assert vm.detail == (
        "Facebook no nos deja leer los comentarios de esta cuenta. Vuelve a "
        "conectarla y deja marcadas todas las casillas que te muestre."
    )
    assert vm.cause == "permission_missing"  # shared action requests permissions again
    vm = notice(status="revoked")
    assert vm.detail == (
        "@cafe ya no está conectada a Qualify. Lo que ya tenías sigue aquí; "
        "para recibir lo nuevo, conéctala otra vez."
    )


@pytest.mark.parametrize("failures", [0, 1, 2, 3, 4])
def test_temporary_warning_is_a_level_until_first_success(failures: int) -> None:
    vm = notice(status="active", cause="", failures=failures)
    assert vm.temporary_warning == (failures >= 3)
    assert not vm.needs_reconnect
    if failures < 3:
        assert vm.title == vm.detail == ""
    else:
        assert vm.title == "Instagram está tardando en responder"
        assert vm.detail == "Seguimos intentando cada pocos minutos. No tienes que hacer nada."


def test_notice_uses_business_time_across_a_day_boundary() -> None:
    assert (
        access_moment(datetime(2026, 10, 28, 1, 40, tzinfo=UTC), ZoneInfo("America/Caracas"))
        == "el martes 9:40 p. m."
    )


@pytest.fixture
def screen(monkeypatch: pytest.MonkeyPatch) -> InboxState:
    async def auth(self: InboxState, cls: object) -> SimpleNamespace:
        return SimpleNamespace(session_tenant_id=str(TENANT))

    monkeypatch.setattr(InboxState, "get_state", auth)
    monkeypatch.setattr(inbox_state, "tenant_zone", lambda _: ZoneInfo("UTC"))
    monkeypatch.setattr(inbox_state, "consume_recovery_refresh", lambda **_: False)
    monkeypatch.setattr(inbox_state, "seconds_since_last_sync", AsyncMock(return_value=None))
    monkeypatch.setattr(InboxState, "_refresh_after_write", AsyncMock())
    state = InboxState()
    state.selected_connection_id = str(CONNECTION)
    state.connections = [InboxConnectionVM(str(CONNECTION), "@cafe", "instagram", "@cafe")]
    monkeypatch.setattr(inbox_state, "instagram_connections", lambda _: list(state.connections))
    return state


@pytest.mark.asyncio
async def test_poll_keeps_outage_and_saved_comments_without_calling_meta(
    screen: InboxState, monkeypatch: pytest.MonkeyPatch
) -> None:
    outage = notice()
    screen.access = outage
    screen.reel_summaries = [
        ReelSummaryVM(
            thread_id="saved",
            external_thread_id="post",
            last_message_at="ayer",
            total=1,
            positive=1,
            neutral=0,
            negative=0,
            not_analyzed=0,
            thumbnail_url="",
            caption="",
            permalink="",
            is_monitored=True,
        )
    ]
    monkeypatch.setattr(inbox_state, "connection_access", lambda *args: notice())
    monkeypatch.setattr(
        inbox_state,
        "get_connection_runtime_state",
        lambda **_: ConnectionRuntimeState("degraded", "auth_expired", 0, False, 1),
    )
    sync = AsyncMock()
    monkeypatch.setattr(inbox_state, "sync_now", sync)
    for _ in range(3):
        await InboxState.sync_comments.fn(screen, "poll")
        assert screen.access == outage
        assert screen.reel_summaries[0].thread_id == "saved"
        assert screen.has_connections and not screen.can_sync
    sync.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger", ["poll", "manual"])
async def test_permanent_failure_shows_notice_immediately(
    screen: InboxState, monkeypatch: pytest.MonkeyPatch, trigger: str
) -> None:
    diagnosis = {"value": InboxAccessVM()}
    monkeypatch.setattr(inbox_state, "connection_access", lambda *args: diagnosis["value"])
    monkeypatch.setattr(
        inbox_state,
        "get_connection_runtime_state",
        lambda **_: ConnectionRuntimeState("active", None, 0, False, 1),
    )

    async def fail(**kwargs: object) -> None:
        diagnosis["value"] = notice()
        raise CommentsAuthExpired(connection_id=CONNECTION)

    monkeypatch.setattr(inbox_state, "sync_now", fail)
    await InboxState.sync_comments.fn(screen, trigger)
    assert screen.access == notice()
    assert screen.sync_error == "" and not screen.is_syncing


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger", ["poll", "manual"])
async def test_transient_failure_then_success(
    screen: InboxState, monkeypatch: pytest.MonkeyPatch, trigger: str
) -> None:
    failures = {"count": 0}
    monkeypatch.setattr(
        inbox_state,
        "connection_access",
        lambda *args: notice(status="active", cause="", failures=failures["count"]),
    )
    monkeypatch.setattr(
        inbox_state,
        "get_connection_runtime_state",
        lambda **_: ConnectionRuntimeState("active", None, failures["count"], False, 1),
    )

    async def fail(**kwargs: object) -> None:
        if failures["count"] >= 3:
            assert screen.access.temporary_warning  # no blanking at start of the next poll
        failures["count"] += 1
        raise CommentsReadError("temporary")

    monkeypatch.setattr(inbox_state, "sync_now", fail)
    for count in range(1, 5):
        await InboxState.sync_comments.fn(screen, trigger)
        assert screen.access.temporary_warning == (count >= 3)
        assert bool(screen.last_review)
        assert screen.sync_error == (
            "Instagram no respondió. Intenta de nuevo en unos minutos."
            if trigger == "manual"
            else ""
        )
    failures["count"] = 0
    monkeypatch.setattr(inbox_state, "sync_now", AsyncMock(return_value=SyncSummaryVM(1, 0)))
    await InboxState.sync_comments.fn(screen, "manual")
    assert screen.access == InboxAccessVM()
    assert screen.sync_error == ""


@pytest.mark.asyncio
async def test_access_refresh_discards_another_tenants_late_result(
    screen: InboxState, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = []

    def read(tenant: UUID, connection: UUID) -> InboxAccessVM:
        seen.append((tenant, connection))
        return notice()

    async def other_tenant(self: InboxState, cls: object) -> SimpleNamespace:
        return SimpleNamespace(session_tenant_id="33333333-3333-4333-8333-333333333333")

    monkeypatch.setattr(inbox_state, "connection_access", read)
    monkeypatch.setattr(InboxState, "get_state", other_tenant)
    await screen._refresh_access(TENANT, str(CONNECTION))
    assert seen == [(TENANT, CONNECTION)]
    assert screen.access == InboxAccessVM()


@pytest.mark.parametrize("status", ["degraded", "revoked", "never"])
def test_view_only_invites_to_connect_when_never_connected(
    screen: InboxState, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    original_cond = rx.cond

    def cond(condition: object, yes: object, no: object = None):
        return (
            (yes if condition else no)
            if isinstance(condition, bool)
            else original_cond(condition, yes, no)
        )

    if status == "never":
        screen.connections = []
    else:
        screen.access = notice(status=status)
    monkeypatch.setattr(rx, "cond", cond)
    monkeypatch.setattr(inbox_page, "InboxState", screen)
    monkeypatch.setattr(inbox_page, "reconnect_result_panel", lambda: rx.fragment())
    monkeypatch.setattr(inbox_page, "_replies_section", lambda: rx.fragment())
    monkeypatch.setattr(inbox_page, "_comments_section", lambda: rx.text("Saved comments"))
    monkeypatch.setattr(inbox_page, "_more_options", lambda: rx.fragment())
    monkeypatch.setattr(inbox_page, "_polling_timer", lambda: rx.fragment())
    monkeypatch.setattr(
        inbox_page, "_sync_now_button", lambda: rx.button("Buscar comentarios nuevos")
    )
    rendered = str(inbox_page._body(wrapped=False))
    assert ("Saved comments" in rendered) == (status != "never")
    assert ("Conecta tu Instagram para ver tus comentarios" in rendered) == (status == "never")
    assert "Buscar comentarios nuevos" not in rendered
    if status != "never":
        # JSON escapes accents in JSX; use the exact serialized text for the position.
        import json

        detail = json.dumps(screen.access.detail, ensure_ascii=True)
        assert rendered.index(detail) < rendered.index("Saved comments")
        assert "Volver a conectar" in rendered
        assert "Pide ayuda" in rendered


def test_candidate_read_failure_keeps_the_existing_list_above_saved_content(
    screen: InboxState, monkeypatch: pytest.MonkeyPatch
) -> None:
    screen.load_error = "No pudimos cargar tus publicaciones recientes."
    original_cond = rx.cond

    def cond(condition: object, yes: object, no: object = None):
        return (
            (yes if condition else no)
            if isinstance(condition, bool)
            else original_cond(condition, yes, no)
        )

    monkeypatch.setattr(rx, "cond", cond)
    monkeypatch.setattr(inbox_page, "InboxState", screen)
    monkeypatch.setattr(inbox_page, "_candidates_body", lambda: rx.text("Saved publications"))
    rendered = str(inbox_page._review_choice_section())
    assert "No pudimos cargar tus publicaciones recientes." in rendered
    assert "Saved publications" in rendered
    assert rendered.index("No pudimos cargar") < rendered.index("Saved publications")


def test_warning_component_and_complete_page_build() -> None:
    assert inbox_page._access_notice()
    assert inbox_page.comments_tab()


@pytest.mark.asyncio
async def test_only_disconnected_account_loads_saved_publications(
    screen: InboxState, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(inbox_state, "connection_access", lambda *args: notice())
    candidates = AsyncMock()
    monkeypatch.setattr(inbox_state, "candidate_media", candidates)
    stored = ReelSummaryVM(
        thread_id="saved",
        external_thread_id="post",
        last_message_at="ayer",
        total=1,
        positive=1,
        neutral=0,
        negative=0,
        not_analyzed=0,
        thumbnail_url="",
        caption="Saved publication",
        permalink="",
        is_monitored=True,
    )
    calls = []

    def saved_page(**kwargs: object):
        calls.append(kwargs)
        return [stored], None, False

    monkeypatch.setattr(inbox_state, "reel_summaries_page", saved_page)
    monkeypatch.setattr(InboxState, "_load_global_summary", AsyncMock())
    _events = [event async for event in InboxState.load_screen.fn(screen)]
    assert screen.has_connections
    assert screen.reel_summaries == [stored]
    assert screen.access.needs_reconnect
    assert calls[0]["tenant_id"] == TENANT
    assert calls[0]["connection_id"] == CONNECTION
    candidates.assert_not_awaited()


@pytest.mark.parametrize("visible", [True, False])
def test_access_read_scopes_both_diagnosis_and_audit_to_tenant(
    monkeypatch: pytest.MonkeyPatch, visible: bool
) -> None:
    statements = []
    moment = datetime(2026, 10, 27, 19, 40, tzinfo=UTC)
    row = SimpleNamespace(
        status="degraded",
        reconnect_reason="auth_expired",
        temporary_failure_count=0,
        current_credential_version=7,
        external_username="cafe",
        external_account_id="id",
    )

    class Session:
        def scalar(self, statement: object) -> object:
            statements.append(statement)
            return (row if visible else None) if len(statements) == 1 else moment

    @contextmanager
    def session(tenant_id: UUID):
        assert tenant_id == TENANT
        yield Session()

    monkeypatch.setattr(inbox_provider, "tenant_session", session)
    monkeypatch.setattr(inbox_provider, "tenant_zone", lambda _: ZoneInfo("America/Caracas"))
    vm = inbox_provider.connection_access(TENANT, CONNECTION)
    if visible:
        assert "el martes 3:40 p. m." in vm.detail
        assert len(statements) == 2
        assert 7 in statements[1].compile().params.values()
    else:
        assert vm == InboxAccessVM() and len(statements) == 1
    for statement in statements:
        values = statement.compile().params.values()
        assert TENANT in values and CONNECTION in values
        assert "oauth_credentials" not in str(statement)
