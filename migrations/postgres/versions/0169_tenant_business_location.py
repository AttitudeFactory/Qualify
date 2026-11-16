"""tenants.business_*: the business location for «Cerca de mi negocio» (m-25038694)

Revision ID: 0169
Revises: 0168
Create Date: 2026-11-16

## Why this exists

The promotion wizard's «Cerca de mi negocio» takes the phone's position every time, so the
owner has to be at the store to promote it. Qualify now remembers the point per business:
one point per tenant, so it lives on `tenants` (already isolated by RLS on its own `id`,
0001) instead of a new table.

## Columns

- `business_latitude numeric(9,6)`, `business_longitude numeric(10,6)`: 6 decimals, the
  precision `MapPoint` accepts (~0.1 m). Range CHECKs mirror `MapPoint.validate`.
- `business_location_set_by` → `users (id, tenant_id)` (the key 0114 added): who saved it,
  always a user of this business. `ON DELETE SET NULL (business_location_set_by)` (Postgres
  ≥ 15, like 0045) so deleting a user never blocks on the tenant row.
- `business_location_set_at`: when. The point is manual input the owner approves when saving
  it (provenance exception of 2026-11-04, `docs/arquitectura.md` §1.6): who + when is its
  provenance.
- CHECK: latitude, longitude and set_at are all set or all NULL.

`qualify_app` keeps column-level UPDATE on `tenants` (0093) and gains it on these four only.

**Downgrade** revokes the grant and drops the columns (the saved points are lost; the owner
can capture the point again).
"""

from alembic import op

revision = "0169"
down_revision = "0168"
branch_labels = None
depends_on = None

LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"
_COLUMNS = (
    "business_latitude, business_longitude, business_location_set_by, business_location_set_at"
)


def upgrade() -> None:
    op.execute(LOCK_TIMEOUT)
    op.execute(f"""
    ALTER TABLE tenants
        ADD COLUMN business_latitude numeric(9,6)
            CHECK (business_latitude BETWEEN -90 AND 90),
        ADD COLUMN business_longitude numeric(10,6)
            CHECK (business_longitude BETWEEN -180 AND 180),
        ADD COLUMN business_location_set_by uuid,
        ADD COLUMN business_location_set_at timestamptz,
        ADD CONSTRAINT ck_tenants_business_location CHECK (
            (business_latitude IS NULL) = (business_longitude IS NULL)
            AND (business_latitude IS NULL) = (business_location_set_at IS NULL)
        ),
        ADD CONSTRAINT fk_tenants_business_location_set_by
            FOREIGN KEY (business_location_set_by, id) REFERENCES users(id, tenant_id)
            ON DELETE SET NULL (business_location_set_by);
    GRANT UPDATE ({_COLUMNS}) ON tenants TO qualify_app;
    """)


def downgrade() -> None:
    op.execute(LOCK_TIMEOUT)
    op.execute(f"""
    REVOKE UPDATE ({_COLUMNS}) ON tenants FROM qualify_app;
    ALTER TABLE tenants
        DROP CONSTRAINT fk_tenants_business_location_set_by,
        DROP CONSTRAINT ck_tenants_business_location,
        DROP COLUMN business_location_set_at,
        DROP COLUMN business_location_set_by,
        DROP COLUMN business_longitude,
        DROP COLUMN business_latitude;
    """)
