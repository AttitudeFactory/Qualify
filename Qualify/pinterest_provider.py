"""Authenticated tenant seam. Environment test tokens never enter customer flows."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from qualify_api.connections.state_token import StartedConnect
from qualify_api.tenancy.models import TenantMember, User
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from .connections_provider import NoActingUser
from .pinterest_vm import BoardVM, PinVM, pin_vm

if TYPE_CHECKING:
    from qualify_api.creative.pinterest_reference import ImportedPinReference


def _service() -> Any:
    from qualify_api.pinterest.composition import production_pinterest_service

    return production_pinterest_service()


def configured() -> bool:
    from qualify_api.pinterest.settings import PinterestSettings

    return PinterestSettings.is_configured()


def account(tenant_id: UUID) -> tuple[str, str]:
    connection = _service().connection(tenant_id)
    if connection is None:
        return "", "disconnected"
    return connection.username, connection.status


def _actor(tenant_id: UUID, auth_user_id: str) -> UUID | None:
    """Resolve the verified login, never an arbitrary owner of the business."""
    try:
        auth_id = UUID(auth_user_id)
    except (ValueError, TypeError):
        return None
    with tenant_session(tenant_id) as session:
        return session.scalar(
            select(User.id)
            .join(TenantMember, TenantMember.user_id == User.id)
            .where(
                User.auth_user_id == auth_id,
                TenantMember.tenant_id == tenant_id,
                TenantMember.role.in_(("owner", "admin")),
            )
        )


def begin_connect(tenant_id: UUID, auth_user_id: str) -> StartedConnect:
    user_id = _required_actor(tenant_id, auth_user_id)
    return _service().start_connect(tenant_id=tenant_id, user_id=user_id)


def disconnect(tenant_id: UUID, auth_user_id: str) -> None:
    user_id = _required_actor(tenant_id, auth_user_id)
    _service().disconnect(tenant_id, user_id)


def _required_actor(tenant_id: UUID, auth_user_id: str) -> UUID:
    from qualify_api.pinterest.client import PinterestError

    try:
        UUID(auth_user_id)
    except (ValueError, TypeError):
        raise NoActingUser("No acting user") from None
    user_id = _actor(tenant_id, auth_user_id)
    if user_id is None:
        raise PinterestError("role", 403)
    return user_id


def cancel_pending(tenant_id: UUID, auth_user_id: str) -> None:
    if not configured():
        return
    user_id = _actor(tenant_id, auth_user_id)
    if user_id is not None:
        _service().cancel_pending(tenant_id, user_id)


def boards(tenant_id: UUID, bookmark: str | None = None) -> tuple[list[BoardVM], str]:
    page = _service().boards(tenant_id, page_size=25, bookmark=bookmark)
    return [BoardVM(board.id, board.name) for board in page.items], page.bookmark or ""


def pins(tenant_id: UUID, board_id: str, bookmark: str | None = None) -> tuple[list[PinVM], str]:
    page = _service().pins(tenant_id, board_id, page_size=25, bookmark=bookmark)
    return [pin_vm(pin) for pin in page.items], page.bookmark or ""


def import_reference(
    tenant_id: UUID, board_id: str, pin_id: str, bookmark: str
) -> ImportedPinReference:
    """Revalidate the Pin against its account and page; browser sends IDs only."""
    from qualify_api.creative.pinterest_reference import import_pin_reference

    pin = _service().resolve_pin(
        tenant_id, board_id, pin_id, page_size=25, bookmark=bookmark or None
    )
    return import_pin_reference(tenant_id=tenant_id, pin=pin, board_id=board_id)
