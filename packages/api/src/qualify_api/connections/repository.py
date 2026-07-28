"""Persistence for the connect flow (C-04.4).

A Protocol plus a Postgres implementation, so the callback's whole decision tree is
testable against an in-memory fake with no database — while the real writes still go
through `tenant_session`, the RLS-scoped door.

Two invariants live here rather than in the service, because they are properties of the
write itself:

**Idempotency.** The natural key is `unique(tenant_id, platform, external_account_id)`
— the first-party analogue of the pipeline's `(brand_id, platform, post_id)`.
Reconnecting an account UPDATEs the existing row and appends `oauth_credentials`
version+1; it never produces a second row. Re-running the callback is safe.

**Atomicity of the credential swap.** The new credential row and the
`current_credential_version` pointer that selects it are written in ONE transaction. Split
them and a crash in between leaves a connection pointing at a version that does not exist,
or a credential nothing can find. Nothing here ever UPDATEs or DELETEs a credential row —
`qualify_app` holds only INSERT on that table, so append-only is enforced by Postgres, not
by this code remembering to behave.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.connections.models import (
    ConnectionEvent,
    OAuthCredential,
    PlatformApp,
    SocialConnection,
)


class PlatformAppMissing(Exception):
    """No `platform_apps` row for the configured Meta app id.

    Global reference data (R1) written by `qualify_admin`/`qualify_owner`, never by the
    request path — so the fix is to seed it, not to have the callback create it.
    """


@dataclass(frozen=True)
class GrantInput:
    """Everything one completed consent produces. Assembled by the service; the ciphertext
    arrives already encrypted, so no plaintext token ever reaches this layer."""

    tenant_id: UUID
    brand_id: UUID | None
    user_id: UUID
    platform_app_id: UUID
    platform: str
    account_type: str
    external_account_id: str
    external_username: str | None
    linked_page_id: str
    granted_scopes: tuple[str, ...]
    access_posture: str
    ciphertext: bytes
    key_id: str
    token_type: str
    issued_at: datetime
    expires_at: datetime | None


@dataclass(frozen=True)
class ConnectionRecord:
    """The outcome of persisting a grant. `previous_status` is None for a brand-new
    connection — that is how the service knows whether to run the pending→active edge or
    the reconnect edge."""

    connection_id: UUID
    tenant_id: UUID
    credential_version: int
    previous_status: str | None

    @property
    def is_new(self) -> bool:
        return self.previous_status is None


class ConnectionRepository(Protocol):
    def platform_app_id(self, app_id: str, *, tenant_id: UUID) -> UUID: ...

    def persist_grant(self, grant: GrantInput) -> ConnectionRecord: ...

    def record_status(
        self,
        *,
        connection_id: UUID,
        tenant_id: UUID,
        status: str,
        verified_at: datetime | None,
        event_type: str,
        credential_version: int,
    ) -> None: ...


class PostgresConnectionRepository:
    """Writes through `tenant_session` — RLS scopes every statement to the grant's tenant,
    and `WITH CHECK` rejects a row whose `tenant_id` disagrees with the session's."""

    def platform_app_id(self, app_id: str, *, tenant_id: UUID) -> UUID:
        # `platform_apps` is global reference data with no RLS (R1), but it is still read
        # through a tenant session: there is no un-scoped door on the request path, and
        # this read always happens inside a flow that already knows its tenant.
        with tenant_session(tenant_id) as session:
            row = session.execute(
                select(PlatformApp.id).where(PlatformApp.app_id == app_id)
            ).first()
        if row is None:
            raise PlatformAppMissing(f"no platform_apps row for app_id={app_id!r}")
        return UUID(str(row[0]))

    def persist_grant(self, grant: GrantInput) -> ConnectionRecord:
        with tenant_session(grant.tenant_id) as session:
            existing = session.scalar(
                select(SocialConnection).where(
                    SocialConnection.tenant_id == grant.tenant_id,
                    SocialConnection.platform == grant.platform,
                    SocialConnection.external_account_id == grant.external_account_id,
                )
            )
            previous_status = existing.status if existing is not None else None

            if existing is None:
                connection = SocialConnection(
                    tenant_id=grant.tenant_id,
                    brand_id=grant.brand_id,
                    platform_app_id=grant.platform_app_id,
                    platform=grant.platform,
                    account_type=grant.account_type,
                    external_account_id=grant.external_account_id,
                    external_username=grant.external_username,
                    linked_page_id=grant.linked_page_id,
                    granted_scopes=list(grant.granted_scopes),
                    status="pending",
                    access_posture=grant.access_posture,
                    current_credential_version=0,
                    connected_by_user_id=grant.user_id,
                )
                session.add(connection)
                session.flush()
            else:
                connection = existing
                # A reconnect refreshes what the platform now reports, including a
                # re-consent that granted a DIFFERENT scope set than last time.
                connection.brand_id = grant.brand_id or connection.brand_id
                connection.external_username = grant.external_username
                connection.linked_page_id = grant.linked_page_id
                connection.granted_scopes = list(grant.granted_scopes)
                connection.access_posture = grant.access_posture
                connection.platform_app_id = grant.platform_app_id

            version = connection.current_credential_version + 1
            session.add(
                OAuthCredential(
                    connection_id=connection.id,
                    tenant_id=grant.tenant_id,
                    version=version,
                    token_type=grant.token_type,
                    ciphertext=grant.ciphertext,
                    key_id=grant.key_id,
                    issued_at=grant.issued_at,
                    expires_at=grant.expires_at,
                )
            )
            # Same transaction as the INSERT above — the pointer and the row it selects
            # must never be observable apart.
            connection.current_credential_version = version
            session.add(
                ConnectionEvent(
                    connection_id=connection.id,
                    tenant_id=grant.tenant_id,
                    credential_version=version,
                    event_type="granted" if previous_status is None else "reconnected",
                    actor="user",
                )
            )
            session.flush()
            return ConnectionRecord(
                connection_id=connection.id,
                tenant_id=grant.tenant_id,
                credential_version=version,
                previous_status=previous_status,
            )

    def record_status(
        self,
        *,
        connection_id: UUID,
        tenant_id: UUID,
        status: str,
        verified_at: datetime | None,
        event_type: str,
        credential_version: int,
    ) -> None:
        with tenant_session(tenant_id) as session:
            connection = session.get(SocialConnection, connection_id)
            if connection is None:  # RLS-filtered or gone; nothing to record
                return
            connection.status = status
            if verified_at is not None:
                connection.last_verified_at = verified_at
            session.add(
                ConnectionEvent(
                    connection_id=connection_id,
                    tenant_id=tenant_id,
                    credential_version=credential_version,
                    event_type=event_type,
                    actor="system",
                )
            )
            session.flush()
