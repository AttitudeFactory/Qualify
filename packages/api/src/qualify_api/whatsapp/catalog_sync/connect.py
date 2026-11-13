"""Administrative registration of a business's WhatsApp catalog (ADR 48 §9).

    python -m qualify_api.whatsapp.catalog_sync.connect --tenant <uuid> --brand <uuid> \\
        --catalog-id <id> [--link-url https://…] [--user <uuid>]

(`just whatsapp-catalog-connect …`). Qualify neither creates nor connects catalogs: the
founder creates the catalog in Commerce Manager, connects it to the WABA by hand, and runs
this to tell Qualify which catalog to write.

1. The brand's number must be connected (`whatsapp_phone_numbers`) → its WABA and its
   connection. Otherwise exit 4 (a precondition of the command, nothing written).
2. `GET /debug_token` on `QUALIFY_WA_SYSTEM_USER_TOKEN` (never printed): valid and carrying
   `CATALOG_REQUIRED_SCOPES`. Otherwise exit 2, nothing written. (`connect.REQUIRED_SCOPES`
   for the number itself is unchanged.)
3. With the STORED credential (`CredentialResolver` over the number's connection):
   `GET /{waba_id}/product_catalogs`; the catalog id must be listed. Authorization refused
   → exit 3; not listed (not connected to this WABA) → exit 5.
4. Upsert by `waba_id` with `access_state='ok'`; re-running only refreshes. If the WABA (or
   the brand) already has ANOTHER catalog with live items → exit 6 (switching would orphan
   them). Exit 1 = any other API error, 4 = usage.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from qualify_api.connections.token_health import MetaTokenHealthClient, TokenHealthError
from qualify_api.whatsapp.catalog_sync.client import WabaCatalogLister
from qualify_api.whatsapp.client import WhatsAppApiError

TOKEN_ENV = "QUALIFY_WA_SYSTEM_USER_TOKEN"
#: `[V]` docs only (ADR 48 §2 [PC], [CM]): reading `product_catalogs` asks for
#: `catalog_management`, which depends on `business_management`.
CATALOG_REQUIRED_SCOPES: frozenset[str] = frozenset({"catalog_management", "business_management"})

EXIT_OK = 0
EXIT_API_ERROR = 1
EXIT_TOKEN_REJECTED = 2
EXIT_AUTH_ERROR = 3
EXIT_USAGE = 4
EXIT_NOT_CONNECTED = 5
EXIT_CONFLICT = 6

_LOGGER = logging.getLogger(__name__)


# --- outcomes and refusals ----------------------------------------------------------------


class CatalogConnectError(Exception):
    exit_code = EXIT_API_ERROR


class NumberNotConnected(CatalogConnectError):
    exit_code = EXIT_USAGE


class CatalogTokenRejected(CatalogConnectError):
    exit_code = EXIT_TOKEN_REJECTED


class CatalogAuthRefused(CatalogConnectError):
    exit_code = EXIT_AUTH_ERROR


class CatalogNotOnWaba(CatalogConnectError):
    exit_code = EXIT_NOT_CONNECTED


class CatalogConflict(CatalogConnectError):
    exit_code = EXIT_CONFLICT


@dataclass(frozen=True)
class PhoneRef:
    row_id: UUID
    waba_id: str
    connection_id: UUID


@dataclass(frozen=True)
class CatalogRegistration:
    tenant_id: UUID
    brand_id: UUID
    phone: PhoneRef
    catalog_id: str
    link_url: str | None
    user_id: UUID
    now: datetime


@dataclass(frozen=True)
class CatalogConnectOutcome:
    catalog_row_id: UUID
    created: bool
    waba_id: str
    catalog_id: str


# --- seams --------------------------------------------------------------------------------


class CatalogRegistry(Protocol):
    def phone_for_brand(self, tenant_id: UUID, brand_id: UUID) -> PhoneRef | None: ...

    def register(self, registration: CatalogRegistration) -> CatalogConnectOutcome:
        """Upsert by `waba_id`; raises `CatalogConflict` when another catalog with live
        items is in the way."""
        ...


class ListerFactory(Protocol):
    async def __call__(self, *, tenant_id: UUID, connection_id: UUID) -> WabaCatalogLister: ...


# --- the decision tree --------------------------------------------------------------------


async def connect_catalog(
    *,
    tenant_id: UUID,
    brand_id: UUID,
    user_id: UUID,
    catalog_id: str,
    link_url: str | None,
    token: str,
    token_health: MetaTokenHealthClient,
    listers: ListerFactory,
    registry: CatalogRegistry,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> CatalogConnectOutcome:
    phone = registry.phone_for_brand(tenant_id, brand_id)
    if phone is None:
        raise NumberNotConnected("the brand has no connected WhatsApp number")

    try:
        report = token_health.debug_token(token)
    except TokenHealthError as exc:
        raise CatalogConnectError(f"debug_token unavailable: {type(exc).__name__}") from None
    if not report.is_valid:
        raise CatalogTokenRejected("debug_token reports is_valid=false")
    missing = CATALOG_REQUIRED_SCOPES - set(report.scopes)
    if missing:
        raise CatalogTokenRejected(f"token lacks required scopes: {', '.join(sorted(missing))}")

    try:
        lister = await listers(tenant_id=tenant_id, connection_id=phone.connection_id)
        catalog_ids = await lister.product_catalog_ids(phone.waba_id)
    except WhatsAppApiError as exc:
        if exc.is_auth_error or (
            exc.code is not None and (exc.code == 10 or 200 <= exc.code < 300)
        ):
            raise CatalogAuthRefused(
                f"Meta refused product_catalogs (status={exc.status} code={exc.code})"
            ) from None
        raise CatalogConnectError(
            f"product_catalogs failed (status={exc.status} code={exc.code} "
            f"transport={exc.is_transport})"
        ) from None
    if catalog_id not in catalog_ids:
        raise CatalogNotOnWaba(f"catalog {catalog_id} is not connected to WABA {phone.waba_id}")

    outcome = registry.register(
        CatalogRegistration(
            tenant_id=tenant_id,
            brand_id=brand_id,
            phone=phone,
            catalog_id=catalog_id,
            link_url=link_url,
            user_id=user_id,
            now=clock(),
        )
    )
    _LOGGER.info(
        "whatsapp catalog connect: tenant_id=%s catalog_row_id=%s created=%s",
        tenant_id,
        outcome.catalog_row_id,
        outcome.created,
    )
    return outcome


# --- Postgres -----------------------------------------------------------------------------


class PostgresCatalogRegistry:
    """Both reads and the write through `tenant_session` (RLS)."""

    def phone_for_brand(self, tenant_id: UUID, brand_id: UUID) -> PhoneRef | None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import select  # noqa: PLC0415

        from qualify_api.whatsapp.models import WhatsAppPhoneNumber  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            row = session.execute(
                select(
                    WhatsAppPhoneNumber.id,
                    WhatsAppPhoneNumber.waba_id,
                    WhatsAppPhoneNumber.connection_id,
                )
                .where(WhatsAppPhoneNumber.brand_id == brand_id)
                .order_by(WhatsAppPhoneNumber.created_at)
                .limit(1)
            ).first()
        if row is None:
            return None
        return PhoneRef(row_id=row.id, waba_id=row.waba_id, connection_id=row.connection_id)

    def register(self, registration: CatalogRegistration) -> CatalogConnectOutcome:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import func, or_, select  # noqa: PLC0415
        from sqlalchemy.exc import IntegrityError  # noqa: PLC0415

        from qualify_api.whatsapp.models import (  # noqa: PLC0415
            WhatsAppCatalog,
            WhatsAppCatalogItem,
        )

        r = registration
        try:
            with tenant_session(r.tenant_id) as session:
                rows = list(
                    session.scalars(
                        select(WhatsAppCatalog)
                        .where(
                            or_(
                                WhatsAppCatalog.waba_id == r.phone.waba_id,
                                WhatsAppCatalog.brand_id == r.brand_id,
                            )
                        )
                        .with_for_update()
                    )
                )
                if len(rows) > 1:
                    raise CatalogConflict("the WABA and the brand belong to different catalogs")
                if rows:
                    row = rows[0]
                    moving = row.catalog_id != r.catalog_id or row.waba_id != r.phone.waba_id
                    if moving:
                        live = session.scalar(
                            select(func.count())
                            .select_from(WhatsAppCatalogItem)
                            .where(
                                WhatsAppCatalogItem.catalog_row_id == row.id,
                                WhatsAppCatalogItem.state != "deleted",
                            )
                        )
                        if live:
                            raise CatalogConflict(
                                f"catalog row {row.id} has {live} live item(s) in another catalog"
                            )
                    row.brand_id = r.brand_id
                    row.phone_number_row_id = r.phone.row_id
                    row.waba_id = r.phone.waba_id
                    row.catalog_id = r.catalog_id
                    if r.link_url is not None:
                        row.link_url = r.link_url
                    row.source = "qualify"
                    row.access_state = "ok"
                    row.access_checked_at = r.now
                    row.updated_at = r.now
                    session.flush()
                    return CatalogConnectOutcome(row.id, False, row.waba_id, row.catalog_id)
                row = WhatsAppCatalog(
                    tenant_id=r.tenant_id,
                    brand_id=r.brand_id,
                    phone_number_row_id=r.phone.row_id,
                    waba_id=r.phone.waba_id,
                    catalog_id=r.catalog_id,
                    link_url=r.link_url,
                    source="qualify",
                    access_state="ok",
                    access_checked_at=r.now,
                    connected_by=r.user_id,
                    connected_at=r.now,
                    updated_at=r.now,
                )
                session.add(row)
                session.flush()
                return CatalogConnectOutcome(row.id, True, row.waba_id, row.catalog_id)
        except IntegrityError:
            # The WABA is registered under another tenant (invisible through RLS).
            raise CatalogConflict("the WABA already has a catalog registered") from None


class ResolverListerFactory:
    def __init__(self, settings: object, encryptor: object) -> None:
        self._settings = settings
        self._encryptor = encryptor

    async def __call__(self, *, tenant_id: UUID, connection_id: UUID) -> WabaCatalogLister:
        from qualify_api.connections.credential_reader import DbCredentialReader  # noqa: PLC0415
        from qualify_api.connections.resolver import InjectingCredentialResolver  # noqa: PLC0415
        from qualify_api.whatsapp.catalog_sync.client import (  # noqa: PLC0415
            HttpWabaCatalogLister,
        )

        resolver = InjectingCredentialResolver(
            DbCredentialReader(tenant_id),
            self._encryptor,  # type: ignore[arg-type]
        )
        graph = await resolver.client_for(
            connection_id,
            scheme=self._settings.graph_auth_scheme,  # type: ignore[attr-defined]
        )
        return HttpWabaCatalogLister(graph, self._settings.graph_url)  # type: ignore[attr-defined]


# --- CLI ----------------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="qualify_api.whatsapp.catalog_sync.connect",
        description=(
            "Register the Commerce Manager catalog connected to a brand's WABA. Reads the "
            f"system-user token from ${TOKEN_ENV} only to check its scopes; never prints it."
        ),
    )
    parser.add_argument("--tenant", required=True, type=UUID, help="tenant id")
    parser.add_argument("--brand", required=True, type=UUID, help="brand id")
    parser.add_argument("--catalog-id", required=True, help="Meta catalog id")
    parser.add_argument(
        "--link-url",
        default=None,
        help="the business's website (https://…) for each item's link; default wa.me/<number>",
    )
    parser.add_argument(
        "--user", type=UUID, default=None, help="user recorded as connected_by (default: owner)"
    )
    return parser.parse_args(argv)


async def run(
    args: argparse.Namespace,
    *,
    token_health: MetaTokenHealthClient | None = None,
    listers: ListerFactory | None = None,
    registry: CatalogRegistry | None = None,
    owner_lookup: Callable[[UUID], UUID | None] | None = None,
) -> int:
    """The CLI body; every dependency injectable so tests run offline."""
    token = os.environ.get(TOKEN_ENV)
    if not token:
        print(f"set {TOKEN_ENV} in the environment (for this one process)", file=sys.stderr)
        return EXIT_USAGE
    link_url = (args.link_url or "").strip() or None
    if link_url is not None and not link_url.startswith("https://"):
        print("--link-url must start with https://", file=sys.stderr)
        return EXIT_USAGE
    catalog_id = (args.catalog_id or "").strip()
    if not catalog_id:
        print("--catalog-id must not be empty", file=sys.stderr)
        return EXIT_USAGE

    if owner_lookup is None:
        from qualify_api.whatsapp.connect import owner_user_id  # noqa: PLC0415

        owner_lookup = owner_user_id
    user_id = args.user or owner_lookup(args.tenant)
    if user_id is None:
        print(f"tenant {args.tenant} has no user to record as connected_by", file=sys.stderr)
        return EXIT_USAGE

    if token_health is None or listers is None:
        from qualify_api.config import MetaOAuthSettings  # noqa: PLC0415
        from qualify_api.connections.crypto import DevEncryptor  # noqa: PLC0415
        from qualify_api.connections.token_health import (  # noqa: PLC0415
            HttpMetaTokenHealthClient,
        )

        settings = MetaOAuthSettings.from_env()
        token_health = token_health or HttpMetaTokenHealthClient(settings)
        listers = listers or ResolverListerFactory(settings, DevEncryptor())
    try:
        outcome = await connect_catalog(
            tenant_id=args.tenant,
            brand_id=args.brand,
            user_id=user_id,
            catalog_id=catalog_id,
            link_url=link_url,
            token=token,
            token_health=token_health,
            listers=listers,
            registry=registry or PostgresCatalogRegistry(),
        )
    except CatalogConnectError as exc:
        print(f"{exc}; nothing written", file=sys.stderr)
        return exc.exit_code
    finally:
        del token
    print(
        f"whatsapp catalog {outcome.catalog_row_id} waba={outcome.waba_id} "
        f"catalog={outcome.catalog_id} {'created' if outcome.created else 'refreshed'}"
    )
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(run(_parse_args(sys.argv[1:] if argv is None else argv)))


if __name__ == "__main__":
    raise SystemExit(main())
