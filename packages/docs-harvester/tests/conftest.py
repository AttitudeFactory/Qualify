from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def ig_root_markdown() -> str:
    return (FIXTURES_DIR / "ig_root.md").read_text(encoding="utf-8")


@pytest.fixture
def ig_overview_markdown() -> str:
    return (FIXTURES_DIR / "ig_overview.md").read_text(encoding="utf-8")


@pytest.fixture
def soft404_html() -> str:
    return (FIXTURES_DIR / "soft404.html").read_text(encoding="utf-8", errors="replace")


@pytest.fixture
def graphapi_html() -> str:
    return (FIXTURES_DIR / "graphapi_overview.html").read_text(encoding="utf-8", errors="replace")
