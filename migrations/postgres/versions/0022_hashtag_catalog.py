"""hashtags + hashtag_terms: the shared hashtag catalog the referentes search reads and
feeds.

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-21

## Why this exists

The Brand Kit's referentes search (`Qualify/creator_discovery.py`) finds accounts with
the hashtags of the operator's own words and of the account's own posts, plus a hard-coded
table of 3 hashtags for each of 8 niches. A business that types its rubro with a typo, or
in a rubro the table does not know, gets a search built from garbage: nothing resolves the
typed words to the hashtags people actually use for that rubro, and nothing remembers what
a search already saw.

This migration adds the memory:

- `hashtags` — one row per hashtag ever seen or seeded, with what is known about it (kind:
  topic / place / generic / noise; niche; country) and how often it has been seen.
- `hashtag_terms` — the link the search needs: a rubro term as people write it
  ("peluqueria canina", folded) → the hashtags that mean it, weighted, with where the link
  came from (`taxonomy` seed, `observed` in a real search, `manual`, later `ai`).

## Why NO tenant_id and NO RLS

A hashtag is public data: `#cucutafood` means the same thing to every tenant, and the
searches that discover it cost credits. Sharing the catalog means one tenant's search
improves everyone's coverage and nobody pays twice for the same knowledge. Same reasoning
as `platform_apps` (R1: global reference data — forcing RLS would break the flow it
serves) and `ingestion.raw_payloads` (ADR 18: brand-agnostic by design). The tables hold
NO tenant data at all: no brand, no operator, no account handle. `test_rls_policy_shape`
only enumerates tables that own a `tenant_id` column, so it does not (and must not) see
these.

The cost of that choice is that `qualify_app` can write rows every tenant reads. The
repository (`qualify_api.hashtags`) is the only writer and validates every value; the
`CHECK`s below are the database's own floor under it (a tag is one lowercase token, never
`#tag`, never with whitespace).

## Notes

- `slug` is the accent-folded, alphanumeric-only spelling of `tag` (`Qualify/
  creator_discovery._slug`) — what typed text is compared against. It is stored, not
  computed, so it can carry a trigram index.
- `pg_trgm` is what makes a typo resolve: "peluqeria canina" is ~0.7 similar to
  "peluqueriacanina". `CREATE EXTENSION` runs as `qualify_owner` (the compose superuser).
  The downgrade does NOT drop the extension: other revisions may come to rely on it.
- `classified_by` records who decided `kind`/`niche` (`rule` = the code's own heuristics,
  `manual`, `ai`), so a later AI pass can re-decide what a rule decided and never
  overwrite what a person decided.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def _id_column() -> sa.Column:
    return sa.Column(
        "id",
        PGUUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        primary_key=True,
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

    op.create_table(
        "hashtags",
        _id_column(),
        sa.Column("tag", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False, server_default="unknown"),
        sa.Column("niche", sa.Text(), nullable=True),
        sa.Column("country_code", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("classified_by", sa.Text(), nullable=False, server_default="rule"),
        sa.Column("networks", ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("seen_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            r"tag <> '' AND tag = lower(tag) AND tag !~ '[#\s]'", name="ck_hashtag_tag_normalized"
        ),
        sa.CheckConstraint("slug <> ''", name="ck_hashtag_slug"),
        sa.CheckConstraint(
            "kind IN ('topic','place','generic','noise','unknown')", name="ck_hashtag_kind"
        ),
        sa.CheckConstraint(
            "source IN ('taxonomy','observed','manual','ai')", name="ck_hashtag_source"
        ),
        sa.CheckConstraint(
            "classified_by IN ('rule','manual','ai')", name="ck_hashtag_classified_by"
        ),
        sa.CheckConstraint(
            "country_code IS NULL OR country_code ~ '^[A-Z]{2}$'", name="ck_hashtag_country"
        ),
        sa.CheckConstraint("seen_count >= 0", name="ck_hashtag_seen_count"),
        sa.UniqueConstraint("tag", name="uq_hashtag_tag"),
    )
    op.execute("CREATE INDEX ix_hashtag_slug_trgm ON hashtags USING gin (slug gin_trgm_ops);")
    op.create_index("ix_hashtag_niche", "hashtags", ["niche"])
    op.execute("GRANT SELECT, INSERT, UPDATE ON hashtags TO qualify_app;")
    op.execute("GRANT SELECT ON hashtags TO qualify_admin;")

    op.create_table(
        "hashtag_terms",
        _id_column(),
        sa.Column("term_slug", sa.Text(), nullable=False),
        sa.Column("term", sa.Text(), nullable=False),
        sa.Column(
            "hashtag_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("hashtags.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("term_slug <> '' AND term <> ''", name="ck_hashtag_term_present"),
        sa.CheckConstraint("weight > 0", name="ck_hashtag_term_weight"),
        sa.CheckConstraint(
            "source IN ('taxonomy','observed','manual','ai')", name="ck_hashtag_term_source"
        ),
        sa.UniqueConstraint("term_slug", "hashtag_id", name="uq_hashtag_term"),
    )
    op.execute(
        "CREATE INDEX ix_hashtag_term_slug_trgm "
        "ON hashtag_terms USING gin (term_slug gin_trgm_ops);"
    )
    op.create_index("ix_hashtag_term_hashtag", "hashtag_terms", ["hashtag_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE ON hashtag_terms TO qualify_app;")
    op.execute("GRANT SELECT ON hashtag_terms TO qualify_admin;")


def downgrade() -> None:
    op.drop_index("ix_hashtag_term_hashtag", table_name="hashtag_terms")
    op.execute("DROP INDEX IF EXISTS ix_hashtag_term_slug_trgm;")
    op.drop_table("hashtag_terms")

    op.drop_index("ix_hashtag_niche", table_name="hashtags")
    op.execute("DROP INDEX IF EXISTS ix_hashtag_slug_trgm;")
    op.drop_table("hashtags")
