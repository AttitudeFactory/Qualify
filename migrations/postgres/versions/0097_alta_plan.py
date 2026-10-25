"""signup_invites: the plan and pack an «Alta de cliente» asked for, and the business it
became (m-24852131)

Revision ID: 0097
Revises: 0096
Create Date: 2026-10-26

The Alta item in Meegle now carries «Plan» (Básico / Plus / Pro; empty = Básico),
«Paquete» (one of the fixed 90-day packs) and «Motivo». When «Datos» is completed there
is no `tenant_id` yet — the business only exists once `register_business` runs — so the
choice rides on the invite row and is applied at registration, through the same team
write paths as the CLI (`plans.service.set_plan`, m-24852145; `plans.pack_service.add_pack`,
m-24852129). Columns:

- `alta_plan_code`, `alta_pack_code` — catalog codes (`basico`, `videos_2`…), validated in
  code against `planes-v1` / `precios-planes-v1` before the invite is created. No CHECK on
  purpose: the catalogs are versioned in code, and a new plan must not need a migration.
- `alta_reason`, `alta_requested_by` — the «Motivo» and the Meegle user who completed
  «Datos» (provenance of the assignment).
- `alta_event_key` — the Meegle event id that asked for it: the idempotency keys of the
  assignment and the pack derive from it (`meegle:<event>:plan` / `:pack`).
- `registered_tenant_id` — the business the invite became, stamped in the same
  transaction that spends it. The «Plan ampliado» node of an already registered Alta finds
  its business through it (never through the item's editable «Tenant» field). Backfilled
  for spent invites whose email belongs to exactly one business.

Same posture as 0063/0064: global, no RLS, `qualify_admin` only (the existing table grant
covers the new columns). Downgrade drops the columns: a plan already applied stays in
`subscription_plan_assignments`; only a choice still waiting for its registration is lost.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0097"
down_revision = "0096"
branch_labels = None
depends_on = None

_TEXT_COLUMNS = (
    "alta_plan_code",
    "alta_pack_code",
    "alta_reason",
    "alta_requested_by",
    "alta_event_key",
)


def upgrade() -> None:
    for name in _TEXT_COLUMNS:
        op.add_column("signup_invites", sa.Column(name, sa.Text(), nullable=True))
    op.add_column(
        "signup_invites",
        sa.Column(
            "registered_tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", name="fk_signup_invites_registered_tenant"),
            nullable=True,
        ),
    )
    op.execute(
        """
        UPDATE signup_invites si
           SET registered_tenant_id = owner.tenant_id
          FROM (
                SELECT lower(email) AS email, (array_agg(DISTINCT tenant_id))[1] AS tenant_id
                  FROM users
                 GROUP BY lower(email)
                HAVING count(DISTINCT tenant_id) = 1
               ) AS owner
         WHERE si.used_at IS NOT NULL
           AND si.registered_tenant_id IS NULL
           AND lower(si.email) = owner.email
        """
    )


def downgrade() -> None:
    op.drop_column("signup_invites", "registered_tenant_id")
    for name in reversed(_TEXT_COLUMNS):
        op.drop_column("signup_invites", name)
