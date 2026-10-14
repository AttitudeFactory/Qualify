"""Cross-tenant resolution of a `mentions` webhook event's owning tenant (QUA-49).

## Why this needs a cross-tenant read at all

Meta's webhook payload names the mentioned account by its own `external_account_id`
(`entry[].id` — see `MENTIONS_ENTRY_ID_CITATION` in `qualify_shared.social.ig_shapes`).
It carries no `tenant_id`, because Meta has no concept of Qualify's tenants. So the very
first thing this receiver must do with an incoming event is answer "which tenant owns
this account", and it must answer that BEFORE any `tenant_session(tenant_id)` can be
opened — that door requires the tenant id as its own argument, which is exactly the
thing not yet known.

## Which door, and why it is narrow (QUA-147)

This lookup reads `social_connections` ACROSS tenants, which FORCE RLS forbids to every
tenant-scoped role. It runs through `qualify_shared.db.webhook.webhook_worker_session` —
`qualify_webhook_worker`, created by migration 0050 for exactly this — never through
`admin_session` any more:

- It runs in the intake PROCESSOR (`qualify_api.webhooks.processor`), outside the HTTP
  request. Before QUA-147 it ran inline in the public webhook route under
  `admin_session`; that exception is gone.
- The role has BYPASSRLS, but BYPASSRLS never bypasses a GRANT: on `social_connections`
  it may SELECT only `id, tenant_id, platform, external_account_id, status`, and it holds
  no privilege on any other tenant table. `test_webhook_schema_db.py` pins that set.
- It is READ-ONLY — one `SELECT`, no `INSERT`/`UPDATE`/`DELETE` (the role could not
  write `social_connections` anyway). `test_mentions_resolve.py`'s
  `test_resolution_never_writes` pins this with a real Postgres check.
- It queries by `(platform, external_account_id)` ONLY — never accepts a `tenant_id`
  from the caller as a shortcut or a trust mechanism. A `tenant_id` supplied by an
  inbound request is not evidence of anything; the whole point of this function is to
  derive that value independently.
- Immediately after this function returns a `RESOLVED` outcome, every subsequent read
  MUST go back through `tenant_session(tenant_id)` using the tenant id this function
  just produced (`mentions.composition.ingest_mention` does).

## Why three outcomes, never a silent pick

`SocialConnection`'s natural key is `UNIQUE(tenant_id, platform, external_account_id)` —
tenant-scoped, not global. Nothing in the schema (checked against
`connections/models.py` and `connections/repository.py` before writing this module)
prevents the same real Instagram account from being connected under two different
tenants; `persist_grant` only ever checks within the tenant it was already called for.
So a query across all tenants can legitimately return zero, one, or more than one row,
and picking "the first" on more-than-one would be exactly the misattribution bug this
module exists to prevent — the same "no fuzzy matching, surface the ambiguity instead
of guessing" discipline `qualify_models.permission_capability.resolve_scope_keys`
already establishes for a different kind of ambiguous match.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from qualify_shared.db.webhook import webhook_worker_session
from sqlalchemy import select

from qualify_api.connections.models import SocialConnection

PLATFORM_INSTAGRAM = "instagram"


class ResolutionOutcome(StrEnum):
    RESOLVED = "resolved"
    ORPHAN = "orphan"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class TenantResolution:
    """The result of resolving one `external_account_id`.

    `tenant_id`/`connection_id` are populated ONLY when `outcome is RESOLVED` — a
    caller must switch on `outcome`, never on whether the ids happen to be set, so
    there is exactly one way to read this type correctly.
    """

    outcome: ResolutionOutcome
    tenant_id: UUID | None = None
    connection_id: UUID | None = None


def resolve_external_account(*, platform: str, external_account_id: str) -> TenantResolution:
    """READ-ONLY cross-tenant lookup of who owns `(platform, external_account_id)`.

    See this module's docstring for the door it uses and why it is narrow.
    Deliberately takes no `tenant_id` parameter — accepting
    one from a caller would defeat the entire point of this function, which is to
    derive that value independently rather than trust an assertion of it.
    """
    with webhook_worker_session() as session:
        rows = session.execute(
            select(SocialConnection.tenant_id, SocialConnection.id).where(
                SocialConnection.platform == platform,
                SocialConnection.external_account_id == external_account_id,
            )
        ).all()

    if not rows:
        return TenantResolution(outcome=ResolutionOutcome.ORPHAN)
    if len(rows) > 1:
        return TenantResolution(outcome=ResolutionOutcome.AMBIGUOUS)

    tenant_id, connection_id = rows[0]
    return TenantResolution(
        outcome=ResolutionOutcome.RESOLVED, tenant_id=tenant_id, connection_id=connection_id
    )


def instagram_tenant_ids() -> tuple[UUID, ...]:
    """READ-ONLY: the tenants that have at least one Instagram connection — the set the
    intake worker's mention-sentiment sweep visits (QUA-152). Same narrow door and the
    same two granted columns (`tenant_id`, `platform`) as `resolve_external_account`;
    every per-tenant read after this goes back through `tenant_session`."""
    with webhook_worker_session() as session:
        return tuple(
            session.scalars(
                select(SocialConnection.tenant_id)
                .where(SocialConnection.platform == PLATFORM_INSTAGRAM)
                .distinct()
            ).all()
        )
