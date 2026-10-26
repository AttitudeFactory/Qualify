"""Durable generation preparation and checkpoints (ADR 41, m-24852166).

Requests and result metadata are tenant content: FORCE RLS, no grants to the
cross-tenant worker role. Binary results live in the existing media store. Leases
and dirty versions permit crash recovery without repeating completed paid steps.
"""

from alembic import op

revision = "0098"
down_revision = "0097"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE creative_jobs ADD CONSTRAINT uq_creative_jobs_tenant_id UNIQUE (tenant_id,id);
        CREATE TABLE creative_pipeline_runs (
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            draft_id uuid NOT NULL,
            revision integer NOT NULL,
            phase text NOT NULL,
            dirty_version bigint NOT NULL DEFAULT 1,
            prepared_version bigint NOT NULL DEFAULT 0,
            lease_token uuid,
            lease_until timestamptz,
            pipeline_version text NOT NULL,
            PRIMARY KEY (tenant_id, draft_id, revision, phase),
            FOREIGN KEY (tenant_id, draft_id)
                REFERENCES content_drafts(tenant_id, id) ON DELETE CASCADE
        );
        CREATE TABLE creative_pipeline_steps (
            tenant_id uuid NOT NULL,
            draft_id uuid NOT NULL,
            revision integer NOT NULL,
            phase text NOT NULL,
            step integer NOT NULL,
            job_id uuid,
            request jsonb NOT NULL,
            result jsonb,
            error text,
            PRIMARY KEY (tenant_id, draft_id, revision, phase, step),
            FOREIGN KEY (tenant_id, draft_id, revision, phase)
                REFERENCES creative_pipeline_runs ON DELETE CASCADE,
            FOREIGN KEY (tenant_id,job_id)
                REFERENCES creative_jobs(tenant_id,id) ON DELETE CASCADE,
            UNIQUE (job_id)
        );
    """)
    for table in ("creative_pipeline_runs", "creative_pipeline_steps"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)""")
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO qualify_app")


def downgrade() -> None:
    op.execute("DROP TABLE creative_pipeline_steps")
    op.execute("DROP TABLE creative_pipeline_runs")
    op.execute("ALTER TABLE creative_jobs DROP CONSTRAINT uq_creative_jobs_tenant_id")
