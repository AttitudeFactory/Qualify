"""PASOS-11: content has a placeholder shape; background work keeps its own progress."""

from __future__ import annotations

from .brand_minimal import _loading_card
from .creative_wizard_pages import _connect_loading


def test_brand_content_load_uses_card_shapes_instead_of_a_work_progress_bar() -> None:
    placeholder = str(_loading_card())
    assert "Skeleton" in placeholder
    assert "q-progress-panel" not in placeholder
    # Reading/scraping a connected profile is actual work, not a content placeholder.
    assert "q-progress-panel" in str(_connect_loading())
