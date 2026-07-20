from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
BRAND_ID = UUID("11111111-1111-1111-1111-111111111111")
PIPELINE_VERSION = "0.1.0"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def brand_id() -> UUID:
    return BRAND_ID


@pytest.fixture
def pipeline_version() -> str:
    return PIPELINE_VERSION
