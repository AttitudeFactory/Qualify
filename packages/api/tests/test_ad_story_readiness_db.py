"""HIS-2 (m-25130282): each cause a historia cannot be a story ad, read against real
Postgres and RLS. Each case changes one fact of a ready piece and puts it back."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from packages.api.tests.test_ad_audience_db import audience_world as shared_audience_world
from packages.api.tests.test_ad_unpublished_db import unpublished_world as shared_unpublished
from qualify_shared.db.connection_purge import connection_purge_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.enhancements import FEATURES
from qualify_api.ads.enhancements_service import save_brand_enhancements
from qualify_api.ads.story_readiness import StoryBlock, story_block
from qualify_api.tenancy.acting import acting_login

pytestmark = pytest.mark.db
audience_world = shared_audience_world
unpublished_world = shared_unpublished

_CASES = [
    (StoryBlock.NOT_APPROVED, "UPDATE content_drafts SET status='draft' WHERE id=:draft"),
    (StoryBlock.EDITED, "UPDATE content_drafts SET revision=revision+1 WHERE id=:draft"),
    (StoryBlock.FILES_DELETED, "UPDATE content_drafts SET media_purged_at=now() WHERE id=:draft"),
    (StoryBlock.NO_VERTICAL, "UPDATE image_assets SET height=width WHERE id=:vertical"),
    (
        StoryBlock.VIDEO_WITHOUT_COVER,
        "UPDATE image_assets SET media_type='video',content_type='video/mp4' WHERE id=:vertical",
    ),
    (StoryBlock.NO_AD_ACCOUNT, "UPDATE ad_accounts SET selected=false WHERE id=:account"),
    (StoryBlock.RECONNECT, "UPDATE ad_accounts SET available=false WHERE id=:account"),
    (StoryBlock.CURRENCY, "UPDATE ad_accounts SET currency='USD' WHERE id=:account"),
]


def _ids(source) -> dict:
    return {
        "draft": source.draft_id,
        "vertical": source.vertical.asset_id,
        "account": source.account_id,
    }


@pytest.mark.parametrize(("expected", "change"), _CASES, ids=[c[0].value for c in _CASES])
def test_each_cause_is_named(unpublished_world, expected: StoryBlock, change: str) -> None:
    source, _, login, _ = unpublished_world
    with acting_login(login):
        assert story_block(source.tenant_id, source.draft_id) is None
    with tenant_session(source.tenant_id) as session:
        session.execute(text(change), _ids(source))
    with acting_login(login):
        assert story_block(source.tenant_id, source.draft_id) == expected


def test_another_business_only_sees_a_missing_piece(unpublished_world) -> None:
    source, *_ = unpublished_world
    assert story_block(uuid4(), source.draft_id) == StoryBlock.MISSING
    assert story_block(source.tenant_id, uuid4()) == StoryBlock.MISSING


def test_a_chat_button_saved_in_the_piece(unpublished_world) -> None:
    source, _, login, _ = unpublished_world
    variant = uuid4()
    copy = {"caption": "Texto", "ads_cta_type": "WHATSAPP_MESSAGE", "ads_destination_url": ""}
    with tenant_session(source.tenant_id) as session:
        session.execute(
            text("""INSERT INTO copy_variants (id,tenant_id,draft_id,ordinal,copy,model_id)
          VALUES(:id,:tenant,:draft,0,CAST(:copy AS jsonb),'fixture')"""),
            {
                "id": variant,
                "tenant": source.tenant_id,
                "draft": source.draft_id,
                "copy": json.dumps(copy | {"ads_destination_url": "https://example.org"}),
            },
        )
        session.execute(
            text("UPDATE content_drafts SET selected_variant_id=:variant WHERE id=:draft"),
            {"variant": variant, "draft": source.draft_id},
        )
    with acting_login(login):
        assert story_block(source.tenant_id, source.draft_id) == StoryBlock.BUTTON


def test_brand_letting_meta_change_its_ads(unpublished_world) -> None:
    source, _, login, _ = unpublished_world
    with acting_login(login):
        save_brand_enhancements(
            tenant_id=source.tenant_id,
            brand_id=source.brand_id,
            values=dict.fromkeys(FEATURES, False) | {FEATURES[0]: True},
            expected_version=0,
        )
        assert story_block(source.tenant_id, source.draft_id) == StoryBlock.ENHANCEMENTS


def test_missing_permission_to_advertise(unpublished_world) -> None:
    source, _, login, _ = unpublished_world
    with connection_purge_session(source.tenant_id) as session:
        session.execute(
            text("DELETE FROM ad_oauth_credentials WHERE connection_id=:connection"),
            {"connection": source.connection_id},
        )
    with acting_login(login):
        assert story_block(source.tenant_id, source.draft_id) == StoryBlock.AD_PERMISSION
