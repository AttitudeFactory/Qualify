"""QUA-146 phase 1: Meta's `media_type` on `monitored_media` — the known vocabulary
(`qualify_api.inbox.media_type`), the explicit reading of an unknown value, and the shape
of migration 0049. Offline; the Postgres half (backfill, verbatim storage) is in the
`db`-marked tests of `test_inbox_repository.py`."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import CheckConstraint, Text

from qualify_api.inbox.media_type import MediaType, is_unrecognized_media_type, known_media_type
from qualify_api.inbox.models import MonitoredMedia
from qualify_api.inbox.repository import MonitoredMediaRecord

_VERSIONS = Path(__file__).resolve().parents[3] / "migrations" / "postgres" / "versions"


def _load(filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        filename.removesuffix(".py"), _VERSIONS / filename
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- the vocabulary --------------------------------------------------------------------


def test_the_known_formats_are_exactly_meta_s_three() -> None:
    assert {m.value for m in MediaType} == {"IMAGE", "VIDEO", "CAROUSEL_ALBUM"}


@pytest.mark.parametrize("raw", ["IMAGE", "VIDEO", "CAROUSEL_ALBUM"])
def test_a_known_value_is_recognized(raw: str) -> None:
    assert known_media_type(raw) is MediaType(raw)
    assert not is_unrecognized_media_type(raw)


def test_null_means_not_read_yet_never_unrecognized() -> None:
    assert known_media_type(None) is None
    assert not is_unrecognized_media_type(None)


@pytest.mark.parametrize("raw", ["REELS", "STORY_VIDEO", "video", " VIDEO", ""])
def test_an_unknown_value_is_unrecognized_and_left_as_is(raw: str) -> None:
    """Exact, case-sensitive match on Meta's spelling: anything else is unrecognized —
    never coerced to a known format, never raised on."""
    assert known_media_type(raw) is None
    assert is_unrecognized_media_type(raw)


def test_the_read_record_carries_the_raw_value_unparsed() -> None:
    record = MonitoredMediaRecord(
        external_media_id="m", is_monitored=True, media_type="FUTURE_FORMAT"
    )
    assert record.media_type == "FUTURE_FORMAT"
    assert MonitoredMediaRecord(external_media_id="m", is_monitored=True).media_type is None


# --- model + migration -----------------------------------------------------------------


def test_the_model_column_is_nullable_text_without_a_check() -> None:
    column = MonitoredMedia.__table__.c.media_type
    assert column.nullable
    assert isinstance(column.type, Text)
    checks = [c for c in MonitoredMedia.__table__.constraints if isinstance(c, CheckConstraint)]
    assert all("media_type" not in str(c.sqltext) for c in checks)


def test_migration_0049_chains_from_0048_and_is_the_only_0049() -> None:
    assert _load("0048_regeneration_replaces_rows.py").revision == "0048"
    migration = _load("0049_monitored_media_type.py")
    assert (migration.revision, migration.down_revision) == ("0049", "0048")
    others = [
        p.name
        for p in _VERSIONS.glob("*.py")
        if p.name != "0049_monitored_media_type.py" and _load(p.name).revision == "0049"
    ]
    assert others == []


def test_the_backfill_touches_only_reels_still_without_a_type() -> None:
    sql = _load("0049_monitored_media_type.py").BACKFILL_REELS_SQL
    assert "SET media_type = 'VIDEO'" in sql
    assert "media_product_type = 'REELS'" in sql
    assert "media_type IS NULL" in sql
