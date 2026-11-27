"""clip_avatar_failure_mails: the email of a Clip's AI part that failed (m-25142979)

Revision ID: 0193
Revises: 0191
Create Date: 2026-11-27

0192 is reserved for m-25129386: whichever of the two reaches `main` second moves its
`down_revision` onto the other (`just migration-guard`).

## Why this exists

A «parte con IA» of a Clip that fails keeps the Clip waiting 72 h for its owner's choice
(m-25129407: «Intentar de nuevo», «Cambiar», «Hacerla nueva» or «Quitar»). Its owner now
gets ONE email per Clip and pass, as with a failed avatar (m-25120319, migration 0186) —
through the same outbox, sender and Resend key, so this revision only widens 0186's table:

- `kind` gains `ai_part_failed` (the email's own words, `mail.clip_ai_part`).
- `block_revisions` (nullable; set — and required — only for `ai_part_failed`): each
  part's revision as it failed. An avatar's failure is stamped on the Clip's plan
  (`failed_at`), but an AI part's wait writes nothing on the Clip, so «this failure was
  already mailed» is the pair (part, revision): «Intentar de nuevo», «Cambiar», «Hacerla
  nueva» and another mode all make the part again at a NEW revision, so a part that
  fails again is a new failure and one more email, once; re-reading a waiting Clip on
  every pass, or a restarted worker, finds its pair already in a row and stages nothing.
  A timestamp could not say it: a part's «when it moved» (`updated_at`, its refund, its
  job's end) can move after the pass that saw it failed.

No new table, policy or grant: 0186's RLS (ENABLE + FORCE + the `NULLIF` policy) and
grants cover the new column. `failed_at` stays the identity's stamp (the moment of the
pass that saw the parts failed), `UNIQUE (clip_id, kind, failed_at)` as before.

**Downgrade** deletes the `ai_part_failed` rows (pending AI part emails are lost; a
re-upgrade stages them again on the Clip's next waiting pass only while it still waits),
drops the column and restores 0186's CHECK.
"""

from __future__ import annotations

from alembic import op

revision = "0193"
down_revision = "0191"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE clip_avatar_failure_mails ADD COLUMN block_revisions integer[];
    ALTER TABLE clip_avatar_failure_mails
        DROP CONSTRAINT clip_avatar_failure_mails_kind_check;
    ALTER TABLE clip_avatar_failure_mails
        ADD CONSTRAINT clip_avatar_failure_mails_kind_check
        CHECK(kind IN ('block_failed','clip_too_long','ai_part_failed'));
    ALTER TABLE clip_avatar_failure_mails
        ADD CONSTRAINT ck_clip_avatar_failure_mail_revisions CHECK(
            (kind = 'ai_part_failed') = (block_revisions IS NOT NULL)
            AND (block_revisions IS NULL OR (
                cardinality(block_revisions) = cardinality(slots)
                AND array_position(block_revisions, NULL) IS NULL)));
    """)


def downgrade() -> None:
    op.execute("""
    DELETE FROM clip_avatar_failure_mails WHERE kind = 'ai_part_failed';
    ALTER TABLE clip_avatar_failure_mails
        DROP CONSTRAINT ck_clip_avatar_failure_mail_revisions;
    ALTER TABLE clip_avatar_failure_mails
        DROP CONSTRAINT clip_avatar_failure_mails_kind_check;
    ALTER TABLE clip_avatar_failure_mails
        ADD CONSTRAINT clip_avatar_failure_mails_kind_check
        CHECK(kind IN ('block_failed','clip_too_long'));
    ALTER TABLE clip_avatar_failure_mails DROP COLUMN block_revisions;
    """)
