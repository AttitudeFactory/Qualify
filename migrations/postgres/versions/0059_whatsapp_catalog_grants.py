"""whatsapp catalog grants: the webhook worker reads a number's brand and products (WA-15)

Revision ID: 0059
Revises: 0058
Create Date: 2026-10-14

Backlog: `docs/backlog-modulo-whatsapp.md` §4 WA-15. A menu's `products` node is rendered
from the catalog of the brand the WhatsApp number belongs to
(`qualify_api.whatsapp.catalog.load_catalog_for_phone`, the WA-07 handler's
`catalog_loader`). That loader runs inside the webhook processor, as
`qualify_webhook_worker` (0050) — the role that already resolves `phone_number_id` →
tenant and loads the published menu. Until now it could read neither the number's
`brand_id` nor `brand_products` at all, so this migration grants exactly what the loader
selects and nothing else. No table, column or policy changes.

**Grants (column-level SELECT only; QUA-214).**

| table | qualify_webhook_worker gains |
|---|---|
| `whatsapp_phone_numbers` | SELECT, 1 column (a) |
| `brand_products` | SELECT, 9 columns (b) |

(a) `brand_id` — on top of 0057's `id, tenant_id, connection_id, phone_number_id`.
(b) `id, tenant_id, brand_id, name, price_amount, price_currency, category, is_active,
    position` — what one list row needs plus the predicates the loader filters on.

Deliberately NOT granted on `brand_products`: `slug`, `description`, `tags`,
`created_by`, `created_at`, `updated_at` — the list row shows name, price and category,
nothing more, and a `SELECT *` from the worker stays denied. No INSERT/UPDATE/DELETE: the
catalog is edited by the app role (`qualify_app`, 0038) through `tenant_session`, never by
the processor.

**Why a BYPASSRLS role reads tenant data here, and why that is bounded.** The worker has
BYPASSRLS since 0050 so its cross-tenant resolution works under FORCE RLS; BYPASSRLS never
bypasses a GRANT, so its reach grows by exactly the two lines above. The tenant predicate
the policy would have applied is applied by the code instead: the loader filters products
by BOTH the phone row's `brand_id` and its `tenant_id` (the phone row itself was resolved
from Meta's `phone_number_id`, never from the payload's claims).

`test_webhook_schema_db.py` and `test_whatsapp_schema_db.py` pin the worker's column
grants; `test_whatsapp_catalog_grants_db.py` exercises them as the real role.

**Downgrade** revokes the two column grants; nothing else to undo, no data touched.
"""

from __future__ import annotations

from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None

_WORKER_PHONE_COLUMNS = ("brand_id",)
_WORKER_PRODUCT_COLUMNS = (
    "id",
    "tenant_id",
    "brand_id",
    "name",
    "price_amount",
    "price_currency",
    "category",
    "is_active",
    "position",
)


def upgrade() -> None:
    op.execute(
        f"GRANT SELECT ({', '.join(_WORKER_PHONE_COLUMNS)}) "
        "ON whatsapp_phone_numbers TO qualify_webhook_worker;"
    )
    op.execute(
        f"GRANT SELECT ({', '.join(_WORKER_PRODUCT_COLUMNS)}) "
        "ON brand_products TO qualify_webhook_worker;"
    )


def downgrade() -> None:
    op.execute(
        f"REVOKE SELECT ({', '.join(_WORKER_PRODUCT_COLUMNS)}) "
        "ON brand_products FROM qualify_webhook_worker;"
    )
    op.execute(
        f"REVOKE SELECT ({', '.join(_WORKER_PHONE_COLUMNS)}) "
        "ON whatsapp_phone_numbers FROM qualify_webhook_worker;"
    )
