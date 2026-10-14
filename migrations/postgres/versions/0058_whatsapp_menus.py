"""whatsapp menus: menus, immutable versions, the thread-state FK and attempts (WA-14, QUA-213)

Revision ID: 0058
Revises: 0057
Create Date: 2026-10-14

Backlog: `docs/backlog-modulo-whatsapp.md` §4 WA-14 (it says "0057_whatsapp_menus"; 0057 is
the WhatsApp base migration, so the menus are 0058). The pure half — `MenuDefinition`,
the engine, the automation body — landed in `qualify_api.whatsapp.menus` (PR #128); this
is the persistence half it was written against.

**What it creates.** Two tenant-scoped tables with the standard `NULLIF` policy of 0001
(R7) and the composite-FK discipline of R2:

- `whatsapp_menus` — one menu a business authors for ONE of its WhatsApp numbers
  (`phone_number_row_id` → `whatsapp_phone_numbers.id`, composite with `tenant_id`; this
  migration adds the `(id, tenant_id)` UNIQUE that 0057's table lacked). `name` is unique
  per number case-insensitively (`uq_wa_menu_phone_name`, an expression index on
  `lower(name)`). `published_version_id` points at the version the number answers with;
  it is a COMPOSITE FK `(published_version_id, id)` → `whatsapp_menu_versions (id,
  menu_id)`, so a menu can only ever publish one of its OWN versions. **At most one
  published menu per number** (`uq_wa_menu_phone_published`, partial on
  `published_version_id IS NOT NULL`): the webhook handler loads "the menu of this number"
  and that lookup must be deterministic; publishing menu B on a number where A is live
  demotes A in the same transaction (`MenuRepository.publish_version`). `is_paused` stops
  the automation for the whole number without unpublishing (a person takes the counter
  for the afternoon); the per-thread pause stays in `whatsapp_thread_state`.
- `whatsapp_menu_versions` — **immutable**. `definition` is the validated
  `MenuDefinition.model_dump()`; `engine_version` is the `ENGINE_VERSION` the definition
  was validated against (provenance: which rules a published version satisfied).
  `version` is a per-menu counter (`uq_wa_menu_version`). Nothing UPDATEs a version
  except its publication stamp (`published_at`, `published_by_user_id`) — enforced by a
  COLUMN-level UPDATE grant, not by code remembering to behave — and nothing deletes
  one: a thread may still sit on it.

**What it changes.**

- `whatsapp_thread_state.menu_version_id` gets the FK 0057 announced: composite
  `(menu_version_id, tenant_id)` → `whatsapp_menu_versions (id, tenant_id)`. Any value
  already there points at nothing (no code wrote the column; only schema tests), so it
  is NULLed first — the posture 0045 took for `content_drafts.campaign_id`.
- `whatsapp_thread_state.attempts int NOT NULL DEFAULT 0` — the engine's
  `ThreadMenuState.attempts` (consecutive unknown inputs on the same node; at
  `MAX_UNKNOWN_ATTEMPTS` it hands off). 0057 had no column for it.

**Grants (minimal, per role).**

| table | qualify_app | qualify_webhook_worker | qualify_admin |
|---|---|---|---|
| `whatsapp_menus` | SELECT, INSERT, UPDATE | SELECT, 5 columns (a) | SELECT |
| `whatsapp_menu_versions` | SELECT, INSERT, UPDATE 2 columns (b) | SELECT, 5 columns (c) | SELECT |

(a) `id, tenant_id, phone_number_row_id, published_version_id, is_paused` — what the
    WA-07 handler needs to find the live menu of a number and know whether it is paused.
(b) `published_at, published_by_user_id` — the publication stamp; every other column of
    a version is frozen for the app role too.
(c) `id, tenant_id, menu_id, version, definition` — the handler loads the published
    definition and records which version it ran.

No role may DELETE from either table. `test_whatsapp_menus_schema_db.py` pins the table,
cell by cell; `test_webhook_schema_db.py` carries the worker's two new column grants.

**Downgrade** drops the FK and `attempts` from `whatsapp_thread_state` (NULLing
`menu_version_id` is not needed: the column stays, only its FK goes), the two tables and
the `(id, tenant_id)` UNIQUE on `whatsapp_phone_numbers`. Menu data is deleted with the
tables, and this docstring says so.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None

_WORKER_MENU_COLUMNS = (
    "id",
    "tenant_id",
    "phone_number_row_id",
    "published_version_id",
    "is_paused",
)
_WORKER_VERSION_COLUMNS = ("id", "tenant_id", "menu_id", "version", "definition")
_APP_VERSION_UPDATE_COLUMNS = ("published_at", "published_by_user_id")


def _enable_tenant_rls(table: str) -> None:
    # NULLIF is load-bearing (R7) — see 0001's `_enable_rls`.
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def upgrade() -> None:
    # 0057 gave `whatsapp_phone_numbers` no `(id, tenant_id)` UNIQUE; the composite FK
    # below needs it.
    op.create_unique_constraint(
        "uq_wa_phone_id_tenant", "whatsapp_phone_numbers", ["id", "tenant_id"]
    )

    # --- whatsapp_menus ----------------------------------------------------------------
    op.create_table(
        "whatsapp_menus",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("brand_id", PGUUID(as_uuid=True), sa.ForeignKey("brands.id"), nullable=True),
        sa.Column("phone_number_row_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        # FK added after `whatsapp_menu_versions` exists (the two tables reference each other).
        sa.Column("published_version_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column("is_paused", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_by_user_id", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("id", "tenant_id", name="uq_wa_menu_id_tenant"),
        sa.ForeignKeyConstraint(
            ["phone_number_row_id", "tenant_id"],
            ["whatsapp_phone_numbers.id", "whatsapp_phone_numbers.tenant_id"],
            name="fk_wa_menu_phone_tenant",
        ),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_wa_menu_name_not_blank"),
    )
    op.create_index("ix_wa_menu_tenant", "whatsapp_menus", ["tenant_id"])
    op.create_index("ix_wa_menu_phone", "whatsapp_menus", ["phone_number_row_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_wa_menu_phone_name "
        "ON whatsapp_menus (tenant_id, phone_number_row_id, lower(name));"
    )
    # One live menu per number: the handler's lookup is deterministic by construction.
    op.execute(
        "CREATE UNIQUE INDEX uq_wa_menu_phone_published "
        "ON whatsapp_menus (phone_number_row_id) WHERE published_version_id IS NOT NULL;"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON whatsapp_menus TO qualify_app;")
    op.execute("GRANT SELECT ON whatsapp_menus TO qualify_admin;")
    op.execute(
        f"GRANT SELECT ({', '.join(_WORKER_MENU_COLUMNS)}) "
        "ON whatsapp_menus TO qualify_webhook_worker;"
    )
    _enable_tenant_rls("whatsapp_menus")

    # --- whatsapp_menu_versions --------------------------------------------------------
    op.create_table(
        "whatsapp_menu_versions",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("menu_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", JSONB(), nullable=False),
        sa.Column("engine_version", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "published_by_user_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("menu_id", "version", name="uq_wa_menu_version"),
        # Targets of the two composite FKs: the thread cursor `(id, tenant_id)` and the
        # menu's own `published_version_id` `(id, menu_id)`.
        sa.UniqueConstraint("id", "tenant_id", name="uq_wa_menu_version_id_tenant"),
        sa.UniqueConstraint("id", "menu_id", name="uq_wa_menu_version_id_menu"),
        sa.ForeignKeyConstraint(
            ["menu_id", "tenant_id"],
            ["whatsapp_menus.id", "whatsapp_menus.tenant_id"],
            name="fk_wa_menu_version_menu_tenant",
        ),
        sa.CheckConstraint("version > 0", name="ck_wa_menu_version_positive"),
    )
    op.create_index("ix_wa_menu_version_tenant", "whatsapp_menu_versions", ["tenant_id"])
    op.execute("GRANT SELECT, INSERT ON whatsapp_menu_versions TO qualify_app;")
    op.execute(
        f"GRANT UPDATE ({', '.join(_APP_VERSION_UPDATE_COLUMNS)}) "
        "ON whatsapp_menu_versions TO qualify_app;"
    )
    op.execute("GRANT SELECT ON whatsapp_menu_versions TO qualify_admin;")
    op.execute(
        f"GRANT SELECT ({', '.join(_WORKER_VERSION_COLUMNS)}) "
        "ON whatsapp_menu_versions TO qualify_webhook_worker;"
    )
    _enable_tenant_rls("whatsapp_menu_versions")

    # A menu publishes one of its OWN versions, or none (MATCH SIMPLE skips the NULL).
    op.execute(
        """
        ALTER TABLE whatsapp_menus
            ADD CONSTRAINT fk_wa_menu_published_version
            FOREIGN KEY (published_version_id, id)
            REFERENCES whatsapp_menu_versions (id, menu_id);
        """
    )

    # --- whatsapp_thread_state: the FK 0057 announced, and the attempts counter -------
    op.execute(
        "UPDATE whatsapp_thread_state SET menu_version_id = NULL WHERE menu_version_id IS NOT NULL;"
    )
    op.execute(
        """
        ALTER TABLE whatsapp_thread_state
            ADD CONSTRAINT fk_wa_thread_state_menu_version_tenant
            FOREIGN KEY (menu_version_id, tenant_id)
            REFERENCES whatsapp_menu_versions (id, tenant_id);
        """
    )
    op.add_column(
        "whatsapp_thread_state",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute(
        "ALTER TABLE whatsapp_thread_state ADD CONSTRAINT ck_wa_thread_state_attempts "
        "CHECK (attempts >= 0);"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE whatsapp_thread_state DROP CONSTRAINT ck_wa_thread_state_attempts;")
    op.drop_column("whatsapp_thread_state", "attempts")
    op.execute(
        "ALTER TABLE whatsapp_thread_state DROP CONSTRAINT fk_wa_thread_state_menu_version_tenant;"
    )

    op.execute("ALTER TABLE whatsapp_menus DROP CONSTRAINT fk_wa_menu_published_version;")
    op.drop_index("ix_wa_menu_version_tenant", table_name="whatsapp_menu_versions")
    op.drop_table("whatsapp_menu_versions")
    op.execute("DROP INDEX uq_wa_menu_phone_published;")
    op.execute("DROP INDEX uq_wa_menu_phone_name;")
    op.drop_index("ix_wa_menu_phone", table_name="whatsapp_menus")
    op.drop_index("ix_wa_menu_tenant", table_name="whatsapp_menus")
    op.drop_table("whatsapp_menus")

    op.drop_constraint("uq_wa_phone_id_tenant", "whatsapp_phone_numbers", type_="unique")
