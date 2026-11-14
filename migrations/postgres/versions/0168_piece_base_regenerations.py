"""piece_base_regenerations: the cap of ONE base regeneration per slide (m-25017283,
ADR 49 §2 item 1 and §8.2)

Revision ID: 0168
Revises: 0167
Create Date: 2026-11-14

## Why this exists

ADR 49 §2 item 1: «si la llamada de la capa informa letras o botones inventados, la base se
regenera una sola vez, y ese tope lo impone una clave única sobre el intento, no un if».
The layer stage (m-25017283) reports `base_has_invented_text`; before it asks Seedream for
a second base it INSERTs one row here. The unique key makes the second attempt for the same
draft, revision and slide impossible — also across a queue resume or a crash between the
paid call and saving the piece — so a slide is never regenerated twice, whatever the code
path.

## Columns

- `tenant_id` + RLS (ENABLE + FORCE + the `NULLIF` policy), grants like 0163/0165
  (`qualify_app` SELECT + INSERT, `qualify_admin` SELECT).
- `brand_id` → `brands (id, tenant_id)`; `draft_id` → `content_drafts (id, tenant_id)`
  `ON DELETE CASCADE`. The version does not exist yet when the regeneration is claimed (it
  is written with the finished piece), so the key is the draft's `revision`.
- `position` 0..9, `UNIQUE (tenant_id, draft_id, revision, position)`: the cap.
- Provenance of the decision: the layer call's `model_id` and `prompt_version`, and
  `reason` (what the model reported).

ADR 49 §2.3 (amendment 2026-11-14): a regeneration is «rehacer» — the regenerated base is
the base of the version this run finishes; an owner's text edit later stays in that same
version as a child of the current leaf (`piece_layers`, 0163) and never claims here.

Short `lock_timeout`: the keys take a brief lock on `content_drafts`; a deploy fails fast
behind a long transaction instead of queueing the app (`deploy/server-deploy.sh` stops
before `up`, the previous release stays live).
"""

from alembic import op

revision = "0168"
down_revision = "0167"
branch_labels = None
depends_on = None

LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"


def upgrade() -> None:
    op.execute(LOCK_TIMEOUT)
    op.execute("""
    CREATE TABLE piece_base_regenerations (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        brand_id uuid NOT NULL,
        draft_id uuid NOT NULL,
        revision integer NOT NULL CHECK (revision > 0),
        position integer NOT NULL CHECK (position BETWEEN 0 AND 9),
        reason text NOT NULL CHECK (char_length(reason) BETWEEN 1 AND 200),
        model_id text NOT NULL CHECK (char_length(model_id) BETWEEN 1 AND 200),
        prompt_version text NOT NULL CHECK (char_length(prompt_version) BETWEEN 1 AND 64),
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_piece_base_regenerations_slide
            UNIQUE (tenant_id, draft_id, revision, position),
        CONSTRAINT fk_piece_base_regenerations_brand FOREIGN KEY (brand_id, tenant_id)
            REFERENCES brands(id, tenant_id),
        CONSTRAINT fk_piece_base_regenerations_draft FOREIGN KEY (draft_id, tenant_id)
            REFERENCES content_drafts(id, tenant_id) ON DELETE CASCADE
    );

    ALTER TABLE piece_base_regenerations ENABLE ROW LEVEL SECURITY;
    ALTER TABLE piece_base_regenerations FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON piece_base_regenerations
      USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
      WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    GRANT SELECT, INSERT ON piece_base_regenerations TO qualify_app;
    GRANT SELECT ON piece_base_regenerations TO qualify_admin;
    """)


def downgrade() -> None:
    op.execute(LOCK_TIMEOUT)
    op.execute("DROP TABLE piece_base_regenerations")
