"""Request-scoped identity for the HTTP surface (C1).

`Principal` is the type real authentication will eventually produce; routes and services
are written against it ONCE and do not change when the dev resolver below is replaced.
The resolver maps opaque bearer credentials from `QUALIFY_DEV_PRINCIPALS`
(`"<token>:<tenant_uuid>:<user_uuid>[,...]"`) — the client presents a CREDENTIAL, not an
identifier, which is the whole difference between authenticating and believing what you
are told. The env map is deliberately disposable: when real auth lands it is deleted in
one motion, and nothing was built on top of it that has to be unbuilt.

Two designs were rejected in refinement (backlog §C1) and stay rejected here: a token
table in Postgres (looks like the start of real auth and invites building on it) and a
`X-Tenant-Id` header into a ContextVar (the same authorization bypass as a body field,
with better thread hygiene).

This module never touches the database: resolution is env-only, `tenant_session` remains
the single road to tenant data, and RLS — not this file — is what decides visibility.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from fastapi import Header, HTTPException


@dataclass(frozen=True)
class Principal:
    """Who is calling, and for which tenant. Produced by authentication, consumed by
    routes; services keep receiving explicit UUIDs and never read ambient identity."""

    tenant_id: UUID
    user_id: UUID


def current_principal() -> Principal:
    """The seam routes depend on. Overridden at app startup (dev resolver) and in tests.
    Raising here keeps an unconfigured deployment from silently trusting every caller —
    the same pattern as `get_connect_service`."""
    raise NotImplementedError("principal dependency is not configured")


def parse_dev_principals(raw: str) -> dict[str, Principal]:
    """Parse `QUALIFY_DEV_PRINCIPALS`. Malformed entries raise at STARTUP — a typo in the
    operator's own map should fail the boot loudly, not surface as a mystery 401 later."""
    mapping: dict[str, Principal] = {}
    for chunk in raw.split(","):
        entry = chunk.strip()
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) != 3 or not all(parts):
            raise ValueError(
                "QUALIFY_DEV_PRINCIPALS entries must be <token>:<tenant_uuid>:<user_uuid>"
            )
        token, tenant_id, user_id = parts
        mapping[token] = Principal(tenant_id=UUID(tenant_id), user_id=UUID(user_id))
    return mapping


def build_dev_principal_dependency() -> Callable[..., Principal]:
    """Build the production override for `current_principal` from the environment.

    The map is parsed once, at app assembly. One 401 for every failure mode — missing
    header, malformed scheme, unknown token — for the same reason the callback's state
    check answers one 403: telling the caller WHICH check failed helps them forge the
    next attempt. 401 and not 409: "you are not authenticated" is a fact about the
    request, not about server state.
    """
    mapping = parse_dev_principals(os.environ.get("QUALIFY_DEV_PRINCIPALS", ""))

    def resolve(authorization: str | None = Header(default=None)) -> Principal:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="not authenticated")
        principal = mapping.get(authorization.removeprefix("Bearer ").strip())
        if principal is None:
            raise HTTPException(status_code=401, detail="not authenticated")
        return principal

    return resolve
