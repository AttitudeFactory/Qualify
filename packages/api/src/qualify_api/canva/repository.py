"""Persistence for the Canva round trip: a Protocol, an in-memory implementation for unit
tests, and the Postgres one (through `tenant_session`, so RLS scopes every query — a
`correlation_state` from another tenant simply finds nothing)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.canva.models import CanvaAccount, CanvaDesignLink
from qualify_api.creative.models import ImageAsset


@dataclass(frozen=True)
class AccountRecord:
    tenant_id: UUID
    user_id: UUID
    access_token_ciphertext: bytes
    refresh_token_ciphertext: bytes
    key_id: str
    expires_at: datetime
    scope: str


@dataclass(frozen=True)
class MediaRef:
    """One stored file of a draft (`image_assets`)."""

    object_key: str
    media_type: str
    width: int | None
    height: int | None
    position: int


@dataclass(frozen=True)
class NewLink:
    tenant_id: UUID
    draft_id: UUID
    created_by_user_id: UUID
    source_object_key: str
    media_type: str
    canva_design_id: str
    correlation_state: str
    edit_url: str
    design_updated_at: int | None


@dataclass(frozen=True)
class LinkRecord:
    id: UUID
    tenant_id: UUID
    draft_id: UUID
    created_by_user_id: UUID
    source_object_key: str
    media_type: str
    canva_design_id: str
    correlation_state: str
    edit_url: str
    status: str
    design_updated_at: int | None
    exported_object_key: str | None
    exported_at: datetime | None
    error: str | None
    created_at: datetime


class CanvaRepository(Protocol):
    def get_account(self, *, tenant_id: UUID, user_id: UUID) -> AccountRecord | None: ...

    def save_account(self, account: AccountRecord) -> None:
        """Insert or replace the user's tokens (a refresh spends the old refresh token,
        so the new pair always overwrites)."""
        ...

    def delete_account(self, *, tenant_id: UUID, user_id: UUID) -> None: ...

    def draft_media(self, *, tenant_id: UUID, draft_id: UUID) -> list[MediaRef]:
        """The draft's stored files, in position order (only those with an object key)."""
        ...

    def add_link(self, new: NewLink) -> LinkRecord: ...

    def get_link(self, *, tenant_id: UUID, link_id: UUID) -> LinkRecord | None: ...

    def link_by_correlation(
        self, *, tenant_id: UUID, correlation_state: str
    ) -> LinkRecord | None: ...

    def links_for_draft(self, *, tenant_id: UUID, draft_id: UUID) -> list[LinkRecord]:
        """Newest first."""
        ...

    def mark_exported(
        self,
        *,
        tenant_id: UUID,
        link_id: UUID,
        object_key: str,
        design_updated_at: int | None,
    ) -> LinkRecord: ...

    def mark_failed(self, *, tenant_id: UUID, link_id: UUID, error: str) -> LinkRecord: ...


# ---------------------------------------------------------------------------------------
# in memory (unit tests)


class InMemoryCanvaRepository:
    def __init__(self) -> None:
        self.accounts: dict[tuple[UUID, UUID], AccountRecord] = {}
        self.links: dict[UUID, LinkRecord] = {}
        self.media: dict[tuple[UUID, UUID], list[MediaRef]] = {}

    def get_account(self, *, tenant_id: UUID, user_id: UUID) -> AccountRecord | None:
        return self.accounts.get((tenant_id, user_id))

    def save_account(self, account: AccountRecord) -> None:
        self.accounts[(account.tenant_id, account.user_id)] = account

    def delete_account(self, *, tenant_id: UUID, user_id: UUID) -> None:
        self.accounts.pop((tenant_id, user_id), None)

    def draft_media(self, *, tenant_id: UUID, draft_id: UUID) -> list[MediaRef]:
        return sorted(self.media.get((tenant_id, draft_id), []), key=lambda m: m.position)

    def add_link(self, new: NewLink) -> LinkRecord:
        record = LinkRecord(
            id=uuid4(),
            **new.__dict__,
            status="open",
            exported_object_key=None,
            exported_at=None,
            error=None,
            created_at=datetime.now(UTC),
        )
        self.links[record.id] = record
        return record

    def get_link(self, *, tenant_id: UUID, link_id: UUID) -> LinkRecord | None:
        link = self.links.get(link_id)
        return link if link is not None and link.tenant_id == tenant_id else None

    def link_by_correlation(self, *, tenant_id: UUID, correlation_state: str) -> LinkRecord | None:
        for link in self.links.values():
            if link.tenant_id == tenant_id and link.correlation_state == correlation_state:
                return link
        return None

    def links_for_draft(self, *, tenant_id: UUID, draft_id: UUID) -> list[LinkRecord]:
        found = [
            link
            for link in self.links.values()
            if link.tenant_id == tenant_id and link.draft_id == draft_id
        ]
        return sorted(found, key=lambda link: link.created_at, reverse=True)

    def mark_exported(
        self,
        *,
        tenant_id: UUID,
        link_id: UUID,
        object_key: str,
        design_updated_at: int | None,
    ) -> LinkRecord:
        link = self.links[link_id]
        assert link.tenant_id == tenant_id
        updated = replace(
            link,
            status="exported",
            exported_object_key=object_key,
            exported_at=datetime.now(UTC),
            design_updated_at=design_updated_at,
            error=None,
        )
        self.links[link_id] = updated
        return updated

    def mark_failed(self, *, tenant_id: UUID, link_id: UUID, error: str) -> LinkRecord:
        link = self.links[link_id]
        assert link.tenant_id == tenant_id
        # a failed re-export keeps the last good file
        status = "exported" if link.exported_object_key else "failed"
        updated = replace(link, status=status, error=error)
        self.links[link_id] = updated
        return updated


# ---------------------------------------------------------------------------------------
# Postgres


def _account(row: CanvaAccount) -> AccountRecord:
    return AccountRecord(
        tenant_id=row.tenant_id,
        user_id=row.user_id,
        access_token_ciphertext=bytes(row.access_token_ciphertext),
        refresh_token_ciphertext=bytes(row.refresh_token_ciphertext),
        key_id=row.key_id,
        expires_at=row.expires_at,
        scope=row.scope,
    )


def _link(row: CanvaDesignLink) -> LinkRecord:
    return LinkRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        draft_id=row.draft_id,
        created_by_user_id=row.created_by_user_id,
        source_object_key=row.source_object_key,
        media_type=row.media_type,
        canva_design_id=row.canva_design_id,
        correlation_state=row.correlation_state,
        edit_url=row.edit_url,
        status=row.status,
        design_updated_at=row.design_updated_at,
        exported_object_key=row.exported_object_key,
        exported_at=row.exported_at,
        error=row.error,
        created_at=row.created_at,
    )


class PostgresCanvaRepository:
    def get_account(self, *, tenant_id: UUID, user_id: UUID) -> AccountRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.scalars(
                select(CanvaAccount).where(CanvaAccount.user_id == user_id)
            ).one_or_none()
            return _account(row) if row is not None else None

    def save_account(self, account: AccountRecord) -> None:
        with tenant_session(account.tenant_id) as session:
            row = session.scalars(
                select(CanvaAccount).where(CanvaAccount.user_id == account.user_id)
            ).one_or_none()
            if row is None:
                row = CanvaAccount(tenant_id=account.tenant_id, user_id=account.user_id)
                session.add(row)
            row.access_token_ciphertext = account.access_token_ciphertext
            row.refresh_token_ciphertext = account.refresh_token_ciphertext
            row.key_id = account.key_id
            row.expires_at = account.expires_at
            row.scope = account.scope
            row.updated_at = datetime.now(UTC)

    def delete_account(self, *, tenant_id: UUID, user_id: UUID) -> None:
        with tenant_session(tenant_id) as session:
            row = session.scalars(
                select(CanvaAccount).where(CanvaAccount.user_id == user_id)
            ).one_or_none()
            if row is not None:
                session.delete(row)

    def draft_media(self, *, tenant_id: UUID, draft_id: UUID) -> list[MediaRef]:
        with tenant_session(tenant_id) as session:
            rows = session.scalars(
                select(ImageAsset)
                .where(ImageAsset.draft_id == draft_id, ImageAsset.object_key.is_not(None))
                .order_by(ImageAsset.position)
            ).all()
            return [
                MediaRef(
                    object_key=str(row.object_key),
                    media_type=row.media_type,
                    width=row.width,
                    height=row.height,
                    position=row.position,
                )
                for row in rows
            ]

    def add_link(self, new: NewLink) -> LinkRecord:
        with tenant_session(new.tenant_id) as session:
            row = CanvaDesignLink(**new.__dict__, status="open")
            session.add(row)
            session.flush()
            session.refresh(row)
            return _link(row)

    def get_link(self, *, tenant_id: UUID, link_id: UUID) -> LinkRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.get(CanvaDesignLink, link_id)
            return _link(row) if row is not None else None

    def link_by_correlation(self, *, tenant_id: UUID, correlation_state: str) -> LinkRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.scalars(
                select(CanvaDesignLink).where(
                    CanvaDesignLink.correlation_state == correlation_state
                )
            ).one_or_none()
            return _link(row) if row is not None else None

    def links_for_draft(self, *, tenant_id: UUID, draft_id: UUID) -> list[LinkRecord]:
        with tenant_session(tenant_id) as session:
            rows = session.scalars(
                select(CanvaDesignLink)
                .where(CanvaDesignLink.draft_id == draft_id)
                .order_by(CanvaDesignLink.created_at.desc())
            ).all()
            return [_link(row) for row in rows]

    def mark_exported(
        self,
        *,
        tenant_id: UUID,
        link_id: UUID,
        object_key: str,
        design_updated_at: int | None,
    ) -> LinkRecord:
        now = datetime.now(UTC)
        with tenant_session(tenant_id) as session:
            row = session.get(CanvaDesignLink, link_id)
            if row is None:
                raise LookupError(f"canva link {link_id} not found")
            row.status = "exported"
            row.exported_object_key = object_key
            row.exported_at = now
            row.design_updated_at = design_updated_at
            row.error = None
            row.updated_at = now
            session.flush()
            return _link(row)

    def mark_failed(self, *, tenant_id: UUID, link_id: UUID, error: str) -> LinkRecord:
        with tenant_session(tenant_id) as session:
            row = session.get(CanvaDesignLink, link_id)
            if row is None:
                raise LookupError(f"canva link {link_id} not found")
            # a failed re-export keeps the last good file
            row.status = "exported" if row.exported_object_key else "failed"
            row.error = error[:2000]
            row.updated_at = datetime.now(UTC)
            session.flush()
            return _link(row)
