"""The connect flow itself (C-04): issue an authorization URL, then finish the callback.

Everything it depends on is a Protocol — platform, repository, jti store, verifier,
encryptor, event publisher — so the entire decision tree below runs against fakes with no
network and no database. That is what makes "cero red en CI" true rather than aspirational.

## The order of operations is the security design

1. **Verify the `state` signature, then spend its `jti`, BEFORE exchanging the code.** A
   forged or replayed callback must cost nothing: no token exchange, no platform call, no
   row. Spending the jti before the exchange also means a callback that crashes mid-flight
   cannot be retried by re-submitting the same URL.
2. **Enumerate Pages BEFORE persisting anything (R4).** There is no pre-auth API path to
   inspect an account you have no token for, so the login fork of ADR 25 cannot happen
   before the URL is issued — it happens here, after consent. If no Page with a linked
   Instagram account comes back, the result is `link_required`: the token is dropped in
   memory, and **no `social_connections` row and no `oauth_credentials` row are written**.
   `linked_page_id` is NOT NULL precisely so this state is unrepresentable rather than
   merely avoided.
3. **Record what was GRANTED, never what was requested (C-04.3).** Meta allows partial
   consent. The literals are stored verbatim; nothing here interprets them.
4. **Encrypt before persisting, verify through the resolver after.** The plaintext token
   exists only between `exchange_code` and `encrypt`. The post-connection check that
   decides active-vs-degraded goes through `CredentialResolver`, which returns an
   authenticated client and never a token — so even this module, which briefly held the
   plaintext, does not reuse it.

A verification failure yields `degraded`, never `active`. The distinction is not cosmetic:
it separates "a transient network blip" from "the client revoked us in the Instagram app",
and it is what lets the UI ask for a reconnect instead of silently showing stale data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.crypto import Encryptor
from qualify_api.connections.events import (
    DomainEvent,
    DomainEventName,
    EventPublisher,
)
from qualify_api.connections.fsm import ConnectionStatus, Trigger, apply_transition
from qualify_api.connections.meta_oauth import LinkedPage, MetaOAuthClient
from qualify_api.connections.repository import (
    ConnectionRepository,
    GrantInput,
)
from qualify_api.connections.state_token import (
    InvalidState,
    JtiStore,
    new_payload,
    sign_state,
    verify_state,
)

# The platform this sprint connects. Facebook Pages are enumerated as the LINK requirement
# (ADR 25), but the account Qualify attaches is the Instagram Business/Creator one.
_PLATFORM = "instagram"
_ACCOUNT_TYPE = "business"

# Module logger. This flow deliberately logs COUNTS and outcomes only: the objects in scope
# here are a token, page ids and usernames, and none of those belong in a log aggregator.
_LOGGER = logging.getLogger(__name__)


class ConnectOutcome(StrEnum):
    ACTIVE = "active"
    DEGRADED = "degraded"
    # `/me/accounts` returned Pages, but none has a linked Instagram account. The genuine R4
    # case. Operator instruction: "link your Instagram account to your Page."
    LINK_REQUIRED = "link_required"
    # `/me/accounts` returned NOTHING. A different problem with an OPPOSITE instruction:
    # "give the app access to your Page." R9(f) split this out of `link_required`, which
    # had been carrying both. Meta filters that edge by TASKS, not ownership
    # (`business-login-for-instagram.md:118`: "Pages that the user can perform tasks on"),
    # so administering the Business Portfolio that owns a Page is NOT the same as holding a
    # task on it — telling such an operator to "link your Instagram" sends them to a setting
    # that is already correct.
    PAGE_ACCESS_REQUIRED = "page_access_required"


@dataclass(frozen=True)
class ConnectResult:
    outcome: ConnectOutcome
    connection_id: UUID | None
    external_username: str | None
    # The two integers R9(e.1) orders recorded, so the empirical test can distinguish
    # "the edge returned nothing" from "it returned Pages that carry no IG account"
    # WITHOUT a second live run. Counts only: no ids, no names, no token — nothing here is
    # PII, which is what makes them safe to log and to return.
    page_count: int = 0
    linked_page_count: int = 0


class ConnectionVerifier(Protocol):
    """Cheap post-connection identity check. Implementations MUST go through
    `CredentialResolver` — they receive ids, never a token."""

    async def verify(self, *, tenant_id: UUID, connection_id: UUID) -> bool: ...


def _audit_event_type(status: ConnectionStatus, *, verified: bool) -> str:
    """The `connection_events` row type for a post-verification outcome.

    Audit rows and domain events are NOT 1:1 (see `events.py`): this row is written even
    when no transition fired, because "we tried to verify and it failed" is a fact worth
    keeping when someone later asks why a client went dark.
    """
    if status is ConnectionStatus.DEGRADED:
        return "degraded"
    return "granted" if verified else "refresh_failed"


def _first_linked_page(pages: tuple[LinkedPage, ...]) -> LinkedPage | None:
    """The first Page that actually carries a linked Instagram account.

    Pages with no linked IG account do not count: the user may administer several Pages
    and have linked none of them, which is exactly the `link_required` case R4 describes.
    """
    return next((page for page in pages if page.instagram_account_id), None)


def _no_connection_outcome(pages: tuple[LinkedPage, ...]) -> ConnectOutcome:
    """Which of the two dead ends this is (R9f).

    Zero Pages and "Pages but none linked" are not degrees of the same problem: they need
    opposite instructions from the operator, so they are separate outcomes rather than one
    outcome with a detail field somebody might not read.
    """
    return ConnectOutcome.PAGE_ACCESS_REQUIRED if not pages else ConnectOutcome.LINK_REQUIRED


class ConnectService:
    def __init__(
        self,
        *,
        settings: MetaOAuthSettings,
        oauth_client: MetaOAuthClient,
        repository: ConnectionRepository,
        jti_store: JtiStore,
        encryptor: Encryptor,
        verifier: ConnectionVerifier,
        publisher: EventPublisher,
    ) -> None:
        self._settings = settings
        self._oauth = oauth_client
        self._repo = repository
        self._jti = jti_store
        self._encryptor = encryptor
        self._verifier = verifier
        self._publisher = publisher

    def start_connect(self, *, tenant_id: UUID, brand_id: UUID | None, user_id: UUID) -> str:
        """Register a one-shot `state` and return the authorization URL to redirect to."""
        payload = new_payload(tenant_id, brand_id, user_id)
        self._jti.issue(payload.jti)
        state = sign_state(payload, self._settings.state_secret)
        return self._oauth.authorization_url(state=state)

    async def complete_connect(self, *, code: str, state: str) -> ConnectResult:
        """Finish the flow. Raises `InvalidState` (→ `invalid_state`) for a bad/replayed `state`."""
        payload = verify_state(
            state, self._settings.state_secret, ttl_seconds=self._settings.state_ttl_seconds
        )
        # Atomic GETDEL. A concurrent duplicate callback loses this race and gets nothing.
        if not self._jti.consume(payload.jti):
            raise InvalidState("state already consumed")

        grant = await self._oauth.exchange_code(code)

        # --- R4: the binding gate. Post-consent enumeration, pre-persistence. ---
        pages = await self._oauth.list_linked_pages(grant.access_token)
        page_count = len(pages)
        linked_page_count = sum(1 for candidate in pages if candidate.instagram_account_id)
        page = _first_linked_page(pages)
        if page is None or page.instagram_account_id is None:
            outcome = _no_connection_outcome(pages)
            # Counts only — never a page id, page name, username or token. This is the
            # observation R9(e.1) needs, and logging it here means the first real run
            # produces the evidence instead of prompting a second run to go get it.
            _LOGGER.warning(
                "connect flow ended without a connection: outcome=%s pages=%d pages_with_ig=%d",
                outcome,
                page_count,
                linked_page_count,
            )
            # `grant` goes out of scope unpersisted. The jti stays spent, so recovering
            # means starting a fresh flow — which is correct: the user must go fix access.
            return ConnectResult(
                outcome=outcome,
                connection_id=None,
                external_username=None,
                page_count=page_count,
                linked_page_count=linked_page_count,
            )

        granted_scopes = await self._oauth.list_granted_scopes(grant.access_token)

        # --- A0: custody the PAGE token, not the user one. ---
        # The Instagram-API-with-Facebook-Login fork publishes with a Facebook Page access
        # token (content-publishing.md:30); the user token `exchange_code` yields is not
        # it. `/me/permissions` above still uses the in-memory user token — that read
        # needs no custody. `[V]` fallback: if the Page carried no token, the user token
        # is persisted as before, distinguishable forever by `token_type`.
        page_token = page.page_access_token
        if page_token is None:
            _LOGGER.warning(
                "page access_token absent from /me/accounts; persisting USER token as fallback"
            )

        now = datetime.now(UTC)
        record = self._repo.persist_grant(
            GrantInput(
                tenant_id=payload.tenant_id,
                brand_id=payload.brand_id,
                user_id=payload.user_id,
                platform_app_id=self._repo.platform_app_id(
                    self._settings.app_id, tenant_id=payload.tenant_id
                ),
                platform=_PLATFORM,
                account_type=_ACCOUNT_TYPE,
                external_account_id=page.instagram_account_id,
                external_username=page.instagram_username,
                linked_page_id=page.page_id,
                granted_scopes=granted_scopes,
                access_posture=self._settings.access_posture,
                # Encrypted HERE. Past this line the plaintext is unreferenced.
                ciphertext=self._encryptor.encrypt(page_token or grant.access_token),
                key_id=self._encryptor.key_id,
                token_type="page" if page_token is not None else grant.token_type,
                issued_at=now,
                # `[V]` conservative: the page token's real lifetime is unobserved, so the
                # user grant's expiry stands in — it can only under-promise, never over.
                expires_at=now + timedelta(seconds=grant.expires_in) if grant.expires_in else None,
            )
        )
        self._publisher.publish(
            DomainEvent(
                name=DomainEventName.GRANTED,
                connection_id=record.connection_id,
                tenant_id=record.tenant_id,
                occurred_at=now,
                data={"credential_version": record.credential_version},
            )
        )

        verified = await self._verifier.verify(
            tenant_id=record.tenant_id, connection_id=record.connection_id
        )
        status = self._apply_post_grant_status(
            previous_status=record.previous_status,
            verified=verified,
            connection_id=record.connection_id,
            tenant_id=record.tenant_id,
            credential_version=record.credential_version,
            now=now,
        )
        return ConnectResult(
            outcome=ConnectOutcome.ACTIVE
            if status == ConnectionStatus.ACTIVE
            else ConnectOutcome.DEGRADED,
            connection_id=record.connection_id,
            external_username=page.instagram_username,
        )

    def _apply_post_grant_status(
        self,
        *,
        previous_status: str | None,
        verified: bool,
        connection_id: UUID,
        tenant_id: UUID,
        credential_version: int,
        now: datetime,
    ) -> ConnectionStatus:
        """Drive the C-03 FSM to the post-verification status.

        Invents NO edges of its own — `fsm.py` owns the lifecycle, and a connect flow
        should not be able to make up transitions. Where the FSM has no legal edge the
        status is left untouched and only an audit row is written, which is the
        conservative reading: an audit row is a fact that happened, a domain event is a
        transition, and no transition occurred.

        Q2 is now ruled (C-04 Q2, architect): a failed verification on a `revoked`
        connection fires `VERIFY_FAIL` and lands in `degraded`. Q1 — re-verifying an
        already-`active` connection — remains unruled and stays a no-op.
        """
        previous = ConnectionStatus(previous_status) if previous_status is not None else None
        trigger = self._post_grant_trigger(previous, verified=verified)

        if trigger is None:
            # No legal edge (Q1/Q2). Status stands; only the audit row records the attempt.
            status = previous if previous is not None else ConnectionStatus.PENDING
        else:
            status = apply_transition(
                previous if previous is not None else ConnectionStatus.PENDING,
                trigger,
                connection_id=connection_id,
                tenant_id=tenant_id,
                publisher=self._publisher,
                now=now,
            )

        self._repo.record_status(
            connection_id=connection_id,
            tenant_id=tenant_id,
            status=str(status),
            verified_at=now if verified else None,
            event_type=_audit_event_type(status, verified=verified),
            credential_version=credential_version,
        )
        return status

    @staticmethod
    def _post_grant_trigger(previous: ConnectionStatus | None, *, verified: bool) -> Trigger | None:
        """Which FSM edge (if any) this grant + verification outcome fires.

        None means "no legal edge" — see the Q1 note above.
        """
        if previous is None:  # brand-new connection, born pending
            return Trigger.VERIFY_OK if verified else Trigger.VERIFY_FAIL
        if verified:
            # Q1: an already-active connection re-verifying is not a transition.
            return None if previous is ConnectionStatus.ACTIVE else Trigger.RECONNECT
        if previous is ConnectionStatus.ACTIVE:
            return Trigger.AUTH_ERROR
        if previous is ConnectionStatus.REVOKED:
            # Q2 ruling: the row now carries a fresh credential, so `revoked` would be a
            # lie about its own state. Degrade instead — see the edge's note in `fsm.py`.
            return Trigger.VERIFY_FAIL
        # `degraded` is already the answer this would produce; no transition, no event.
        return None
