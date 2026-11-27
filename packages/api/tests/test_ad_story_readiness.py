"""HIS-2 (m-25130282): a historia that cannot be a story ad names its cause, and a Meta
refusal at preparation keeps the next step its number has."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from packages.api.tests.test_ad_story import prepare as story_prepare
from packages.api.tests.test_ad_story import story as story  # noqa: F401
from packages.api.tests.test_ad_story import story_video as story_video  # noqa: F401
from packages.api.tests.test_ad_unpublished import form, prepare
from packages.api.tests.test_ad_unpublished import service as service  # noqa: F401
from packages.api.tests.test_ad_unpublished_video import mp4
from packages.api.tests.test_ad_unpublished_video import video as video  # noqa: F401

from qualify_api.ads import unpublished_service as module
from qualify_api.ads.errors import CODE_MESSAGES, SUBCODE_MESSAGES, MarketingError
from qualify_api.ads.story_readiness import StoryBlock, files_block, piece_block
from qualify_api.ads.unpublished import UnpublishedUnavailable
from qualify_api.ads.unpublished_service import PREPARE_REFUSED, meta_refusal

NOW = datetime.now(UTC)


def piece(**changes: object) -> dict:
    return {
        "version_id": uuid4(),
        "status": "approved",
        "revision": 2,
        "approved_revision": 2,
        "media_purged_at": None,
        "published_media_id": None,
    } | changes


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (None, StoryBlock.MISSING),
        (piece(version_id=None), StoryBlock.MISSING),
        (piece(status="draft"), StoryBlock.NOT_APPROVED),
        (piece(revision=3), StoryBlock.EDITED),
        (piece(media_purged_at=NOW), StoryBlock.FILES_DELETED),
        (piece(), None),
        # Epic D1: already published by Qualify is never a cause (a new 9:16 creative).
        (piece(published_media_id="1"), None),
    ],
)
def test_piece_causes(row: dict | None, expected: StoryBlock | None) -> None:
    assert piece_block(row) == expected


def asset(kind: str, content_type: str, width: int, height: int) -> dict:
    return {"media_type": kind, "content_type": content_type, "width": width, "height": height}


@pytest.mark.parametrize(
    ("assets", "expected"),
    [
        ([asset("image", "image/png", 1080, 1920)], None),
        (
            [asset("video", "video/mp4", 1080, 1920), asset("image", "image/jpeg", 9, 16)],
            None,
        ),
        ([asset("video", "video/mp4", 1080, 1920)], StoryBlock.VIDEO_WITHOUT_COVER),
        ([asset("image", "image/png", 1080, 1350)], StoryBlock.NO_VERTICAL),
        ([asset("image", "image/webp", 1080, 1920)], StoryBlock.NO_VERTICAL),
        ([asset("video", "video/quicktime", 1080, 1920)], StoryBlock.NO_VERTICAL),
        ([], StoryBlock.NO_VERTICAL),
    ],
)
def test_file_causes(assets: list[dict], expected: StoryBlock | None) -> None:
    assert files_block(assets) == expected


def test_a_numbered_meta_refusal_keeps_its_next_step() -> None:
    assert str(meta_refusal(MarketingError("x", code=190))) == CODE_MESSAGES[190]
    assert (
        str(meta_refusal(MarketingError("x", code=100, subcode=1815199)))
        == (SUBCODE_MESSAGES[1815199])
    )
    # Never Meta's own text; a number we do not know, or an unknown outcome, stays generic.
    assert str(meta_refusal(MarketingError("Meta's text", code=100))) == PREPARE_REFUSED
    assert str(meta_refusal(MarketingError("x", code=190, outcome_unknown=True))) == (
        PREPARE_REFUSED
    )


@pytest.mark.asyncio
async def test_validate_only_refusal_reaches_the_owner_with_its_cause(service) -> None:  # noqa: F811
    *_, client, _ = service

    async def refuse(resource: str, *, params: dict) -> None:
        raise MarketingError("refused", code=294)

    client.validate = refuse
    with pytest.raises(UnpublishedUnavailable) as error:
        await prepare(service)
    assert str(error.value) == CODE_MESSAGES[294]
    assert not client.updates


# -- the local limits, measured at «Ver cómo queda», name the story's own way out --------


@pytest.mark.asyncio
async def test_a_heavy_story_photo_says_to_make_the_historia_again(story, monkeypatch) -> None:  # noqa: F811
    monkeypatch.setattr(module, "MAX_IMAGE_BYTES", 10)
    with pytest.raises(UnpublishedUnavailable) as error:
        await story_prepare(story)
    assert str(error.value) == module.STORY_LIMITS[module.IMAGE_TOO_LARGE]
    assert "elige otro" not in str(error.value) and not story[3].upload_calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("seconds", "limit", "key"),
    [(61, None, module.VIDEO_DURATION), (5, 10, module.TOO_LARGE)],
)
async def test_a_long_or_heavy_story_video_says_to_make_the_historia_again(
    story_video,  # noqa: F811
    monkeypatch,
    seconds: float,
    limit: int | None,
    key: str,
) -> None:
    obj, selected, actor, client, store = story_video
    store.put(selected.vertical.object_key, io.BytesIO(mp4(90, 160, seconds)), "video/mp4")
    if limit:
        monkeypatch.setattr(module, "MAX_VIDEO_BYTES", limit)
    with pytest.raises(UnpublishedUnavailable) as error:
        await obj.prepare(
            tenant_id=selected.tenant_id,
            draft_id=selected.draft_id,
            ad_account_id=selected.account_id,
            feed_asset_id=None,
            vertical_asset_id=selected.vertical.asset_id,
            vertical_thumbnail_asset_id=selected.vertical.thumbnail.asset_id,
            form=form(),
            actor=actor,
            request_key=uuid4(),
            confirm_preparation=True,
        )
    assert str(error.value) == module.STORY_LIMITS[key] and "elige otro" not in str(error.value)
    assert not client.video_uploads


@pytest.mark.asyncio
async def test_a_pair_keeps_its_choose_another_text(service, monkeypatch) -> None:  # noqa: F811
    monkeypatch.setattr(module, "MAX_IMAGE_BYTES", 10)
    with pytest.raises(UnpublishedUnavailable, match="como máximo 8 MB"):
        await prepare(service)
