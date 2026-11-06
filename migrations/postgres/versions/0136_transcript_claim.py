"""public_reels: the transcript claim and the raw transcript answer; consumption_ledger:
one row per idempotency key (VE-04b, m-24921057; ADR 42, ADR 44)

Revision ID: 0136
Revises: 0135
Create Date: 2026-11-06

## Why

`public_reels` is global (0117): two businesses that follow the same account share its
reels, and each run transcribes the candidates that have none (`transcript_at IS NULL`).
`save_transcript` writes once, but the guard ran only AFTER the paid call: two businesses
transcribing the same reel at the same moment both paid ScrapeCreators, and the second
write was dropped. Founder, 2026-11-06: a DB guard so that never happens.

## `public_reels.transcript_lock_until` — the claim (same shape as 0117's
`reel_accounts.refresh_lock_until`)

`reel_store.claim_transcript` sets it with ONE `UPDATE … WHERE transcript_at IS NULL AND
(transcript_lock_until IS NULL OR transcript_lock_until <= :now) RETURNING`: the row lock
serializes two claims, the second re-checks the WHERE after the first commits and finds
it taken, so only the claimant calls the vendor. `save_transcript` clears it with the
transcript; a failed call clears it (`release_transcript`, only while it is still the
caller's value); a crashed worker's claim lapses by itself at `transcript_lock_until`.
A timestamp names no tenant, brand or user (0117's rule for global tables holds).

## `public_reels.transcript_payload_id` + `transcript_payload_fetched_at` — provenance

The raw transcript answer is kept in `vendor_payloads` (house rule: raw scrape payloads
are kept, so a newer `transcript_reader_version` can re-parse them without paying again).
Same pair as 0117's `source_payload_id` / `source_payload_fetched_at`: the FK (ON DELETE
SET NULL — `vendor_payloads` is upserted in place and TTL-deletable) and WHICH fetch of
it, with the same CHECK (an id needs its fetch time).

## `consumption_ledger.idempotency_key` — partial UNIQUE (WHERE NOT NULL)

The only writer that sets a key is the paid transcript row (`reels_transcript:<uuid4>`,
the gate's `vendor_usage_events.request_key`); Claude's rows (`claude_tools`) leave it
NULL, and no other writer exists. Measured 2026-11-06 on the local dev database: 0 rows,
0 keys, so no duplicate can block the index. The index spans tenants (an index ignores
RLS): the writers insert with `ON CONFLICT (idempotency_key) WHERE idempotency_key IS
NOT NULL DO NOTHING`, so a repeated key is dropped instead of failing the whole
`consumption_scope`; the keys are server-generated UUIDs, so one tenant can neither
guess nor collide with another's. No grant changes (`qualify_app` keeps 0105's).

## Grants

`qualify_app` already has table-level SELECT, INSERT, UPDATE on `public_reels` (0117),
which covers the new columns; `qualify_admin` keeps SELECT. No other role reads
`public_reels`.

**Downgrade** drops the index, the CHECK, the FK columns and the claim: a claim in flight
is forgotten (the write-once guard of `save_transcript` still stands) and the pointers to
the kept answers are lost (the `vendor_payloads` rows themselves stay).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0136"
down_revision = "0135"
branch_labels = None
depends_on = None

REELS = "public_reels"
LEDGER = "consumption_ledger"
PAYLOAD_CHECK = "ck_public_reel_transcript_payload"
LEDGER_KEY = "uq_consumption_ledger_idempotency_key"


def upgrade() -> None:
    op.add_column(REELS, sa.Column("transcript_lock_until", sa.DateTime(timezone=True)))
    op.add_column(
        REELS,
        sa.Column(
            "transcript_payload_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey(
                "vendor_payloads.id",
                name="fk_public_reel_transcript_payload",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
    )
    op.add_column(REELS, sa.Column("transcript_payload_fetched_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        PAYLOAD_CHECK,
        REELS,
        "transcript_payload_id IS NULL OR transcript_payload_fetched_at IS NOT NULL",
    )
    op.create_index(
        LEDGER_KEY,
        LEDGER,
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(LEDGER_KEY, table_name=LEDGER)
    op.drop_constraint(PAYLOAD_CHECK, REELS, type_="check")
    for column in (
        "transcript_payload_fetched_at",
        "transcript_payload_id",
        "transcript_lock_until",
    ):
        op.drop_column(REELS, column)
