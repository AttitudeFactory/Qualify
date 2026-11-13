"""m-24820842 (drafts 9808559f / cb647505 / 0bcd259b): a clip made from photo A (opening),
photo B (between) and photo C (closing) plus two reference videos was stored with
`clip_image_keys=[]`. The backend's whole path — `MediaInputs` validation, `create_draft`'s
normalization, `prepare_new_brief` and the insert (a full `model_dump`, never updated
afterwards) — must keep B; a creation log line says how many middle photos arrived and how
many were stored."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import pytest
from qualify_creative.enums import ContentKind
from qualify_creative.schemas import MediaInputs

from .test_content_service import (
    BRAND_ID,
    TENANT_ID,
    USER_ID,
    make_brief,
    make_kit,
    make_service,
    make_voice,
)
from .test_creative_clip import _clip_producer, _clip_store
from .test_creative_media_byteplus import FakeSeedance

T = "9cd9637c-8bd0-4293-9d68-40a71c140c00"
A = f"uploads/{T}/catalog/p/a.jpg"
B = f"uploads/{T}/catalog/p/b.jpg"
C = f"t/{T}/stock/pixabay/1/c.jpg"
VIDEOS = (f"t/{T}/stock/pixabay/video-1/v1.mp4", f"t/{T}/stock/pixabay/video-2/v2.mp4")


def _clip_brief(brand_id: UUID = BRAND_ID) -> Any:
    return make_brief(
        variants=1,
        brand_id=brand_id,
        kind=ContentKind.CLIP,
        media=MediaInputs(
            duration_seconds=5,
            clip_first_frame_key=A,
            clip_last_frame_key=C,
            clip_image_keys=(B,),
            clip_image_roles=("product",),
            clip_video_keys=VIDEOS,
            product_source="catalog",
        ),
    )


def test_the_middle_photo_survives_create_and_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="qualify_api.creative.service")
    producer = _clip_producer(_clip_store(), FakeSeedance())  # the real prepare_new_brief
    service, repo, _ = make_service(kit=make_kit(), voice=make_voice(), media=producer)
    service.dispatcher = None
    draft_id = service.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=_clip_brief(), user_id=USER_ID
    )
    stored = repo.get_brief(tenant_id=TENANT_ID, brief_id=repo.drafts[draft_id].brief_id)
    assert stored is not None
    assert stored.media.clip_image_keys == (B,)
    assert stored.media.clip_image_roles == ("product",)
    assert (stored.media.clip_first_frame_key, stored.media.clip_last_frame_key) == (A, C)
    assert stored.media.clip_video_keys == VIDEOS
    assert any("1 middle image(s) received, 1 stored" in r.getMessage() for r in caplog.records)


@pytest.mark.db
def test_the_stored_row_keeps_the_middle_photo() -> None:
    from qualify_api.creative.service import PostgresContentRepository

    from . import test_content_service as base

    tenant_id, brand_id, user_id = base.seed_db_tenant()
    repo = PostgresContentRepository()
    draft_id = repo.insert_brief_and_draft(
        tenant_id=tenant_id,
        user_id=user_id,
        brief=_clip_brief(brand_id),
        voice_profile_version=1,
        pipeline_version="creative-v2-brand9",
        request_key=None,
    )
    record = repo.get_draft(tenant_id=tenant_id, draft_id=draft_id)
    stored = repo.get_brief(tenant_id=tenant_id, brief_id=record.brief_id)
    assert stored is not None and stored.media.clip_image_keys == (B,)
