"""A settled publish attempt accepts its Instagram permalink once (m-25019220, epic
m-25019215; founder 2026-11-13)

Revision ID: 0160
Revises: 0159
Create Date: 2026-11-13

0159 added `publish_attempts.permalink` («Ver en Instagram» in «Tu semana»), but the
permalink is only known AFTER Instagram accepted the publication — when the attempt is
already settled — and `publish_attempts_settle_once()` (0003, last rewritten by 0106)
refuses every UPDATE of a settled row. Nothing could ever fill the column.

This revision widens that trigger by exactly one case: an UPDATE of a settled row whose
ONLY change is `permalink` going from NULL to a non-NULL value (every other column
identical, compared the way 0106 compares the purge exception: `to_jsonb(NEW) - col =
to_jsonb(OLD) - col`). Overwriting a permalink, clearing it, or touching any other column
of a settled row — media key, status, outcome — stays refused. The purge role's exception
(0106: `qualify_connection_purge` clearing `raw_response_r2_key`) is kept verbatim.

Who writes it: `planner.permalinks` (the calendar tick, read-only towards Meta) and the
backfill `just publish-backfill` — both through `tenant_session` with
`UPDATE … WHERE permalink IS NULL`.

No table, column, grant or RLS change: `qualify_app` already holds UPDATE on
`publish_attempts` (0003). **Downgrade** restores 0106's function body verbatim; the
permalinks already written stay (the column is 0159's).
"""

from __future__ import annotations

from alembic import op

revision = "0160"
down_revision = "0159"
branch_labels = None
depends_on = None

_WITH_PERMALINK_FILL = """
CREATE OR REPLACE FUNCTION publish_attempts_settle_once() RETURNS trigger AS $$
BEGIN
    IF OLD.settled_at IS NOT NULL THEN
        IF current_user = 'qualify_connection_purge'
            AND NEW.raw_response_r2_key IS NULL
            AND (to_jsonb(NEW) - 'raw_response_r2_key') =
                (to_jsonb(OLD) - 'raw_response_r2_key') THEN
            RETURN NEW;
        END IF;
        IF OLD.permalink IS NULL
            AND NEW.permalink IS NOT NULL
            AND (to_jsonb(NEW) - 'permalink') = (to_jsonb(OLD) - 'permalink') THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION
            'publish_attempts %: already settled at %, refusing terminal overwrite',
            OLD.id, OLD.settled_at USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

# 0106's body, verbatim.
_PURGE_ONLY = """
        CREATE OR REPLACE FUNCTION publish_attempts_settle_once() RETURNS trigger AS $$
        BEGIN
            IF OLD.settled_at IS NOT NULL THEN
                IF current_user = 'qualify_connection_purge'
                    AND NEW.raw_response_r2_key IS NULL
                    AND (to_jsonb(NEW) - 'raw_response_r2_key') =
                        (to_jsonb(OLD) - 'raw_response_r2_key') THEN
                    RETURN NEW;
                END IF;
                RAISE EXCEPTION
                    'publish_attempts %: already settled at %, refusing terminal overwrite',
                    OLD.id, OLD.settled_at USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.execute(_WITH_PERMALINK_FILL)


def downgrade() -> None:
    op.execute(_PURGE_ONLY)
