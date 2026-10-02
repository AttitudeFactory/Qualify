"""creators: the shared pool of scraped creators and the vendor's answers

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-01

§ request 2026-10-01: "primero busca en la db las cuentas que estaban ya scrapeadas y
luego, si no hay coincidencias o hacen falta, va al scraper". Until now every tenant's
referentes search started from zero: phases and profile reads were kept per tenant, so
the search tenant A paid for yesterday taught tenant B nothing today. A TikTok or
Instagram account is public data, like a hashtag (0023): what one search learned about
it serves every tenant. Three tables, none with a `tenant_id` and none with RLS —
the same rule 0023 states (global reference data; `test_rls_policy_shape` only
enumerates tables that own a `tenant_id`, so it must not see these).

## vendor_payloads

The vendor's answer to one call, as it came (`payload`), keyed by endpoint and
parameters, with a time to live: 7 days for a search page or a Google query, 30 for a
profile read (the vendor's own cache keeps profiles that long), a 404 kept too
(`status`). The search's HTTP layer (`creator_discovery._get_retry`) asks here first:
the same query inside its TTL is served from this table — zero credits, no network —
and only what is missing goes to the vendor. The raw answer is kept whole, so a field
the parsers did not read yet can be read later without paying again (the raw-payload
rule of Fase 1's ingestion, ADR 18, applied here).

## creators

One row per public account, as last seen: what the searches know (size, bio, link,
category, related accounts, the hashtags it uses, how many of its videos carried the
AI label...), `read_at` when a profile read backed it, `missing` for a handle that
does not exist. Every account a phase saw lands here, not only the eight it showed.

## creator_sightings

Which search surfaced which account: `(network, handle, kind, term)` plus the country
and city the phase ran for — the index that answers "qué cuentas aparecieron para
`programacion`" tomorrow, for anyone.

What stays private, per tenant: the sort (`brand_account_labels`), the phases a brand
ran (`brand_discovery_phases`), the brand's own account (`creator_profile_cache`) and
its growth history (`creator_reads`).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None

_HANDLE_CHECK = "handle <> '' AND handle = lower(handle) AND left(handle, 1) <> '@'"
_NETWORK_CHECK = "network IN ('tiktok','instagram')"


def _id() -> sa.Column:
    return sa.Column(
        "id", PGUUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True
    )


def _now(name: str) -> sa.Column:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "vendor_payloads",
        _id(),
        sa.Column("vendor", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("params_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Integer(), server_default="200", nullable=False),
        sa.Column("payload", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("credits_charged", sa.Integer(), server_default="0", nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hits", sa.Integer(), server_default="0", nullable=False),
        _now("updated_at"),
        sa.UniqueConstraint("vendor", "path", "params_key", name="uq_vendor_payload"),
        sa.CheckConstraint("vendor <> '' AND path <> ''", name="ck_vendor_payload_key"),
        sa.CheckConstraint("expires_at > fetched_at", name="ck_vendor_payload_ttl"),
    )
    op.create_index("ix_vendor_payloads_expires", "vendor_payloads", ["expires_at"])
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON vendor_payloads TO qualify_app;")
    op.execute("GRANT SELECT ON vendor_payloads TO qualify_admin;")

    op.create_table(
        "creators",
        _id(),
        sa.Column("network", sa.Text(), nullable=False),
        sa.Column("handle", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), server_default="", nullable=False),
        sa.Column("bio", sa.Text(), server_default="", nullable=False),
        sa.Column("external_url", sa.Text(), server_default="", nullable=False),
        sa.Column("profile_url", sa.Text(), server_default="", nullable=False),
        sa.Column("avatar_url", sa.Text(), server_default="", nullable=False),
        sa.Column("category", sa.Text(), server_default="", nullable=False),
        sa.Column("country_code", sa.Text(), server_default="", nullable=False),
        sa.Column("followers", sa.BigInteger(), nullable=True),
        sa.Column("total_likes", sa.BigInteger(), nullable=True),
        sa.Column("is_private", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("missing", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("related", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("hashtags", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("posts_seen", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ai_posts_seen", sa.Integer(), server_default="0", nullable=False),
        sa.Column("likes_seen", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("comments_seen", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("views_seen", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
        _now("first_seen_at"),
        _now("updated_at"),
        sa.UniqueConstraint("network", "handle", name="uq_creator"),
        sa.CheckConstraint(_NETWORK_CHECK, name="ck_creator_network"),
        sa.CheckConstraint(_HANDLE_CHECK, name="ck_creator_handle_normalized"),
        sa.CheckConstraint("posts_seen >= ai_posts_seen", name="ck_creator_ai_posts"),
    )
    op.create_index("ix_creators_seen", "creators", ["seen_at"])
    op.create_index("ix_creators_followers", "creators", ["network", "followers"])
    op.execute("GRANT SELECT, INSERT, UPDATE ON creators TO qualify_app;")
    op.execute("GRANT SELECT ON creators TO qualify_admin;")

    op.create_table(
        "creator_sightings",
        _id(),
        sa.Column("network", sa.Text(), nullable=False),
        sa.Column("handle", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("term", sa.Text(), nullable=False),
        sa.Column("country_code", sa.Text(), server_default="", nullable=False),
        sa.Column("city_slug", sa.Text(), server_default="", nullable=False),
        sa.Column("times", sa.Integer(), server_default="1", nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
        _now("first_seen_at"),
        sa.UniqueConstraint(
            "network", "handle", "kind", "term", "country_code", "city_slug", name="uq_sighting"
        ),
        sa.CheckConstraint(_NETWORK_CHECK, name="ck_sighting_network"),
        sa.CheckConstraint(_HANDLE_CHECK, name="ck_sighting_handle_normalized"),
        sa.CheckConstraint(
            "kind IN ('keyword','hashtag','google','related','mirror','manual','profile')",
            name="ck_sighting_kind",
        ),
    )
    op.create_index("ix_sightings_term", "creator_sightings", ["kind", "term", "seen_at"])
    op.create_index("ix_sightings_account", "creator_sightings", ["network", "handle"])
    op.execute("GRANT SELECT, INSERT, UPDATE ON creator_sightings TO qualify_app;")
    op.execute("GRANT SELECT ON creator_sightings TO qualify_admin;")


def downgrade() -> None:
    op.drop_index("ix_sightings_account", table_name="creator_sightings")
    op.drop_index("ix_sightings_term", table_name="creator_sightings")
    op.drop_table("creator_sightings")
    op.drop_index("ix_creators_followers", table_name="creators")
    op.drop_index("ix_creators_seen", table_name="creators")
    op.drop_table("creators")
    op.drop_index("ix_vendor_payloads_expires", table_name="vendor_payloads")
    op.drop_table("vendor_payloads")
