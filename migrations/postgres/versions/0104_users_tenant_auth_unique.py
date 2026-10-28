"""Allow a single login (auth_user_id) to belong to multiple tenants (m-24849188).

Changes the unique constraint on `users` table from global UNIQUE(auth_user_id)
(uq_users_auth_user_id, introduced in 0008) to UNIQUE(tenant_id, auth_user_id)
(uq_users_tenant_auth_user_id), supporting multi-tenant ownership for a single
login (ADR 43 §2.1).
"""

from __future__ import annotations

from alembic import op

revision = "0104"
down_revision = "0103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_users_auth_user_id", "users", type_="unique")
    op.create_unique_constraint(
        "uq_users_tenant_auth_user_id", "users", ["tenant_id", "auth_user_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_users_tenant_auth_user_id", "users", type_="unique")
    op.create_unique_constraint("uq_users_auth_user_id", "users", ["auth_user_id"])
