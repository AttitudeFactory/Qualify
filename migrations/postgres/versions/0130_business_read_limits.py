"""business_read_limits: businesses whose ScrapeCreators reads skip Qualify's caps, set from
the «Alta de cliente» in Meegle (m-24956180)

Revision ID: 0130
Revises: 0129
Create Date: 2026-11-05

Founder decision (Herwin, 2026-11-05): Bianki must have unlimited Creators revisions, and
the switch is turned from Meegle, not from an environment variable. The Alta item gains an
optional select «Lecturas sin límite» (Sí / No), read with «Plan» / «Paquete» when
«Datos» or «Plan ampliado» is completed (`qualify_api.meegle.plan_request`).

- `business_read_limits` — one row per business, the state in force. `uncapped_reads`
  true = the metered gate books every credit as always but does not check the business's
  cap (ADR 42 §2.4, 150/600) and the Creators module skips its own budget (50/300). No row
  = capped, today's behaviour. Provenance of the value: `meegle_work_item_id` (the Alta),
  `set_by` (who completed the node, `meegle:<email>`), `event_key` (the Meegle event) and
  `updated_at`. Standard tenant RLS (R7, NULLIF kept); `qualify_app` SELECT only — the
  gate reads it inside `tenant_session`, a business can never uncap itself —
  `qualify_admin` writes it (the Meegle handler, through `admin_session`).
- `signup_invites.alta_uncapped_reads` — the choice of an Alta that is not registered
  yet, applied by `apply_on_registration` with the plan (same posture as the 0097
  columns: global, `qualify_admin` only through the existing table grant). NULL = not set.

Downgrade drops both: every business goes back to the caps (two-way door).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0130"
down_revision = "0129"
branch_labels = None
depends_on = None

_TABLE = "business_read_limits"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column(
            "tenant_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("uncapped_reads", sa.Boolean(), nullable=False),
        sa.Column("meegle_work_item_id", sa.BigInteger(), nullable=True),
        sa.Column("set_by", sa.Text(), nullable=False),
        sa.Column("event_key", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("btrim(set_by) <> ''", name="ck_business_read_limits_who"),
    )
    op.execute(f"GRANT SELECT ON {_TABLE} TO qualify_app;")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {_TABLE} TO qualify_admin;")
    # NULLIF is load-bearing (R7) — see 0001's `_enable_rls`.
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {_TABLE}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )

    op.add_column("signup_invites", sa.Column("alta_uncapped_reads", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("signup_invites", "alta_uncapped_reads")
    op.drop_table(_TABLE)
