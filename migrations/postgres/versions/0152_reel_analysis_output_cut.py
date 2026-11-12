"""public_reel_analyses: `model_output_cut` joins the closed list of `error_code`
(m-24993025)

Revision ID: 0152
Revises: 0151
Create Date: 2026-11-12

On 2026-11-10 two ~60 s TikTok reels failed the describe step with Haiku's answer cut at
`max_tokens = 9000`. A cut was retried like any unusable answer («a cut answer may fit on
a second try») and every retry paid again for the same cut. The describe step now sizes
the output cap to the request (`reel_analysis_ai.output_token_cap`) and a cut that still
happens fails at once with its own reason, `model_output_cut`, so the cause is visible on
the row instead of hiding under `model_failed`.

Only `ck_pra_error_code` (0119) changes. `public_reel_analyses` is the shared, global
analysis (ADR 44): no `tenant_id`, no RLS (0119's docstring), no grant changes — the
worker role already writes `error_code`.

**Downgrade** turns every `model_output_cut` back into `model_failed` (the reason it had
before this revision), then restores 0119's list.
"""

from __future__ import annotations

from alembic import op

revision = "0152"
down_revision = "0151"
branch_labels = None
depends_on = None

TABLE = "public_reel_analyses"
CHECK = "ck_pra_error_code"

ERROR_CODES_0119 = (
    "source_unavailable",
    "source_expired",
    "source_too_large",
    "source_unreadable",
    "model_failed",
)
ERROR_CODES = (*ERROR_CODES_0119, "model_output_cut")


def _check(codes: tuple[str, ...]) -> str:
    return f"error_code IS NULL OR error_code IN ({', '.join(repr(c) for c in codes)})"


def upgrade() -> None:
    op.drop_constraint(CHECK, TABLE, type_="check")
    op.create_check_constraint(CHECK, TABLE, _check(ERROR_CODES))


def downgrade() -> None:
    op.execute(
        f"UPDATE {TABLE} SET error_code = 'model_failed' WHERE error_code = 'model_output_cut'"
    )
    op.drop_constraint(CHECK, TABLE, type_="check")
    op.create_check_constraint(CHECK, TABLE, _check(ERROR_CODES_0119))
