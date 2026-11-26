"""monthly_posts: one «Publicación del mes» per brand and month (m-25120705, epic m-25120477)

Revision ID: 0184
Revises: 0183
Create Date: 2026-11-25

Once a month the calendar worker prepares ONE post for the month's most relevant date
(`ads.month_plan.event_of_month`) for each brand that turned the setting on
(`planner.monthly_post`), and leaves it in «Por aprobar». The post spends one of the
client's monthly creations, so it must happen at most once per brand and month: this table
is that guarantee. `UNIQUE (brand_id, period)` is the claim — the chore inserts the row
first (`ON CONFLICT ON CONSTRAINT uq_monthly_post`) and only the winner calls the
generator; the generator's own `request_key` (derived from brand and month) is the second
lock against a double charge.

- `status`: `pending` (claimed, generator not settled yet; a stale claim is taken again by
  a later run, see `planner.monthly_post_job`), `created` (`draft_id` set) or `skipped`
  (`skip_reason`: no event, not enough creations, Brand Kit not ready… — nothing charged).
- Provenance (house rule): `event_id` + `event_date` + `calendar_version` (the calendar
  table, `calendario-v1`) and `pipeline_version` (the chore's).
- `draft_id` → `content_drafts` `ON DELETE SET NULL (draft_id)`: an owner deleting the
  piece keeps the row, so the month is never prepared twice.

Tenant table: `tenant_id` + RLS ENABLE/FORCE + the NULLIF policy; `qualify_app` reads and
writes (the chore runs through `tenant_session`), `qualify_admin` reads.

**Downgrade** drops the table: the record of which months were prepared is lost (the drafts
themselves stay), so a re-upgrade in the same month could prepare that month again — the
generator's request key still returns the existing draft without a second charge.
"""

from __future__ import annotations

from alembic import op

revision = "0184"
down_revision = "0183"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE monthly_posts (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        brand_id uuid NOT NULL,
        period date NOT NULL CHECK(extract(day FROM period) = 1),
        event_id text,
        event_date date,
        calendar_version text NOT NULL CHECK(calendar_version <> ''),
        kind text NOT NULL CHECK(kind <> ''),
        status text NOT NULL DEFAULT 'pending'
            CHECK(status IN ('pending','created','skipped')),
        skip_reason text,
        draft_id uuid,
        pipeline_version text NOT NULL CHECK(pipeline_version <> ''),
        claimed_at timestamptz NOT NULL DEFAULT now(),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_monthly_post UNIQUE(brand_id, period),
        CONSTRAINT ck_monthly_post_skip CHECK((status = 'skipped') = (skip_reason IS NOT NULL)),
        CONSTRAINT ck_monthly_post_event CHECK((event_id IS NULL) = (event_date IS NULL)),
        FOREIGN KEY(brand_id, tenant_id) REFERENCES brands(id, tenant_id) ON DELETE CASCADE,
        FOREIGN KEY(draft_id, tenant_id) REFERENCES content_drafts(id, tenant_id)
            ON DELETE SET NULL (draft_id)
    );
    CREATE INDEX ix_monthly_posts_tenant ON monthly_posts(tenant_id);
    ALTER TABLE monthly_posts ENABLE ROW LEVEL SECURITY;
    ALTER TABLE monthly_posts FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON monthly_posts
      USING(tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid)
      WITH CHECK(tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid);
    GRANT SELECT,INSERT,UPDATE ON monthly_posts TO qualify_app;
    GRANT SELECT ON monthly_posts TO qualify_admin;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE monthly_posts")
