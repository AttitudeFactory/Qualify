"""Persistence for WhatsApp menus (WA-14, persistence half; migration 0058).

A Protocol plus two implementations — Postgres through the sanctioned doors, memory for
tests — so the WA-16 editor and the WA-07 handler are testable without a database while
the real writes still go through `tenant_session` (RLS-scoped, `qualify_app`).

Two doors, on purpose:

- **Everything the editor does** (`create_menu`, `save_version`, `publish_version`,
  `set_paused`, the reads) runs as `qualify_app` under `tenant_session(tenant_id)`.
- **`load_published_menu_for_phone`** runs as `qualify_webhook_worker` under
  `webhook_worker_session()` — the processor is tenant-blind when a message arrives and
  resolves the number first (0057's docstring). The worker holds SELECT on exactly the
  columns this query reads (0058's table), so the statement is a core `select` of those
  columns, never `select(WhatsAppMenu)`.

Invariants that live HERE because they are properties of the write itself:

- **Versions are immutable and validated.** `save_version` accepts a `MenuDefinition`
  or its JSON and stores `model_dump(mode="json")` plus the `ENGINE_VERSION` it was
  validated against; an invalid definition raises `pydantic.ValidationError` and writes
  nothing. Numbering is `max(version) + 1` under a row lock on the menu, so two editors
  saving at once get 3 and 4, not two 3s (and `uq_wa_menu_version` would refuse the
  second anyway).
- **Publishing is atomic and exclusive per number.** `publish_version` stamps the
  version (`published_at`/`published_by_user_id`, only the first time), demotes any
  other published menu on the same number and points the menu at the version — one
  transaction, so the number never has zero or two live menus mid-way, and
  `uq_wa_menu_phone_published` is never violated.
- **A paused menu is not loaded.** `load_published_menu_for_phone` returns `None` for a
  number whose live menu `is_paused`; the handler then stays silent, which is what
  "pause" means to the person who took the counter.
- **«Eliminar» archives (m-24986800, decision D1; migration 0147).** `archive_menu`
  stamps `archived_at` and clears `published_version_id` in one UPDATE under a row lock;
  it refuses the menu that is answering (published and not paused: the owner pauses it
  first) with `MenuIsAnswering`, and is idempotent on an already archived menu. An
  archived menu is invisible to every other call here — `get_menu` and `list_menus` skip
  it and the writes raise `MenuNotFound` — and `ck_wa_menu_archived_unpublished` keeps it
  from ever being the number's live menu, so the webhook loader never selects it. Its
  versions and the chats that used them stay (provenance).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from qualify_shared.db.session import tenant_session
from qualify_shared.db.webhook import webhook_worker_session
from sqlalchemy import Select, func, select, update

from qualify_api.tenancy.acting import require_acting_member
from qualify_api.whatsapp.menus.engine import ENGINE_VERSION
from qualify_api.whatsapp.menus.schema import MenuDefinition
from qualify_api.whatsapp.models import WhatsAppMenu, WhatsAppMenuVersion

# What the WA-07 handler takes as `menu_loader`: the live definition of a number and the
# version id to record on the thread, or None (no menu, nothing published, or paused).
MenuLoader = Callable[[UUID], "tuple[MenuDefinition, UUID] | None"]


class MenuNotFound(LookupError):
    """No menu with that id in the tenant."""


class MenuVersionNotFound(LookupError):
    """No version with that id belonging to that menu."""


class MenuIsAnswering(Exception):
    """The menu is the number's live one (published and not paused): it cannot be
    archived until the owner pauses it — «Para eliminarlo, primero páusalo.»"""


@dataclass(frozen=True)
class MenuRecord:
    id: UUID
    tenant_id: UUID
    brand_id: UUID | None
    phone_number_row_id: UUID
    name: str
    published_version_id: UUID | None
    is_paused: bool
    created_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None

    @property
    def is_answering(self) -> bool:
        """What a customer's message meets: published and not paused."""
        return self.published_version_id is not None and not self.is_paused


@dataclass(frozen=True)
class MenuVersionRecord:
    id: UUID
    tenant_id: UUID
    menu_id: UUID
    version: int
    definition: MenuDefinition
    engine_version: str
    published_at: datetime | None
    published_by_user_id: UUID | None
    created_at: datetime


def coerce_definition(definition: MenuDefinition | Mapping[str, Any]) -> MenuDefinition:
    """A `MenuDefinition` as given; a mapping validated into one (raises
    `pydantic.ValidationError` with the field errors the editor can show)."""
    if isinstance(definition, MenuDefinition):
        return definition
    return MenuDefinition.model_validate(dict(definition))


class MenuRepository(Protocol):
    def create_menu(
        self,
        *,
        tenant_id: UUID,
        phone_number_row_id: UUID,
        name: str,
        brand_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
    ) -> MenuRecord: ...

    def get_menu(
        self, *, tenant_id: UUID, menu_id: UUID, include_archived: bool = False
    ) -> MenuRecord | None: ...

    def list_menus(self, *, tenant_id: UUID, phone_number_row_id: UUID) -> list[MenuRecord]: ...

    def save_version(
        self,
        *,
        tenant_id: UUID,
        menu_id: UUID,
        definition: MenuDefinition | Mapping[str, Any],
    ) -> MenuVersionRecord: ...

    def list_versions(self, *, tenant_id: UUID, menu_id: UUID) -> list[MenuVersionRecord]: ...

    def publish_version(
        self,
        *,
        tenant_id: UUID,
        menu_id: UUID,
        version_id: UUID,
        user_id: UUID | None,
        now: datetime | None = None,
    ) -> MenuRecord: ...

    def set_paused(self, *, tenant_id: UUID, menu_id: UUID, paused: bool) -> MenuRecord: ...

    def get_published(self, *, tenant_id: UUID, menu_id: UUID) -> MenuDefinition | None: ...

    def archive_menu(
        self, *, tenant_id: UUID, menu_id: UUID, now: datetime | None = None
    ) -> MenuRecord: ...

    def load_published_menu_for_phone(
        self, phone_number_row_id: UUID
    ) -> tuple[MenuDefinition, UUID] | None: ...


def _now(now: datetime | None) -> datetime:
    return now if now is not None else datetime.now(UTC)


# --- Memory ----------------------------------------------------------------------------


class MemoryMenuRepository:
    """Same contract, dicts underneath. Tenant scoping is by filter (the production door
    scopes by RLS); the one-live-menu-per-number and immutable-version rules are kept."""

    def __init__(self) -> None:
        self._menus: dict[UUID, MenuRecord] = {}
        self._versions: dict[UUID, MenuVersionRecord] = {}

    def create_menu(
        self,
        *,
        tenant_id: UUID,
        phone_number_row_id: UUID,
        name: str,
        brand_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
    ) -> MenuRecord:
        if not name.strip():
            raise ValueError("menu name must not be blank")
        for existing in self._menus.values():
            if (
                existing.tenant_id == tenant_id
                and existing.phone_number_row_id == phone_number_row_id
                and existing.archived_at is None
                and existing.name.lower() == name.lower()
            ):
                raise ValueError(f"a menu named {name!r} already exists for this number")
        now = _now(None)
        record = MenuRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            brand_id=brand_id,
            phone_number_row_id=phone_number_row_id,
            name=name,
            published_version_id=None,
            is_paused=False,
            created_by_user_id=created_by_user_id,
            created_at=now,
            updated_at=now,
        )
        self._menus[record.id] = record
        return record

    def get_menu(
        self, *, tenant_id: UUID, menu_id: UUID, include_archived: bool = False
    ) -> MenuRecord | None:
        menu = self._menus.get(menu_id)
        if menu is None or menu.tenant_id != tenant_id:
            return None
        if menu.archived_at is not None and not include_archived:
            return None
        return menu

    def _require(self, tenant_id: UUID, menu_id: UUID) -> MenuRecord:
        menu = self.get_menu(tenant_id=tenant_id, menu_id=menu_id)
        if menu is None:
            raise MenuNotFound(str(menu_id))
        return menu

    def list_menus(self, *, tenant_id: UUID, phone_number_row_id: UUID) -> list[MenuRecord]:
        rows = [
            m
            for m in self._menus.values()
            if m.tenant_id == tenant_id
            and m.phone_number_row_id == phone_number_row_id
            and m.archived_at is None
        ]
        return sorted(rows, key=lambda m: (m.created_at, m.name))

    def save_version(
        self,
        *,
        tenant_id: UUID,
        menu_id: UUID,
        definition: MenuDefinition | Mapping[str, Any],
    ) -> MenuVersionRecord:
        self._require(tenant_id, menu_id)
        parsed = coerce_definition(definition)
        current = max(
            (v.version for v in self._versions.values() if v.menu_id == menu_id), default=0
        )
        record = MenuVersionRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            menu_id=menu_id,
            version=current + 1,
            definition=parsed,
            engine_version=ENGINE_VERSION,
            published_at=None,
            published_by_user_id=None,
            created_at=_now(None),
        )
        self._versions[record.id] = record
        return record

    def list_versions(self, *, tenant_id: UUID, menu_id: UUID) -> list[MenuVersionRecord]:
        rows = [
            v for v in self._versions.values() if v.tenant_id == tenant_id and v.menu_id == menu_id
        ]
        return sorted(rows, key=lambda v: v.version)

    def publish_version(
        self,
        *,
        tenant_id: UUID,
        menu_id: UUID,
        version_id: UUID,
        user_id: UUID | None,
        now: datetime | None = None,
    ) -> MenuRecord:
        menu = self._require(tenant_id, menu_id)
        version = self._versions.get(version_id)
        if version is None or version.menu_id != menu_id:
            raise MenuVersionNotFound(str(version_id))
        at = _now(now)
        if version.published_at is None:
            self._versions[version_id] = replace(
                version, published_at=at, published_by_user_id=user_id
            )
        for other in list(self._menus.values()):
            if (
                other.id != menu.id
                and other.phone_number_row_id == menu.phone_number_row_id
                and other.published_version_id is not None
            ):
                self._menus[other.id] = replace(other, published_version_id=None, updated_at=at)
        updated = replace(menu, published_version_id=version_id, updated_at=at)
        self._menus[menu.id] = updated
        return updated

    def set_paused(self, *, tenant_id: UUID, menu_id: UUID, paused: bool) -> MenuRecord:
        menu = self._require(tenant_id, menu_id)
        updated = replace(menu, is_paused=paused, updated_at=_now(None))
        self._menus[menu.id] = updated
        return updated

    def get_published(self, *, tenant_id: UUID, menu_id: UUID) -> MenuDefinition | None:
        menu = self._require(tenant_id, menu_id)
        if menu.published_version_id is None:
            return None
        return self._versions[menu.published_version_id].definition

    def archive_menu(
        self, *, tenant_id: UUID, menu_id: UUID, now: datetime | None = None
    ) -> MenuRecord:
        menu = self._menus.get(menu_id)
        if menu is None or menu.tenant_id != tenant_id:
            raise MenuNotFound(str(menu_id))
        if menu.archived_at is not None:
            return menu
        if menu.is_answering:
            raise MenuIsAnswering(str(menu_id))
        at = _now(now)
        updated = replace(menu, archived_at=at, published_version_id=None, updated_at=at)
        self._menus[menu.id] = updated
        return updated

    def load_published_menu_for_phone(
        self, phone_number_row_id: UUID
    ) -> tuple[MenuDefinition, UUID] | None:
        for menu in self._menus.values():
            if (
                menu.phone_number_row_id == phone_number_row_id
                and menu.archived_at is None
                and menu.is_answering
            ):
                version = self._versions[menu.published_version_id]
                return version.definition, version.id
        return None


# --- Postgres --------------------------------------------------------------------------


def _menu_record(row: WhatsAppMenu) -> MenuRecord:
    return MenuRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        brand_id=row.brand_id,
        phone_number_row_id=row.phone_number_row_id,
        name=row.name,
        published_version_id=row.published_version_id,
        is_paused=row.is_paused,
        created_by_user_id=row.created_by_user_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        archived_at=row.archived_at,
    )


def _live_menu(menu_id: UUID) -> Select[tuple[WhatsAppMenu]]:
    """The menu by id, unless archived: what every editor read and write starts from."""
    return select(WhatsAppMenu).where(
        WhatsAppMenu.id == menu_id, WhatsAppMenu.archived_at.is_(None)
    )


def _version_record(row: WhatsAppMenuVersion) -> MenuVersionRecord:
    return MenuVersionRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        menu_id=row.menu_id,
        version=row.version,
        definition=MenuDefinition.model_validate(row.definition),
        engine_version=row.engine_version,
        published_at=row.published_at,
        published_by_user_id=row.published_by_user_id,
        created_at=row.created_at,
    )


def load_published_menu_for_phone(phone_number_row_id: UUID) -> tuple[MenuDefinition, UUID] | None:
    """The live menu of a number, read as `qualify_webhook_worker` (tenant-blind, the
    worker's column grants only). None when the number has no published menu or its
    menu is paused. An archived menu is never found: archiving clears its
    `published_version_id` and `ck_wa_menu_archived_unpublished` (0147) keeps it so —
    which is why the worker needs no grant on `archived_at`."""
    stmt = (
        select(WhatsAppMenuVersion.id, WhatsAppMenuVersion.definition)
        .join(WhatsAppMenu, WhatsAppMenu.published_version_id == WhatsAppMenuVersion.id)
        .where(
            WhatsAppMenu.phone_number_row_id == phone_number_row_id,
            WhatsAppMenu.is_paused.is_(False),
        )
    )
    with webhook_worker_session() as session:
        row = session.execute(stmt).first()
        if row is None:
            return None
        return MenuDefinition.model_validate(row.definition), row.id


class PostgresMenuRepository:
    """All editor access through `tenant_session` — RLS scopes every statement and the
    composite FKs keep a row's tenant agreeing with its number's and its menu's."""

    def create_menu(
        self,
        *,
        tenant_id: UUID,
        phone_number_row_id: UUID,
        name: str,
        brand_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
    ) -> MenuRecord:
        with tenant_session(tenant_id) as session:
            row = WhatsAppMenu(
                tenant_id=tenant_id,
                brand_id=brand_id,
                phone_number_row_id=phone_number_row_id,
                name=name,
                created_by_user_id=created_by_user_id,
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            return _menu_record(row)

    def get_menu(
        self, *, tenant_id: UUID, menu_id: UUID, include_archived: bool = False
    ) -> MenuRecord | None:
        """None for an unknown id, another tenant's menu (RLS) and — unless
        `include_archived` — an archived one."""
        stmt = (
            select(WhatsAppMenu).where(WhatsAppMenu.id == menu_id)
            if include_archived
            else _live_menu(menu_id)
        )
        with tenant_session(tenant_id) as session:
            row = session.scalars(stmt).one_or_none()
            return _menu_record(row) if row is not None else None

    def list_menus(self, *, tenant_id: UUID, phone_number_row_id: UUID) -> list[MenuRecord]:
        with tenant_session(tenant_id) as session:
            rows = session.scalars(
                select(WhatsAppMenu)
                .where(
                    WhatsAppMenu.phone_number_row_id == phone_number_row_id,
                    WhatsAppMenu.archived_at.is_(None),
                )
                .order_by(WhatsAppMenu.created_at, WhatsAppMenu.name)
            ).all()
            return [_menu_record(r) for r in rows]

    def save_version(
        self,
        *,
        tenant_id: UUID,
        menu_id: UUID,
        definition: MenuDefinition | Mapping[str, Any],
    ) -> MenuVersionRecord:
        parsed = coerce_definition(definition)
        with tenant_session(tenant_id) as session:
            menu = session.scalars(_live_menu(menu_id).with_for_update()).one_or_none()
            if menu is None:
                raise MenuNotFound(str(menu_id))
            current = session.scalar(
                select(func.coalesce(func.max(WhatsAppMenuVersion.version), 0)).where(
                    WhatsAppMenuVersion.menu_id == menu_id
                )
            )
            row = WhatsAppMenuVersion(
                tenant_id=tenant_id,
                menu_id=menu_id,
                version=int(current or 0) + 1,
                definition=parsed.model_dump(mode="json"),
                engine_version=ENGINE_VERSION,
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            return _version_record(row)

    def list_versions(self, *, tenant_id: UUID, menu_id: UUID) -> list[MenuVersionRecord]:
        with tenant_session(tenant_id) as session:
            rows = session.scalars(
                select(WhatsAppMenuVersion)
                .where(WhatsAppMenuVersion.menu_id == menu_id)
                .order_by(WhatsAppMenuVersion.version)
            ).all()
            return [_version_record(r) for r in rows]

    def publish_version(
        self,
        *,
        tenant_id: UUID,
        menu_id: UUID,
        version_id: UUID,
        user_id: UUID | None,
        now: datetime | None = None,
    ) -> MenuRecord:
        # S5 (m-24849192): publishing a menu makes it answer customers; the acting
        # login's membership is checked fresh first (no-op for system callers).
        require_acting_member(tenant_id)
        at = _now(now)
        with tenant_session(tenant_id) as session:
            menu = session.scalars(_live_menu(menu_id).with_for_update()).one_or_none()
            if menu is None:
                raise MenuNotFound(str(menu_id))
            version = session.scalars(
                select(WhatsAppMenuVersion).where(
                    WhatsAppMenuVersion.id == version_id,
                    WhatsAppMenuVersion.menu_id == menu_id,
                )
            ).one_or_none()
            if version is None:
                raise MenuVersionNotFound(str(version_id))
            if version.published_at is None:
                # The only UPDATE `qualify_app` holds on versions: these two columns.
                version.published_at = at
                version.published_by_user_id = user_id
            # Demote the number's current live menu BEFORE pointing this one, so the
            # partial unique index never sees two.
            session.execute(
                update(WhatsAppMenu)
                .where(
                    WhatsAppMenu.phone_number_row_id == menu.phone_number_row_id,
                    WhatsAppMenu.id != menu.id,
                    WhatsAppMenu.published_version_id.is_not(None),
                )
                .values(published_version_id=None, updated_at=at)
            )
            menu.published_version_id = version.id
            menu.updated_at = at
            session.flush()
            session.refresh(menu)
            return _menu_record(menu)

    def set_paused(self, *, tenant_id: UUID, menu_id: UUID, paused: bool) -> MenuRecord:
        with tenant_session(tenant_id) as session:
            menu = session.scalars(_live_menu(menu_id).with_for_update()).one_or_none()
            if menu is None:
                raise MenuNotFound(str(menu_id))
            menu.is_paused = paused
            menu.updated_at = _now(None)
            session.flush()
            session.refresh(menu)
            return _menu_record(menu)

    def get_published(self, *, tenant_id: UUID, menu_id: UUID) -> MenuDefinition | None:
        with tenant_session(tenant_id) as session:
            menu = session.scalars(_live_menu(menu_id)).one_or_none()
            if menu is None:
                raise MenuNotFound(str(menu_id))
            if menu.published_version_id is None:
                return None
            version = session.get(WhatsAppMenuVersion, menu.published_version_id)
            assert version is not None  # FK: a published id always resolves
            return MenuDefinition.model_validate(version.definition)

    def archive_menu(
        self, *, tenant_id: UUID, menu_id: UUID, now: datetime | None = None
    ) -> MenuRecord:
        """«Eliminar» (m-24986800): archive under a row lock, so a publish or a «Reanudar»
        racing it either lands first (and this refuses) or waits and then finds no menu.
        Idempotent: an already archived menu is returned as it is. Another tenant's menu
        is invisible under RLS — `MenuNotFound`, exactly like an unknown id."""
        # Removing what a number answers with is the owner's call: membership checked
        # fresh, as for publishing (no-op for system callers).
        require_acting_member(tenant_id)
        at = _now(now)
        with tenant_session(tenant_id) as session:
            menu = session.scalars(
                select(WhatsAppMenu).where(WhatsAppMenu.id == menu_id).with_for_update()
            ).one_or_none()
            if menu is None:
                raise MenuNotFound(str(menu_id))
            if menu.archived_at is not None:
                return _menu_record(menu)
            if menu.published_version_id is not None and not menu.is_paused:
                raise MenuIsAnswering(str(menu_id))
            # One UPDATE: archived and unpublished together (0147's CHECK holds both).
            menu.archived_at = at
            menu.published_version_id = None
            menu.updated_at = at
            session.flush()
            session.refresh(menu)
            return _menu_record(menu)

    def load_published_menu_for_phone(
        self, phone_number_row_id: UUID
    ) -> tuple[MenuDefinition, UUID] | None:
        return load_published_menu_for_phone(phone_number_row_id)


__all__ = [
    "MemoryMenuRepository",
    "MenuIsAnswering",
    "MenuLoader",
    "MenuNotFound",
    "MenuRecord",
    "MenuRepository",
    "MenuVersionNotFound",
    "MenuVersionRecord",
    "PostgresMenuRepository",
    "coerce_definition",
    "load_published_menu_for_phone",
]
