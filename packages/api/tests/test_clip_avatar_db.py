"""m-25112920 against Postgres: an avatar block is a child of its Clip in a slot of
migration 0119 (no migration of its own); the store finds the blocks, their kept video
and the stretches that are blocks' videos — never another business's (RLS); and a block
settling opens no `join` on its Clip (only a video by parts joins). No vendor is called."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.enums import ContentFormat, ContentKind
from qualify_creative.schemas import ContentBrief, MediaInputs, SourceSegment
from qualify_shared.db.session import tenant_session
from sqlalchemy import create_engine, text

from qualify_api.creative import clip_avatar as ca
from qualify_api.creative import models as orm
from qualify_api.creative.parts import mark_parent_dirty
from qualify_api.creative.service import PostgresContentRepository

from . import test_content_service as base

pytestmark = pytest.mark.db


def _business(monkeypatch: pytest.MonkeyPatch) -> tuple[UUID, UUID, UUID]:
    monkeypatch.setattr(base, "DB_TENANT", uuid4())
    return base.seed_db_tenant()


def _clip(brand: UUID, tenant: UUID) -> ContentBrief:
    return ContentBrief.model_validate(
        {
            "brand_id": brand,
            "objective": "sale",
            "topic": "arepa de chócolo",
            "image_route": "from_upload",
            "source_media_key": f"uploads/{tenant}/a.mp4",
            "kind": ContentKind.CLIP,
            "format": ContentFormat.REELS_9_16,
            "variants_requested": 1,
            "media": MediaInputs(
                clip_reference_mode="local",
                segments=(
                    SourceSegment(key=f"uploads/{tenant}/a.mp4", start_s=0, end_s=4, speed=1),
                ),
            ),
        }
    )


def _world(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    tenant, brand, user = _business(monkeypatch)
    repo = PostgresContentRepository()
    clip_brief = _clip(brand, tenant)
    clip = repo.insert_brief_and_draft(
        tenant_id=tenant,
        user_id=user,
        brief=clip_brief,
        voice_profile_version=1,
        pipeline_version="creative-v1",
    )
    request = ca.AvatarBlockRequest(
        kind="presenter", script="Hola, soy Ana.", avatar_prompt="Mujer sonriente"
    )
    block = repo.insert_brief_and_draft(
        tenant_id=tenant,
        user_id=user,
        brief=ca.block_brief(clip_brief, request),
        voice_profile_version=1,
        pipeline_version="creative-v1",
        parent_draft_id=clip,
        part_index=1,
    )
    key = f"t/{tenant}/generated/{block}/r1/video.mp4"
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE content_drafts SET status = 'generated' WHERE id IN (:c, :b)"),
            {"c": clip, "b": block},
        )
        session.add(
            orm.ImageAsset(
                tenant_id=tenant,
                draft_id=block,
                media_url=key,
                object_key=key,
                media_type="video",
                provider="omnihuman",
                model_id="omnihuman-1.5",
                params={"duration_seconds": 4.2, "model_revision": "omni15"},
            )
        )
    return {"tenant": tenant, "user": user, "clip": clip, "block": block, "key": key}


def test_the_store_finds_the_block_its_video_and_its_stretch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world(monkeypatch)
    tenant, clip, block, key = world["tenant"], world["clip"], world["block"], world["key"]
    store = ca.PostgresClipAvatarStore()
    row = store.clip(tenant_id=tenant, clip_id=clip)
    assert row is not None and row.status == "generated" and row.parent_draft_id is None
    (found,) = store.blocks_of(tenant_id=tenant, clip_id=clip)
    assert (found.id, found.slot, found.kind, found.removed) == (block, 1, "presenter", False)
    video = store.block_video(tenant_id=tenant, block_id=block)
    assert video is not None and video.object_key == key and video.seconds == 4.2
    owned = f"uploads/{tenant}/a.mp4"
    sources = store.generated_sources(tenant_id=tenant, keys=[key, owned])
    assert list(sources) == [key]
    source = sources[key]
    assert source.block_id == block and source.clip_id == clip
    assert (source.provider, source.model_id, source.model_revision) == (
        "omnihuman",
        "omnihuman-1.5",
        "omni15",
    )
    # another business sees nothing of it (RLS)
    other = uuid4()
    assert store.clip(tenant_id=other, clip_id=clip) is None
    assert store.blocks_of(tenant_id=other, clip_id=clip) == ()
    assert store.generated_sources(tenant_id=other, keys=[key]) == {}
    assert source.block is True and source.ai_generated is True


def test_a_seedance_piece_reads_as_ai_and_an_own_composition_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The label's evidence as Postgres keeps it: a Seedance clip's asset is AI by its
    provider; our composition of the owner's photos (provider `qualify`, a draft that
    needs no disclosure) is not; neither is a block."""
    world = _world(monkeypatch)
    tenant, user = world["tenant"], world["user"]
    repo = PostgresContentRepository()
    made: dict[str, str] = {}
    for name, provider in (("seedance", "seedance"), ("own", "qualify")):
        draft = repo.insert_brief_and_draft(
            tenant_id=tenant,
            user_id=user,
            brief=_clip(_brand_of(tenant, world["clip"]), tenant),
            voice_profile_version=1,
            pipeline_version="creative-v1",
        )
        key = f"t/{tenant}/generated/{draft}/r1/video.mp4"
        with tenant_session(tenant) as session:
            session.execute(
                text("UPDATE content_drafts SET requires_ai_disclosure = false WHERE id = :d"),
                {"d": draft},
            )
            session.add(
                orm.ImageAsset(
                    tenant_id=tenant,
                    draft_id=draft,
                    media_url=key,
                    object_key=key,
                    media_type="video",
                    provider=provider,
                    model_id=f"{provider}-model",
                    params={"duration_seconds": 4.0},
                )
            )
        made[name] = key
    sources = ca.PostgresClipAvatarStore().generated_sources(
        tenant_id=tenant, keys=list(made.values())
    )
    seedance, own = sources[made["seedance"]], sources[made["own"]]
    assert (seedance.ai_generated, seedance.block) == (True, False)
    assert (own.ai_generated, own.block) == (False, False)


def _brand_of(tenant: UUID, draft: UUID) -> UUID:
    with tenant_session(tenant) as session:
        return session.scalar(
            text("SELECT brand_id FROM content_drafts WHERE id = :d"), {"d": draft}
        )


def test_the_slot_is_unique_under_the_clip(monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlalchemy.exc import IntegrityError

    world = _world(monkeypatch)
    repo = PostgresContentRepository()
    with tenant_session(world["tenant"]) as session:
        brief_id = session.scalar(
            text("SELECT brief_id FROM content_drafts WHERE id = :b"), {"b": world["block"]}
        )
    brief = repo.get_brief(tenant_id=world["tenant"], brief_id=brief_id)
    assert brief is not None and brief.media.clip_avatar_block
    with pytest.raises(IntegrityError):
        repo.insert_brief_and_draft(
            tenant_id=world["tenant"],
            user_id=world["user"],
            brief=brief,
            voice_profile_version=1,
            pipeline_version="creative-v1",
            parent_draft_id=world["clip"],
            part_index=1,
        )


def test_a_block_settling_opens_no_join_on_its_clip(monkeypatch: pytest.MonkeyPatch) -> None:
    world = _world(monkeypatch)
    with tenant_session(world["tenant"]) as session:
        mark_parent_dirty(session, world["block"])
        runs = session.scalar(
            text("SELECT count(*) FROM creative_pipeline_runs WHERE draft_id = :c"),
            {"c": world["clip"]},
        )
    assert runs == 0


# ---------------------------------------------------------------------------
# review of 9ffa7eee: the queue finds the block's reservation; Deivid 2026-11-24: the
# daily cap of 3 blocks per business, counted by Postgres


def _service(env: dict[str, str]) -> tuple[ca.ClipAvatarService, Any]:
    from qualify_creative.pricing import JsonPricingTable
    from qualify_creative.router import CreativeRouter

    from qualify_api.creative.composition import DbBrandKitReader, DbVoiceProfileReader
    from qualify_api.creative.creations import PostgresCreationsLedger
    from qualify_api.creative.queue_dispatch import QueueDispatcher
    from qualify_api.creative.service import ContentService

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
    return ca.ClipAvatarService(content, env=env), content


def _request() -> ca.AvatarBlockRequest:
    return ca.AvatarBlockRequest(
        kind="presenter", script="Hola, soy Ana.", avatar_prompt="Mujer sonriente"
    )


def test_the_queue_finds_a_blocks_reservation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review of 9ffa7eee (blocking): without its charge row the queue refused every
    block («generation reservation is no longer active») after Seedream and Seed Speech
    were paid. The job is claimed as the worker claims it and goes through the real
    `PipelineExecutor._validate_reservation`. No vendor is called."""
    from qualify_api.creative.worker.executor import JobContext
    from qualify_api.creative.worker.pipeline import PipelineExecutor

    world = _world(monkeypatch)
    tenant = world["tenant"]
    service, content = _service({ca.PRESENTER_SWITCH: "on"})
    block = service.create_block(
        tenant_id=tenant, user_id=world["user"], clip_id=world["clip"], request=_request()
    )
    # claimed as the worker claims it (setup only: the table's owner, as the queue tests)
    owner = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    with owner.begin() as connection:
        job = connection.execute(
            text("""
            UPDATE creative_jobs SET status = 'claimed', claim_token = 7,
                claimed_by = 'test-worker', lease_until = now() + interval '5 minutes'
            WHERE draft_id = :b RETURNING id, kind, revision, position, vendor_model, charge_id
        """),
            {"b": block},
        ).one()
    owner.dispose()
    with tenant_session(tenant) as session:
        charge = session.execute(
            text("SELECT status, request_kind, weight FROM creation_charges WHERE id = :c"),
            {"c": job.charge_id},
        ).one()
    assert (charge.status, charge.request_kind, charge.weight) == (
        "charged",
        "clip_avatar_block",
        0,
    )
    context = JobContext(
        job_id=job.id,
        tenant_id=tenant,
        draft_id=block,
        kind=job.kind,
        revision=job.revision,
        position=job.position,
        vendor_model=job.vendor_model,
        lane="now",
        vendor_priority=0,
        deadline=None,
        claim_token=7,
    )
    executor = PipelineExecutor(content, None, None, "omnihuman")
    executor._validate_reservation(context)
    # the control: what 9ffa7eee left (no charge row) is refused by the same check
    owner = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    with owner.begin() as connection:
        connection.execute(
            text("UPDATE creative_jobs SET charge_id = NULL WHERE id = :j"), {"j": job.id}
        )
    owner.dispose()
    with pytest.raises(ValueError, match="reservation is no longer active"):
        executor._validate_reservation(context)


def test_the_daily_cap_is_three_blocks_of_the_business_own_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world(monkeypatch)  # its block was made today: it counts
    tenant, user, clip = world["tenant"], world["user"], world["clip"]
    service, _ = _service({ca.PRESENTER_SWITCH: "on"})
    store = ca.PostgresClipAvatarStore()
    assert store.blocks_made_today(tenant_id=tenant) == 1
    for _ in range(ca.AVATAR_DAILY_CAP - 1):
        service.create_block(tenant_id=tenant, user_id=user, clip_id=clip, request=_request())
    with tenant_session(tenant) as session:
        jobs_before = session.scalar(text("SELECT count(*) FROM creative_jobs"))
    with pytest.raises(ca.AvatarDailyCapReached):
        service.create_block(tenant_id=tenant, user_id=user, clip_id=clip, request=_request())
    with tenant_session(tenant) as session:
        assert session.scalar(text("SELECT count(*) FROM creative_jobs")) == jobs_before
        # one that failed before anything was paid (no usage with a cost) frees its place
        session.execute(
            text("UPDATE content_drafts SET status = 'failed' WHERE id = :b"),
            {"b": world["block"]},
        )
    assert store.blocks_made_today(tenant_id=tenant) == ca.AVATAR_DAILY_CAP - 1
    service.create_block(tenant_id=tenant, user_id=user, clip_id=clip, request=_request())
    assert store.blocks_made_today(tenant_id=tenant) == ca.AVATAR_DAILY_CAP
    # another business is not affected
    other_world = _world(monkeypatch)
    assert store.blocks_made_today(tenant_id=other_world["tenant"]) == 1
    # the business's next day frees the cap
    with tenant_session(tenant) as session:
        session.execute(
            text(
                "UPDATE content_drafts SET created_at = created_at - interval '1 day' "
                "WHERE parent_draft_id = :c"
            ),
            {"c": clip},
        )
    assert store.blocks_made_today(tenant_id=tenant) == 0


def test_pending_seconds_are_the_brands_uncharged_live_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world(monkeypatch)
    store = ca.PostgresClipAvatarStore()
    with tenant_session(world["tenant"]) as session:
        brand = session.scalar(
            text("SELECT brand_id FROM content_drafts WHERE id = :c"), {"c": world["clip"]}
        )
    assert store.pending_block_seconds(tenant_id=world["tenant"], brand_id=brand) == (
        1,
        ca.script_seconds("Hola, soy Ana."),
    )
    tenant = world["tenant"]

    def owed() -> tuple[int, int]:
        return store.pending_block_seconds(tenant_id=tenant, brand_id=brand)

    def run(sql: str) -> None:
        with tenant_session(tenant) as session:
            session.execute(text(sql), {"b": world["block"], "c": world["clip"]})

    # its Clip approved: it was charged then, or never will be — it owes nothing
    run("UPDATE content_drafts SET status = 'approved' WHERE id = :c")
    assert owed() == (0, 0)
    run("UPDATE content_drafts SET status = 'generated' WHERE id = :c")
    # made in another month, its Clip still waiting: it still owes (a block of the
    # 31st approved on the 1st)
    run("UPDATE content_drafts SET created_at = created_at - interval '40 days' WHERE id = :b")
    assert owed() == (1, ca.script_seconds("Hola, soy Ana."))
    # its Clip's files purged by the retention: it owes nothing any more
    run("UPDATE content_drafts SET media_purged_at = now() WHERE id = :c")
    assert owed() == (0, 0)
    run("UPDATE content_drafts SET media_purged_at = NULL WHERE id = :c")
    assert owed() == (1, ca.script_seconds("Hola, soy Ana."))
    run("UPDATE content_drafts SET status = 'failed' WHERE id = :b")
    assert owed() == (0, 0)


def test_the_same_request_key_gives_the_same_block_one_after_the_other_and_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A double click or a retry of the screen: the same request key makes ONE block,
    asked one after the other or by two threads at once — the second gets the first's
    draft, never an error, never a second row."""
    import threading

    world = _world(monkeypatch)
    tenant, user, clip = world["tenant"], world["user"], world["clip"]
    service, _ = _service({ca.PRESENTER_SWITCH: "on"})

    def ask(key: UUID) -> UUID:
        return service.create_block(
            tenant_id=tenant, user_id=user, clip_id=clip, request=_request(), request_key=key
        )

    def rows(key: UUID) -> int:
        with tenant_session(tenant) as session:
            return int(
                session.scalar(
                    text("SELECT count(*) FROM content_drafts WHERE request_key = :k"),
                    {"k": key},
                )
            )

    one_after = uuid4()
    first = ask(one_after)
    assert ask(one_after) == first and rows(one_after) == 1

    at_once = uuid4()
    start = threading.Barrier(2)
    answers: list[UUID] = []
    errors: list[BaseException] = []

    def racer() -> None:
        try:
            start.wait()
            answers.append(ask(at_once))
        except BaseException as exc:  # noqa: BLE001 — the test reports it
            errors.append(exc)

    threads = [threading.Thread(target=racer) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert errors == [] and len(answers) == 2
    assert answers[0] == answers[1] and rows(at_once) == 1


# ---------------------------------------------------------------------------
# m-25119867 (option B): the avatar chosen at the Clip's first «Crear», on Postgres


def _first_create(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from qualify_api.creative.queue_dispatch import SWITCH

    monkeypatch.setenv(SWITCH, "queue")
    for switch in (ca.PRESENTER_SWITCH, ca.ANIMATED_SWITCH):
        monkeypatch.setenv(switch, "on")
    tenant, brand, user = _business(monkeypatch)
    service, content = _service({ca.PRESENTER_SWITCH: "on"})
    return {"tenant": tenant, "brand": brand, "user": user, "service": service, "content": content}


def _create_b(world: dict[str, Any], **kw: Any) -> ca.ClipWithBlocks:
    return world["service"].create_clip_with_blocks(
        tenant_id=world["tenant"],
        brand_id=world["brand"],
        user_id=world["user"],
        brief=_clip(world["brand"], world["tenant"]),
        blocks=[ca.ClipAvatarPlacement(block=_request(), at=0)],
        **kw,
    )


def _count(tenant: UUID, sql: str, **params: Any) -> int:
    with tenant_session(tenant) as session:
        return int(session.scalar(text(sql), params) or 0)


def test_the_first_create_writes_the_clip_and_its_blocks_in_one_go(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _first_create(monkeypatch)
    tenant = world["tenant"]
    key = uuid4()
    made = _create_b(world, request_key=key)
    assert _create_b(world, request_key=key) == made  # the same «Crear» again
    store = ca.PostgresClipAvatarStore()
    clip = store.clip(tenant_id=tenant, clip_id=made.clip_id)
    assert clip is not None and clip.status == "drafting" and clip.parent_draft_id is None
    (block,) = store.blocks_of(tenant_id=tenant, clip_id=made.clip_id)
    assert block.id == made.block_ids[0] and block.slot == 1 and block.status == "drafting"
    brief = world["content"].repository.get_brief(tenant_id=tenant, brief_id=clip.brief_id)
    assert [(e.slot, e.at) for e in brief.media.clip_avatar_plan] == [(1, 0)]
    # each has its queued job (the reaper spares a draft with one) and its charge row
    for draft in (made.clip_id, made.block_ids[0]):
        queued = "SELECT count(*) FROM creative_jobs WHERE draft_id = :d AND status = 'queued'"
        assert _count(tenant, queued, d=draft) == 1
        charges = "SELECT count(*) FROM creation_charges WHERE draft_id = :d"
        assert _count(tenant, charges, d=draft) == 1


def test_a_refused_first_create_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    world = _first_create(monkeypatch)
    tenant = world["tenant"]
    for _ in range(ca.AVATAR_DAILY_CAP):
        _create_b(world)
    drafts = _count(tenant, "SELECT count(*) FROM content_drafts")
    jobs = _count(tenant, "SELECT count(*) FROM creative_jobs")
    with pytest.raises(ca.AvatarDailyCapReached) as refused:
        _create_b(world)
    assert refused.value.owner_message == ca.FIRST_CREATE_DAILY_CAP_TEXT
    assert _count(tenant, "SELECT count(*) FROM content_drafts") == drafts
    assert _count(tenant, "SELECT count(*) FROM creative_jobs") == jobs


def test_a_block_settling_wakes_its_waiting_clip(monkeypatch: pytest.MonkeyPatch) -> None:
    world = _first_create(monkeypatch)
    tenant = world["tenant"]
    made = _create_b(world)
    sql = (
        "SELECT dirty_version FROM creative_pipeline_runs "
        "WHERE draft_id = :c AND phase = 'generation'"
    )
    before = _count(tenant, sql, c=made.clip_id)
    with tenant_session(tenant) as session:
        mark_parent_dirty(session, made.block_ids[0])
    assert _count(tenant, sql, c=made.clip_id) == before + 1
    joins = "SELECT count(*) FROM creative_pipeline_runs WHERE draft_id = :c AND phase = 'join'"
    assert _count(tenant, joins, c=made.clip_id) == 0  # never a join on a Clip


def test_a_failed_clips_blocks_owe_nothing_on_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    """P6 (Deivid 2026-11-25): from the moment the Clip fails its blocks free the month."""
    world = _first_create(monkeypatch)
    tenant = world["tenant"]
    made = _create_b(world)
    store = ca.PostgresClipAvatarStore()
    assert store.pending_block_seconds(tenant_id=tenant, brand_id=world["brand"])[0] == 1
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE content_drafts SET status = 'failed' WHERE id = :c"), {"c": made.clip_id}
        )
    assert store.pending_block_seconds(tenant_id=tenant, brand_id=world["brand"]) == (0, 0)


def test_the_clip_waits_then_takes_its_blocks_video_in_a_new_brief(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _first_create(monkeypatch)
    tenant, content = world["tenant"], world["content"]
    made = _create_b(world)
    block = made.block_ids[0]
    record = content.repository.get_draft(tenant_id=tenant, draft_id=made.clip_id)
    asked = content.repository.get_brief(tenant_id=tenant, brief_id=record.brief_id)
    with pytest.raises(ca.ClipBlocksWait):
        content._clip_plan_ready(tenant, record, asked)
    key = f"t/{tenant}/generated/{block}/r1/video.mp4"
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE content_drafts SET status = 'generated' WHERE id = :b"), {"b": block}
        )
        session.add(
            orm.ImageAsset(
                tenant_id=tenant,
                draft_id=block,
                media_url=key,
                object_key=key,
                media_type="video",
                provider="omnihuman",
                model_id="omnihuman-1.5",
                params={"duration_seconds": 3.6},
            )
        )
    fresh, brief = content._clip_plan_ready(tenant, record, asked)
    assert fresh.brief_id != record.brief_id and fresh.status == "drafting"
    assert brief.media.clip_avatar_plan == ()
    assert brief.media.segments[0].key == key
    assert content.repository.get_brief(tenant_id=tenant, brief_id=fresh.brief_id) == brief
    # the brief the owner sent is still there
    assert content.repository.get_brief(tenant_id=tenant, brief_id=record.brief_id) == asked
    wait = world["service"].clip_wait(tenant_id=tenant, clip_id=made.clip_id)
    assert wait is not None and wait.state == "assembling"


# ---------------------------------------------------------------------------
# m-25119867 PR 2: retry, remove, the owner's 72 h, attention, the reaper — on Postgres


def _fail_block(tenant: UUID, block: UUID, *, paid: bool = False) -> None:
    with tenant_session(tenant) as session:
        session.execute(
            text("""
            UPDATE content_drafts SET status = 'failed', failure_reason = 'provider_error'
            WHERE id = :b
        """),
            {"b": block},
        )
        if paid:
            brand = session.scalar(
                text("SELECT brand_id FROM content_drafts WHERE id = :b"), {"b": block}
            )
            session.add(
                orm.CreativeUsageEvent(
                    tenant_id=tenant,
                    brand_id=brand,
                    draft_id=block,
                    provider="seedream",
                    model_id="seedream-4",
                    unit="piece",
                    input_tokens=0,
                    output_tokens=0,
                    cache_read_tokens=0,
                    cache_creation_tokens=0,
                    pieces=1,
                    cost_usd=0.03,
                    paid_by="platform",
                    pricing_table_version="v9",
                    occurred_at=datetime.now(UTC),
                )
            )


def _pass(world: dict[str, Any], clip: UUID) -> None:
    """One pass of the Clip's run outside the worker (no lease: the same writes)."""
    content, tenant = world["content"], world["tenant"]
    try:
        content.run_generation(tenant_id=tenant, draft_id=clip)
    except ca.ClipBlocksWait:
        pass


def test_retry_and_remove_on_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    world = _first_create(monkeypatch)
    tenant, service = world["tenant"], world["service"]
    made = _create_b(world)
    block = made.block_ids[0]
    _fail_block(tenant, block, paid=True)
    _pass(world, made.clip_id)  # the failure is seen: its 72 h start
    wait = service.clip_wait(tenant_id=tenant, clip_id=made.clip_id)
    assert wait is not None and wait.needs_attention and wait.wait_until is not None
    assert service.clips_needing_attention(tenant_id=tenant) == 1
    used = ca.PostgresClipAvatarStore().blocks_made_today(tenant_id=tenant)
    assert used == 1  # the first attempt paid: it counts
    args = {"tenant_id": tenant, "user_id": world["user"], "clip_id": made.clip_id}
    assert service.retry_block(block_id=block, **args) == block
    assert service.retry_block(block_id=block, **args) == block  # a double tap: one attempt
    with tenant_session(tenant) as session:
        row = session.execute(
            text("SELECT status, revision, failure_detail FROM content_drafts WHERE id = :b"),
            {"b": block},
        ).one()
        charges = session.execute(
            text("SELECT revision, weight FROM creation_charges WHERE draft_id = :b ORDER BY 1"),
            {"b": block},
        ).all()
        jobs = session.scalar(
            text("""
            SELECT count(*) FROM creative_jobs
            WHERE draft_id = :b AND revision = 2 AND status = 'queued'
        """),
            {"b": block},
        )
    assert (row.status, row.revision, row.failure_detail) == ("drafting", 2, None)
    assert [(c.revision, c.weight) for c in charges] == [(1, 0), (2, 0)] and jobs == 1
    # ADR 50 §11 P1: the retry is one more avatar of the day
    assert ca.PostgresClipAvatarStore().blocks_made_today(tenant_id=tenant) == used + 1
    assert service.clips_needing_attention(tenant_id=tenant) == 0
    # it fails again before paying anything: that attempt no longer counts
    _fail_block(tenant, block)
    assert ca.PostgresClipAvatarStore().blocks_made_today(tenant_id=tenant) == used
    _pass(world, made.clip_id)
    remove = {k: v for k, v in args.items()}
    assert service.remove_block(block_id=block, **remove) is True
    assert service.remove_block(block_id=block, **remove) is False
    with tenant_session(tenant) as session:
        removed = session.scalar(
            text("SELECT part_removed_at IS NOT NULL FROM content_drafts WHERE id = :b"),
            {"b": block},
        )
        dirty = session.scalar(
            text("""
            SELECT dirty_version > prepared_version FROM creative_pipeline_runs
            WHERE draft_id = :c AND phase = 'generation'
        """),
            {"c": made.clip_id},
        )
    assert removed and dirty
    wait = service.clip_wait(tenant_id=tenant, clip_id=made.clip_id)
    assert wait is not None and wait.state == "assembling" and not wait.needs_attention


def test_the_owners_72_hours_on_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import timedelta

    world = _first_create(monkeypatch)
    tenant, content = world["tenant"], world["content"]
    t0 = datetime.now(UTC)
    content._clip_avatar_clock = lambda: t0
    made = _create_b(world)
    _fail_block(tenant, made.block_ids[0])
    _pass(world, made.clip_id)
    content._clip_avatar_clock = lambda: t0 + timedelta(hours=72)
    _pass(world, made.clip_id)
    with tenant_session(tenant) as session:
        clip = session.execute(
            text("SELECT status, failure_reason, failure_detail FROM content_drafts WHERE id = :c"),
            {"c": made.clip_id},
        ).one()
        charge = session.scalar(
            text("SELECT status FROM creation_charges WHERE draft_id = :c AND revision = 1"),
            {"c": made.clip_id},
        )
    assert (clip.status, clip.failure_reason) == ("failed", ca.AVATAR_BLOCK_FAILED)
    assert clip.failure_detail == ca.AVATAR_BLOCK_FAILED_TEXT and charge == "refunded"
    assert world["service"].clips_needing_attention(tenant_id=tenant) == 0


def test_the_reaper_never_fails_a_clip_waiting_for_its_avatars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.creative.dispatch import reap_stale_drafts

    world = _first_create(monkeypatch)
    tenant = world["tenant"]
    made = _create_b(world)
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE content_drafts SET updated_at = now() - interval '3 hours' WHERE id = :c"),
            {"c": made.clip_id},
        )
    reap_stale_drafts(tenant_id=tenant)
    with tenant_session(tenant) as session:
        status = session.scalar(
            text("SELECT status FROM content_drafts WHERE id = :c"), {"c": made.clip_id}
        )
    assert status == "drafting"  # its job is queued: spared, whatever its stamp
