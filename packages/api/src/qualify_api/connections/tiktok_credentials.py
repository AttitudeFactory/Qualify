"""TikTok credential custody: refresh-token rotation behind the resolver seam (m-24921091).

Meta tokens never rotate in this repo; TikTok's do. The access token lives 24 h and the
refresh token ~365 days, and a refresh may return a NEW refresh token that replaces the old
one. So the credential is an encrypted JSON blob (`TikTokTokens.to_blob`) and this module is
the only place that reads, refreshes and rewrites it:

- `TikTokCredentialResolver.client_for` returns an authenticated client and never a token,
  exactly like `InjectingCredentialResolver`; the refresh happens inside it, on demand.
- **One refresh in flight per connection** (`RefreshLock`, C-03.4) and a double check inside
  the lock: a contender that lost the race re-reads and uses the winner's token. TikTok
  invalidates a refresh token once it is rotated, so two concurrent refreshes would
  disconnect the account.
- **Append-only rotation.** The new blob is a new `oauth_credentials` version written in one
  transaction with the pointer, guarded by the version read BEFORE the refresh: a reconnect
  that landed meanwhile is never overwritten by a refresh of the old grant.
- A dead refresh token (or an expired one) degrades the connection with `auth_expired`
  (reconnect needed) and raises `TikTokReconnectRequired`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

import httpx
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.connections.crypto import Encryptor
from qualify_api.connections.locks import RefreshLock
from qualify_api.connections.models import ConnectionEvent, OAuthCredential, SocialConnection
from qualify_api.connections.resolver import (
    AuthenticatedClient,
    CredentialReader,
    build_authenticated_client,
)
from qualify_api.connections.tiktok_oauth import (
    TikTokOAuthClient,
    TikTokOAuthError,
    TikTokTokens,
)

_LOGGER = logging.getLogger(__name__)

#: Refresh when the access token has less than this left (it lives 24 h).
REFRESH_MARGIN = timedelta(minutes=10)
_LOCK_WAIT_STEPS = 5
_LOCK_WAIT_SECONDS = 1.0


class TikTokReconnectRequired(Exception):
    """The stored grant can no longer produce a working token: the client must reconnect."""


class TikTokRefreshBusy(Exception):
    """Another worker is refreshing this connection and did not finish in time. Transient."""


class TikTokCredentialRotator(Protocol):
    def current_version(self, *, tenant_id: UUID, connection_id: UUID) -> int | None: ...

    def rotate(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        expected_version: int,
        ciphertext: bytes,
        key_id: str,
        issued_at: datetime,
        expires_at: datetime,
    ) -> int | None:
        """Append version+1 and move the pointer; None if the version moved (lost a race)."""
        ...


class PostgresTikTokCredentialRotator:
    def current_version(self, *, tenant_id: UUID, connection_id: UUID) -> int | None:
        with tenant_session(tenant_id) as session:
            return session.scalar(
                select(SocialConnection.current_credential_version).where(
                    SocialConnection.id == connection_id, SocialConnection.tenant_id == tenant_id
                )
            )

    def rotate(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        expected_version: int,
        ciphertext: bytes,
        key_id: str,
        issued_at: datetime,
        expires_at: datetime,
    ) -> int | None:
        with tenant_session(tenant_id) as session:
            connection = session.scalar(
                select(SocialConnection)
                .where(
                    SocialConnection.id == connection_id, SocialConnection.tenant_id == tenant_id
                )
                .with_for_update()
            )
            if connection is None or connection.current_credential_version != expected_version:
                return None
            version = expected_version + 1
            session.add(
                OAuthCredential(
                    connection_id=connection_id,
                    tenant_id=tenant_id,
                    version=version,
                    token_type="tiktok",
                    ciphertext=ciphertext,
                    key_id=key_id,
                    issued_at=issued_at,
                    expires_at=expires_at,
                )
            )
            connection.current_credential_version = version
            session.add(
                ConnectionEvent(
                    connection_id=connection_id,
                    tenant_id=tenant_id,
                    credential_version=version,
                    event_type="refreshed",
                    actor="system",
                )
            )
            session.flush()
            return version


class TikTokCredentialResolver:
    """Bound to one tenant at construction (same discipline as `DbCredentialReader`)."""

    def __init__(
        self,
        *,
        tenant_id: UUID,
        reader: CredentialReader,
        encryptor: Encryptor,
        oauth: TikTokOAuthClient,
        rotator: TikTokCredentialRotator,
        lock: RefreshLock | None,
        degrader: Callable[[UUID], None] | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._tenant_id = tenant_id
        self._reader = reader
        self._encryptor = encryptor
        self._oauth = oauth
        self._rotator = rotator
        self._lock = lock
        self._degrader = degrader
        self._now = now
        self._transport = transport

    def _load(self, connection_id: UUID) -> TikTokTokens:
        credential = self._reader.read_current(connection_id)
        blob = self._encryptor.decrypt(credential.ciphertext, key_id=credential.key_id)
        return TikTokTokens.from_blob(blob)

    def _fresh(self, tokens: TikTokTokens) -> bool:
        return tokens.access_expires_at - REFRESH_MARGIN > self._now()

    def _reconnect(self, connection_id: UUID) -> TikTokReconnectRequired:
        if self._degrader is not None:
            self._degrader(connection_id)
        return TikTokReconnectRequired("tiktok grant expired or revoked")

    async def client_for(
        self, connection_id: UUID, *, scheme: str = "Bearer"
    ) -> AuthenticatedClient:
        tokens = await self._usable_tokens(connection_id)
        return build_authenticated_client(
            tokens.access_token, scheme=scheme, transport=self._transport
        )

    async def revoke_at_provider(self, connection_id: UUID) -> None:
        """Best effort on disconnect: ask TikTok to invalidate the access token."""
        try:
            await self._oauth.revoke(self._load(connection_id).access_token)
        except Exception as exc:  # noqa: BLE001 — the local revocation already happened
            _LOGGER.warning("tiktok provider revoke failed: %s", type(exc).__name__)

    async def _usable_tokens(self, connection_id: UUID) -> TikTokTokens:
        tokens = self._load(connection_id)
        if self._fresh(tokens):
            return tokens
        if tokens.refresh_expires_at <= self._now():
            raise self._reconnect(connection_id)
        if self._lock is None:
            return await self._refresh(connection_id)
        for _ in range(_LOCK_WAIT_STEPS):
            with self._lock.acquire(self._tenant_id, connection_id) as got:
                if got:
                    # Double check INSIDE the lock: a winner may have refreshed already.
                    current = self._load(connection_id)
                    if self._fresh(current):
                        return current
                    return await self._refresh(connection_id)
            await asyncio.sleep(_LOCK_WAIT_SECONDS)
            current = self._load(connection_id)
            if self._fresh(current):
                return current
        raise TikTokRefreshBusy("another refresh is in flight")

    async def _refresh(self, connection_id: UUID) -> TikTokTokens:
        version = self._rotator.current_version(
            tenant_id=self._tenant_id, connection_id=connection_id
        )
        if version is None:
            raise self._reconnect(connection_id)
        old = self._load(connection_id)
        try:
            new = await self._oauth.refresh(old.refresh_token)
        except TikTokOAuthError as exc:
            if exc.is_permanent_auth_failure:
                raise self._reconnect(connection_id) from None
            raise
        rotated = self._rotator.rotate(
            tenant_id=self._tenant_id,
            connection_id=connection_id,
            expected_version=version,
            ciphertext=self._encryptor.encrypt(new.to_blob()),
            key_id=self._encryptor.key_id,
            issued_at=self._now(),
            expires_at=new.access_expires_at,
        )
        if rotated is None:
            # A reconnect landed while we refreshed: its grant wins; use it.
            return self._load(connection_id)
        return new


class TikTokConnectionVerifier:
    """Post-connection check through the resolver: a successful `/v2/user/info/` call."""

    def __init__(self, resolver_factory: Callable[[UUID], TikTokCredentialResolver], base_url: str):
        self._resolver_factory = resolver_factory
        self._base_url = base_url.rstrip("/")

    async def verify(self, *, tenant_id: UUID, connection_id: UUID) -> bool:
        try:
            client = await self._resolver_factory(tenant_id).client_for(connection_id)
        except Exception:  # noqa: BLE001 — any credential failure is a failed verification
            return False
        try:
            response = await client.get(
                f"{self._base_url}/v2/user/info/", params={"fields": "open_id"}
            )
        except Exception:  # noqa: BLE001
            return False
        finally:
            aclose = getattr(client, "aclose", None)
            if aclose is not None:
                await aclose()
        return response.status_code == 200
