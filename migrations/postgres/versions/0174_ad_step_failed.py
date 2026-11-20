"""ad_promotion_steps: a creation step can fail and be claimed again (m-25077974)

Revision ID: 0174
Revises: 0173
Create Date: 2026-11-20

## Why this exists

A creation step had two states: `in_flight` (claimed, the POST may be on its way) and
`completed`. A definite Meta rejection (4xx) after the claim, or a local check that refused
the write before any POST (the five-minute receipt expiring mid-creation), left the step
`in_flight` forever: recovery found nothing in Meta and the promotion could never finish.

- New state `failed` (no `meta_id`): Meta created nothing for this step. Only a definite
  answer or a refusal before the POST leads here; a network error or timeout keeps the step
  `in_flight`, recoverable by enumerating the account (no duplicate campaigns).
- The immutability trigger now allows exactly: `in_flight` → `completed` (sets `meta_id`),
  `in_flight` → `failed`, and `failed` → `in_flight` with a new `claim_token` (the owner's
  retry). Payload, resource and promotion stay immutable; `completed` stays final.

No new table: RLS and grants are unchanged (0114).

**Downgrade** deletes the `failed` steps (nothing exists in Meta for them; the promotion's
next attempt claims the step again) and restores the two-state check and trigger.
"""

from alembic import op

revision = "0174"
down_revision = "0173"
branch_labels = None
depends_on = None

LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"

TRIGGER = """
CREATE OR REPLACE FUNCTION ad_promotion_steps_immutable() RETURNS trigger AS $$
BEGIN
  IF OLD.state = 'completed' OR NOT (
    (OLD.state = 'in_flight' AND NEW.state = 'completed'
      AND (to_jsonb(NEW) - ARRAY['state','meta_id'])
        IS NOT DISTINCT FROM (to_jsonb(OLD) - ARRAY['state','meta_id']))
    OR (OLD.state = 'in_flight' AND NEW.state = 'failed'
      AND (to_jsonb(NEW) - ARRAY['state'])
        IS NOT DISTINCT FROM (to_jsonb(OLD) - ARRAY['state']))
    OR (OLD.state = 'failed' AND NEW.state = 'in_flight'
      AND (to_jsonb(NEW) - ARRAY['state','claim_token'])
        IS NOT DISTINCT FROM (to_jsonb(OLD) - ARRAY['state','claim_token']))
  ) THEN
    RAISE EXCEPTION 'creation intent cannot be replaced or reset'
      USING ERRCODE='check_violation';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;
"""

TRIGGER_0114 = """
CREATE OR REPLACE FUNCTION ad_promotion_steps_immutable() RETURNS trigger AS $$
BEGIN
  IF OLD.state = 'completed' OR
    (to_jsonb(NEW) - ARRAY['state','meta_id']) IS DISTINCT FROM
    (to_jsonb(OLD) - ARRAY['state','meta_id']) OR NEW.state <> 'completed' THEN
    RAISE EXCEPTION 'creation intent cannot be replaced or reset'
      USING ERRCODE='check_violation';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.execute(LOCK_TIMEOUT)
    op.drop_constraint("ck_ad_step_state", "ad_promotion_steps", type_="check")
    op.create_check_constraint(
        "ck_ad_step_state",
        "ad_promotion_steps",
        "(state IN ('in_flight','failed') AND meta_id IS NULL) OR "
        "(state = 'completed' AND meta_id IS NOT NULL AND meta_id ~ '^[0-9]+$')",
    )
    op.execute(TRIGGER)


def downgrade() -> None:
    op.execute(LOCK_TIMEOUT)
    op.execute(TRIGGER_0114)
    op.execute("DELETE FROM ad_promotion_steps WHERE state = 'failed'")
    op.drop_constraint("ck_ad_step_state", "ad_promotion_steps", type_="check")
    op.create_check_constraint(
        "ck_ad_step_state",
        "ad_promotion_steps",
        "(state = 'in_flight' AND meta_id IS NULL) OR "
        "(state = 'completed' AND meta_id IS NOT NULL AND meta_id ~ '^[0-9]+$')",
    )
