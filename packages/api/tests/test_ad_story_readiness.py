"""HIS-2 (m-25130282): a historia that cannot be a story ad names its cause, and a Meta
refusal at preparation keeps the next step its number has."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from packages.api.tests.test_ad_unpublished import prepare
from packages.api.tests.test_ad_unpublished import service as service  # noqa: F401

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
