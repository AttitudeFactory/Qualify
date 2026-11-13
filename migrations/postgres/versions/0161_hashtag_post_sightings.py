"""hashtag_post_sightings: the views and the date of the public posts each hashtag of the
shared catalog was seen on (m-25026377, epic m-25026375 «Etiquetas que se están viendo»,
`docs/epica-etiquetas-publicaciones.md`)

Revision ID: 0161
Revises: 0160
Create Date: 2026-11-13

## Why this exists

The catalog (0023) knows how many times a tag was SEEN (`hashtags.seen_count`), not how
many people watched the posts that carried it nor when they were posted. «Popular» in
«Sugerir con IA» therefore meant «we saw it often», not «people are watching it now». The
referentes search and the reels reads already receive every post's views and date with
its caption, for credits already spent; this table keeps them, so «popular» can mean
views in the last 90 days — with no new paid call.

One row per (hashtag, network, post): `UNIQUE (hashtag_id, network, post_id)`, so seeing
the same post again (another phase, another search, a re-run) updates the row instead of
adding one — the window's sum can never count a post twice. Views are kept monotonic
(`GREATEST`, a later read of the same post has at least as many), the post date is
kept once known.

Provenance (house rule): `source` (`referentes` = a referentes search feed, `public_reels`
= a reels read, 0117), `source_ref` (the KIND of read only, `<network>:<kind>` —
`tiktok:hashtag`, `instagram:reels`, `instagram:public_reels`; a CHECK forbids anything
else, so a query's words never land here) and `parser_version` (which reader, at which
version, produced the numbers). The post itself — `(network, post_id)`, the provider's
id — is the source id; for a reels read it is also `public_reels`' natural key.

## Why NO tenant_id and NO RLS (the 0023 / 0117 shared-catalog exception)

Same reasoning as its parent table `hashtags` (0023) and as `public_reels` (0117): a public
post's view count and date are public data, the same for every tenant, and sharing them
is the point — one business's search makes «popular» better for all, and nobody pays
twice. The rule that keeps this safe (ADR 42 §6) holds here too: **no column names a
tenant, a brand or a user, nor records who searched or looked, nor what they typed**;
not even the post's author handle is stored — only the provider's post id, which is
public. A search's words (the operator's rubro, the city, the brand's own hashtag) are
attributable to a business, which is why `source_ref` is restricted to a kind.
`test_rls_policy_shape` only enumerates tables that own a `tenant_id`, so it does not
(and must not) see this one.

## Grants

`qualify_app` reads and writes it (the catalog's only writer, `qualify_api.hashtags`, runs
through `tenant_session`), never DELETE; `qualify_admin` reads it. `ON DELETE CASCADE`
from `hashtags`, like `hashtag_terms`.

**Downgrade** drops the table: what is lost is derived from reads already paid for; the
`hashtags` rows (0023) are untouched.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0161"
down_revision = "0160"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hashtag_post_sightings",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "hashtag_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("hashtags.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("network", sa.Text(), nullable=False),
        sa.Column("post_id", sa.Text(), nullable=False),
        # NULL = the provider did not say (never "posted now" / "zero views")
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("views", sa.BigInteger(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("parser_version", sa.Text(), nullable=False),
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
        sa.CheckConstraint("network IN ('tiktok','instagram')", name="ck_hashtag_sighting_network"),
        sa.CheckConstraint("post_id <> ''", name="ck_hashtag_sighting_post_id"),
        sa.CheckConstraint("views IS NULL OR views >= 0", name="ck_hashtag_sighting_views"),
        sa.CheckConstraint(
            "source IN ('referentes','public_reels')", name="ck_hashtag_sighting_source"
        ),
        sa.CheckConstraint("parser_version <> ''", name="ck_hashtag_sighting_provenance"),
        sa.CheckConstraint(
            "source_ref ~ '^(tiktok|instagram):[a-z_]{1,32}$'",
            name="ck_hashtag_sighting_source_ref",
        ),
        sa.UniqueConstraint("hashtag_id", "network", "post_id", name="uq_hashtag_sighting"),
    )
    # The 90-day window per tag: `WHERE hashtag_id = ANY(...) AND posted_at >= ...`.
    op.create_index(
        "ix_hashtag_sighting_recent", "hashtag_post_sightings", ["hashtag_id", "posted_at"]
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON hashtag_post_sightings TO qualify_app;")
    op.execute("GRANT SELECT ON hashtag_post_sightings TO qualify_admin;")


def downgrade() -> None:
    op.drop_index("ix_hashtag_sighting_recent", table_name="hashtag_post_sightings")
    op.drop_table("hashtag_post_sightings")
