"""m-24789644 (Interacciones · Fase A): the module is named «Interacciones» everywhere it
is named (B1, the `/inbox` route unchanged), and every commented media shows its type —
Reel, Foto, Video, Carrusel, Publicación or Historia (B2)."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from qualify_api.sentiment.repository import (
    AnalysisVersion,
    MemorySentimentRepository,
    ReelSummary,
)

from . import inbox_page, inbox_provider
from .inbox_vm import CandidateMediaVM, media_format_label
from .ui.layout import NAV_ITEMS

_HERE = Path(__file__).parent
_TENANT = UUID("a2470000-0000-4000-8000-000000000001")
_CONNECTION = UUID("c2470000-0000-4000-8000-000000000001")
_NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


# --- B1: the name ------------------------------------------------------------------


def test_the_sidebar_never_says_interacciones_and_comentarios_keeps_its_route() -> None:
    """m-24842958 (N1): «Interacciones» is «Comentarios», in the owner's words. Since
    NAV-1 (m-24842957) comments are a tab of «Por responder», not a menu entry of their
    own; the `/inbox` address keeps working."""
    assert not any(label in ("Contenido", "Interacciones") for label, *_ in NAV_ITEMS)
    assert 'route="/inbox"' in (_HERE / "Qualify.py").read_text(encoding="utf-8")


def test_the_tab_title_and_the_header_say_comentarios() -> None:
    app_source = (_HERE / "Qualify.py").read_text(encoding="utf-8")
    assert 'title="Qualify · Comentarios"' in app_source
    assert 'title="Qualify · Interacciones"' not in app_source
    assert 'title="Qualify · Contenido"' not in app_source
    header = inspect.getsource(inbox_page.inbox_topbar)
    assert '"Comentarios"' in header and '"Interacciones"' not in header


# --- B2: the type of each commented media -------------------------------------------


@pytest.mark.parametrize(
    ("product_type", "media_type", "label"),
    [
        ("REELS", "VIDEO", "Reel"),
        ("FEED", "IMAGE", "Foto"),
        ("FEED", "VIDEO", "Video"),
        ("FEED", "CAROUSEL_ALBUM", "Carrusel"),
        ("FEED", "SOMETHING_NEW", "Publicación"),
        ("STORY", "IMAGE", "Historia"),
        (None, None, ""),
    ],
)
def test_media_format_label(product_type: str | None, media_type: str | None, label: str) -> None:
    assert media_format_label(product_type, media_type) == label


def _summary(product_type: str | None, media_type: str | None) -> ReelSummary:
    return ReelSummary(
        thread_id=uuid4(),
        external_thread_id="m1",
        last_message_at=_NOW - timedelta(hours=1),
        total=1,
        positive=0,
        neutral=0,
        negative=0,
        not_analyzed=1,
        is_monitored=True,
        media_posted_at=_NOW - timedelta(days=1),
        media_product_type=product_type,
        media_type=media_type,
    )


def _card(summary: ReelSummary, candidates: list[CandidateMediaVM] | None = None):  # type: ignore[no-untyped-def]
    original = inbox_provider._list_reel_summaries
    inbox_provider._list_reel_summaries = lambda **kwargs: (summary,)
    try:
        items, _cursor, _more = inbox_provider.reel_summaries_page(
            tenant_id=_TENANT,
            connection_id=_CONNECTION,
            cursor=None,
            candidates=candidates or [],
            now=_NOW,
        )
    finally:
        inbox_provider._list_reel_summaries = original
    return items[0]


def test_the_card_shows_the_persisted_type() -> None:
    assert _card(_summary("FEED", "CAROUSEL_ALBUM")).format_label == "Carrusel"


def test_a_legacy_row_falls_back_to_the_live_candidates_type() -> None:
    candidate = CandidateMediaVM(
        external_media_id="m1",
        posted_at="20 oct 2026, 10:00",
        is_monitored=True,
        caption="",
        permalink="",
        thumbnail_url="",
        format_label="Reel",
    )

    assert _card(_summary(None, None), [candidate]).format_label == "Reel"


def test_an_unknown_type_shows_no_badge() -> None:
    assert _card(_summary(None, None)).format_label == ""


def test_the_card_and_the_detail_header_render_the_type_badge() -> None:
    assert "_format_badge(reel)" in inspect.getsource(inbox_page._reel_summary_card)
    assert "_format_badge(reel)" in inspect.getsource(inbox_page._reel_detail_header)


def test_the_memory_repository_carries_the_persisted_type() -> None:
    repo = MemorySentimentRepository()
    message_id = uuid4()
    repo.seed_message(
        message_id=message_id,
        connection_id=_CONNECTION,
        source_id="c1",
        text="¿precio?",
        posted_at=_NOW,
        external_thread_id="m1",
    )
    repo.seed_monitored_media(
        connection_id=_CONNECTION,
        external_media_id="m1",
        is_monitored=True,
        media_product_type="FEED",
        media_type="IMAGE",
    )

    (summary,) = repo.list_reel_summaries(
        tenant_id=_TENANT,
        connection_id=_CONNECTION,
        version=AnalysisVersion("d", "p", "m", None),
        cursor=None,
    )

    assert (summary.media_product_type, summary.media_type) == ("FEED", "IMAGE")
