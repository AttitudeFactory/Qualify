"""The seam between the `/whatsapp` screen (WA-12) and the real WhatsApp backend.

Two kinds of call, same split as `connections_provider.py`:

- **Postgres reads/writes this module owns** go through `tenant_session(tenant_id)` — the
  only sanctioned door — so RLS scopes every row to the tenant even though the queries
  carry no `WHERE tenant_id`. `numbers_for` reads the tenant's WhatsApp connections joined
  with `whatsapp_phone_numbers` (WA-05) plus the latest inbound `messages.ingested_at`;
  `_store_phone_metadata` refreshes the Graph metadata on that row after «Verificar ahora».
- **Graph calls** go through `qualify_api.whatsapp.HttpWhatsAppClient`, built over the
  `AuthenticatedClient` a per-tenant `InjectingCredentialResolver(DbCredentialReader(
  tenant_id), …)` returns — exactly the path the publishing/inbox compositions use. The
  resolver decrypts inside itself and hands back a client with the header already
  injected: **no token ever reaches this module, the state or the browser.**

A Graph call that comes back 401 / code 190 (`WhatsAppApiError.is_auth_error`) degrades
the connection through `degrade_connection_on_auth_error` before the error propagates —
the same posture `publishing/service.py` has — so the FSM status on screen tells the
truth after the failure. Every other `WhatsAppApiError` propagates untouched; the state
turns it into a banner carrying the Meta code only (`whatsapp_vm.graph_error_notice`).

The Graph seam is injectable (`opener`, `degrader`, `health_check`, `store`) so
`test_whatsapp_provider.py` drives every function with a fake client and no network.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections import check_connection_health
from qualify_api.connections.composition import degrade_connection_on_auth_error
from qualify_api.connections.credential_reader import DbCredentialReader
from qualify_api.connections.crypto import DevEncryptor
from qualify_api.connections.models import SocialConnection
from qualify_api.connections.resolver import InjectingCredentialResolver
from qualify_api.inbox.models import Message
from qualify_api.tenancy.models import Brand
from qualify_api.whatsapp.client import (
    BusinessProfileUpdate,
    HttpWhatsAppClient,
    PhoneNumberInfo,
    WhatsAppApiError,
    WhatsAppClient,
)
from qualify_api.whatsapp.models import WhatsAppPhoneNumber
from qualify_shared.db.session import tenant_session
from sqlalchemy import func, select

from .whatsapp_vm import (
    BusinessProfileVM,
    ProfileForm,
    QrCodeVM,
    WhatsAppNumberVM,
    build_number_vm,
    build_profile_vm,
    build_qr_vm,
)

# The Cloud API is `graph.facebook.com` throughout and Meta documents `Bearer` for it
# (client.py docstring). Named, never defaulted — R12's discipline on the resolver.
_GRAPH_SCHEME = "Bearer"

ClientOpener = Callable[[UUID, UUID], AbstractAsyncContextManager[WhatsAppClient]]
Degrader = Callable[..., object]
HealthCheck = Callable[..., bool]


class UnknownWhatsAppNumber(LookupError):
    """No WhatsApp number row is visible for this connection under this tenant. Covers
    "belongs to another tenant" too — RLS makes the two the same read."""


# ======================================================================================
# Postgres (tenant_session only)
# ======================================================================================


def numbers_for(tenant_id: UUID) -> list[WhatsAppNumberVM]:
    """The tenant's WhatsApp numbers, newest connection first, as client-safe VMs.

    Inner join on `whatsapp_phone_numbers`: a WhatsApp connection without its phone row
    is a half-finished `whatsapp.connect` and has nothing to show here. Blocking —
    callers on the event loop must run it off-thread.
    """
    last_inbound = (
        select(
            Message.connection_id.label("connection_id"),
            func.max(Message.ingested_at).label("last_inbound_at"),
        )
        .where(Message.direction == "inbound")
        .group_by(Message.connection_id)
        .subquery()
    )
    with tenant_session(tenant_id) as session:
        rows = session.execute(
            select(
                SocialConnection, WhatsAppPhoneNumber, Brand.name, last_inbound.c.last_inbound_at
            )
            .join(WhatsAppPhoneNumber, WhatsAppPhoneNumber.connection_id == SocialConnection.id)
            .outerjoin(Brand, SocialConnection.brand_id == Brand.id)
            .outerjoin(last_inbound, last_inbound.c.connection_id == SocialConnection.id)
            .where(SocialConnection.platform == "whatsapp")
            .order_by(SocialConnection.connected_at.desc())
        ).all()
        # Built inside the session: ORM rows are not usable once it closes.
        return [
            build_number_vm(
                connection_id=str(connection.id),
                status=connection.status,
                display_phone_number=phone.display_phone_number,
                verified_name=phone.verified_name,
                brand=brand_name,
                quality_rating=phone.quality_rating,
                messaging_limit_tier=phone.messaging_limit_tier,
                name_status=phone.name_status,
                platform_status=phone.platform_status,
                last_health_checked_at=connection.last_health_checked_at,
                last_synced_at=phone.last_synced_at,
                last_inbound_at=inbound_at,
            )
            for connection, phone, brand_name, inbound_at in rows
        ]


def _phone_ids(tenant_id: UUID, connection_id: UUID) -> tuple[str, str]:
    """(phone_number_id, waba_id) for the connection — the two ids the Graph client is
    bound to. Read under RLS, so another tenant's connection is simply not found."""
    with tenant_session(tenant_id) as session:
        row = session.execute(
            select(WhatsAppPhoneNumber.phone_number_id, WhatsAppPhoneNumber.waba_id).where(
                WhatsAppPhoneNumber.connection_id == connection_id
            )
        ).first()
    if row is None:
        raise UnknownWhatsAppNumber(str(connection_id))
    return row[0], row[1]


def _store_phone_metadata(tenant_id: UUID, connection_id: UUID, info: PhoneNumberInfo) -> None:
    """Refresh the Graph metadata on the number's row (`qualify_app` holds UPDATE, 0057).
    A field Meta omitted keeps its stored value for the display number (NOT NULL); the
    nullable ones take what Meta reports now, same as the connect command's re-run."""
    with tenant_session(tenant_id) as session:
        phone = session.scalar(
            select(WhatsAppPhoneNumber).where(WhatsAppPhoneNumber.connection_id == connection_id)
        )
        if phone is None:
            raise UnknownWhatsAppNumber(str(connection_id))
        if info.display_phone_number:
            phone.display_phone_number = info.display_phone_number
        phone.verified_name = info.verified_name
        phone.name_status = info.name_status
        phone.quality_rating = info.quality_rating
        phone.messaging_limit_tier = info.messaging_limit_tier
        phone.platform_status = info.status
        phone.last_synced_at = datetime.now(UTC)
        session.flush()


# ======================================================================================
# Graph (through the CredentialResolver — never a token here)
# ======================================================================================


@asynccontextmanager
async def open_whatsapp_client(
    tenant_id: UUID, connection_id: UUID
) -> AsyncIterator[WhatsAppClient]:
    """A `WhatsAppClient` bound to this connection's number, closed on exit.

    Raises `UnknownWhatsAppNumber` (no phone row visible) and `CredentialNotFound` (no
    credential visible) before any network call."""
    phone_number_id, waba_id = await asyncio.to_thread(_phone_ids, tenant_id, connection_id)
    settings = MetaOAuthSettings.from_env()
    resolver = InjectingCredentialResolver(DbCredentialReader(tenant_id), DevEncryptor())
    graph = await resolver.client_for(connection_id, scheme=_GRAPH_SCHEME)
    try:
        yield HttpWhatsAppClient(
            graph_client=graph,
            graph_url=settings.graph_url,
            phone_number_id=phone_number_id,
            waba_id=waba_id,
        )
    finally:
        aclose = getattr(graph, "aclose", None)
        if aclose is not None:
            await aclose()


async def _call[T](
    tenant_id: UUID,
    connection_id: UUID,
    call: Callable[[WhatsAppClient], Awaitable[T]],
    *,
    opener: ClientOpener,
    degrader: Degrader,
) -> T:
    """Run one Graph call; on an auth error degrade the connection, then re-raise."""
    async with opener(tenant_id, connection_id) as client:
        try:
            return await call(client)
        except WhatsAppApiError as exc:
            if exc.is_auth_error:
                await asyncio.to_thread(degrader, tenant_id=tenant_id, connection_id=connection_id)
            raise


async def verify_number(
    tenant_id: UUID,
    connection_id: UUID,
    *,
    opener: ClientOpener = open_whatsapp_client,
    degrader: Degrader = degrade_connection_on_auth_error,
    health_check: HealthCheck = check_connection_health,
    store: Callable[[UUID, UUID, PhoneNumberInfo], None] = _store_phone_metadata,
) -> bool:
    """«Verificar ahora»: the token health-check (`/debug_token`, QUA-91 — it moves
    `last_health_checked_at` or degrades the connection) and, when the token is still
    valid, a fresh `GET /{PHONE_NUMBER_ID}` whose metadata is written back to
    `whatsapp_phone_numbers`. Returns whether the token was valid.

    Manual-trigger only, like the `/connections` button: nothing calls this on a timer.
    """
    healthy = await asyncio.to_thread(
        health_check, tenant_id=tenant_id, connection_id=connection_id
    )
    if not healthy:
        return False
    info = await _call(
        tenant_id,
        connection_id,
        lambda client: client.get_phone_number(),
        opener=opener,
        degrader=degrader,
    )
    await asyncio.to_thread(store, tenant_id, connection_id, info)
    return True


async def load_profile(
    tenant_id: UUID,
    connection_id: UUID,
    *,
    opener: ClientOpener = open_whatsapp_client,
    degrader: Degrader = degrade_connection_on_auth_error,
) -> BusinessProfileVM:
    profile = await _call(
        tenant_id,
        connection_id,
        lambda client: client.get_business_profile(),
        opener=opener,
        degrader=degrader,
    )
    return build_profile_vm(
        about=profile.about,
        address=profile.address,
        description=profile.description,
        email=profile.email,
        websites=profile.websites,
        vertical=profile.vertical,
        profile_picture_url=profile.profile_picture_url,
    )


def profile_update_from_form(form: ProfileForm) -> BusinessProfileUpdate:
    """Form strings → the client's update. `about` is the one field Meta refuses empty
    (the client validates it as required), so an empty one means "leave it as is";
    every other field is sent, so clearing it on screen clears it on Meta. Websites
    collapse to the non-empty ones; an empty vertical is not sent."""
    websites = [site.strip() for site in (form.website_1, form.website_2) if site.strip()]
    about = form.about.strip()
    return BusinessProfileUpdate(
        about=about or None,
        address=form.address.strip(),
        description=form.description.strip(),
        email=form.email.strip(),
        vertical=form.vertical or None,
        websites=websites,
    )


async def save_profile(
    tenant_id: UUID,
    connection_id: UUID,
    form: ProfileForm,
    *,
    opener: ClientOpener = open_whatsapp_client,
    degrader: Degrader = degrade_connection_on_auth_error,
) -> None:
    """Raises `ValueError` when a field breaks a Meta-published limit (the client checks
    before any request) and `WhatsAppApiError` for a platform refusal."""
    update = profile_update_from_form(form)
    await _call(
        tenant_id,
        connection_id,
        lambda client: client.update_business_profile(update),
        opener=opener,
        degrader=degrader,
    )


async def set_profile_picture(
    tenant_id: UUID,
    connection_id: UUID,
    content: bytes,
    content_type: str,
    filename: str,
    *,
    opener: ClientOpener = open_whatsapp_client,
    degrader: Degrader = degrade_connection_on_auth_error,
) -> None:
    """Upload the photo and point the business profile at it.

    TODO(WA-06 follow-up): Meta documents `profile_picture_handle` as the `h` handle of
    the **Resumable Upload API** (`POST /{APP_ID}/uploads?file_length=&file_type=` →
    `POST /upload:{SESSION_ID}` with header `file_offset: 0`, which answers `{"h": …}`),
    not the media id `POST /{PHONE_NUMBER_ID}/media` returns. `HttpWhatsAppClient` only
    has `upload_media` (its `BusinessProfileUpdate` docstring says the handle is
    "accepted as an opaque string"), so this sends the media id and Meta will most
    likely refuse it with a code-100 parameter error, which the screen shows as a `warn`
    banner with that code. The fix belongs in `packages/api` (owned by the backend), as
    a `upload_profile_picture(content, content_type) -> str` on the client, needing the
    app id plus the scheme R12 pins for the upload host; once it exists, swap the first
    call below for it — nothing else here changes.
    """
    async with opener(tenant_id, connection_id) as client:
        try:
            handle = await client.upload_media(content, content_type, filename)
            await client.update_business_profile(
                BusinessProfileUpdate(profile_picture_handle=handle)
            )
        except WhatsAppApiError as exc:
            if exc.is_auth_error:
                await asyncio.to_thread(degrader, tenant_id=tenant_id, connection_id=connection_id)
            raise


async def list_qr_codes(
    tenant_id: UUID,
    connection_id: UUID,
    *,
    opener: ClientOpener = open_whatsapp_client,
    degrader: Degrader = degrade_connection_on_auth_error,
) -> list[QrCodeVM]:
    """Every QR code of the number. Meta's list omits `qr_image_url` (client.py, `QrCode`
    docstring), so these VMs carry no image; the state keeps the images of codes created
    in this session.

    TODO(WA-06 follow-up): Meta's reference shows `GET …/message_qrdls` accepting
    `fields=code,prefilled_message,deep_link_url,qr_image_url.format(PNG)`; if a live
    call confirms it, `HttpWhatsAppClient.list_qr_codes` should request it and every
    listed code gets its PNG back. Not changed here — `packages/api` is not this screen's.
    """
    codes = await _call(
        tenant_id,
        connection_id,
        lambda client: client.list_qr_codes(),
        opener=opener,
        degrader=degrader,
    )
    return [
        build_qr_vm(
            code=qr.code,
            prefilled_message=qr.prefilled_message,
            deep_link_url=qr.deep_link_url,
            image_url=qr.qr_image_url,
        )
        for qr in codes
    ]


async def create_qr_code(
    tenant_id: UUID,
    connection_id: UUID,
    prefilled_message: str,
    *,
    opener: ClientOpener = open_whatsapp_client,
    degrader: Degrader = degrade_connection_on_auth_error,
) -> QrCodeVM:
    qr = await _call(
        tenant_id,
        connection_id,
        lambda client: client.create_qr_code(prefilled_message, "PNG"),
        opener=opener,
        degrader=degrader,
    )
    return build_qr_vm(
        code=qr.code,
        prefilled_message=qr.prefilled_message,
        deep_link_url=qr.deep_link_url,
        image_url=qr.qr_image_url,
    )


async def delete_qr_code(
    tenant_id: UUID,
    connection_id: UUID,
    code: str,
    *,
    opener: ClientOpener = open_whatsapp_client,
    degrader: Degrader = degrade_connection_on_auth_error,
) -> None:
    await _call(
        tenant_id,
        connection_id,
        lambda client: client.delete_qr_code(code),
        opener=opener,
        degrader=degrader,
    )
