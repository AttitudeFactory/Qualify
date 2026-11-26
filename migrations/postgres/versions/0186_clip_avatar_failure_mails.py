"""clip_avatar_failure_mails: one email per Clip and pass when avatars need the owner (m-25120319)

Revision ID: 0186
Revises: 0185
Create Date: 2026-11-26

Epic m-25026566. When an avatar block of a Clip fails — or comes out but makes the Clip
pass 60 s (`clip_too_long`) — the Clip waits 72 h for its owner (m-25119867, ADR 50 §11
P2): the worker's pass that sees it stamps `failed_at` on the Clip's plan, in a new brief
written under the run's fence. In THAT same transaction it now stages ONE row here for
everything that pass stamped, and a sender in the creative worker's mail chore emails the
Clip's author through the existing Resend sender.

Why a table (and not an existing outbox): the two mail outboxes on `main` are shaped for
their own mail — `content_draft_warning_batches` is keyed by brand/recipient/retention
stage and `final_mail_batches` by user and day — and the stamp lives inside a JSON brief,
so nothing else can say «this failure was already mailed» across worker restarts.

- Identity (Deivid, 2026-11-26: one email per Clip and pass): `(clip_id, kind,
  failed_at)` — `UNIQUE`, staged with `ON CONFLICT DO NOTHING`. Every block a pass stamps
  carries that pass's `failed_at`, so two avatars failing together are ONE row (`slots`,
  `block_ids`). A retry clears the plan's `failed_at`; a failure seen on a later pass gets
  a new stamp, a new row and one more email. Re-reading the state or restarting the
  worker never stages a second row for the same stamp.
- `kind`: `block_failed` (an avatar could not be made) or `clip_too_long` (it was made
  but the Clip passes 60 s with it) — each has its own words.
- `idempotency_key` (`UNIQUE`) is sent as Resend's `Idempotency-Key`; the mail is frozen
  in `payload` before the first attempt and resent verbatim; after 23 h of uncertain
  attempts the row is closed (`closed_reason='uncertain'`) instead of risking a double.
- `closed_reason`: `resolved` (the owner retried or removed every avatar of the row, or
  the Clip moved on, before it was sent), `switched_off`, `no_recipient`, `rejected`,
  `uncertain`.
- Provenance: `failure_codes` (each block's `failure_reason`, or `clip_too_long`) and
  `source_version` (the template's version).
- No email address, name or script is stored outside `payload` (the frozen mail).
- `block_ids` is an array, so it carries no foreign key; the row goes with its Clip
  (`ON DELETE CASCADE`) and the sender re-reads every block before each attempt.

Tenant table: `tenant_id` + RLS ENABLE/FORCE + the NULLIF policy; `qualify_app` reads and
writes (the stage runs inside the Clip's `tenant_unit_of_work`, the sender through
`tenant_session`), `qualify_admin` reads (tenant discovery for the sender).

**Downgrade** drops the table: pending emails are lost and a re-upgrade does not stage
them again (their `failed_at` is already on the plan) — nothing is sent twice.
"""

from __future__ import annotations

from alembic import op

revision = "0186"
down_revision = "0185"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE clip_avatar_failure_mails (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        clip_id uuid NOT NULL,
        kind text NOT NULL CHECK(kind IN ('block_failed','clip_too_long')),
        failed_at timestamptz NOT NULL,
        slots smallint[] NOT NULL,
        block_ids uuid[] NOT NULL,
        failure_codes text[] NOT NULL,
        user_id uuid NOT NULL,
        idempotency_key text NOT NULL CHECK(idempotency_key <> ''),
        source_version text NOT NULL CHECK(source_version <> ''),
        payload jsonb,
        lease_token uuid,
        lease_until timestamptz,
        first_attempt_at timestamptz,
        sent_at timestamptz,
        provider_id text,
        closed_at timestamptz,
        closed_reason text CHECK(closed_reason IN
            ('resolved','switched_off','no_recipient','rejected','uncertain')),
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_clip_avatar_failure_mail UNIQUE(clip_id, kind, failed_at),
        CONSTRAINT uq_clip_avatar_failure_mail_key UNIQUE(idempotency_key),
        CONSTRAINT ck_clip_avatar_failure_mail_blocks CHECK(
            cardinality(slots) BETWEEN 1 AND 6
            AND cardinality(block_ids) = cardinality(slots)
            AND cardinality(failure_codes) = cardinality(slots)
            AND slots <@ ARRAY[1,2,3,4,5,6]::smallint[]),
        CONSTRAINT ck_clip_avatar_failure_mail_closed
            CHECK((closed_at IS NULL) = (closed_reason IS NULL)),
        CONSTRAINT ck_clip_avatar_failure_mail_attempt
            CHECK(first_attempt_at IS NULL OR payload IS NOT NULL),
        FOREIGN KEY(clip_id, tenant_id) REFERENCES content_drafts(id, tenant_id)
            ON DELETE CASCADE
    );
    CREATE INDEX ix_clip_avatar_failure_mails_pending
        ON clip_avatar_failure_mails(tenant_id, created_at)
        WHERE sent_at IS NULL AND closed_at IS NULL;
    ALTER TABLE clip_avatar_failure_mails ENABLE ROW LEVEL SECURITY;
    ALTER TABLE clip_avatar_failure_mails FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON clip_avatar_failure_mails
      USING(tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid)
      WITH CHECK(tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid);
    GRANT SELECT,INSERT,UPDATE ON clip_avatar_failure_mails TO qualify_app;
    GRANT SELECT ON clip_avatar_failure_mails TO qualify_admin;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE clip_avatar_failure_mails")
