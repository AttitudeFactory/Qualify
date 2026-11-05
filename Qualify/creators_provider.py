"""The transport of Creadores (Delivery 1, m-24946129 / m-24946132): everything the
screens ask of `qualify_api.creators.service` (docs/diseno-modulo-creadores.md §10),
scoped to the session's tenant and business, returning view models. Synchronous — the
states call it through `asyncio.to_thread`.

Reflex imports **only** the service facade and its dataclasses (§10.1). The import is
lazy (`_service`), for two reasons: importing the app never needs Postgres or the
vendor key, and the tests swap the whole facade for an in-memory twin with one
`monkeypatch.setattr(creators_provider, "_service", …)`.

`refresh_creator` is the one call here that pays. Only `CreatorsState` /
`CreatorSheetState` / `CreatorsCompareState` background events reach it, never a page
load (§8.3).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from types import ModuleType
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .creators_vm import (
    ComparisonVM,
    CreatorCardVM,
    SheetVM,
    build_card_vm,
    build_comparison_vm,
    build_sheet_vm,
)

logger = logging.getLogger(__name__)


def _service() -> ModuleType:
    from qualify_api.creators import service  # noqa: PLC0415 — see the module docstring

    return service


def _now() -> datetime:
    return datetime.now(UTC)


def _zone(name: str) -> tzinfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def business_zone(tenant_id: UUID) -> tzinfo:
    """The business's timezone, for «hoy» / «ayer» (best effort: UTC if unknown)."""
    try:
        from .conversations_provider import gateway  # noqa: PLC0415

        return _zone(gateway().timezone(tenant_id))
    except Exception:  # noqa: BLE001 — a wrong «hoy» is better than no screen
        return ZoneInfo("UTC")


def session_brand(tenant_id: UUID) -> UUID | None:
    """The business the session works in (ADR 43: the sealed business), never the
    browser's word for it."""
    from .creative_provider import default_brand_id  # noqa: PLC0415

    return default_brand_id(tenant_id)


def acting_user(tenant_id: UUID, email: str) -> UUID | None:
    """Who adds the creator (`add_creator(user_id=…)`): the logged-in person, else the
    business's owner (the same stand-in the rest of the app uses)."""
    from .connections_provider import acting_user_id  # noqa: PLC0415
    from .conversations_provider import gateway  # noqa: PLC0415

    user = gateway().acting_user(tenant_id, email) if email else None
    return user or acting_user_id(tenant_id)


# --- what went wrong, as kinds the state can word -----------------------------------


class CreatorsUnavailable(Exception):
    """The business does not have the module (§11) — the screen shows «Pronto»."""


class BadHandle(ValueError):
    """What was typed is not an Instagram username (vacío, espacios, > 30, símbolos)."""


class WrongNetwork(ValueError):
    """Delivery 1 reads Instagram only."""


class WrongCount(ValueError):
    """Comparar takes 2 to 4."""


class NotFound(LookupError):
    """Not a creator of this business (or archived), or — in Comparar — one without a
    read yet (`CreatorNotFound` / `NotReadYet`)."""


def _translate(exc: Exception) -> Exception:
    service = _service()
    if isinstance(exc, service.CreatorsDisabled):
        return CreatorsUnavailable()
    if isinstance(exc, service.InvalidHandle):
        return BadHandle()
    if isinstance(exc, service.UnsupportedNetwork):
        return WrongNetwork()
    if isinstance(exc, service.TooManyToCompare):
        return WrongCount()
    if isinstance(exc, service.CreatorNotFound):
        return NotFound()
    return exc


def _known_errors() -> tuple[type[Exception], ...]:
    service = _service()
    return (
        service.CreatorsDisabled,
        service.InvalidHandle,
        service.UnsupportedNetwork,
        service.TooManyToCompare,
        service.CreatorNotFound,
    )


# --- reads ------------------------------------------------------------------------


def creators_enabled(tenant_id: UUID) -> bool:
    """§11: the env switch `QUALIFY_CREATORS_TENANTS`, read by the backend. A backend
    that is not there yet (or fails) means «off»: the owner keeps the «Pronto» screen."""
    try:
        return bool(_service().creators_enabled(tenant_id))
    except Exception as exc:  # noqa: BLE001 — the switch never takes a page down
        logger.warning("creators_enabled failed: %s", type(exc).__name__)
        return False


def cards(
    tenant_id: UUID,
    brand_id: UUID,
    *,
    working: Sequence[str] = (),
    zone: tzinfo | None = None,
    now: datetime | None = None,
) -> list[CreatorCardVM]:
    """«Tus creadores», the last read first (UX §2.1)."""
    now = now or _now()
    try:
        rows = _service().list_creators(tenant_id, brand_id, now=now)
    except _known_errors() as exc:
        raise _translate(exc) from exc
    epoch = datetime.min.replace(tzinfo=UTC)

    def _recent(card: Any) -> datetime:
        moment = card.read_at or card.tracked.created_at or epoch
        return moment if moment.tzinfo else moment.replace(tzinfo=UTC)

    ordered = sorted(rows, key=_recent, reverse=True)
    return [
        build_card_vm(card, now=now, zone=zone, working=str(card.tracked.id) in working)
        for card in ordered
    ]


def names(tenant_id: UUID, brand_id: UUID) -> dict[str, tuple[str, str]]:
    """tracked id → (full name, avatar url), to put faces on Comparar's columns."""
    try:
        rows = _service().list_creators(tenant_id, brand_id)
    except _known_errors() as exc:
        raise _translate(exc) from exc
    return {str(c.tracked.id): (c.full_name or "", c.avatar_url or "") for c in rows}


def sheet(
    tenant_id: UUID,
    brand_id: UUID,
    tracked_id: UUID,
    *,
    zone: tzinfo | None = None,
    now: datetime | None = None,
) -> SheetVM | None:
    """The sheet, or None while the creator has no read yet."""
    now = now or _now()
    try:
        found = _service().creator_sheet(tenant_id, brand_id, tracked_id, now=now)
    except _known_errors() as exc:
        raise _translate(exc) from exc
    return build_sheet_vm(found, now=now, zone=zone) if found is not None else None


def compare(
    tenant_id: UUID,
    brand_id: UUID,
    tracked_ids: Sequence[UUID],
    *,
    zone: tzinfo | None = None,
    now: datetime | None = None,
) -> ComparisonVM:
    now = now or _now()
    try:
        comparison = _service().compare_creators(tenant_id, brand_id, list(tracked_ids), now=now)
        faces = names(tenant_id, brand_id)
    except _known_errors() as exc:
        raise _translate(exc) from exc
    return build_comparison_vm(comparison, now=now, names=faces, zone=zone)


# --- writes -----------------------------------------------------------------------


@dataclass(frozen=True)
class Added:
    """What `add_creator` returned, as the drawer needs it."""

    tracked_id: str
    handle: str
    had_read: bool  # it already had a read (it was in the list, or archived with one)


def add(tenant_id: UUID, brand_id: UUID, raw: str, *, user_id: UUID) -> Added:
    """Normalize and save (idempotent; reactivates an archived one). Does NOT pay."""
    try:
        tracked = _service().add_creator(tenant_id, brand_id, raw, user_id=user_id)
    except _known_errors() as exc:
        raise _translate(exc) from exc
    return Added(
        tracked_id=str(tracked.id),
        handle=tracked.handle,
        had_read=tracked.last_snapshot_id is not None,
    )


def archive(tenant_id: UUID, brand_id: UUID, tracked_id: UUID) -> None:
    try:
        _service().archive_creator(tenant_id, brand_id, tracked_id)
    except _known_errors() as exc:
        raise _translate(exc) from exc


def refresh(tenant_id: UUID, brand_id: UUID, tracked_id: UUID) -> str:
    """The one paid call (§8.3). Returns `RefreshOutcome.status`; the credits it spent
    are logged here and never reach the screen (ADR 42 §2.9)."""
    try:
        outcome = _service().refresh_creator(tenant_id, brand_id, tracked_id)
    except _known_errors() as exc:
        raise _translate(exc) from exc
    logger.info(
        "creators refresh tracked=%s status=%s credits=%s partial=%s",
        tracked_id,
        outcome.status,
        outcome.credits,
        outcome.partial,
    )
    return str(outcome.status)
