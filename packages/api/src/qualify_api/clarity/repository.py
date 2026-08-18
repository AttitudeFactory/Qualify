"""Persistence seam for the clarity module.

`PostgresClarityRepository` goes through `tenant_session` exclusively — same custody
as leads: the tenant uuid only ever scopes an RLS transaction. `MemoryClarityRepository`
mirrors the semantics for the service tests (zero network, zero DB).

`fetches_on` counts snapshot rows on a UTC calendar date because that is the ledger
the daily budget reads: one successful API call == one snapshot row, so counting rows
counts spent quota. Requests made outside Qualify (a manual curl) are invisible to
this ledger — the service keeps its budget below Microsoft's 10 partly for that reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol
from uuid import UUID, uuid4

from qualify_shared.db.session import tenant_session
from sqlalchemy import Date, cast, func, select
from sqlalchemy.dialects.postgresql import insert

from qualify_api.clarity.models import ClaritySettings, ClaritySnapshot


@dataclass(frozen=True)
class SettingsRow:
    project_id: str
    token_ciphertext: bytes
    token_key_id: str
    active: bool


@dataclass(frozen=True)
class SnapshotRow:
    id: UUID
    num_of_days: int
    dimensions: list[str]
    payload: list[dict]
    fetched_at: datetime


class ClarityRepository(Protocol):
    def get_settings(self, *, tenant_id: UUID) -> SettingsRow | None: ...

    def upsert_settings(
        self,
        *,
        tenant_id: UUID,
        project_id: str,
        token_ciphertext: bytes,
        token_key_id: str,
        active: bool = True,
    ) -> UUID: ...

    def latest_snapshot(self, *, tenant_id: UUID) -> SnapshotRow | None: ...

    def insert_snapshot(
        self, *, tenant_id: UUID, num_of_days: int, dimensions: list[str], payload: list[dict]
    ) -> SnapshotRow: ...

    def fetches_on(self, *, tenant_id: UUID, day: date) -> int: ...


class PostgresClarityRepository:
    def get_settings(self, *, tenant_id: UUID) -> SettingsRow | None:
        with tenant_session(tenant_id) as session:
            row = session.scalar(select(ClaritySettings))
            if row is None:
                return None
            return SettingsRow(
                project_id=row.project_id,
                token_ciphertext=row.token_ciphertext,
                token_key_id=row.token_key_id,
                active=row.active,
            )

    def upsert_settings(
        self,
        *,
        tenant_id: UUID,
        project_id: str,
        token_ciphertext: bytes,
        token_key_id: str,
        active: bool = True,
    ) -> UUID:
        stmt = insert(ClaritySettings).values(
            tenant_id=tenant_id,
            project_id=project_id,
            token_ciphertext=token_ciphertext,
            token_key_id=token_key_id,
            active=active,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_clarity_settings_tenant",
            set_={
                "project_id": stmt.excluded.project_id,
                "token_ciphertext": stmt.excluded.token_ciphertext,
                "token_key_id": stmt.excluded.token_key_id,
                "active": stmt.excluded.active,
                "updated_at": func.now(),
            },
        ).returning(ClaritySettings.id)
        with tenant_session(tenant_id) as session:
            return session.execute(stmt).scalar_one()

    def latest_snapshot(self, *, tenant_id: UUID) -> SnapshotRow | None:
        with tenant_session(tenant_id) as session:
            row = session.scalar(
                select(ClaritySnapshot).order_by(ClaritySnapshot.fetched_at.desc()).limit(1)
            )
            if row is None:
                return None
            return _snapshot_row(row)

    def insert_snapshot(
        self, *, tenant_id: UUID, num_of_days: int, dimensions: list[str], payload: list[dict]
    ) -> SnapshotRow:
        with tenant_session(tenant_id) as session:
            row = ClaritySnapshot(
                tenant_id=tenant_id,
                num_of_days=num_of_days,
                dimensions=dimensions,
                payload=payload,
                fetched_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            return _snapshot_row(row)

    def fetches_on(self, *, tenant_id: UUID, day: date) -> int:
        with tenant_session(tenant_id) as session:
            count = session.scalar(
                select(func.count())
                .select_from(ClaritySnapshot)
                .where(cast(ClaritySnapshot.fetched_at, Date) == day)
            )
            return int(count or 0)


def _snapshot_row(row: ClaritySnapshot) -> SnapshotRow:
    return SnapshotRow(
        id=row.id,
        num_of_days=row.num_of_days,
        dimensions=list(row.dimensions),
        payload=list(row.payload),
        fetched_at=row.fetched_at,
    )


class MemoryClarityRepository:
    """Test double. Mirrors the Postgres implementation's semantics."""

    def __init__(self) -> None:
        self.settings: dict[UUID, tuple[UUID, SettingsRow]] = {}
        self.snapshots: dict[UUID, list[SnapshotRow]] = {}

    def get_settings(self, *, tenant_id: UUID) -> SettingsRow | None:
        stored = self.settings.get(tenant_id)
        return stored[1] if stored else None

    def upsert_settings(
        self,
        *,
        tenant_id: UUID,
        project_id: str,
        token_ciphertext: bytes,
        token_key_id: str,
        active: bool = True,
    ) -> UUID:
        row_id = self.settings[tenant_id][0] if tenant_id in self.settings else uuid4()
        self.settings[tenant_id] = (
            row_id,
            SettingsRow(
                project_id=project_id,
                token_ciphertext=token_ciphertext,
                token_key_id=token_key_id,
                active=active,
            ),
        )
        return row_id

    def latest_snapshot(self, *, tenant_id: UUID) -> SnapshotRow | None:
        rows = self.snapshots.get(tenant_id, [])
        return rows[-1] if rows else None

    def insert_snapshot(
        self, *, tenant_id: UUID, num_of_days: int, dimensions: list[str], payload: list[dict]
    ) -> SnapshotRow:
        row = SnapshotRow(
            id=uuid4(),
            num_of_days=num_of_days,
            dimensions=list(dimensions),
            payload=list(payload),
            fetched_at=datetime.now(UTC),
        )
        self.snapshots.setdefault(tenant_id, []).append(row)
        return row

    def fetches_on(self, *, tenant_id: UUID, day: date) -> int:
        rows = self.snapshots.get(tenant_id, [])
        return sum(1 for row in rows if row.fetched_at.date() == day)
