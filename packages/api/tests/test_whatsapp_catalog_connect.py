"""ADR 48 §9: `python -m qualify_api.whatsapp.catalog_sync.connect` with fakes for
`/debug_token`, `product_catalogs` and the registry — every exit code, never Meta, never
the database, and the token never printed."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

import pytest

from qualify_api.connections.token_health import TokenHealthError, TokenHealthReport
from qualify_api.whatsapp.catalog_sync import connect
from qualify_api.whatsapp.catalog_sync.client import FakeWabaCatalogLister
from qualify_api.whatsapp.client import WhatsAppApiError

TENANT = UUID("11111111-1111-4111-8111-111111111111")
BRAND = UUID("22222222-2222-4222-8222-222222222222")
USER = UUID("33333333-3333-4333-8333-333333333333")
TOKEN = "SUPER_SECRET_SYSTEM_USER_TOKEN"
WABA = "waba-1"
CATALOG = "cat-1"
PHONE = connect.PhoneRef(row_id=UUID(int=7), waba_id=WABA, connection_id=UUID(int=8))
ALL_SCOPES = (
    "whatsapp_business_messaging",
    "whatsapp_business_management",
    "catalog_management",
    "business_management",
)


@dataclass
class FakeHealth:
    valid: bool = True
    scopes: tuple[str, ...] = ALL_SCOPES
    error: Exception | None = None

    def debug_token(self, token: str) -> TokenHealthReport:
        if self.error is not None:
            raise self.error
        return TokenHealthReport(
            is_valid=self.valid, expires_at=None, data_access_expires_at=None, scopes=self.scopes
        )


@dataclass
class FakeRegistry:
    phone: connect.PhoneRef | None = PHONE
    conflict: bool = False
    registered: list[connect.CatalogRegistration] = field(default_factory=list)

    def phone_for_brand(self, tenant_id: UUID, brand_id: UUID) -> connect.PhoneRef | None:
        return self.phone

    def register(self, registration: connect.CatalogRegistration) -> connect.CatalogConnectOutcome:
        if self.conflict:
            raise connect.CatalogConflict("live items elsewhere")
        self.registered.append(registration)
        return connect.CatalogConnectOutcome(UUID(int=99), True, WABA, registration.catalog_id)


def _listers(lister: FakeWabaCatalogLister):  # noqa: ANN202
    async def factory(*, tenant_id: UUID, connection_id: UUID) -> FakeWabaCatalogLister:
        assert connection_id == PHONE.connection_id
        return lister

    return factory


def _args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "tenant": TENANT,
        "brand": BRAND,
        "catalog_id": CATALOG,
        "link_url": None,
        "user": USER,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


async def _run(
    *,
    args: argparse.Namespace | None = None,
    health: FakeHealth | None = None,
    lister: FakeWabaCatalogLister | None = None,
    registry: FakeRegistry | None = None,
) -> int:
    return await connect.run(
        args or _args(),
        token_health=health or FakeHealth(),
        listers=_listers(lister or FakeWabaCatalogLister(catalogs={WABA: ["other", CATALOG]})),
        registry=registry or FakeRegistry(),
        owner_lookup=lambda tenant: USER,
    )


@pytest.fixture(autouse=True)
def _token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(connect.TOKEN_ENV, TOKEN)


async def test_ok_registers_the_catalog(capsys: pytest.CaptureFixture[str]) -> None:
    registry = FakeRegistry()
    code = await _run(registry=registry, args=_args(link_url="https://bianki.example"))
    assert code == connect.EXIT_OK
    [registration] = registry.registered
    assert registration.catalog_id == CATALOG
    assert registration.link_url == "https://bianki.example"
    assert registration.phone == PHONE and registration.user_id == USER
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err


async def test_missing_token_is_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(connect.TOKEN_ENV)
    assert await _run() == connect.EXIT_USAGE


async def test_a_link_that_is_not_https_is_usage() -> None:
    registry = FakeRegistry()
    assert await _run(args=_args(link_url="http://x.example"), registry=registry) == 4
    assert registry.registered == []


async def test_no_connected_number_is_usage() -> None:
    assert await _run(registry=FakeRegistry(phone=None)) == connect.EXIT_USAGE


@pytest.mark.parametrize(
    "health",
    [
        FakeHealth(valid=False),
        FakeHealth(scopes=("whatsapp_business_messaging", "whatsapp_business_management")),
        FakeHealth(scopes=("catalog_management",)),
    ],
)
async def test_token_rejected_writes_nothing(
    health: FakeHealth, capsys: pytest.CaptureFixture[str]
) -> None:
    registry = FakeRegistry()
    assert await _run(health=health, registry=registry) == connect.EXIT_TOKEN_REJECTED
    assert registry.registered == []
    assert TOKEN not in capsys.readouterr().err


async def test_debug_token_unavailable_is_an_api_error() -> None:
    assert await _run(health=FakeHealth(error=TokenHealthError("down"))) == connect.EXIT_API_ERROR


@pytest.mark.parametrize(
    "error",
    [
        WhatsAppApiError("x", status=401),
        WhatsAppApiError("x", status=400, code=190),
        WhatsAppApiError("x", status=403, code=200),
    ],
)
async def test_meta_refusing_the_list_is_exit_3(error: WhatsAppApiError) -> None:
    registry = FakeRegistry()
    assert await _run(lister=FakeWabaCatalogLister(error=error), registry=registry) == 3
    assert registry.registered == []


async def test_other_api_errors_are_exit_1() -> None:
    lister = FakeWabaCatalogLister(error=WhatsAppApiError("x", status=500))
    assert await _run(lister=lister) == connect.EXIT_API_ERROR


async def test_a_catalog_not_on_the_waba_is_exit_5() -> None:
    registry = FakeRegistry()
    lister = FakeWabaCatalogLister(catalogs={WABA: ["someone-else"]})
    assert await _run(lister=lister, registry=registry) == connect.EXIT_NOT_CONNECTED
    assert registry.registered == []


async def test_another_catalog_with_live_items_is_exit_6() -> None:
    assert await _run(registry=FakeRegistry(conflict=True)) == connect.EXIT_CONFLICT


async def test_connect_catalog_scopes_constant() -> None:
    assert connect.CATALOG_REQUIRED_SCOPES == frozenset(
        {"catalog_management", "business_management"}
    )
    outcome = await connect.connect_catalog(
        tenant_id=TENANT,
        brand_id=BRAND,
        user_id=USER,
        catalog_id=CATALOG,
        link_url=None,
        token=TOKEN,
        token_health=FakeHealth(),
        listers=_listers(FakeWabaCatalogLister(catalogs={WABA: [CATALOG]})),
        registry=FakeRegistry(),
        clock=lambda: datetime(2026, 11, 12, tzinfo=UTC),
    )
    assert outcome.created and outcome.catalog_id == CATALOG
