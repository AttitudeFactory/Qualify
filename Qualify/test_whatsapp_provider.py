"""Network-free tests for `whatsapp_provider` (WA-12).

Every Graph-backed function is driven with a fake `WhatsAppClient` through the injectable
`opener`, so nothing here touches Meta, Postgres or a credential. They pin:

- «Verificar ahora» = token health-check first; the phone metadata is fetched and stored
  only when the token is still valid.
- A 401 / code 190 from Graph degrades the connection (the injected degrader) and the
  error still propagates; any other error never degrades.
- The form → `BusinessProfileUpdate` mapping, the photo chain, and the QR calls.
- Structural guarantees: Postgres only through `tenant_session`, Graph only through the
  `CredentialResolver` with an explicit `Bearer` scheme, and no token handling at all.
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import pytest
from qualify_api.whatsapp.client import (
    BusinessProfile,
    BusinessProfileUpdate,
    PhoneNumberInfo,
    QrCode,
    WhatsAppApiError,
)

from . import whatsapp_provider
from .whatsapp_provider import (
    create_qr_code,
    delete_qr_code,
    list_qr_codes,
    load_profile,
    profile_update_from_form,
    save_profile,
    set_profile_picture,
    verify_number,
)
from .whatsapp_vm import ProfileForm

TENANT = UUID("00000000-0000-0000-0000-0000000000aa")
CONNECTION = UUID("00000000-0000-0000-0000-0000000000bb")

_INFO = PhoneNumberInfo(
    id="1234",
    verified_name="Bianki",
    display_phone_number="+57 300 1234567",
    quality_rating="GREEN",
    messaging_limit_tier="TIER_1K",
    name_status="APPROVED",
    status="CONNECTED",
    code_verification_status="VERIFIED",
)


class FakeClient:
    """Implements the slice of `WhatsAppClient` the screen uses; records every call."""

    def __init__(self, fail_with: WhatsAppApiError | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.fail_with = fail_with
        self.qr_codes = [
            QrCode(
                code="QR1",
                prefilled_message="Hola, vengo del mostrador",
                deep_link_url="https://wa.me/message/QR1",
            )
        ]

    def _maybe_fail(self) -> None:
        if self.fail_with is not None:
            raise self.fail_with

    async def get_phone_number(self) -> PhoneNumberInfo:
        self.calls.append(("get_phone_number", None))
        self._maybe_fail()
        return _INFO

    async def get_business_profile(self) -> BusinessProfile:
        self.calls.append(("get_business_profile", None))
        self._maybe_fail()
        return BusinessProfile(
            about="Pastelería",
            address="Calle 1",
            description="Tortas",
            email="hola@bianki.co",
            profile_picture_url="https://cdn/p.jpg",
            websites=("https://bianki.co", "https://ig.me/bianki"),
            vertical="RESTAURANT",
        )

    async def update_business_profile(self, profile: BusinessProfileUpdate) -> None:
        self.calls.append(("update_business_profile", profile))
        self._maybe_fail()

    async def upload_media(self, content: bytes, content_type: str, filename: str) -> str:
        self.calls.append(("upload_media", (len(content), content_type, filename)))
        self._maybe_fail()
        return "MEDIA-1"

    async def list_qr_codes(self) -> list[QrCode]:
        self.calls.append(("list_qr_codes", None))
        self._maybe_fail()
        return list(self.qr_codes)

    async def create_qr_code(self, prefilled_message: str, image_format: str = "PNG") -> QrCode:
        self.calls.append(("create_qr_code", (prefilled_message, image_format)))
        self._maybe_fail()
        return QrCode(
            code="QR2",
            prefilled_message=prefilled_message,
            deep_link_url="https://wa.me/message/QR2",
            qr_image_url="https://scontent/qr2.png",
        )

    async def delete_qr_code(self, code: str) -> None:
        self.calls.append(("delete_qr_code", code))
        self._maybe_fail()


class Harness:
    """The fake opener + degrader + health check + store, with call records."""

    def __init__(self, client: FakeClient, *, healthy: bool = True) -> None:
        self.client = client
        self.healthy = healthy
        self.opened: list[tuple[UUID, UUID]] = []
        self.degraded: list[dict[str, UUID]] = []
        self.health_checks: list[dict[str, UUID]] = []
        self.stored: list[tuple[UUID, UUID, PhoneNumberInfo]] = []

    @asynccontextmanager
    async def opener(self, tenant_id: UUID, connection_id: UUID) -> AsyncIterator[FakeClient]:
        self.opened.append((tenant_id, connection_id))
        yield self.client

    def degrader(self, **kwargs: UUID) -> None:
        self.degraded.append(kwargs)

    def health_check(self, **kwargs: UUID) -> bool:
        self.health_checks.append(kwargs)
        return self.healthy

    def store(self, tenant_id: UUID, connection_id: UUID, info: PhoneNumberInfo) -> None:
        self.stored.append((tenant_id, connection_id, info))

    @property
    def graph(self) -> dict[str, Any]:
        return {"opener": self.opener, "degrader": self.degrader}


def _names(calls: Sequence[tuple[str, Any]]) -> list[str]:
    return [name for name, _ in calls]


# --- «Verificar ahora» --------------------------------------------------------------------


async def test_verify_healthy_refreshes_the_phone_metadata() -> None:
    h = Harness(FakeClient())
    ok = await verify_number(
        TENANT, CONNECTION, health_check=h.health_check, store=h.store, **h.graph
    )
    assert ok is True
    assert h.health_checks == [{"tenant_id": TENANT, "connection_id": CONNECTION}]
    assert _names(h.client.calls) == ["get_phone_number"]
    assert h.stored == [(TENANT, CONNECTION, _INFO)]
    assert h.degraded == []


async def test_verify_unhealthy_touches_neither_graph_nor_the_row() -> None:
    """`check_connection_health` already degraded the connection; asking Graph for the
    number with a dead token would only produce a second, louder failure."""
    h = Harness(FakeClient(), healthy=False)
    ok = await verify_number(
        TENANT, CONNECTION, health_check=h.health_check, store=h.store, **h.graph
    )
    assert ok is False
    assert h.opened == [] and h.client.calls == [] and h.stored == []


async def test_auth_error_degrades_then_propagates() -> None:
    h = Harness(FakeClient(fail_with=WhatsAppApiError("x", status=401, code=190)))
    with pytest.raises(WhatsAppApiError):
        await verify_number(
            TENANT, CONNECTION, health_check=h.health_check, store=h.store, **h.graph
        )
    assert h.degraded == [{"tenant_id": TENANT, "connection_id": CONNECTION}]
    assert h.stored == []


async def test_non_auth_error_never_degrades() -> None:
    h = Harness(FakeClient(fail_with=WhatsAppApiError("x", status=400, code=100)))
    with pytest.raises(WhatsAppApiError):
        await load_profile(TENANT, CONNECTION, **h.graph)
    assert h.degraded == []


# --- Perfil -------------------------------------------------------------------------------


async def test_load_profile_maps_to_the_vm() -> None:
    h = Harness(FakeClient())
    vm = await load_profile(TENANT, CONNECTION, **h.graph)
    assert vm.about == "Pastelería"
    assert (vm.website_1, vm.website_2) == ("https://bianki.co", "https://ig.me/bianki")
    assert vm.vertical == "RESTAURANT"
    assert vm.picture_url == "https://cdn/p.jpg"
    assert h.opened == [(TENANT, CONNECTION)]


def _form(**overrides: str) -> ProfileForm:
    values = {
        "about": " Pastelería ",
        "address": "Calle 1",
        "description": "",
        "email": "hola@bianki.co",
        "website_1": "",
        "website_2": "https://bianki.co",
        "vertical": "RESTAURANT",
    }
    values.update(overrides)
    return ProfileForm(**values)


def test_profile_update_from_form() -> None:
    update = profile_update_from_form(_form())
    assert update.about == "Pastelería"
    assert update.websites == ["https://bianki.co"]
    assert update.description == ""  # cleared on screen → cleared on Meta
    assert update.vertical == "RESTAURANT"
    assert update.profile_picture_handle is None
    # Meta refuses an empty `about`: empty means "leave it as is", never "".
    assert profile_update_from_form(_form(about="  ")).about is None
    assert profile_update_from_form(_form(vertical="")).vertical is None


async def test_save_profile_sends_the_update() -> None:
    h = Harness(FakeClient())
    await save_profile(TENANT, CONNECTION, _form(), **h.graph)
    [(name, update)] = h.client.calls
    assert name == "update_business_profile"
    assert update == profile_update_from_form(_form())


async def test_profile_picture_uploads_then_points_the_profile_at_it() -> None:
    h = Harness(FakeClient())
    await set_profile_picture(TENANT, CONNECTION, b"\xff\xd8jpeg", "image/jpeg", "p.jpg", **h.graph)
    assert _names(h.client.calls) == ["upload_media", "update_business_profile"]
    assert h.client.calls[0][1] == (6, "image/jpeg", "p.jpg")
    assert h.client.calls[1][1] == BusinessProfileUpdate(profile_picture_handle="MEDIA-1")


async def test_profile_picture_auth_error_degrades() -> None:
    h = Harness(FakeClient(fail_with=WhatsAppApiError("x", status=401)))
    with pytest.raises(WhatsAppApiError):
        await set_profile_picture(TENANT, CONNECTION, b"x", "image/png", "p.png", **h.graph)
    assert len(h.degraded) == 1


# --- QR -----------------------------------------------------------------------------------


async def test_list_qr_codes() -> None:
    h = Harness(FakeClient())
    [qr] = await list_qr_codes(TENANT, CONNECTION, **h.graph)
    assert qr.code == "QR1"
    assert qr.image_url == ""  # Meta's list omits it
    assert qr.channel_label == "Mostrador"


async def test_create_qr_code_asks_for_a_png() -> None:
    h = Harness(FakeClient())
    qr = await create_qr_code(TENANT, CONNECTION, "Hola, vengo del empaque", **h.graph)
    assert h.client.calls == [("create_qr_code", ("Hola, vengo del empaque", "PNG"))]
    assert qr.image_url == "https://scontent/qr2.png"
    assert qr.channel_label == "Empaque"


async def test_delete_qr_code() -> None:
    h = Harness(FakeClient())
    await delete_qr_code(TENANT, CONNECTION, "QR1", **h.graph)
    assert h.client.calls == [("delete_qr_code", "QR1")]


# --- structure ------------------------------------------------------------------------------


def test_provider_reaches_postgres_only_through_tenant_session() -> None:
    source = inspect.getsource(whatsapp_provider)
    for forbidden in ("create_engine", "sessionmaker", "admin_session", "credential_session"):
        assert forbidden not in source, f"{forbidden} bypasses the sanctioned door (C-01.4)"
    assert source.count("tenant_session(") >= 3


def test_graph_goes_through_the_resolver_never_a_token() -> None:
    source = inspect.getsource(whatsapp_provider)
    assert "InjectingCredentialResolver(DbCredentialReader(tenant_id)" in source
    assert "scheme=_GRAPH_SCHEME" in source and '_GRAPH_SCHEME = "Bearer"' in source
    for forbidden in (
        "decrypt(",
        "_InjectedAuthClient",
        "QUALIFY_WA_SYSTEM_USER_TOKEN",
        "oauth_credentials",
    ):
        assert forbidden not in source, f"{forbidden}: the screen must never handle a token"


def test_opener_is_the_real_one_by_default() -> None:
    for fn in (verify_number, load_profile, save_profile, list_qr_codes, create_qr_code):
        default = inspect.signature(fn).parameters["opener"].default
        assert default is whatsapp_provider.open_whatsapp_client
