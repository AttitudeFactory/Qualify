"""«Eliminar» a WhatsApp menu = archive it (m-24986800, founder decision D1 of
`docs/ux-aprobados-y-menus.md` §5: archive, never a hard delete).

The owner reads «Eliminar» / «No se puede deshacer»; underneath the menu row, its
versions (provenance of every answer a chat got) and the thread state that points at
them stay intact. 0058 grants no role DELETE on either table, and that stays so.

- `whatsapp_menus.archived_at timestamptz NULL` — set once by
  `PostgresMenuRepository.archive_menu`; an archived menu is out of every list and read
  of the editor, and can never be published again.
- `ck_wa_menu_archived_unpublished`: `archived_at IS NULL OR published_version_id IS
  NULL`. Archiving clears the pointer in the same UPDATE, so an archived menu can never be
  the number's live menu — every reader that finds the live menu through
  `published_version_id` (the webhook loader, chat attachments, metrics) excludes it by
  construction, with no new column grant to `qualify_webhook_worker`. The repository
  refuses to archive the menu that is answering (published and not paused); this
  constraint is the backstop for the "never publish an archived menu" half.
- `uq_wa_menu_phone_name` becomes partial (`WHERE archived_at IS NULL`): an archived
  «Menú principal» must not stop the owner from creating a new «Menú principal».

Grants: none added. `qualify_app` already holds table-level UPDATE on `whatsapp_menus`
(0058), which covers the new column; RLS (0058's `tenant_isolation`) is unchanged.
No index: the editor lists by `ix_wa_menu_phone` and a number has a handful of menus.

Downgrade refuses while an archived menu exists (it would reappear in the owner's list
and could collide on the full name index), then restores 0058's index and drops the
constraint and the column.
"""

from alembic import op

revision = "0148"
down_revision = "0147"
branch_labels = None
depends_on = None

MENUS = "whatsapp_menus"


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE {MENUS} ADD COLUMN archived_at timestamptz NULL;
        ALTER TABLE {MENUS} ADD CONSTRAINT ck_wa_menu_archived_unpublished
            CHECK (archived_at IS NULL OR published_version_id IS NULL);
        DROP INDEX uq_wa_menu_phone_name;
        CREATE UNIQUE INDEX uq_wa_menu_phone_name
            ON {MENUS} (tenant_id, phone_number_row_id, lower(name))
            WHERE archived_at IS NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            -- scoped to this check: every tenant's rows, then RLS back on for the rest
            PERFORM set_config('row_security', 'off', true);
            IF EXISTS (SELECT 1 FROM {MENUS} WHERE archived_at IS NOT NULL) THEN
                RAISE EXCEPTION 'whatsapp_menus holds archived menus; downgrading would '
                                'show them to their owners again — resolve them first';
            END IF;
            PERFORM set_config('row_security', 'on', true);
        END
        $$;
        DROP INDEX uq_wa_menu_phone_name;
        CREATE UNIQUE INDEX uq_wa_menu_phone_name
            ON {MENUS} (tenant_id, phone_number_row_id, lower(name));
        ALTER TABLE {MENUS} DROP CONSTRAINT ck_wa_menu_archived_unpublished;
        ALTER TABLE {MENUS} DROP COLUMN archived_at;
        """
    )
