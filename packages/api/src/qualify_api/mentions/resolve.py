"""Cross-tenant resolution of a `mentions` webhook event's owning tenant (QUA-49).

## Why this needs a cross-tenant read at all

Meta's webhook payload names the mentioned account by its own `external_account_id`
(`entry[].id` — see `MENTIONS_ENTRY_ID_CITATION` in `qualify_shared.social.ig_shapes`).
It carries no `tenant_id`, because Meta has no concept of Qualify's tenants. So the very
first thing this receiver must do with an incoming event is answer "which tenant owns
this account", and it must answer that BEFORE any `tenant_session(tenant_id)` can be
opened — that door requires the tenant id as its own argument, which is exactly the
thing not yet known.

## Why `admin_session()` specifically, and why that is not a rule change

`qualify_shared.db.admin.admin_session` is documented as BYPASSRLS and reserved for
provisioning/seed, with "nothing on the request path may import it" stated as the
general rule. This module is a DELIBERATE, NARROW exception to that rule, not a
reinterpretation of it:

- It is the ONLY function in this codebase that does so on a request path.
- It is READ-ONLY — see `resolve_external_account` below, which issues exactly one
  `SELECT` and no `INSERT`/`UPDATE`/`DELETE`. `test_mentions_resolve.py`'s
  `test_resolution_never_writes` pins this with a real Postgres check, not just a
  reading of this docstring.
- It queries by `(platform, external_account_id)` ONLY — never accepts a `tenant_id`
  from the caller as a shortcut or a trust mechanism. A `tenant_id` supplied by an
  inbound request is not evidence of anything; the whole point of this function is to
  derive that value independently.
- The one existing precedent for `admin_session` on a request path
  (`auth/service.py`'s signup flow) is narrower than this: it uses `admin_session` only
  to WRITE a brand-new tenant under an identifier already minted by this process, and
  its own docstring states "no cross-tenant READ happens on the login path at all."
  This module is the first genuine cross-tenant SEARCH in the codebase — worth this
  much explanation for exactly that reason.
- Immediately after this function returns a `RESOLVED` outcome, every subsequent read
  MUST go back through `tenant_session(tenant_id)` using the tenant id this function
  just produced. Nothing downstream of this module is licensed to keep using
  `admin_session` — the exception is scoped to this one lookup, not inherited by
  whatever consumes its result.

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

from qualify_shared.db.admin import admin_session
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

    See this module's docstring for why `admin_session` is used here and nowhere
    else on a request path. Deliberately takes no `tenant_id` parameter — accepting
    one from a caller would defeat the entire point of this function, which is to
    derive that value independently rather than trust an assertion of it.
    """
    with admin_session() as session:
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
