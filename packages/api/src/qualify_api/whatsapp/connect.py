"""Administrative connect of a WhatsApp Business phone number (WA-05, QUA-205).

    python -m qualify_api.whatsapp.connect --tenant <uuid> --brand <uuid> \\
        --waba-id <id> --phone-number-id <id> [--user <uuid>]

There is no OAuth here, by design (`docs/plan-modulo-whatsapp-cloud-api.md` §2.2): for a
WABA the operator administers, Meta needs no App Review and no consent screen — the
credential is a **system-user access token** generated once in Business Settings. This
command is the one process that ever reads it from the environment
(`QUALIFY_WA_SYSTEM_USER_TOKEN`); it is never printed, never logged, never stored anywhere
but `oauth_credentials.ciphertext`. After this, every WhatsApp caller gets an
`AuthenticatedClient` from `CredentialResolver` and never sees the token again.

## Verify before writing, write in the same shape as Instagram

1. `GET /debug_token` on the token: it must be `is_valid` and its scopes must include
   `whatsapp_business_messaging` AND `whatsapp_business_management`. Otherwise nothing
   is written (exit 2).
2. `GET /{phone_number_id}?fields=…` with the token: the number's metadata. A token
   Meta rejects here (`WhatsAppApiError.is_auth_error`) also writes nothing (exit 3);
   a number the token cannot see is a plain API error (exit 1).
3. `persist_grant` — the SAME repository the OAuth callback uses — writes
   `social_connections` (`platform='whatsapp'`, `account_type='waba_phone_number'`,
   `external_account_id=phone_number_id`, `linked_page_id=None`, allowed only for this
   platform by `ck_conn_linked_page_by_platform`) plus the encrypted credential
   (`token_type='system_user'`, no calendar expiry) and the `granted` event, in one
   transaction.
4. The C-03 FSM: a new row is born `pending` and verification already passed in steps
   1–2, so `VERIFY_OK` takes it to `active`. A re-run on an `active` row is not a
   transition (Q1); on a `degraded`/`revoked` row it is `RECONNECT` → `active`.
5. `whatsapp_phone_numbers` is upserted by `phone_number_id` with the metadata of step 2.

Idempotent: running it again rotates the credential (version + 1, append-only) and
refreshes username, scopes and metadata; it never produces a second connection or a
second phone row. That is exactly the rotation path when the system-user token is
regenerated in Meta.
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
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.crypto import DevEncryptor, Encryptor
from qualify_api.connections.events import DomainEvent, DomainEventName, EventPublisher
from qualify_api.connections.fsm import ConnectionStatus, Trigger, apply_transition
from qualify_api.connections.repository import (
    ConnectionRepository,
    GrantInput,
    PostgresConnectionRepository,
)
from qualify_api.connections.resolver import _InjectedAuthClient
from qualify_api.connections.token_health import (
    HttpMetaTokenHealthClient,
    MetaTokenHealthClient,
    TokenHealthError,
)
from qualify_api.tenancy.models import TenantMember, User
from qualify_api.whatsapp.client import HttpWhatsAppClient, WhatsAppApiError, WhatsAppClient
from qualify_api.whatsapp.phone_numbers import (
    PhoneNumberUpsert,
    PostgresWhatsAppPhoneNumberRepository,
    WhatsAppPhoneNumberRepository,
)

PLATFORM = "whatsapp"
ACCOUNT_TYPE = "waba_phone_number"
TOKEN_TYPE = "system_user"
TOKEN_ENV = "QUALIFY_WA_SYSTEM_USER_TOKEN"

# Both must be on the token. Literals, not `ScopeKey`s: this check guards a write, and
# the matrix in `qualify_models` is downstream presentation. `[V]` same as the matrix's
# table — observed on the live /debug_token 2026-10-14.
REQUIRED_SCOPES: frozenset[str] = frozenset(
    {"whatsapp_business_messaging", "whatsapp_business_management"}
)

# Exit codes, so a shell (or a deploy script) can tell the outcomes apart.
EXIT_OK = 0
EXIT_API_ERROR = 1
EXIT_TOKEN_REJECTED = 2  # not is_valid, or a required scope missing — nothing written
EXIT_AUTH_ERROR = 3  # Meta rejected the token on the Graph call — nothing written
EXIT_USAGE = 4

# Counts and identifiers only, never the token or a response body.
_LOGGER = logging.getLogger(__name__)


class TokenRejected(Exception):
    """`/debug_token` said the token is not usable. Message never carries the token."""


class ScopesMissing(TokenRejected):
    """The token is valid but lacks one or both required WhatsApp scopes."""

    def __init__(self, missing: frozenset[str]) -> None:
        self.missing = missing
        super().__init__(f"token lacks required scopes: {', '.join(sorted(missing))}")


class PhoneNumberMismatch(Exception):
    """Graph answered for a different id than the one asked — never expected, but a
    wrong row keyed by `phone_number_id` is exactly the kind of fact worth refusing."""


class NoActingUser(RuntimeError):
    """The tenant has no user to record as `connected_by_user_id`. Raised, never
    defaulted: the column is NOT NULL and the audit trail must name a real row."""


@dataclass(frozen=True)
class ConnectOutcome:
    """What one run did. Distinct from `connections.service.ConnectOutcome` (the OAuth
    callback's enum): this is the administrative command's receipt. Nothing here is
    credential material — safe to print and to log."""

    connection_id: UUID
    status: str
    credential_version: int
    created_connection: bool
    created_phone_number: bool
    display_phone_number: str
    verified_name: str | None
    granted_scopes: tuple[str, ...]


def _post_grant_trigger(previous: ConnectionStatus | None) -> Trigger | None:
    """The `verified=True` column of `ConnectService._post_grant_trigger`'s table.

    Verification is not optional here — steps 1–2 ran before anything was persisted —
    so the only inputs are the previous status. `None` means "no legal edge" (Q1: an
    already-active row re-verifying is not a transition)."""
    if previous is None:
        return Trigger.VERIFY_OK
    if previous is ConnectionStatus.ACTIVE:
        return None
    return Trigger.RECONNECT


async def connect_whatsapp_number(
    *,
    tenant_id: UUID,
    brand_id: UUID | None,
    user_id: UUID,
    waba_id: str,
    phone_number_id: str,
    token: str,
    settings: MetaOAuthSettings,
    encryptor: Encryptor,
    repository: ConnectionRepository,
    phone_numbers_repo: WhatsAppPhoneNumberRepository,
    token_health: MetaTokenHealthClient,
    whatsapp_client: WhatsAppClient,
    publisher: EventPublisher,
    clock: Callable[[], datetime],
) -> ConnectOutcome:
    """The whole decision tree, with every side effect behind a Protocol.

    Raises `TokenRejected`/`ScopesMissing` (step 1), `WhatsAppApiError` (step 2, check
    `is_auth_error`) or `PhoneNumberMismatch` BEFORE any write; after the first write the
    remaining steps only touch rows this run owns, and a re-run repairs any of them.
    """
    # --- 1. The token must be valid and carry both scopes. No write before this. ---
    report = token_health.debug_token(token)
    if not report.is_valid:
        raise TokenRejected("debug_token reports is_valid=false")
    granted = tuple(report.scopes)
    missing = REQUIRED_SCOPES - set(granted)
    if missing:
        raise ScopesMissing(frozenset(missing))

    # --- 2. The number must be readable with this token. Still no write. ---
    info = await whatsapp_client.get_phone_number()
    if info.id != phone_number_id:
        raise PhoneNumberMismatch(
            f"asked for phone_number_id={phone_number_id} but Graph answered id={info.id}"
        )
    display_number = info.display_phone_number or phone_number_id

    # --- 3. Persist connection + encrypted credential + event, in one transaction. ---
    now = clock()
    record = repository.persist_grant(
        GrantInput(
            tenant_id=tenant_id,
            brand_id=brand_id,
            user_id=user_id,
            platform_app_id=repository.platform_app_id(settings.app_id, tenant_id=tenant_id),
            platform=PLATFORM,
            account_type=ACCOUNT_TYPE,
            external_account_id=phone_number_id,
            external_username=display_number,
            linked_page_id=None,
            granted_scopes=granted,
            access_posture=settings.access_posture,
            # Encrypted HERE. Past this line the plaintext is unreferenced by this flow.
            ciphertext=encryptor.encrypt(token),
            key_id=encryptor.key_id,
            token_type=TOKEN_TYPE,
            issued_at=now,
            # A system-user token has no calendar expiry; `/debug_token` returns
            # `expires_at=0` for it, the same convention `token_health.py` documents.
            expires_at=None,
        )
    )
    publisher.publish(
        DomainEvent(
            name=DomainEventName.GRANTED,
            connection_id=record.connection_id,
            tenant_id=record.tenant_id,
            occurred_at=now,
            data={"credential_version": record.credential_version, "platform": PLATFORM},
        )
    )

    # --- 4. FSM. Verification already passed, so this is the verified=True column. ---
    previous = (
        ConnectionStatus(record.previous_status) if record.previous_status is not None else None
    )
    trigger = _post_grant_trigger(previous)
    if trigger is None:
        status = previous if previous is not None else ConnectionStatus.PENDING
    else:
        status = apply_transition(
            previous if previous is not None else ConnectionStatus.PENDING,
            trigger,
            connection_id=record.connection_id,
            tenant_id=record.tenant_id,
            publisher=publisher,
            now=now,
        )
    repository.record_status(
        connection_id=record.connection_id,
        tenant_id=record.tenant_id,
        status=str(status),
        verified_at=now,
        event_type="granted",
        credential_version=record.credential_version,
    )

    # --- 5. The number row, keyed by Meta's global id. ---
    created_phone = phone_numbers_repo.upsert(
        PhoneNumberUpsert(
            tenant_id=tenant_id,
            brand_id=brand_id,
            connection_id=record.connection_id,
            waba_id=waba_id,
            phone_number_id=phone_number_id,
            display_phone_number=display_number,
            verified_name=info.verified_name,
            name_status=info.name_status,
            quality_rating=info.quality_rating,
            messaging_limit_tier=info.messaging_limit_tier,
            platform_status=info.status,
            synced_at=now,
        )
    )
    _LOGGER.info(
        "whatsapp connect: connection=%s status=%s credential_version=%d new=%s",
        record.connection_id,
        status,
        record.credential_version,
        record.is_new,
    )
    return ConnectOutcome(
        connection_id=record.connection_id,
        status=str(status),
        credential_version=record.credential_version,
        created_connection=record.is_new,
        created_phone_number=created_phone,
        display_phone_number=display_number,
        verified_name=info.verified_name,
        granted_scopes=granted,
    )


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def owner_user_id(tenant_id: UUID) -> UUID | None:
    """The user the grant is attributed to when `--user` is not given: the tenant's
    `owner`, else its eldest user. Same stand-in `connections_provider.acting_user_id`
    uses for the Instagram flow, read through `tenant_session` so a tenant can only
    resolve to its OWN user."""
    with tenant_session(tenant_id) as session:
        owner = session.scalar(
            select(User.id)
            .join(TenantMember, TenantMember.user_id == User.id)
            .where(TenantMember.role == "owner")
            .order_by(User.created_at)
        )
        if owner is not None:
            return owner
        return session.scalar(select(User.id).order_by(User.created_at))


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="qualify_api.whatsapp.connect",
        description=(
            "Connect a WhatsApp Business phone number to a tenant. Reads the system-user "
            f"token from ${TOKEN_ENV}; never prints it."
        ),
    )
    parser.add_argument("--tenant", required=True, type=UUID, help="tenant id")
    parser.add_argument(
        "--brand", type=UUID, default=None, help="brand id (optional; kept on re-run if omitted)"
    )
    parser.add_argument("--waba-id", required=True, help="WhatsApp Business Account id")
    parser.add_argument("--phone-number-id", required=True, help="Meta phone_number_id")
    parser.add_argument(
        "--user",
        type=UUID,
        default=None,
        help="user recorded as connected_by (default: the tenant's owner)",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    token = os.environ.get(TOKEN_ENV)
    if not token:
        print(f"set {TOKEN_ENV} in the environment (for this one process)", file=sys.stderr)
        return EXIT_USAGE

    user_id = args.user or owner_user_id(args.tenant)
    if user_id is None:
        print(f"tenant {args.tenant} has no user to attribute the grant to", file=sys.stderr)
        return EXIT_USAGE

    settings = MetaOAuthSettings.from_env()
    graph = _InjectedAuthClient(token, scheme="Bearer")
    whatsapp_client = HttpWhatsAppClient(
        graph_client=graph,
        graph_url=settings.graph_url,
        phone_number_id=args.phone_number_id,
        waba_id=args.waba_id,
    )
    try:
        outcome = await connect_whatsapp_number(
            tenant_id=args.tenant,
            brand_id=args.brand,
            user_id=user_id,
            waba_id=args.waba_id,
            phone_number_id=args.phone_number_id,
            token=token,
            settings=settings,
            encryptor=DevEncryptor(),
            repository=PostgresConnectionRepository(),
            phone_numbers_repo=PostgresWhatsAppPhoneNumberRepository(),
            token_health=HttpMetaTokenHealthClient(settings),
            whatsapp_client=whatsapp_client,
            publisher=_cli_publisher(),
            clock=lambda: datetime.now(UTC),
        )
    except ScopesMissing as exc:
        print(
            f"token rejected: missing scopes {sorted(exc.missing)}; nothing written. "
            "Regenerate the system-user token with whatsapp_business_messaging and "
            "whatsapp_business_management.",
            file=sys.stderr,
        )
        return EXIT_TOKEN_REJECTED
    except TokenRejected as exc:
        print(f"token rejected: {exc}; nothing written", file=sys.stderr)
        return EXIT_TOKEN_REJECTED
    except TokenHealthError as exc:
        print(f"debug_token unavailable: {exc}; nothing written", file=sys.stderr)
        return EXIT_API_ERROR
    except WhatsAppApiError as exc:
        if exc.is_auth_error:
            print(
                f"Meta rejected the token on the Graph call (status={exc.status} "
                f"code={exc.code}); nothing written",
                file=sys.stderr,
            )
            return EXIT_AUTH_ERROR
        print(
            f"whatsapp api error: status={exc.status} code={exc.code} subcode={exc.subcode} "
            f"transport={exc.is_transport}; nothing written",
            file=sys.stderr,
        )
        return EXIT_API_ERROR
    except PhoneNumberMismatch as exc:
        print(f"{exc}; nothing written", file=sys.stderr)
        return EXIT_API_ERROR
    finally:
        del token
        await graph.aclose()

    verified = f" ({outcome.verified_name})" if outcome.verified_name else ""
    print(
        f"whatsapp connection {outcome.connection_id} status={outcome.status} "
        f"number={outcome.display_phone_number}{verified} "
        f"credential_version={outcome.credential_version} "
        f"{'created' if outcome.created_connection else 'refreshed'}"
    )
    return EXIT_OK


def _cli_publisher() -> EventPublisher:
    """The shared in-process publisher of the connections module, so a subscriber sees
    this grant next to every other lifecycle event. Imported lazily: `composition.py`
    pulls in the whole connect graph, which this command otherwise does not need."""
    from qualify_api.connections.composition import production_event_publisher

    return production_event_publisher()


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(_parse_args(sys.argv[1:] if argv is None else argv)))


if __name__ == "__main__":
    raise SystemExit(main())
