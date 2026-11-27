"""m-25129406 against Postgres: a Clip and its «parte con IA» children are written in ONE
transaction (children of migration 0119 under a `CLIP` parent, no migration of their own),
each with its queued job and its charge row; the same `request_key` makes one; a refused
«Crear» writes nothing; a part settling wakes its waiting Clip and opens no `join`; the
store and the assembly's lookup find the parts — never another business's (RLS). No
vendor is called."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.enums import ContentFormat, ContentKind
from qualify_creative.schemas import ContentBrief, MediaInputs, SourceSegment, VideoPartPlan
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creative import clip_ai_parts as cap
from qualify_api.creative import clip_avatar as ca
from qualify_api.creative import models as orm
from qualify_api.creative.parts import mark_parent_dirty
from qualify_api.creative.video_pipeline import local
from qualify_api.creative.video_pipeline.ai_parts import CLIP_AI_PARTS_SWITCH
from qualify_api.creative.video_pipeline.recipe import RecipeRefused

from . import test_content_service as base

pytestmark = pytest.mark.db


def _clip(brand: UUID, tenant: UUID) -> ContentBrief:
    own = f"uploads/{tenant}/a.mp4"
    return ContentBrief.model_validate(
        {
            "brand_id": brand,
            "objective": "sale",
            "topic": "arepa de chócolo",
            "image_route": "from_upload",
            "source_media_key": own,
            "kind": ContentKind.CLIP,
            "format": ContentFormat.REELS_9_16,
            "variants_requested": 1,
            "media": MediaInputs(
                clip_reference_mode="local",
                segments=(
                    SourceSegment(key=own, start_s=0, end_s=4, speed=1),
                    SourceSegment(kind="ai_part", key="ai_part:0", start_s=0, end_s=5),
                ),
                ai_parts=(
                    VideoPartPlan(mode="reference", seconds=5, description="La arepa servida"),
                ),
                effects_pipeline_version=local.LOCAL_EFFECTS_PIPELINE_VERSION,
            ),
        }
    )


def _world(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from qualify_creative.pricing import JsonPricingTable
    from qualify_creative.router import CreativeRouter

    from qualify_api.creative.composition import DbBrandKitReader, DbVoiceProfileReader
    from qualify_api.creative.creations import PostgresCreationsLedger
    from qualify_api.creative.queue_dispatch import SWITCH, QueueDispatcher
    from qualify_api.creative.service import ContentService

    monkeypatch.setenv(SWITCH, "queue")
    monkeypatch.setenv(CLIP_AI_PARTS_SWITCH, "on")
    monkeypatch.setattr(base, "DB_TENANT", uuid4())
    tenant, brand, user = base.seed_db_tenant()
    pricing = JsonPricingTable("v1")
    content = ContentService(
        router=CreativeRouter(
            {"anthropic": base.FakeCopyAdapter()}, pricing, base.StaticKeyResolver()
        ),
        pricing=pricing,
        credentials=base.StaticKeyResolver(),
        brand_service=DbBrandKitReader(),
        voice_service=DbVoiceProfileReader(),
        creations=PostgresCreationsLedger(),
    )
    content.dispatcher = QueueDispatcher(content.repository, pricing_version=pricing.version)
    service = cap.ClipAiPartsService(content)
    return {"tenant": tenant, "brand": brand, "user": user, "service": service}


def _create(world: dict[str, Any], **kw: Any) -> cap.ClipWithAiParts:
    return world["service"].create_clip_with_ai_parts(
        tenant_id=world["tenant"],
        brand_id=world["brand"],
        user_id=world["user"],
        brief=kw.pop("brief", None) or _clip(world["brand"], world["tenant"]),
        **kw,
    )


def _count(tenant: UUID, sql: str, **params: Any) -> int:
    with tenant_session(tenant) as session:
        return int(session.scalar(text(sql), params) or 0)


def test_the_clip_and_its_parts_are_written_in_one_go(monkeypatch: pytest.MonkeyPatch) -> None:
    world = _world(monkeypatch)
    tenant = world["tenant"]
    key = uuid4()
    made = _create(world, request_key=key)
    assert _create(world, request_key=key) == made  # the same «Crear» again
    (part,) = cap.PostgresAiPartsStore().parts_of(tenant_id=tenant, clip_id=made.clip_id)
    assert part.id == made.part_ids[0] and part.slot == 1 and part.status == "drafting"
    for draft in (made.clip_id, *made.part_ids):
        queued = "SELECT count(*) FROM creative_jobs WHERE draft_id = :d AND status = 'queued'"
        assert _count(tenant, queued, d=draft) == 1
        charges = "SELECT count(*) FROM creation_charges WHERE draft_id = :d"
        assert _count(tenant, charges, d=draft) == 1
    from qualify_creative.creations import load_weights

    previews = "SELECT previews FROM creation_charges WHERE draft_id = :d"
    one = 1 if load_weights().monthly_preview_quota > 0 else 0
    assert _count(tenant, previews, d=made.part_ids[0]) == one  # one vista previa
    # another business sees none of it (RLS)
    assert cap.PostgresAiPartsStore().parts_of(tenant_id=uuid4(), clip_id=made.clip_id) == ()


def test_a_refused_create_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    world = _world(monkeypatch)
    tenant = world["tenant"]
    drafts = _count(tenant, "SELECT count(*) FROM content_drafts")
    monkeypatch.setenv(CLIP_AI_PARTS_SWITCH, "off")
    with pytest.raises(RecipeRefused):
        _create(world)
    assert _count(tenant, "SELECT count(*) FROM content_drafts") == drafts
    assert _count(tenant, "SELECT count(*) FROM creative_jobs") == 0
    assert _count(tenant, "SELECT count(*) FROM creation_charges") == 0


def test_a_part_settling_wakes_its_waiting_clip(monkeypatch: pytest.MonkeyPatch) -> None:
    world = _world(monkeypatch)
    tenant = world["tenant"]
    made = _create(world)
    sql = (
        "SELECT dirty_version FROM creative_pipeline_runs "
        "WHERE draft_id = :c AND phase = 'generation'"
    )
    before = _count(tenant, sql, c=made.clip_id)
    with tenant_session(tenant) as session:
        mark_parent_dirty(session, made.part_ids[0])
    assert _count(tenant, sql, c=made.clip_id) == before + 1
    joins = "SELECT count(*) FROM creative_pipeline_runs WHERE draft_id = :c AND phase = 'join'"
    assert _count(tenant, joins, c=made.clip_id) == 0  # never a join on a Clip


def test_the_lookups_find_the_parts_video_and_mark_it_an_ai_part(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world(monkeypatch)
    tenant = world["tenant"]
    made = _create(world)
    part_id = made.part_ids[0]
    key = f"t/{tenant}/generated/{part_id}/r1/video.mp4"
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE content_drafts SET status = 'generated' WHERE id = :p"), {"p": part_id}
        )
        session.add(
            orm.ImageAsset(
                tenant_id=tenant,
                draft_id=part_id,
                media_url=key,
                object_key=key,
                media_type="video",
                provider="seedance",
                model_id="dreamina-seedance-2-0",
                params={"duration_seconds": 5.0, "part": {"seconds": 5, "mode": "reference"}},
            )
        )
    store = cap.PostgresAiPartsStore()
    (row,) = store.parts_of(tenant_id=tenant, clip_id=made.clip_id)
    assert row.status == "generated" and row.revision == 1
    video = store.part_video(tenant_id=tenant, part_id=part_id)
    assert video is not None and video.object_key == key and video.seconds == 5.0
    sources = ca.PostgresClipAvatarStore().generated_sources(tenant_id=tenant, keys=[key])
    source = sources[key]
    assert source.ai_generated is True and source.block is False
    assert source.ai_part is not None and source.ai_part["mode"] == "reference"
    assert source.clip_id == made.clip_id
    assert ca.PostgresClipAvatarStore().generated_sources(tenant_id=uuid4(), keys=[key]) == {}


def test_a_failed_clip_gives_every_parts_preview_back_in_its_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decided 2026-11-26: a part failed → the Clip fails at once and the vistas previas of
    ALL its parts come back in the same transaction; a second try gives nothing twice."""
    from qualify_api.creative.queue_dispatch import CheckpointError

    world = _world(monkeypatch)
    tenant, content = world["tenant"], world["service"]._content  # noqa: SLF001
    made = _create(world)
    draft = content.repository.get_draft(tenant_id=tenant, draft_id=made.clip_id)
    rows = cap.PostgresAiPartsStore().parts_of(tenant_id=tenant, clip_id=made.clip_id)
    give_back = [(row.id, row.revision) for row in rows]
    status = "SELECT status FROM content_drafts WHERE id = :d"
    refunded = "SELECT count(*) FROM creation_charges WHERE draft_id = :d AND status = 'refunded'"
    cancelled = "SELECT count(*) FROM creative_jobs WHERE draft_id = :d AND status = 'cancelled'"

    # a give-back that breaks rolls the whole write back: nothing failed, nothing given
    ledger = content.creations
    real = ledger.refund
    monkeypatch.setattr(ledger, "refund", lambda **_: (_ for _ in ()).throw(RuntimeError()))
    with pytest.raises(RuntimeError):
        content._fail_waiting_clip(  # noqa: SLF001
            tenant,
            draft,
            reason=cap.AI_PART_FAILED,
            detail=cap.AI_PART_FAILED_TEXT,
            give_back=give_back,
            stop_children=True,
        )
    with tenant_session(tenant) as session:
        assert session.scalar(text(status), {"d": made.clip_id}) == "drafting"
        assert session.scalar(text(status), {"d": made.part_ids[0]}) == "drafting"
    assert _count(tenant, refunded, d=made.part_ids[0]) == 0
    assert _count(tenant, cancelled, d=made.part_ids[0]) == 0
    monkeypatch.setattr(ledger, "refund", real)

    content._fail_waiting_clip(  # noqa: SLF001
        tenant,
        draft,
        reason=cap.AI_PART_FAILED,
        detail=cap.AI_PART_FAILED_TEXT,
        give_back=give_back,
        stop_children=True,
    )
    for part_id in made.part_ids:
        assert _count(tenant, refunded, d=part_id) == 1
        # the part still being made stops with its Clip, its unsent job cancelled
        assert _count(tenant, cancelled, d=part_id) == 1
        with tenant_session(tenant) as session:
            assert session.scalar(text(status), {"d": part_id}) == "failed"
    with tenant_session(tenant) as session:
        assert session.scalar(text(status), {"d": made.clip_id}) == "failed"
    # the ledger never gives back twice
    content._give_back_parts(tenant, give_back, "again")  # noqa: SLF001
    assert _count(tenant, refunded, d=made.part_ids[0]) == 1
    with pytest.raises(CheckpointError):  # the Clip already moved: nothing again
        content._fail_waiting_clip(  # noqa: SLF001
            tenant, draft, reason="x", detail="y", give_back=give_back
        )
    assert _count(tenant, refunded, d=made.part_ids[0]) == 1
