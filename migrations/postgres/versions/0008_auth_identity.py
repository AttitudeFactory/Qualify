"""auth identity: link local users to their Supabase Auth user (QUA-66)

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-18

`users.auth_user_id` is the local end of the identity link: the uuid of the Supabase
Auth (GoTrue) user whose `app_metadata.tenant_id` points back at this row's tenant.
Decisions encoded here:

- **Nullable**, because seeded/pre-auth users legitimately have no login yet (the
  seed's inmobiliaria agents, for instance). A user without a login is a seat, not an
  error.
- **UNIQUE without `tenant_id`**, deliberately breaking the `UNIQUE(tenant_id, email)`
  pattern of 0001: one identity-provider credential maps to exactly ONE local user —
  which, via `users.tenant_id`, is exactly one tenant. That is the founder's
  `1 login = 1 tenant = 1 negocio` ruling (2026-08-16) expressed as a constraint, and
  it is what makes credential→tenant resolution deterministic (a global uniqueness the
  cross-tenant email lookup could never provide). Postgres UNIQUE ignores NULLs, so
  login-less users don't collide.
- No FK, obviously — the other end lives in Supabase, not in this database. Supabase
  is identity-only (founder ruling 2026-08-18): no business data crosses over.
- RLS is untouched: 0001 already enabled/forced RLS on `users`; a new column inherits
  the row policy. The login path reads this column through `tenant_session(tenant_id)`
  with the tenant taken from the verified `app_metadata` stamp, never the other way
  around.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("auth_user_id", PGUUID(as_uuid=True), nullable=True))
    op.create_unique_constraint("uq_users_auth_user_id", "users", ["auth_user_id"])


def downgrade() -> None:
    op.drop_constraint("uq_users_auth_user_id", "users", type_="unique")
    op.drop_column("users", "auth_user_id")
