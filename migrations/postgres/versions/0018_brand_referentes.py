"""brand_discovery_phases + brand_discovered_accounts + brand_account_labels: the Brand
Kit's referentes search (`Qualify/creator_discovery.py`, phases sector → national →
local) and the operator's referente/competencia/detractor sort, persisted per tenant

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-16

Until now the phases lived in `Qualify/fixtures/discovery_cache.json` and the sort lived
only in the Reflex session — a reload lost it. What is persisted here is the RESULT of
the referentes algorithm and the human decision over it. What is deliberately NOT: the
brand's own profile read (that belongs to Conexiones), the vendor profile facts of the
accounts found (`discovery_profiles.json` stays the store for those) and raw vendor
payloads.

**Recomputable by design — `algorithm_version` + `seed`.** Every phase row is stamped
with `creator_discovery.PHASED_PLAN_VERSION` (a test fingerprints the algorithm so it
cannot change without a bump) and carries the full seed it was computed from, so a
newer algorithm can recompute a brand's phases without the operator walking the wizard
again. A recompute never edits a row: it inserts the new phase and stamps the old one
`superseded_at`, so old and new versions can be compared.

`seed` shape (JSONB, validated in the repository, not here): `{handle, niches, terms,
related, country_code, city, hashtags: [{"tag": ..., "origin": ...}]}`. Hashtags carry
their ORIGIN (`profile` today; a future hashtag discovery or manual entry adds its own)
so a recompute can rebuild exactly the part of the seed a source changed.

**One current phase per (brand, phase_key)** — partial UNIQUE index over the rows with
`superseded_at IS NULL`. `phase_key` is free text on purpose (no CHECK list): a new
phase (e.g. a hashtag phase) must not need a migration.

**Labels are keyed by the account, not by the phase.** `brand_account_labels` is
`(brand_id, network, handle)`, so a recompute that drops or re-ranks an account never
loses what the operator decided about it.

**One handle normalization.** The code had two (`_normalize_handle` vs `_slug`); here
the key is the username lowercased with no leading "@", enforced by CHECK so the same
account can never be stored twice under two spellings.

Grants: phases get UPDATE (only `superseded_at` is ever written after insert — repository
discipline); accounts are append-only; labels are the operator's mutable choice
(re-sort = UPDATE, Deshacer = DELETE). RLS on all three, same NULLIF policy as 0001.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def _enable_tenant_rls(table: str, *, key_column: str = "tenant_id") -> None:
    # NULLIF is load-bearing (R7) — see 0001's `_enable_rls`. Duplicated per-migration
    # rather than shared, same as every prior revision in this chain does.
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
            USING ({key_column} = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK ({key_column} = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def _id_column() -> sa.Column:
    return sa.Column(
        "id",
        PGUUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        primary_key=True,
    )


def _handle_checks(table: str) -> list[sa.CheckConstraint]:
    return [
        sa.CheckConstraint("network <> ''", name=f"ck_{table}_network"),
        sa.CheckConstraint(
            "handle <> '' AND handle = lower(handle) AND left(handle, 1) <> '@'",
            name=f"ck_{table}_handle_normalized",
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "brand_discovery_phases",
        _id_column(),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("brand_id", PGUUID(as_uuid=True), sa.ForeignKey("brands.id"), nullable=False),
        sa.Column("phase_key", sa.Text(), nullable=False),
        sa.Column("algorithm_version", sa.Integer(), nullable=False),
        sa.Column("seed_signature", sa.Text(), nullable=False),
        sa.Column("seed", JSONB(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("queries", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("errors", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source", sa.Text(), nullable=False, server_default="scrapecreators"),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("phase_key <> ''", name="ck_discovery_phase_key"),
        sa.CheckConstraint("algorithm_version > 0", name="ck_discovery_phase_version"),
        sa.CheckConstraint("credits >= 0", name="ck_discovery_phase_credits"),
    )
    op.create_index("ix_discovery_phase_tenant", "brand_discovery_phases", ["tenant_id"])
    op.create_index(
        "ix_discovery_phase_lookup",
        "brand_discovery_phases",
        ["brand_id", "phase_key", "seed_signature"],
    )
    # Anti-drift target for brand_discovered_accounts' composite FK (R2 discipline).
    op.create_unique_constraint(
        "uq_discovery_phase_id_tenant", "brand_discovery_phases", ["id", "tenant_id"]
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_discovery_phase_current
            ON brand_discovery_phases (brand_id, phase_key)
            WHERE superseded_at IS NULL;
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON brand_discovery_phases TO qualify_app;")
    op.execute("GRANT SELECT ON brand_discovery_phases TO qualify_admin;")
    _enable_tenant_rls("brand_discovery_phases")

    op.create_table(
        "brand_discovered_accounts",
        _id_column(),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("phase_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("network", sa.Text(), nullable=False),
        sa.Column("handle", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("followers", sa.BigInteger(), nullable=True),
        sa.Column("profile_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("avatar_url", sa.Text(), nullable=False, server_default=""),
        # The card exactly as the wizard rendered it (`creator_discovery.account_card`).
        sa.Column("card", JSONB(), nullable=False),
        # Which searches surfaced the account (`Candidate.sources`) — how a future hashtag
        # discovery's contribution to referentes gets measured.
        sa.Column("found_by", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.CheckConstraint("rank >= 0", name="ck_discovered_account_rank"),
        *_handle_checks("discovered_account"),
        sa.ForeignKeyConstraint(
            ["phase_id", "tenant_id"],
            ["brand_discovery_phases.id", "brand_discovery_phases.tenant_id"],
            name="fk_discovered_account_phase_tenant",
        ),
        sa.UniqueConstraint("phase_id", "network", "handle", name="uq_discovered_account"),
        sa.UniqueConstraint("phase_id", "rank", name="uq_discovered_account_rank"),
    )
    op.create_index("ix_discovered_account_tenant", "brand_discovered_accounts", ["tenant_id"])
    op.execute("GRANT SELECT, INSERT ON brand_discovered_accounts TO qualify_app;")
    op.execute("GRANT SELECT ON brand_discovered_accounts TO qualify_admin;")
    _enable_tenant_rls("brand_discovered_accounts")

    op.create_table(
        "brand_account_labels",
        _id_column(),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("brand_id", PGUUID(as_uuid=True), sa.ForeignKey("brands.id"), nullable=False),
        sa.Column("network", sa.Text(), nullable=False),
        sa.Column("handle", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("labeled_by", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "labeled_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "label IN ('referente','competencia','detractor')", name="ck_account_label"
        ),
        *_handle_checks("account_label"),
        sa.UniqueConstraint("brand_id", "network", "handle", name="uq_account_label"),
    )
    op.create_index("ix_account_label_tenant", "brand_account_labels", ["tenant_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON brand_account_labels TO qualify_app;")
    op.execute("GRANT SELECT ON brand_account_labels TO qualify_admin;")
    _enable_tenant_rls("brand_account_labels")


def downgrade() -> None:
    op.drop_index("ix_account_label_tenant", table_name="brand_account_labels")
    op.drop_table("brand_account_labels")

    op.drop_index("ix_discovered_account_tenant", table_name="brand_discovered_accounts")
    op.drop_table("brand_discovered_accounts")

    op.execute("DROP INDEX IF EXISTS uq_discovery_phase_current;")
    op.drop_constraint("uq_discovery_phase_id_tenant", "brand_discovery_phases", type_="unique")
    op.drop_index("ix_discovery_phase_lookup", table_name="brand_discovery_phases")
    op.drop_index("ix_discovery_phase_tenant", table_name="brand_discovery_phases")
    op.drop_table("brand_discovery_phases")
