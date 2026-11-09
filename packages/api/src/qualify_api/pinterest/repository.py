"""Tenant metadata and append-only encrypted credential writes."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from threading import RLock
from typing import Protocol
from uuid import UUID, uuid4

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.pinterest.client import PinterestError


@dataclass(frozen=True)
class Connection:
    id: UUID
    tenant_id: UUID
    username: str = ""
    status: str = "disconnected"
    version: int = 0


@dataclass(frozen=True)
class Credential:
    ciphertext: bytes = field(repr=False)
    key_id: str
    version: int


class Repository(Protocol):
    def authorize(self, tenant_id: UUID, user_id: UUID) -> None: ...
    def connection(self, tenant_id: UUID) -> Connection | None: ...
    def ensure(self, tenant_id: UUID) -> Connection: ...
    def read(self, tenant_id: UUID) -> Credential: ...
    def save(
        self,
        tenant_id: UUID,
        *,
        expected_version: int,
        username: str,
        user_id: UUID | None,
        ciphertext: bytes,
        key_id: str,
        expires_at: datetime,
    ) -> bool: ...
    def disconnect(self, tenant_id: UUID, user_id: UUID) -> None: ...
    def unavailable(self, tenant_id: UUID, expected_version: int) -> None: ...


class PostgresRepository:
    def authorize(self, tenant_id: UUID, user_id: UUID) -> None:
        with tenant_session(tenant_id) as session:
            member = session.scalar(
                text("""SELECT u.id FROM users u JOIN tenant_members m
                ON m.user_id=u.id AND m.tenant_id=u.tenant_id
                WHERE u.id=:uid AND u.tenant_id=:tid AND m.role IN ('owner','admin')"""),
                {"uid": user_id, "tid": tenant_id},
            )
            if member is None:
                raise PinterestError("permission", 403)

    def connection(self, tenant_id: UUID) -> Connection | None:
        with tenant_session(tenant_id) as session:
            row = session.execute(
                text("SELECT id,tenant_id,username,status,version FROM pinterest_connections")
            ).first()
        return Connection(*row) if row else None

    def ensure(self, tenant_id: UUID) -> Connection:
        with tenant_session(tenant_id) as session:
            session.execute(
                text(
                    "INSERT INTO pinterest_connections(tenant_id) VALUES (:tid) "
                    "ON CONFLICT(tenant_id) DO NOTHING"
                ),
                {"tid": tenant_id},
            )
        connection = self.connection(tenant_id)
        if connection is None:
            raise PinterestError("not_found")
        return connection

    def read(self, tenant_id: UUID) -> Credential:
        from qualify_api.connections.credential_reader import read_pinterest_credential

        return read_pinterest_credential(tenant_id)

    def save(
        self,
        tenant_id: UUID,
        *,
        expected_version: int,
        username: str,
        user_id: UUID | None,
        ciphertext: bytes,
        key_id: str,
        expires_at: datetime,
    ) -> bool:
        with tenant_session(tenant_id) as session:
            row = session.execute(
                text("SELECT id,version FROM pinterest_connections FOR UPDATE")
            ).first()
            if row is None or row.version != expected_version:
                return False
            # The actor must be a member of this business, including multi-business memberships.
            if user_id is not None:
                member = session.scalar(
                    text("""SELECT u.id FROM users u JOIN tenant_members m
                    ON m.user_id=u.id AND m.tenant_id=u.tenant_id
                    WHERE u.id=:uid AND u.tenant_id=:tid AND m.role IN ('owner','admin')
                    FOR UPDATE OF m"""),
                    {"uid": user_id, "tid": tenant_id},
                )
                if member is None:
                    raise PinterestError("permission", 403)
            version = expected_version + 1
            session.execute(
                text("""INSERT INTO pinterest_credentials
                (tenant_id,connection_id,version,ciphertext,key_id,expires_at)
                VALUES (:tid,:cid,:v,:ct,:kid,:expiry)"""),
                {
                    "tid": tenant_id,
                    "cid": row.id,
                    "v": version,
                    "ct": ciphertext,
                    "kid": key_id,
                    "expiry": expires_at,
                },
            )
            session.execute(
                text("""UPDATE pinterest_connections SET username=:name,status='active',version=:v,
                connected_by_user_id=COALESCE(:uid,connected_by_user_id),updated_at=now()"""),
                {"name": username, "v": version, "uid": user_id},
            )
        return True

    def disconnect(self, tenant_id: UUID, user_id: UUID) -> None:
        with tenant_session(tenant_id) as session:
            # Match save(): connection before membership, never the opposite order.
            session.execute(text("SELECT id FROM pinterest_connections FOR UPDATE")).first()
            member = session.scalar(
                text("""SELECT u.id FROM users u JOIN tenant_members m
                ON m.user_id=u.id AND m.tenant_id=u.tenant_id
                WHERE u.id=:uid AND u.tenant_id=:tid AND m.role IN ('owner','admin')
                FOR UPDATE OF m"""),
                {"uid": user_id, "tid": tenant_id},
            )
            if member is None:
                raise PinterestError("permission", 403)
            # Version invalidates both in-flight callbacks and rotating refreshes.
            cutoff = session.scalar(
                text("""UPDATE pinterest_connections SET status='disconnected',username='',
                version=version+1,updated_at=now() RETURNING version""")
            )
        # Only the credential custodian erases old ciphertext; app has no secret SELECT.
        from qualify_api.connections.credential_reader import erase_pinterest_credentials

        if cutoff is not None:
            erase_pinterest_credentials(tenant_id, int(cutoff))

    def unavailable(self, tenant_id: UUID, expected_version: int) -> None:
        with tenant_session(tenant_id) as session:
            session.execute(
                text("""UPDATE pinterest_connections SET status='reconnect',updated_at=now()
                WHERE version=:v AND status='active'"""),
                {"v": expected_version},
            )


class MemoryRepository:
    """Synthetic per-tenant store for contract tests; never configured in production."""

    def __init__(self) -> None:
        self.connections: dict[UUID, Connection] = {}
        self.credentials: dict[UUID, Credential] = {}
        self._lock = RLock()
        self.denied_users: set[tuple[UUID, UUID]] = set()

    def authorize(self, tenant_id: UUID, user_id: UUID) -> None:
        if (tenant_id, user_id) in self.denied_users:
            raise PinterestError("permission", 403)

    def connection(self, tenant_id: UUID) -> Connection | None:
        return self.connections.get(tenant_id)

    def ensure(self, tenant_id: UUID) -> Connection:
        with self._lock:
            return self.connections.setdefault(tenant_id, Connection(uuid4(), tenant_id))

    def read(self, tenant_id: UUID) -> Credential:
        row = self.connection(tenant_id)
        credential = self.credentials.get(tenant_id)
        if (
            row is None
            or row.status != "active"
            or credential is None
            or row.version != credential.version
        ):
            raise PinterestError("authentication", 401)
        return credential

    def save(
        self,
        tenant_id: UUID,
        *,
        expected_version: int,
        username: str,
        user_id: UUID | None,
        ciphertext: bytes,
        key_id: str,
        expires_at: datetime,
    ) -> bool:
        with self._lock:
            row = self.ensure(tenant_id)
            if user_id is not None:
                self.authorize(tenant_id, user_id)
            if row.version != expected_version:
                return False
            self.connections[tenant_id] = replace(
                row, username=username, status="active", version=row.version + 1
            )
            self.credentials[tenant_id] = Credential(ciphertext, key_id, row.version + 1)
            return True

    def disconnect(self, tenant_id: UUID, user_id: UUID) -> None:
        with self._lock:
            self.authorize(tenant_id, user_id)
            row = self.ensure(tenant_id)
            self.connections[tenant_id] = replace(
                row, status="disconnected", username="", version=row.version + 1
            )
            self.credentials.pop(tenant_id, None)

    def unavailable(self, tenant_id: UUID, expected_version: int) -> None:
        with self._lock:
            row = self.connection(tenant_id)
            if row and row.version == expected_version and row.status == "active":
                self.connections[tenant_id] = replace(row, status="reconnect")
