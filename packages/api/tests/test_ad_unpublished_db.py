"""Real RLS, immutable claims, source revisions and distinct unpublished result ownership."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from packages.api.tests.test_ad_audience_db import audience_world as shared_audience_world
from qualify_shared.db.session import tenant_session, tenant_unit_of_work
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from qualify_api.ads.enhancements import BrandEnhancementSettings, compose_brand_policy
from qualify_api.ads.promotion_repository import PostgresPromotionRepository
from qualify_api.ads.promotions import STEPS, PromotionRequest, step_payload
from qualify_api.ads.results_service import _scope
from qualify_api.ads.unpublished import ImageAdForm, UnpublishedUnavailable, creative_payload
from qualify_api.ads.unpublished_repository import (
    UnpublishedRepository,
    guard_source,
    load_image_source,
)
from qualify_api.auth.business import NotAMember
from qualify_api.tenancy.acting import acting_login

pytestmark = pytest.mark.db
audience_world = shared_audience_world


@pytest.fixture
def unpublished_world(audience_world):
    ids, login, actor, connection, brand = audience_world
    tenant, account = ids["tenant_id"], ids["ad_account_id"]
    draft, version, feed, vertical = (uuid4() for _ in range(4))
    with tenant_session(tenant) as session:
        brief = session.scalar(
            text("SELECT brief_id FROM content_drafts WHERE id=:id"),
            {"id": ids["content_draft_id"]},
        )
        session.execute(
            text("""INSERT INTO content_drafts
          (id,tenant_id,brand_id,brief_id,status,pipeline_version,revision,approved_revision)
          VALUES(:draft,:tenant,:brand,:brief,'approved','fixture',1,1)"""),
            {"draft": draft, "tenant": tenant, "brand": brand, "brief": brief},
        )
        session.execute(
            text("""INSERT INTO piece_versions
          (id,tenant_id,brand_id,draft_id,revision,status)
          VALUES(:version,:tenant,:brand,:draft,1,'active')"""),
            {"version": version, "tenant": tenant, "brand": brand, "draft": draft},
        )
        session.execute(
            text("UPDATE content_drafts SET active_version_id=:version WHERE id=:draft"),
            {"version": version, "draft": draft},
        )
        for asset, width, height in ((feed, 40, 50), (vertical, 90, 160)):
            session.execute(
                text("""INSERT INTO image_assets
              (id,tenant_id,draft_id,version_id,media_url,object_key,content_type,width,height,media_type)
              VALUES(:id,:tenant,:draft,:version,'unused',:key,'image/png',:width,:height,'image')"""),
                {
                    "id": asset,
                    "tenant": tenant,
                    "draft": draft,
                    "version": version,
                    "key": f"t/{tenant}/generated/{draft}/{asset}.png",
                    "width": width,
                    "height": height,
                },
            )
    with acting_login(login):
        source = load_image_source(tenant, draft, account, feed, vertical)
    now = datetime.now(UTC)
    form = ImageAdForm(
        "Texto",
        "Título",
        "https://example.org",
        100_00,
        now + timedelta(days=1),
        now + timedelta(days=2),
        "CO",
    )
    return source, form, login, actor


def test_source_version_ownership_and_upload_claim_survives_rollback(unpublished_world):
    source, form, login, actor = unpublished_world
    repo = UnpublishedRepository()
    with acting_login(login):
        recipe = repo.approve(source, form, actor, uuid4())
        with pytest.raises(RuntimeError), tenant_unit_of_work(source.tenant_id):
            row, fresh = repo.claim_upload(source, source.feed, "a" * 64)
            assert fresh
            raise RuntimeError("outer rollback")
        same, fresh = repo.claim_upload(source, source.feed, "a" * 64)
        assert not fresh and same["id"] == row["id"] and same["state"] == "creating"
        repo.finish_upload(source.tenant_id, row["id"], None)
        with pytest.raises(IntegrityError), tenant_session(source.tenant_id) as session:
            session.execute(
                text("UPDATE ad_unpublished_uploads SET state='creating' WHERE id=:id"),
                {"id": row["id"]},
            )
        with pytest.raises(IntegrityError), tenant_session(source.tenant_id) as session:
            session.execute(
                text("UPDATE ad_unpublished_sources SET source='{}' WHERE id=:id"),
                {"id": recipe["id"]},
            )
        with tenant_session(uuid4()) as session:
            assert session.scalar(text("SELECT count(*) FROM ad_unpublished_sources")) == 0
            assert session.scalar(text("SELECT count(*) FROM ad_unpublished_uploads")) == 0
        with pytest.raises(UnpublishedUnavailable):
            load_image_source(
                source.tenant_id,
                source.draft_id,
                source.account_id,
                uuid4(),
                source.vertical.asset_id,
            )
        # A competing HTTP request cannot obtain a second dispatch claim for identical bytes.
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(
                pool.map(lambda _: repo.claim_upload(source, source.vertical, "b" * 64), range(2))
            )
        assert sum(fresh for _, fresh in claims) == 1
        with tenant_session(source.tenant_id) as session:
            session.execute(
                text("UPDATE content_drafts SET revision=revision+1 WHERE id=:id"),
                {"id": source.draft_id},
            )
        with pytest.raises(UnpublishedUnavailable):
            guard_source(source)


def test_unpublished_promotion_has_read_pause_scope_without_publish_attempt(unpublished_world):
    source, form, login, actor = unpublished_world
    repo = UnpublishedRepository()
    with acting_login(login):
        recipe = repo.approve(source, form, actor, uuid4())
        request = compose_brand_policy(
            PromotionRequest(
                source.tenant_id,
                source.brand_id,
                str(uuid4()),
                source.meta_account_id,
                "OUTCOME_TRAFFIC",
                "LEARN_MORE",
                form.link_url,
                "lifetime",
                form.budget_minor,
                "COP",
                form.start_time,
                form.end_time,
                actor,
                recipe["approved_at"],
                content_draft_id=source.draft_id,
                creative=creative_payload(source, form, ("hash1", "hash2")),
            ),
            BrandEnhancementSettings(source.tenant_id, source.brand_id),
        )
        promotions = PostgresPromotionRepository()
        promotion = promotions.create_or_get(request)
        repo.link(source.tenant_id, recipe["id"], promotion.id)
        for resource in STEPS:
            token = uuid4()
            promotion = promotions.get(source.tenant_id, promotion.id)
            assert promotions.claim(
                source.tenant_id, promotion.id, resource, step_payload(promotion, resource), token
            )
            assert promotions.complete(
                source.tenant_id, promotion.id, resource, token, str(uuid4().int)
            )
        scoped = _scope(source.tenant_id, promotion.id)
        assert scoped.connection.connection_id == source.connection_id
        # Pausing stays possible after the piece is edited: its original recipe is
        # immutable provenance, not a requirement to keep spending-approved content editable.
        with tenant_session(source.tenant_id) as session:
            session.execute(
                text("UPDATE content_drafts SET revision=revision+1 WHERE id=:id"),
                {"id": source.draft_id},
            )
        assert _scope(source.tenant_id, promotion.id) == scoped
        with tenant_session(source.tenant_id) as session:
            session.execute(
                text("UPDATE ad_accounts SET credential_version=credential_version+1 WHERE id=:id"),
                {"id": source.account_id},
            )
        from qualify_api.ads.results import ResultsUnavailable

        with pytest.raises(ResultsUnavailable):
            _scope(source.tenant_id, promotion.id)
        with pytest.raises(NotAMember):
            repo.approve(replace(source, tenant_id=uuid4()), form, actor, uuid4())


def test_video_source_covers_claims_and_transitions(unpublished_world):
    source, form, login, actor = unpublished_world
    clips, covers = [], []
    with tenant_session(source.tenant_id) as session:
        version = session.scalar(
            text("SELECT active_version_id FROM content_drafts WHERE id=:id"),
            {"id": source.draft_id},
        )
        for width, height in ((40, 50), (90, 160)):
            for media, kind, out in (("video", "video/mp4", clips), ("image", "image/png", covers)):
                asset = uuid4()
                session.execute(
                    text("""INSERT INTO image_assets
                  (id,tenant_id,draft_id,version_id,media_url,object_key,content_type,width,height,
                   media_type)
                  VALUES(:id,:tenant,:draft,:version,'unused',:key,:kind,:width,:height,:media)"""),
                    {
                        "id": asset,
                        "tenant": source.tenant_id,
                        "draft": source.draft_id,
                        "version": version,
                        "key": f"t/{source.tenant_id}/generated/{asset}",
                        "kind": kind,
                        "width": width,
                        "height": height,
                        "media": media,
                    },
                )
                out.append(asset)
    repo = UnpublishedRepository()
    with acting_login(login):
        args = (source.tenant_id, source.draft_id, source.account_id, *clips)
        with pytest.raises(UnpublishedUnavailable, match="portada"):
            load_image_source(*args)
        with pytest.raises(UnpublishedUnavailable, match="mezclar"):
            load_image_source(
                source.tenant_id,
                source.draft_id,
                source.account_id,
                source.feed.asset_id,
                clips[1],
                (None, covers[1]),
            )
        with pytest.raises(UnpublishedUnavailable):  # a cover must be an image
            load_image_source(*args, (clips[0], covers[1]))
        video = load_image_source(*args, tuple(covers))
        assert video.is_video and video.feed.thumbnail.asset_id == covers[0]
        guard_source(video)
        recipe = repo.approve(video, form, actor, uuid4())
        assert recipe["pipeline_version"] == "ad-unpublished-video-v1"
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(
                pool.map(lambda _: repo.claim_video(video, video.feed, "c" * 64, 10), range(2))
            )
        tokens = [token for _, token in claims if token is not None]
        assert len(tokens) == 1
        row = next(row for row, token in claims if token is not None)
        repo.video_named(video.tenant_id, row["id"], tokens[0], "901")
        with pytest.raises(UnpublishedUnavailable):  # nothing can rename the remote video
            repo.video_named(video.tenant_id, row["id"], tokens[0], "902")
        with pytest.raises(IntegrityError):  # a named video never returns to ready
            repo.finish_video(video.tenant_id, row["id"], tokens[0], "ready")
        repo.finish_video(video.tenant_id, row["id"], tokens[0], "processing")
        repo.video_checked(video.tenant_id, row["id"], "processing")
        repo.video_checked(video.tenant_id, row["id"], "ready_remote")
        again, token = repo.claim_video(video, video.feed, "c" * 64, 10)
        assert token is None and again["state"] == "ready_remote" and again["video_id"] == "901"
        with pytest.raises(IntegrityError), tenant_session(video.tenant_id) as session:
            session.execute(
                text("UPDATE ad_unpublished_videos SET state='processing' WHERE id=:id"),
                {"id": row["id"]},
            )
        # Unsent claims go back to ready; an unknown send stays unknown.
        fresh, token = repo.claim_video(video, video.vertical, "d" * 64, 10)
        repo.finish_video(video.tenant_id, fresh["id"], token, "ready")
        fresh, token = repo.claim_video(video, video.vertical, "d" * 64, 10)
        repo.finish_video(video.tenant_id, fresh["id"], token, "unknown")
        assert repo.claim_video(video, video.vertical, "d" * 64, 10)[1] is None
        # A claim whose process died stays submitting; once idle 30 minutes it is unknown.
        crashed, token = repo.claim_video(video, video.vertical, "e" * 64, 10)
        assert token is not None
        with pytest.raises(IntegrityError), tenant_session(video.tenant_id) as session:
            session.execute(  # a fresh claim cannot be declared stale
                text("""UPDATE ad_unpublished_videos SET state='unknown',claim_token=NULL,
                  detail='stale claim' WHERE id=:id"""),
                {"id": crashed["id"]},
            )
        assert repo.claim_video(video, video.vertical, "e" * 64, 10)[0]["state"] == "submitting"
        with tenant_session(video.tenant_id) as session:
            session.execute(
                text("""UPDATE ad_unpublished_videos SET updated_at=now()-interval '1 hour'
                  WHERE id=:id"""),
                {"id": crashed["id"]},
            )
        stale, again = repo.claim_video(video, video.vertical, "e" * 64, 10)
        assert again is None and stale["state"] == "unknown" and stale["detail"] == "stale claim"
        with pytest.raises(UnpublishedUnavailable):  # the dead holder can no longer settle
            repo.finish_video(video.tenant_id, crashed["id"], token, "processing")
        with tenant_session(uuid4()) as session:
            assert session.scalar(text("SELECT count(*) FROM ad_unpublished_videos")) == 0
