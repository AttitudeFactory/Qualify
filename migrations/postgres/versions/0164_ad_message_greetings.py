"""Owner-written greeting for ads that open a chat (m-24828980)

Revision ID: 0164
Revises: 0163
Create Date: 2026-11-13

A promotion that opens WhatsApp or Instagram Direct can carry a welcome text and up to four
suggested questions. The owner writes them per brand; each save is a new immutable version
(append-only: the app role has no UPDATE or DELETE), so an approved promotion keeps pointing
at the exact text it froze in its request snapshot. The owner's own text is manual input
(docs/arquitectura.md §1.6): provenance is the login that wrote it, the time and the
pipeline version. RLS forced in this revision.
"""

from alembic import op

revision = "0164"
down_revision = "0163"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE ad_message_greetings (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        brand_id uuid NOT NULL,
        version integer NOT NULL CHECK(version>0),
        welcome_text text NOT NULL CHECK(char_length(btrim(welcome_text)) BETWEEN 1 AND 300),
        questions jsonb NOT NULL CHECK(jsonb_typeof(questions)='array'
            AND jsonb_array_length(questions) BETWEEN 1 AND 4),
        -- Identity-provider login id is provenance, not a cross-business local user FK.
        created_by uuid NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        pipeline_version text NOT NULL,
        UNIQUE(tenant_id,brand_id,version),
        UNIQUE(id,tenant_id),
        FOREIGN KEY(brand_id,tenant_id) REFERENCES brands(id,tenant_id) ON DELETE CASCADE
    );
    ALTER TABLE ad_message_greetings ENABLE ROW LEVEL SECURITY;
    ALTER TABLE ad_message_greetings FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON ad_message_greetings
      USING(tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid)
      WITH CHECK(tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid);
    GRANT SELECT,INSERT ON ad_message_greetings TO qualify_app;
    GRANT SELECT ON ad_message_greetings TO qualify_admin;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE ad_message_greetings")
