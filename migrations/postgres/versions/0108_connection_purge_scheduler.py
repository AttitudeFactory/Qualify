"""Restricted automatic purge discovery and fair retry ordering (m-24789547).

The existing NOBYPASSRLS purge role discovers only due tenant UUIDs through a
bounded SECURITY DEFINER function. It gains no cross-tenant table policy, role
membership, credential reads or additional DELETE privileges.
"""

from alembic import op

revision = "0108"
down_revision = "0107"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE connection_purge_requests ADD COLUMN scheduler_attempted_at timestamptz;
        CREATE INDEX ix_connection_purge_discovery ON connection_purge_requests (tenant_id)
            WHERE status IN ('scheduled','running');
        CREATE FUNCTION public.connection_purge_due_tenants(
            moment timestamptz, after_tenant uuid, batch_limit integer)
        RETURNS TABLE (tenant_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
            SELECT DISTINCT r.tenant_id FROM public.connection_purge_requests r
            WHERE r.status IN ('scheduled','running') AND r.due_at <= moment
              AND (after_tenant IS NULL OR r.tenant_id > after_tenant)
            ORDER BY r.tenant_id LIMIT greatest(1, least(batch_limit, 1000))
        $$;
        REVOKE ALL ON FUNCTION public.connection_purge_due_tenants(timestamptz,uuid,integer)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION public.connection_purge_due_tenants(timestamptz,uuid,integer)
            TO qualify_connection_purge;
    """)


def downgrade() -> None:
    op.execute("""
        DROP FUNCTION public.connection_purge_due_tenants(timestamptz,uuid,integer);
        DROP INDEX ix_connection_purge_discovery;
        ALTER TABLE connection_purge_requests DROP COLUMN scheduler_attempted_at;
    """)
