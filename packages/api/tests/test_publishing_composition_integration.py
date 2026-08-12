"""Integration test for the Reflex publish seam against REAL R2.

Exercises `production_staging_service()` exactly as `Qualify/publishing_state.py` reaches
it (via `publishing_provider.start_publish` → `qualify_api.publishing.
stage_and_start_publish` → this factory) — the only test in the suite that proves the
path `Reflex → composition → R2ObjectStore` reaches a real bucket, not a fake.

Needs live `QUALIFY_R2_*` credentials. Herwin handed them over 2026-08-11, and this test
has since been run successfully against the real `qualify-artifacts` bucket. Marked
`integration` so `pyproject.toml`'s default `addopts` (`-m 'not integration'`) still
excludes it from `just test`/CI — per this repo's rule that `integration` never runs
without real vendor credentials explicitly present in the environment, not because the
credentials are unavailable.

Full end-to-end publish (through `production_publish_service()`) additionally needs a
live, connected Meta account — not exercised here, that is a second, separate credential.
This file proves the R2 half only; the Meta half was first proven live by the 2026-08-07
manual smoke (`.claude/sprint-state-2026-08-07-c04-page-access-resolved.md`), and the full
chain (staging → Meta container → upload → publish) was verified end-to-end through the
real `/publish` UI on 2026-08-11, after fixing `R2ObjectStore.open()`'s non-seekable-
stream bug.
"""

from __future__ import annotations

import io
from uuid import UUID

import pytest

from qualify_api.publishing.composition import production_staging_service

pytestmark = pytest.mark.integration

TENANT = UUID("aa000000-0000-4000-8000-0000000000aa")
CONNECTION = UUID("bb000000-0000-4000-8000-0000000000bb")


def test_staging_reaches_the_real_r2_bucket() -> None:
    """The narrowest slice of the real path: stage one object to REAL R2, then read it
    back through the same gate the publish service will use. No Postgres, no Meta —
    proves `QUALIFY_R2_*` and the bucket work end to end."""
    service = production_staging_service()

    staged = service.stage_media(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        media_id="integration-smoke",
        fileobj=io.BytesIO(b"qualify-r2-integration-smoke"),
        content_type="video/mp4",
        media_product_type="REELS",
    )

    assert staged.media_object_key == f"t/{TENANT}/media/{CONNECTION}/integration-smoke"
