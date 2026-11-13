"""Story ads (m-25026350): one 9:16 asset, only Instagram stories, a link button; the
unpublished image/video pairs keep their exact snapshot."""

from __future__ import annotations

import asyncio
import io
from dataclasses import asdict, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from packages.api.tests.test_ad_unpublished import form, source
from packages.api.tests.test_ad_unpublished import service as service  # noqa: F401
from PIL import Image

from qualify_api.ads import unpublished_service as module
from qualify_api.ads.unpublished import (
    PIPELINE,
    STORY_FORMAT,
    STORY_PIPELINE,
    STORY_VIDEO_PIPELINE,
    ImageAdForm,
    ImageSelection,
    ImageSource,
    UnpublishedUnavailable,
    VideoSelection,
    creative_payload,
    recipe_hash,
    video_creative_payload,
)
from qualify_api.ads.unpublished_repository import thumbnails


@pytest.fixture
def story(service, monkeypatch):  # noqa: F811
    obj, selected, actor, client, store = service
    chosen = replace(selected, feed=None)
    monkeypatch.setattr(module, "load_image_source", lambda *args: chosen)
    return obj, chosen, actor, client, store


async def prepare(bundle, chosen_form=None):
    obj, selected, actor, *_ = bundle
    return await obj.prepare(
        tenant_id=selected.tenant_id,
        draft_id=selected.draft_id,
        ad_account_id=selected.account_id,
        feed_asset_id=None,
        vertical_asset_id=selected.vertical.asset_id,
        form=chosen_form or form(),
        actor=actor,
        request_key=uuid4(),
        confirm_preparation=True,
    )


@pytest.mark.asyncio
async def test_story_ad_is_stories_only_with_the_piece_link_button_and_needs_consent(story):
    obj, selected, actor, client, _ = story
    preview = await prepare(story, replace(form(), cta_type="SHOP_NOW"))
    assert client.upload_calls == 1 and len(client.objects) == 4
    assert client.previews == ["INSTAGRAM_STORY"]
    assert preview.feed_html == "" and preview.vertical_html == "preview:INSTAGRAM_STORY"
    adset = next(row for row in client.objects.values() if row["_resource"] == "adsets")
    assert adset["targeting"]["publisher_platforms"] == ["instagram"]
    assert adset["targeting"]["instagram_positions"] == ["story"]
    assert (adset["optimization_goal"], adset["destination_type"]) == ("LINK_CLICKS", "WEBSITE")
    creative = next(row for row in client.objects.values() if row["_resource"] == "adcreatives")
    assert "asset_feed_spec" not in creative
    link = creative["object_story_spec"]["link_data"]
    assert link["call_to_action"] == {"type": "SHOP_NOW", "value": {"link": "https://example.org"}}
    assert link["image_hash"] == "hash1" and link["link"] == "https://example.org"
    review = obj.reviews.get(selected.tenant_id, preview.review_id)
    assert review.checks_snapshot["kind"] == "unpublished-story-images"
    assert review.checks_snapshot["source"]["pipeline"] == STORY_PIPELINE
    assert not client.updates  # nothing runs before the spending consent
    with pytest.raises(UnpublishedUnavailable, match="Confirma"):
        await obj.confirm(
            tenant_id=selected.tenant_id,
            recipe_id=preview.recipe_id,
            review_id=preview.review_id,
            actor=actor,
            confirm_charge=False,
        )
    result = await asyncio.wait_for(
        obj.confirm(
            tenant_id=selected.tenant_id,
            recipe_id=preview.recipe_id,
            review_id=preview.review_id,
            actor=actor,
            confirm_charge=True,
        ),
        3,
    )
    assert result == "active" and len(client.updates) == 3


@pytest.mark.asyncio
async def test_a_story_that_is_not_9_16_is_refused_before_any_meta_call(story, monkeypatch):
    obj, selected, actor, client, _ = story
    wrong = replace(selected, vertical=replace(selected.vertical, width=40, height=50))
    monkeypatch.setattr(module, "load_image_source", lambda *args: wrong)
    with pytest.raises(UnpublishedUnavailable, match="9:16 para la historia"):
        await prepare(story)
    assert client.upload_calls == 0 and not client.calls and not obj.recipes.rows


@pytest.mark.asyncio
async def test_an_unreadable_story_image_is_refused_before_any_meta_call(story):
    obj, selected, actor, client, store = story
    store.objects[selected.vertical.object_key] = b"not an image"
    with pytest.raises(UnpublishedUnavailable):
        await prepare(story)
    assert client.upload_calls == 0 and not client.calls and not obj.recipes.rows


def test_call_now_is_never_a_story_button():
    with pytest.raises(UnpublishedUnavailable):
        replace(form(), cta_type="CALL_NOW").validate(datetime.now(UTC))


def test_story_video_carries_its_cover_and_button_in_video_data():
    pair = source()
    cover = ImageSelection(uuid4(), "t/x/cover.png", "image/png", 90, 160)
    video = VideoSelection(uuid4(), "t/x/v.mp4", "video/mp4", 1080, 1920, cover)
    chosen = replace(pair, feed=None, vertical=video)
    assert chosen.snapshot()["pipeline"] == STORY_VIDEO_PIPELINE
    spec = video_creative_payload(chosen, form(), (("123", "cover-hash"),))["object_story_spec"]
    assert spec["video_data"] == {
        "video_id": "123",
        "image_hash": "cover-hash",
        "message": "Prueba",
        "title": "Título",
        "call_to_action": {"type": "LEARN_MORE", "value": {"link": "https://example.org"}},
    }
    with pytest.raises(UnpublishedUnavailable, match="9:16 para la historia"):
        replace(chosen, vertical=replace(video, thumbnail=replace(cover, width=40))).snapshot()
    with pytest.raises(UnpublishedUnavailable):
        video_creative_payload(chosen, form(), (("123", "a"), ("456", "b")))
    assert thumbnails(chosen.snapshot()) == (None, cover.asset_id)


def test_pair_snapshot_and_hash_are_unchanged_and_differ_from_the_story():
    pair = source()
    snapshot = pair.snapshot()
    # The pair snapshot is exactly the dataclass plus its pipeline: no story key leaks in.
    assert set(snapshot) == set(asdict(pair)) | {"pipeline"} and snapshot["pipeline"] == PIPELINE
    assert snapshot["feed"]["asset_id"] == str(pair.feed.asset_id)
    # Golden hash computed with main's unpublished.py before this change (4e74c550).
    u = UUID

    def img(n, width, height):
        return ImageSelection(
            u(int=n), f"t/{u(int=1)}/generated/{n}.png", "image/png", width, height
        )

    fixed = ImageSource(
        *(u(int=n) for n in (1, 2, 3, 4)),
        3,
        u(int=5),
        u(int=6),
        2,
        "12",
        "42",
        "7",
        "COP",
        "America/Bogota",
        img(7, 40, 50),
        img(8, 90, 160),
    )
    fixed_form = ImageAdForm(
        "Prueba",
        "Título",
        "https://example.org",
        100_00,
        datetime(2030, 1, 1, tzinfo=UTC),
        datetime(2030, 1, 2, tzinfo=UTC),
        "CO",
    )
    stored = recipe_hash(fixed, fixed_form, u(int=9))
    assert stored == "44823b49a46c61faac2a964490e2e0f64ec167597058ee94c52287c158804066"
    assert recipe_hash(replace(fixed, feed=None), fixed_form, u(int=9)) != stored
    spec = creative_payload(pair, form(), ("a", "b"))
    assert "asset_customization_rules" in spec["asset_feed_spec"]
    with pytest.raises(UnpublishedUnavailable):
        creative_payload(replace(pair, feed=None), form(), ("a", "b"))


def test_story_image_is_measured_like_a_pair_image(story):
    obj, selected, *_ = story
    data = io.BytesIO()
    Image.new("RGB", (selected.vertical.width, selected.vertical.height)).save(data, "PNG")
    assert module.image_bytes(obj.gate, selected, selected.vertical)
    assert selected.snapshot()["feed"] is None
    with pytest.raises(UnpublishedUnavailable, match=STORY_FORMAT[:20]):
        replace(selected, vertical=replace(selected.vertical, content_type="image/gif")).snapshot()
