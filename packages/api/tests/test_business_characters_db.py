"""Business characters against Postgres (m-25129385, migration 0187): a round and its jobs in
one transaction (idempotent by request key), the pre-POST stamp taken once, the key CHECK
agrees with the gate's key builder, RLS hides another business's rows, the caps (5 saved,
2 rounds a day) under the business's lock, names unique per business, no DELETE grant, the
`in_use` read of a scene's brief, a USD cost booked once, and the downgrade refusing while
characters exist."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from uuid import UUID, uuid4

import pytest
from packages.api.tests.test_creative_retention_db import _provision
from qualify_shared.db.session import tenant_session
from qualify_shared.objects.keys import business_character_key
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from qualify_api.creative import business_characters as bc
from qualify_api.creative import job_queue as q
from qualify_api.creative.business_character_ai import PostgresOptionUsageLedger

pytestmark = pytest.mark.db

TENANT = UUID("c0000000-0000-4000-8000-0000251293a1")
OTHER = UUID("c0000000-0000-4000-8000-0000251293a2")
ON = {bc.CHARACTER_SCENE_SWITCH_ENV: "on", bc.ARK_KEY_ENV: "k"}
_MIGRATION = (
    Path(__file__).resolve().parents[3] / "migrations/postgres/versions/0187_business_characters.py"
)


class _Objects:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_business_characters(self, tenant_id: UUID, brand_id: UUID, keys: list[str]) -> None:
        self.deleted.extend(keys)


def _service(tenant: UUID = TENANT) -> tuple[bc.BusinessCharacterService, UUID, UUID]:
    brand, user, _ = _provision(tenant, "characters")
    with tenant_session(tenant) as session:  # a fresh business for every test
        session.execute(
            text(
                "UPDATE business_characters SET status = 'deleted', deleted_at = now(), "
                "name = COALESCE(name, 'x') WHERE brand_id = :b AND status <> 'deleted'"
            ),
            {"b": brand},
        )
        session.execute(
            text(
                "UPDATE business_characters SET created_at = created_at - interval '2 days' "
                "WHERE brand_id = :b"
            ),
            {"b": brand},
        )
    service = bc.BusinessCharacterService(
        repo=bc.PostgresCharacterRepository(),
        usage=bc.PostgresCharacterUsage(),
        objects=_Objects(),
        env=ON,
    )
    return service, brand, user


def _ready(service: bc.BusinessCharacterService, option: bc.BusinessCharacter) -> None:
    service.mark_ready(
        tenant_id=option.tenant_id,
        character_id=option.id,
        object_key=business_character_key(option.tenant_id, option.brand_id, option.id),
        content_type="image/jpeg",
        width=1080,
        height=1920,
        byte_size=10,
        sha256="0" * 64,
        model_revision=bc.MODEL_ID,
        drawn_at=datetime.now(UTC),
    )


def _round(
    service: bc.BusinessCharacterService, brand: UUID, user: UUID, tenant: UUID = TENANT
) -> bc.DrawingRound:
    return service.request_drawings(
        tenant,
        brand,
        user,
        description="Un cocinero alegre con delantal verde",
        style="realista",
        request_key=uuid4().hex,
    )


def test_a_round_is_three_options_and_three_jobs_once() -> None:
    service, brand, user = _service()
    key = uuid4().hex
    round_ = service.request_drawings(
        TENANT, brand, user, description="Una cocinera alegre", style="animado", request_key=key
    )
    assert len(round_.options) == 3 and round_.status == bc.ROUND_DRAWING
    with tenant_session(TENANT) as session:
        jobs = [
            q.load_job(session, j)
            for j in session.execute(
                text("SELECT id FROM creative_jobs WHERE business_character_id = ANY(:ids)"),
                {"ids": [o.id for o in round_.options]},
            ).scalars()
        ]
    assert len(jobs) == 3
    for job in jobs:
        assert job is not None and job.kind == q.KIND_BUSINESS_CHARACTER
        assert job.vendor_model == q.SEEDREAM_PRO_POOL and job.draft_id is None
        assert job.pricing_version == "v10"
    again = service.request_drawings(
        TENANT, brand, user, description="Una cocinera alegre", style="animado", request_key=key
    )
    assert again.round_id == round_.round_id
    with tenant_session(TENANT) as session:
        again_job = q.enqueue_business_character_job(
            session,
            tenant_id=TENANT,
            character_id=round_.options[0].id,
            pricing_version="v10",
            pipeline_version=bc.PIPELINE_VERSION,
        )
    assert not again_job.created


def test_the_stamp_is_taken_once() -> None:
    service, brand, user = _service()
    option = _round(service, brand, user).options[0]
    repo = bc.PostgresCharacterRepository()
    now = datetime.now(UTC)
    assert repo.start_request(tenant_id=TENANT, character_id=option.id, at=now)
    assert not repo.start_request(tenant_id=TENANT, character_id=option.id, at=now)
    repo.clear_request(tenant_id=TENANT, character_id=option.id)
    assert repo.start_request(tenant_id=TENANT, character_id=option.id, at=now)


def test_the_key_check_matches_the_gate_key_builder() -> None:
    service, brand, user = _service()
    first, second, _third = _round(service, brand, user).options
    _ready(service, first)
    repo = bc.PostgresCharacterRepository()
    with pytest.raises(IntegrityError):
        repo.save(
            replace(
                second,
                status=bc.STATUS_READY,
                object_key=business_character_key(TENANT, brand, first.id),
            ),
            expected_status=bc.STATUS_PENDING,
        )


def test_choose_rename_delete_and_the_caps_under_the_lock() -> None:
    service, brand, user = _service()
    round_ = _round(service, brand, user)
    for option in round_.options:
        _ready(service, option)
    saved = service.choose_option(TENANT, brand, round_.round_id, round_.options[0].id, name="Nina")
    assert saved.status == bc.STATUS_SAVED
    statuses = {
        o.id: o.status
        for o in bc.PostgresCharacterRepository().list_brand(tenant_id=TENANT, brand_id=brand)
    }
    assert sorted(statuses.values()) == ["discarded", "discarded", "saved"]
    # the second round of the day; the third is refused
    second = _round(service, brand, user)
    for option in second.options:
        _ready(service, option)
    with pytest.raises(bc.CharacterRefused) as refused:
        service.choose_option(TENANT, brand, second.round_id, second.options[0].id, name="nina")
    assert refused.value.code == bc.NAME_TAKEN
    service.choose_option(TENANT, brand, second.round_id, second.options[0].id, name="Pepe")
    with pytest.raises(bc.CharacterRefused) as refused:
        _round(service, brand, user)
    assert refused.value.code == bc.DAILY_CAP
    assert service.list_characters(TENANT, brand).rounds_left_today == 0
    renamed = service.rename_character(TENANT, brand, saved.id, name="Nina la cocinera")
    assert renamed.name == "Nina la cocinera"
    service.delete_character(TENANT, brand, saved.id)
    view = service.list_characters(TENANT, brand)
    assert [c.name for c in view.saved] == ["Pepe"] and view.slots_left == 4


def test_the_sixth_saved_character_is_refused() -> None:
    service, brand, user = _service()
    with tenant_session(TENANT) as session:
        for i in range(5):
            session.execute(
                text(
                    """
                    INSERT INTO business_characters (
                        id, tenant_id, brand_id, round_id, option_index, request_key, style,
                        description, prompt, name, status, model_id, prompt_version,
                        pipeline_version, pricing_table_version, quoted_usd, object_key,
                        saved_at, created_at
                    ) VALUES (
                        :id, :t, :b, gen_random_uuid(), 1, :k, 'animado', 'una descripción',
                        'p', :name, 'saved', 'm', 'v', 'p', 'v10', 0.045,
                        'seasonal/' || :t || '/' || :b || '/personajes-negocio/' || :id || '.jpg',
                        now(), now() - interval '2 days'
                    )
                    """
                ),
                {"id": uuid4(), "t": TENANT, "b": brand, "k": uuid4().hex, "name": f"P{i}"},
            )
    with pytest.raises(bc.CharacterRefused) as refused:
        _round(service, brand, user)
    assert refused.value.code == bc.LIMIT_REACHED


def test_another_business_never_sees_a_character_and_no_one_can_delete_rows() -> None:
    service, brand, user = _service()
    option = _round(service, brand, user).options[0]
    _provision(OTHER, "other")
    repo = bc.PostgresCharacterRepository()
    assert repo.get(tenant_id=OTHER, character_id=option.id) is None
    assert repo.get(tenant_id=TENANT, character_id=option.id) is not None
    with pytest.raises(DBAPIError):
        with tenant_session(TENANT) as session:
            session.execute(
                text("DELETE FROM business_characters WHERE id = :id"), {"id": option.id}
            )


def test_a_character_in_a_scene_of_a_video_not_approved_yet_is_in_use() -> None:
    service, brand, user = _service()
    character_id = uuid4()
    usage = bc.PostgresCharacterUsage()
    assert not usage.in_unapproved_video(
        tenant_id=TENANT, brand_id=brand, character_id=character_id
    )
    with tenant_session(TENANT) as session:
        brief = session.execute(
            text(
                """
                INSERT INTO content_briefs (
                    tenant_id, brand_id, objective, topic, platform, format, intent,
                    content_type, image_route, variants_requested, kind, media, created_by
                ) VALUES (
                    :t, :b, 'sales', 'x', 'instagram', 'reel', 'promo', 'video', 'ai', 1,
                    'clip', CAST(:media AS jsonb), :u
                ) RETURNING id
                """
            ),
            {
                "t": TENANT,
                "b": brand,
                "u": user,
                "media": json.dumps({bc.SCENE_MEDIA_KEY: [{"character_id": str(character_id)}]}),
            },
        ).scalar_one()
        draft = session.execute(
            text(
                """
                INSERT INTO content_drafts (tenant_id, brand_id, brief_id, status, pipeline_version)
                VALUES (:t, :b, :brief, 'generated', 'p') RETURNING id
                """
            ),
            {"t": TENANT, "b": brand, "brief": brief},
        ).scalar_one()
    assert usage.in_unapproved_video(tenant_id=TENANT, brand_id=brand, character_id=character_id)
    assert (
        usage.unapproved_video(tenant_id=TENANT, brand_id=brand, character_id=character_id) == draft
    )
    assert not usage.in_unapproved_video(tenant_id=TENANT, brand_id=brand, character_id=uuid4())
    assert not usage.in_unapproved_video(tenant_id=OTHER, brand_id=brand, character_id=character_id)
    # failed and rejected videos can be tried again: they still hold the character
    for status in ("failed", "rejected"):
        with tenant_session(TENANT) as session:
            session.execute(
                text("UPDATE content_drafts SET status = :s WHERE id = :d"),
                {"s": status, "d": draft},
            )
        assert usage.in_unapproved_video(
            tenant_id=TENANT, brand_id=brand, character_id=character_id
        )
    with tenant_session(TENANT) as session:
        session.execute(
            text(
                "UPDATE content_drafts SET status = 'approved', approved_at = now(), "
                "approved_by = :u WHERE id = :d"
            ),
            {"d": draft, "u": user},
        )
    assert not usage.in_unapproved_video(
        tenant_id=TENANT, brand_id=brand, character_id=character_id
    )


def test_discarding_is_conditional_and_keeps_the_cost_the_worker_noted() -> None:
    service, brand, user = _service()
    round_ = _round(service, brand, user)
    first, second, third = round_.options
    service.note_paid(
        tenant_id=TENANT,
        character_id=second.id,
        cost_usd=Decimal("0.045"),
        vendor_request_id="seedream-sync:x",
    )
    _ready(service, first)
    service.choose_option(TENANT, brand, round_.round_id, first.id, name="Nina")
    repo = bc.PostgresCharacterRepository()
    stored = repo.get(tenant_id=TENANT, character_id=second.id)
    assert stored is not None and stored.status == bc.STATUS_DISCARDED
    assert stored.cost_usd == Decimal("0.045")
    assert (
        repo.discard(tenant_id=TENANT, character_ids=[second.id, third.id], at=datetime.now(UTC))
        == []
    )
    # an option discarded meanwhile cannot be chosen: a clear refusal, never a raw error
    with pytest.raises(bc.CharacterRefused) as refused:
        service.choose_option(TENANT, brand, round_.round_id, third.id, name="Otro")
    assert refused.value.code == bc.NOT_FOUND


def test_the_usd_cost_is_booked_once_per_option() -> None:
    service, brand, user = _service()
    option = _round(service, brand, user).options[0]
    ledger = PostgresOptionUsageLedger()
    args = dict(
        tenant_id=TENANT,
        brand_id=brand,
        character_id=option.id,
        model_id=bc.MODEL_ID,
        pieces=1,
        cost_usd=Decimal("0.045"),
        pricing_version="v10",
        occurred_at=datetime.now(UTC),
    )
    assert ledger.record(**args)  # type: ignore[arg-type]
    assert not ledger.record(**args)  # type: ignore[arg-type]
    with tenant_session(TENANT) as session:
        rows = session.execute(
            text(
                "SELECT unit, cost_usd FROM creative_usage_events WHERE brand_id = :b "
                "AND unit = 'business_character_image' AND occurred_at >= :since"
            ),
            {"b": brand, "since": args["occurred_at"]},
        ).all()
    assert [(r.unit, Decimal(r.cost_usd)) for r in rows] == [
        ("business_character_image", Decimal("0.045"))
    ]


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_the_downgrade_refuses_while_characters_exist_then_runs_clean_without_them() -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    service, brand, user = _service()
    _round(service, brand, user)
    migration = _load(_MIGRATION, "migration_0187")
    engine = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    try:
        with engine.connect() as conn:
            outer = conn.begin()
            try:
                with Operations.context(MigrationContext.configure(conn)):
                    savepoint = conn.begin_nested()
                    with pytest.raises(DBAPIError, match="downgrade 0187 refused"):
                        migration.downgrade()
                    savepoint.rollback()
                    conn.execute(text("SET LOCAL row_security = off"))
                    conn.execute(
                        text("DELETE FROM creative_jobs WHERE kind = 'business_character'")
                    )
                    conn.execute(text("DELETE FROM business_characters"))
                    conn.execute(text("SET LOCAL row_security = on"))
                    migration.downgrade()
                    assert (
                        conn.execute(text("SELECT to_regclass('business_characters')")).scalar_one()
                        is None
                    )
                    migration.upgrade()
                    assert (
                        conn.execute(text("SELECT to_regclass('business_characters')")).scalar_one()
                        is not None
                    )
            finally:
                outer.rollback()
    finally:
        engine.dispose()


def test_rls_is_forced_and_the_grants_are_the_house_ones() -> None:
    from qualify_shared.db.admin import admin_session

    with admin_session() as session:
        rls, forced = session.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = 'business_characters'"
            )
        ).one()
        assert rls and forced
        policy = session.execute(
            text(
                "SELECT qual, with_check FROM pg_policies "
                "WHERE tablename = 'business_characters' AND policyname = 'tenant_isolation'"
            )
        ).one()
        assert "NULLIF" in policy.qual and "NULLIF" in policy.with_check
        grants = {
            (role, privilege)
            for role in ("qualify_app", "qualify_admin", "qualify_creative_worker")
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE")
            if session.execute(
                text("SELECT has_table_privilege(:r, 'business_characters', :p)"),
                {"r": role, "p": privilege},
            ).scalar_one()
        }
    assert grants == {
        ("qualify_app", "SELECT"),
        ("qualify_app", "INSERT"),
        ("qualify_app", "UPDATE"),
        ("qualify_admin", "SELECT"),
    }
