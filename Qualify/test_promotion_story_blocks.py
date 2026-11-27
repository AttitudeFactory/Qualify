"""HIS-2 (m-25130282): a historia that cannot be a story ad says why and what to do,
one text per cause the backend names — never the old catch-all empty state."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from qualify_api.ads.story_readiness import StoryBlock, files_block

from . import promotion_state
from .ad_enhancements_ui import ad_enhancement_permissions
from .promotion_provider import story_block_text
from .promotion_state import PromotionState
from .promotion_story_ui import story_empty
from .promotion_unpublished_provider import story_kinds
from .promotion_vm import STORY_BLOCKS
from .test_promotion_story import ZONE, story_source
from .test_promotion_wizard import PIECE, ActionContext


def test_every_cause_has_one_text_with_its_next_step() -> None:
    assert set(STORY_BLOCKS) == {block.value for block in StoryBlock}
    for message, action in STORY_BLOCKS.values():
        assert message.endswith((".", "».")) and len(message) < 260
        # No jargon, no impossible step: no «9:16», no cover picker, no «publica primero».
        for word in ("9:16", "Elige una portada", "Publica primero", "story", "post"):
            assert word not in message
        assert action is None or action[1] in {
            "/connections",
            "/brand/kit#permisos-de-meta",
            "/drafts",
        }
    assert "published" not in STORY_BLOCKS  # epic D1: never a cause on the story path


def test_the_action_is_where_the_text_sends_the_owner() -> None:
    for block, (message, action) in STORY_BLOCKS.items():
        _, label, href = story_block_text(block)
        if "Tus redes" in label:
            assert "Tus redes" in message and href == "/connections"
        if "Tu marca" in label:
            assert "Tu marca" in message and href == "/brand/kit#permisos-de-meta"
            assert "permisos-de-meta" in repr(ad_enhancement_permissions().render())
        assert (label, href) == (action or ("", ""))


def _asset(kind: str, content_type: str, width: int, height: int) -> dict:
    return {
        "id": uuid4(),
        "media_type": kind,
        "content_type": content_type,
        "width": width,
        "height": height,
    }


@pytest.mark.parametrize(
    "assets",
    [
        [_asset("image", "image/jpeg", 1080, 1920)],
        [_asset("video", "video/mp4", 1080, 1920)],
        [_asset("video", "video/mp4", 1080, 1920), _asset("image", "image/png", 1080, 1920)],
        [_asset("image", "image/jpeg", 1080, 1350)],
        [_asset("image", "image/webp", 1080, 1920)],
        [],
    ],
)
def test_the_backend_and_the_wizard_agree_on_the_files(assets: list[dict]) -> None:
    assert (files_block(assets) is None) == bool(story_kinds(assets))


def test_an_automatic_cover_is_only_its_videos_cover() -> None:
    """N1 (m-25142900): a frame of the video makes it a story ad, never a photo option."""
    video = _asset("video", "video/mp4", 1080, 1920)
    frame = _asset("image", "image/jpeg", 1080, 1920) | {"auto_cover": True}
    assert files_block([video, frame]) is None
    assert story_kinds([video, frame]) == ["videos"]
    assert story_kinds([video, frame, _asset("image", "image/png", 1080, 1920)]) == [
        "videos",
        "images",
    ]


def _context(params: dict) -> ActionContext:
    context = ActionContext()
    context.draft_id = str(PIECE)
    context.router = SimpleNamespace(url=SimpleNamespace(query_parameters=params))
    context.read_step = lambda: None
    context.choose_source = lambda value: PromotionState.choose_source.fn(context, value)
    return context


@pytest.mark.asyncio
async def test_a_blocked_historia_names_its_cause_and_never_reads_the_sources(monkeypatch):
    context = _context({"formato": "historia"})
    monkeypatch.setattr(
        promotion_state, "story_block_view", lambda *a: story_block_text("currency")
    )
    monkeypatch.setattr(
        promotion_state, "load_sources", lambda *a, **k: pytest.fail("refreshed Meta health")
    )
    _ = [event async for event in PromotionState.load.fn(context)]
    message, (label, href) = STORY_BLOCKS["currency"]
    assert context.sources == [] and context.error == ""
    assert (context.story_block, context.story_block_action, context.story_block_href) == (
        message,
        label,
        href,
    )


@pytest.mark.asyncio
async def test_a_ready_historia_shows_no_block_and_an_empty_one_still_says_why(monkeypatch):
    context = _context({"formato": "historia"})
    monkeypatch.setattr(promotion_state, "story_block_view", lambda *a: ("", "", ""))
    monkeypatch.setattr(promotion_state, "load_sources", lambda *a, **k: ([story_source()], ZONE))
    _ = [event async for event in PromotionState.load.fn(context)]
    assert len(context.sources) == 1 and context.story_block == ""
    # Ready a moment ago, gone now: still a cause, never the old catch-all.
    monkeypatch.setattr(promotion_state, "load_sources", lambda *a, **k: ([], ZONE))
    context = _context({"formato": "historia"})
    _ = [event async for event in PromotionState.load.fn(context)]
    assert context.story_block == STORY_BLOCKS["missing"][0]


def test_the_empty_screen_shows_the_cause_and_its_action() -> None:
    rendered = repr(story_empty().render())
    assert "story_block" in rendered and "story_block_href" in rendered


def test_a_missing_piece_has_no_way_back_to_it_only_to_por_aprobar() -> None:
    assert story_block_text("missing")[1:] == ("Ir a Por aprobar", "/drafts")
    rendered = repr(story_empty().render())
    # «Volver a la pieza» sits behind the missing piece's href.
    assert '"/drafts"' in rendered.replace('\\"', '"')
