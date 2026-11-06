"""Version policy is frozen per execution; all values and storage are in memory."""

import socket
from uuid import uuid4

import pytest
from qualify_creative.enums import ContentKind

from qualify_api.creative import pipeline
from qualify_api.creative.pipeline import Preparation, frozen_inputs, preparing

from .test_creative_media_byteplus import TENANT_ID, _brief, _kit
from .test_creative_queue_pipeline import Checkpoints


@pytest.mark.parametrize("existing", ["none", "inputs", "references", "paid_copy"])
def test_new_execution_stamps_nine_but_replays_never_reinterpret_inputs(monkeypatch, existing):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network forbidden")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    steps = Checkpoints()
    monkeypatch.setattr(pipeline, "PipelineStore", lambda: steps)
    brief, kit = _brief(ContentKind.CLIP), _kit()
    if existing == "inputs":
        steps.rows[-1] = {
            "request": {"brief": brief.model_dump(mode="json"), "kit": kit.model_dump(mode="json")}
        }
    elif existing == "references":
        steps.rows[-2] = {"request": {"brand_refs": {"block_version": 8}}}
    elif existing == "paid_copy":
        steps.rows[0] = {"request": {"old_copy": True}, "result": {"paid": True}}
    calls = []

    def stamp(source, current_kit):
        calls.append(current_kit)
        return source.model_copy(
            update={"media": source.media.model_copy(update={"brand_application_version": 2})}
        )

    run = Preparation(TENANT_ID, uuid4(), 2, "generation", uuid4(), 1)
    with preparing(run):
        first, _ = frozen_inputs(brief=brief, kit=kit, prepare_brief=stamp, new_execution=True)
        second, _ = frozen_inputs(brief=brief, kit=kit, prepare_brief=stamp, new_execution=True)
    assert first == second
    assert first.media.brand_application_version == (2 if existing == "none" else 0)
    assert len(calls) == (1 if existing == "none" else 0)
    assert run.step == 0
    if existing == "paid_copy":
        assert steps.rows[0]["result"] == {"paid": True}


@pytest.mark.parametrize("server_stamped", [False, True])
def test_queued_request_without_any_steps_keeps_server_policy(monkeypatch, server_stamped):
    steps = Checkpoints()
    monkeypatch.setattr(pipeline, "PipelineStore", lambda: steps)
    brief, kit = _brief(ContentKind.CLIP), _kit()
    called = []

    def stamp(source, current_kit):
        called.append(True)
        return source.model_copy(
            update={"media": source.media.model_copy(update={"brand_application_version": 2})}
        )

    with preparing(Preparation(TENANT_ID, uuid4(), 1, "generation", uuid4(), 1)):
        frozen, _ = frozen_inputs(
            brief=brief, kit=kit, prepare_brief=stamp, new_execution=server_stamped
        )
    assert frozen.media.brand_application_version == (2 if server_stamped else 0)
    assert len(called) == int(server_stamped)


def test_stock_guide_roles_are_resolved_before_price_and_cannot_change_after_selection():
    from qualify_creative.creations import weight_for, weight_for_request

    from qualify_api.creative.brand_references import BrandReferencesSet
    from qualify_api.creative.resource_selection import ResourcePlan, validate_plan

    from .test_creative_media_byteplus import MemoryStore, _producer

    source = _brief(
        ContentKind.STATIC_FLYER,
        carousel=True,
        product_keys=(
            f"uploads/{TENANT_ID}/stock/guide.jpg",
            f"uploads/{TENANT_ID}/catalog/product.jpg",
        ),
    )
    producer = _producer(MemoryStore())
    producer._reference_compiler_version = 9
    frozen = producer.prepare_new_brief(source, _kit())
    assert source.media.product_image_roles == ()
    assert frozen.media.product_image_roles == ("composition", "product")
    assert weight_for(frozen) == weight_for_request(
        ContentKind.STATIC_FLYER.value, carousel_images=1
    )
    plan = ResourcePlan(
        resource_indices=(),
        photo_indices=(0, 1),
        guide_indices=(0,),
        logo_placement="none",
        signature_basis="none",
        explicit_quote="",
        reason="local fixture",
    )
    selected = BrandReferencesSet(block_version=9)
    validate_plan(plan, frozen, selected, frozen.media.product_keys)
    with pytest.raises(ValueError, match="frozen photo role"):
        validate_plan(
            plan.model_copy(update={"guide_indices": ()}),
            frozen,
            selected,
            frozen.media.product_keys,
        )


def test_worker_lease_policy_comes_from_its_pipeline_run_not_current_draft(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace

    statements = []

    class Result:
        def mappings(self):
            return self

        def first(self):
            return {"dirty_version": 3, "pipeline_version": "creative-v1"}

    class Session:
        def execute(self, statement, params):
            statements.append(str(statement))
            return Result()

    @contextmanager
    def session(tenant):
        yield Session()

    monkeypatch.setattr(pipeline, "tenant_session", session)
    run = pipeline.PipelineStore().acquire(TENANT_ID, uuid4(), 1, "generation")
    assert run.pipeline_version == "creative-v1"
    assert run.version == 3
    assert "RETURNING dirty_version, pipeline_version" in statements[0]
    assert "revision=:r" in statements[0]
    current_draft = SimpleNamespace(pipeline_version="creative-v2-brand9", revision=2)
    assert run.revision != current_draft.revision


@pytest.mark.parametrize("stock_guide", [False, True])
def test_new_creation_and_regeneration_callers_stamp_before_charge_and_share_quote(
    monkeypatch, stock_guide
):
    from types import SimpleNamespace

    from qualify_api.creative import service as service_module
    from qualify_api.creative.fsm import GENERATED
    from qualify_api.creative.service import ContentService

    from .test_creative_media_byteplus import MemoryStore, _producer

    keys = (
        f"uploads/{TENANT_ID}/stock/guide.jpg"
        if stock_guide
        else f"uploads/{TENANT_ID}/product1.jpg",
        f"uploads/{TENANT_ID}/product2.jpg",
    )
    brief = _brief(ContentKind.STATIC_FLYER, carousel=True, product_keys=keys)
    draft_id, brief_id = uuid4(), uuid4()
    record = SimpleNamespace(
        id=draft_id, brief_id=brief_id, brand_id=brief.brand_id, revision=1, status=GENERATED
    )
    events = []

    class Repo:
        def get_draft(self, **kwargs):
            return record

        def get_brief(self, **kwargs):
            return brief

        def brief_kind(self, **kwargs):
            # VE-08: `reject(regenerate=True)` reads the kind for the parent-text cap
            return brief.kind.value

        def insert_brief_and_draft(self, **kwargs):
            events.append(("insert", kwargs))
            return draft_id

        def bump_revision(self, **kwargs):
            events.append(("stamp", kwargs))
            return 2

        def update_status(self, **kwargs):
            events.append(("status", kwargs))

        def draft_videos_for(self, **kwargs):
            return ()

    class Creations:
        def balance(self, **kwargs):
            return SimpleNamespace(shortfall=lambda price: None)

        def charge(self, **kwargs):
            assert events[-1][0] in {"insert", "stamp"}
            assert events[-1][1]["pipeline_version"] == "creative-v2-brand9"
            events.append(("charge", kwargs))

    service = object.__new__(ContentService)
    service._repo, service._creations = Repo(), Creations()
    service._media = _producer(MemoryStore())
    service._brand = SimpleNamespace(kit=lambda **kwargs: _kit())
    service._voice = SimpleNamespace(active=lambda **kwargs: SimpleNamespace(version=1))
    service.dispatcher = SimpleNamespace(
        dispatch_generation=lambda **kwargs: events.append(("dispatch", kwargs))
    )
    monkeypatch.setattr(service, "_require_draft", lambda **kwargs: record)
    monkeypatch.setattr(service, "_require_detail", lambda **kwargs: "detail")
    monkeypatch.setattr(service_module.review, "score_rejection", lambda **kwargs: None)
    new_quote = service.recreate_price(tenant_id=TENANT_ID, draft_id=draft_id)
    ContentService.create_draft.__wrapped__(
        service, tenant_id=TENANT_ID, brand_id=brief.brand_id, brief=brief, user_id=uuid4()
    )
    assert events[1][1]["price"] == new_quote
    assert events[0][1]["brief"].media.product_image_roles == (
        "composition" if stock_guide else "product",
        "product",
    )
    events.clear()
    redo_quote = service.regeneration_price(tenant_id=TENANT_ID, draft_id=draft_id)
    ContentService.reject.__wrapped__.__wrapped__(
        service,
        tenant_id=TENANT_ID,
        draft_id=draft_id,
        reason="Otra versión",
        user_id=uuid4(),
        regenerate=True,
    )
    assert events[0][0] == "stamp" and events[1][0] == "charge"
    assert events[1][1]["price"] == redo_quote
    assert events[1][1]["revision"] == 2
    assert events[-1][0] == "dispatch"
    assert brief.media.brand_application_version == 0 and record.revision == 1
