"""`db`-marked: every `ContentKind` the generator can submit is a kind the database
accepts. `clip` reached the generator without widening `ck_content_briefs_kind` (fixed by
migration 0068, 2026-10-20) and every clip failed at INSERT as «No se pudo hablar con la
base de datos» — a new kind must come with its migration, and this says so in CI."""

from __future__ import annotations

import pytest
from qualify_creative.enums import ContentKind
from qualify_shared.db.admin import admin_session
from sqlalchemy import text

pytestmark = pytest.mark.db


def test_the_brief_kind_check_admits_every_content_kind() -> None:
    with admin_session() as session:
        definition = session.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_content_briefs_kind'"
            )
        )
    assert definition is not None
    missing = [kind.value for kind in ContentKind if f"'{kind.value}'" not in definition]
    assert missing == []
