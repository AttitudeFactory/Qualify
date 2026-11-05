"""Reflex state for TikTok (m-24921091): the account card in «Tus redes»
(`TikTokConnectionsState`) and «Enviar a TikTok» on an approved piece
(`TikTokDraftState`).

Both hold only the whitelisted view models of `tiktok_vm` — never a row, never a token. All
database and network work runs off the event loop (`asyncio.to_thread`, or the provider's
own worker loop for the async seams). The tenant comes from `AuthState`, per session.

**No scheduling, no publishing.** The only write toward TikTok is one human click that puts
an approved video in the creator's TikTok inbox (a notification in the app); the owner
finishes and publishes it from there.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import UUID

import reflex as rx
from qualify_api.connections import ConnectionNotFound
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .connections_provider import NoActingUser, acting_user_id
from .connections_state import ConnectionsState
from .connections_vm import safe_return_path
from .oauth_binding_js import bound_redirect
from .tenant import tenant_uuid
from .tiktok_provider import (
    begin_tiktok_connect,
    disconnect_tiktok_account,
    failed_attempts,
    latest_draft,
    refresh_draft,
    send_to_tiktok_drafts,
    tiktok_accounts,
    tiktok_available,
    tiktok_final_wait,
    tiktok_target,
)
from .tiktok_vm import (
    ACCOUNTS_ELEMENT_ID,
    CONNECT_FAILED,
    DISCONNECT_FAILED,
    DRAFT_SEND_FAILED,
    DRAFT_STILL_SENDING,
    FINAL_WAIT_NOTE,
    LOAD_FAILED,
    NO_DRAFT,
    NOT_FOUND,
    POLL_MAX_READS,
    POLL_SECONDS,
    FinalWaitVM,
    TikTokAccountVM,
    TikTokDraftVM,
    build_draft_vm,
    connect_result_notice,
    final_review_href,
    first_sendable,
    is_final_wait_refusal,
    is_tiktok_result,
    next_attempt,
)

logger = logging.getLogger(__name__)

_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."


class TikTokConnectionsState(rx.State):
    """The TikTok part of «Tus redes»."""

    #: The deployment has the TikTok app configured (`TIKTOK_*`); otherwise nothing offers
    #: to connect, and only accounts already connected are shown (to disconnect them).
    available: bool = False
    accounts: list[TikTokAccountVM] = []
    is_loading: bool = False
    load_error: str = ""
    action_error: str = ""
    connecting: bool = False
    #: Per card, like `ConnectionsState.checking_connection_ids`: a disconnect in flight.
    busy_ids: list[str] = []
    #: The result of the TikTok round trip (`?connect=<code>&platform=tiktok`).
    connect_notice: str = ""
    connect_notice_tone: str = "info"
    connected_ok: bool = False

    @rx.var
    def has_accounts(self) -> bool:
        return len(self.accounts) > 0

    @rx.var
    def show_section(self) -> bool:
        """Shown when TikTok can be connected here, or an account is already connected."""
        return self.available or len(self.accounts) > 0

    @rx.event
    def read_connect_result(self) -> None:
        self.apply_connect_result(dict(self.router.url.query_parameters))

    def apply_connect_result(self, params: dict[str, object]) -> None:
        """Split from `read_connect_result` so it runs without a live router (tests). Only a
        TikTok callback is read here; Meta's stays `ConnectionsState`'s."""
        code = str(params.get("connect", "") or "") if is_tiktok_result(params) else ""
        self.connected_ok = code == "active"
        self.connect_notice, self.connect_notice_tone = connect_result_notice(code)
        self.action_error = ""

    @rx.event
    def dismiss_connected(self) -> rx.event.EventSpec:
        """«Ver mi TikTok»: close the panel and bring the account's card into view."""
        self.connected_ok = False
        return rx.scroll_to(ACCOUNTS_ELEMENT_ID)

    @rx.event(background=True)
    async def load(self) -> None:
        async with self:
            self.is_loading = True
            self.load_error = ""
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        tenant_id = tenant_uuid(session_tenant_id) if session_tenant_id else None
        if tenant_id is None:
            async with self:
                self.is_loading = False
                self.accounts = []
            return
        try:
            available = tiktok_available()
            accounts = await asyncio.to_thread(tiktok_accounts, tenant_id)
        except SQLAlchemyError as exc:
            logger.error("tiktok accounts load failed: %s", type(exc).__name__)
            async with self:
                self.is_loading = False
                self.load_error = LOAD_FAILED
            return
        async with self:
            auth = await self.get_state(AuthState)
            if session_tenant_id == auth.session_tenant_id:  # a logout raced this load
                self.available = available
                self.accounts = accounts
            self.is_loading = False

    @rx.event(background=True)
    async def start_connect(self) -> AsyncIterator[rx.event.EventSpec]:
        """«Conectar TikTok»: mint the one-shot consent URL now and send the browser there."""
        async for event in self._launch(connection_id=""):
            yield event

    @rx.event(background=True)
    async def reconnect(self, connection_id: str) -> AsyncIterator[rx.event.EventSpec]:
        """«Volver a conectar» on a card: the same TikTok account must come back."""
        async for event in self._launch(connection_id=connection_id):
            yield event

    async def _launch(self, *, connection_id: str) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            if self.connecting:
                return  # a double click must not mint two consent URLs
            self.connecting = True
            self.action_error = ""
            self.connect_notice = ""
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        tenant_id = tenant_uuid(session_tenant_id)
        target: UUID | None = None
        if connection_id:
            try:
                target = UUID(connection_id)
            except ValueError:
                target = None
        if tenant_id is None or (connection_id and target is None):
            async with self:
                self.connecting = False
                self.action_error = _NO_SESSION if tenant_id is None else NOT_FOUND
            return
        if not tiktok_available():
            async with self:
                self.connecting = False
                self.action_error = CONNECT_FAILED
            return
        try:
            started = await asyncio.to_thread(begin_tiktok_connect, tenant_id, target)
        except NoActingUser:
            async with self:
                self.connecting = False
                self.action_error = CONNECT_FAILED
            return
        except ConnectionNotFound:
            async with self:
                self.connecting = False
                self.action_error = NOT_FOUND
            yield TikTokConnectionsState.load
            return
        except (RedisError, SQLAlchemyError, KeyError) as exc:
            logger.error("tiktok start_connect failed: %s", type(exc).__name__)
            async with self:
                self.connecting = False
                self.action_error = CONNECT_FAILED
            return
        async with self:
            self.connecting = False
        yield bound_redirect(started)  # binding cookie, then TikTok (m-24921205)

    @rx.event(background=True)
    async def disconnect(self, connection_id: str) -> AsyncIterator[rx.event.EventSpec]:
        """Disconnect one TikTok account, then reload. `ConnectionNotFound` is reported as
        not-found and never as success (it also covers another tenant's id)."""
        async with self:
            if connection_id in self.busy_ids:
                return
            self.busy_ids.append(connection_id)
            self.action_error = ""
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        tenant_id = tenant_uuid(session_tenant_id)
        try:
            target = UUID(connection_id)
        except ValueError:
            target = None
        if tenant_id is None or target is None:
            async with self:
                self.busy_ids.remove(connection_id)
            return
        try:
            await disconnect_tiktok_account(tenant_id, target)
        except ConnectionNotFound:
            async with self:
                self.busy_ids.remove(connection_id)
                self.action_error = NOT_FOUND
            yield TikTokConnectionsState.load
            return
        except SQLAlchemyError as exc:
            logger.error("tiktok disconnect failed: %s", type(exc).__name__)
            async with self:
                self.busy_ids.remove(connection_id)
                self.action_error = DISCONNECT_FAILED
            return
        async with self:
            self.busy_ids.remove(connection_id)
        yield TikTokConnectionsState.load


class TikTokDraftState(rx.State):
    """«Enviar a TikTok» on `/drafts/[draft_id]`. The page shows the card
    only for an APPROVED piece (`CreativeState.draft.status`); this state says whether the
    piece is one video, which account receives it, and the last draft sent."""

    post_id: str = ""
    loaded: bool = False
    available: bool = False
    eligible: bool = False
    output_port: str = ""
    #: The piece was made for TikTok (`tiktok_video`): TikTok is its next step.
    tiktok_only: bool = False
    account_id: str = ""
    account_name: str = ""
    #: A TikTok account exists but none can receive a video (to reconnect).
    needs_reconnect: bool = False
    #: The account «Volver a conectar TikTok» brings back (the same one must return).
    reconnect_id: str = ""
    draft: TikTokDraftVM = TikTokDraftVM()
    #: m-24945954: the video is still a vista previa for the backend gate — no button,
    #: a neutral line saying when it can go (or that the owner confirms it first).
    final_wait: FinalWaitVM = FinalWaitVM()
    sending: bool = False
    polling: bool = False
    error: str = ""

    @rx.var
    def show_card(self) -> bool:
        """The piece is one video and TikTok is reachable from here: connected, or
        connectable (the card then invites to connect it)."""
        return self.loaded and self.eligible and (self.available or self.account_id != "")

    @rx.var
    def can_send(self) -> bool:
        return (
            self.account_id != ""
            and not self.sending
            and not self.draft.in_progress
            and not self.final_wait.waiting
        )

    @rx.var
    def review_href(self) -> str:
        """«Revisar video»: where the owner confirms the final before sending it."""
        return final_review_href(self.post_id) if self.post_id else ""

    @rx.var
    def connect_href(self) -> str:
        """Tus redes, with the way back to this piece (`?volver=`, N4)."""
        return f"/connections?volver=/drafts/{self.post_id}" if self.post_id else "/connections"

    def _route_post(self) -> UUID | None:
        raw = str(self.router.page.params.get("draft_id", "") or "")
        try:
            return UUID(raw)
        except ValueError:
            return None

    @rx.event(background=True)
    async def load(self) -> AsyncIterator[rx.event.EventSpec]:
        """on_load of the piece: which account, whether the piece is one video, and the
        last draft of it already sent (so a revisit shows «Enviado a TikTok»)."""
        async with self:
            post_id = self._route_post()
            self.post_id = str(post_id) if post_id else ""
            self.loaded = False
            self.error = ""
            self.draft = TikTokDraftVM()
            self.final_wait = FinalWaitVM()
            self.account_id = ""
            self.account_name = ""
            self.reconnect_id = ""
            self.tiktok_only = False
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        tenant_id = tenant_uuid(session_tenant_id) if session_tenant_id else None
        if tenant_id is None or post_id is None:
            return
        try:
            accounts = await asyncio.to_thread(tiktok_accounts, tenant_id)
            account = first_sendable(accounts)
            target = await asyncio.to_thread(tiktok_target, tenant_id, post_id)
            draft = (
                await asyncio.to_thread(latest_draft, tenant_id, post_id, target.output_port)
                if target.eligible
                else TikTokDraftVM()
            )
            wait = (
                await asyncio.to_thread(tiktok_final_wait, tenant_id, post_id, target.output_port)
                if target.eligible
                else FinalWaitVM()
            )
        except SQLAlchemyError as exc:
            # The card is an extra on this screen: a failed read hides it, never the piece.
            logger.error("tiktok draft card load failed: %s", type(exc).__name__)
            return
        async with self:
            if self.post_id != str(post_id):
                return  # the owner already opened another piece
            self.available = tiktok_available()
            self.eligible = target.eligible
            self.output_port = target.output_port
            self.tiktok_only = target.tiktok_only
            self.account_id = account.id if account else ""
            self.account_name = account.name if account else ""
            self.needs_reconnect = account is None and len(accounts) > 0
            self.reconnect_id = accounts[0].id if self.needs_reconnect else ""
            self.draft = draft
            self.final_wait = wait
            self.loaded = True
        if draft.in_progress:
            yield TikTokDraftState.poll

    @rx.event(background=True)
    async def check_final(self) -> None:
        """Ask the backend gate again whether the video final is ready (m-24945954) —
        right after the piece is approved here, and whenever its final changes on screen
        (`CreativeState.poll_final`), so the button appears without a reload. Once it is
        ready, a send refused only because it was a vista previa is cleared: the next try
        is the normal «Enviar a TikTok», never «Intentar de nuevo» after «No se envió»."""
        async with self:
            if not self.loaded or not self.eligible:
                return
            raw_post, port = self.post_id, self.output_port
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        tenant_id = tenant_uuid(session_tenant_id) if session_tenant_id else None
        post_id = tenant_uuid(raw_post)
        if tenant_id is None or post_id is None:
            return
        try:
            wait = await asyncio.to_thread(tiktok_final_wait, tenant_id, post_id, port)
        except SQLAlchemyError as exc:
            logger.error("tiktok final check failed: %s", type(exc).__name__)
            return  # keep what the card shows; the send itself still asks the gate
        async with self:
            if self.post_id != raw_post:
                return  # the owner already opened another piece
            self.final_wait = wait
            if is_final_wait_refusal(self.draft):
                self.draft = NO_DRAFT

    @rx.event(background=True)
    async def connect_here(self) -> AsyncIterator[rx.event.EventSpec]:
        """«Conectar TikTok» / «Volver a conectar TikTok» on the piece: start TikTok's
        consent straight away, remembering this piece as the way back — the same `?volver=`
        origin Tus redes keeps (`ConnectionsState.return_to`), so its «TikTok conectado»
        panel offers «Seguir donde estabas» back here."""
        async with self:
            post_id, reconnect_id = self.post_id, self.reconnect_id
            connections = await self.get_state(ConnectionsState)
            back = safe_return_path(f"/drafts/{post_id}") if post_id else ""
            connections.return_to = back or ""
        if reconnect_id:
            yield TikTokConnectionsState.reconnect(reconnect_id)
        else:
            yield TikTokConnectionsState.start_connect

    @rx.event(background=True)
    async def send(self) -> AsyncIterator[rx.event.EventSpec]:
        """«Enviar a TikTok» / «Intentar de nuevo». Idempotent: a double
        click, or a second click on a draft already sent, never puts a second video in
        the owner's TikTok (the backend's key is per approved revision and attempt)."""
        async with self:
            if (
                self.sending
                or self.draft.in_progress
                or not self.account_id
                or self.final_wait.waiting
            ):
                return
            self.sending = True
            self.error = ""
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
            session_user_id = auth._session_user_id
            raw_post, raw_account, port = self.post_id, self.account_id, self.output_port
        tenant_id = tenant_uuid(session_tenant_id)
        try:
            post_id, connection_id = UUID(raw_post), UUID(raw_account)
        except ValueError:
            post_id = connection_id = None  # type: ignore[assignment]
        if tenant_id is None or post_id is None or connection_id is None:
            async with self:
                self.sending = False
                self.error = _NO_SESSION
            return
        try:
            user_id = tenant_uuid(session_user_id) or await asyncio.to_thread(
                acting_user_id, tenant_id
            )
            if user_id is None:
                raise NoActingUser(str(tenant_id))
            failures = await asyncio.to_thread(
                failed_attempts, tenant_id, connection_id, post_id, port
            )
            draft = await send_to_tiktok_drafts(
                tenant_id=tenant_id,
                user_id=user_id,
                connection_id=connection_id,
                post_id=post_id,
                output_port=port,
                attempt=next_attempt(failures),
            )
        except Exception as exc:  # noqa: BLE001 — R2/Redis/HTTP/DB: the owner can retry
            logger.error("tiktok draft send failed: %s", type(exc).__name__)
            async with self:
                self.sending = False
                self.error = DRAFT_SEND_FAILED
            return
        wait = FinalWaitVM()
        if is_final_wait_refusal(draft):
            # The final went back to being made (or the card was stale): wait, calmly,
            # instead of «No se envió» — the owner did nothing wrong.
            try:
                wait = await asyncio.to_thread(tiktok_final_wait, tenant_id, post_id, port)
            except SQLAlchemyError as exc:
                logger.error("tiktok final check failed: %s", type(exc).__name__)
                wait = FinalWaitVM(True, FINAL_WAIT_NOTE)
            if not wait.waiting:
                wait = FinalWaitVM(True, FINAL_WAIT_NOTE)  # the gate said preview: trust it
        async with self:
            self.sending = False
            if self.post_id == raw_post:
                if wait.waiting:
                    self.final_wait = wait
                    self.draft = NO_DRAFT
                else:
                    self.draft = draft
        if draft.in_progress:
            yield TikTokDraftState.poll

    @rx.event(background=True)
    async def poll(self) -> None:
        """Read the draft's status every few seconds until TikTok settles it, then stop —
        and after `POLL_MAX_READS` stop anyway and say to come back (never endless)."""
        async with self:
            if self.polling:
                return
            self.polling = True
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
            raw_post, raw_account, raw_draft = self.post_id, self.account_id, self.draft.draft_id
        tenant_id = tenant_uuid(session_tenant_id)
        try:
            connection_id, draft_id = UUID(raw_account), UUID(raw_draft)
        except ValueError:
            connection_id = draft_id = None  # type: ignore[assignment]
        if tenant_id is None or connection_id is None or draft_id is None:
            async with self:
                self.polling = False
            return
        draft: TikTokDraftVM | None = None
        for _ in range(POLL_MAX_READS):
            await asyncio.sleep(POLL_SECONDS)
            try:
                draft = await refresh_draft(
                    tenant_id=tenant_id, connection_id=connection_id, draft_id=draft_id
                )
            except Exception as exc:  # noqa: BLE001 — transient: keep the last known state
                logger.warning("tiktok draft refresh failed: %s", type(exc).__name__)
                continue
            async with self:
                if self.post_id != raw_post:
                    self.polling = False
                    return  # the owner left this piece
                self.draft = draft
            if not draft.in_progress:
                break
        async with self:
            self.polling = False
            if self.post_id == raw_post and self.draft.in_progress:
                self.draft = build_draft_vm(
                    draft_id=self.draft.draft_id,
                    status=self.draft.status,
                    message=DRAFT_STILL_SENDING,
                )
