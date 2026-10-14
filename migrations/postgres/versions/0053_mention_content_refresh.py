"""mentions: the app role may refresh a mention's CONTENT columns (QUA-152)

Revision ID: 0053
Revises: 0052
Create Date: 2026-10-13

"Actualizar" in the Dashboard de Menciones re-reads the visible mentions from their network
so a change shows up — a post or comment that had no likes and now has some, an edited
text, a link that was missing. Until now a mention was written once (0013 granted
`qualify_app` SELECT, INSERT only), so nothing could change after ingestion.

The grant is COLUMN-LEVEL and covers only what a fresh read can change: the content, the
counters, the link and the enrichment status. Identity stays immutable for the app role —
`id`, `tenant_id`, `connection_id`, `platform`, `external_account_id`, `media_id`,
`comment_id`, `received_at` — so the natural key (`uq_mention_natural_key`) and tenant
attribution can never be rewritten. RLS still scopes every UPDATE to the session's tenant.

`downgrade` revokes exactly these column grants; the data written meanwhile stays.
"""

from __future__ import annotations

from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None

_COLUMNS = (
    "caption",
    "text",
    "author_username",
    "media_type",
    "like_count",
    "content_posted_at",
    "permalink",
    "enrichment_status",
)


def upgrade() -> None:
    op.execute(f"GRANT UPDATE ({', '.join(_COLUMNS)}) ON mentions TO qualify_app;")


def downgrade() -> None:
    op.execute(f"REVOKE UPDATE ({', '.join(_COLUMNS)}) ON mentions FROM qualify_app;")
