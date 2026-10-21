"""`qualify_api.creative.angle_sets.AngleSetService` (ticket 24803289) against an
in-memory repository and scripted fakes — no Postgres, no network: the set's creation
(the price frozen from the catalog, a missing price told, the angles stored with their
provenance, the top-up call, the typed failure), one draft per kept angle inside ONE
campaign, a refused brief failing only its angle, the retry of one angle alone, the
discard/restore gate, the approval through the content service, and the gallery view
with the price guard."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.angles import (
    AngleBrand,
    AnglePreset,
    AngleProduct,
    CreativeAngle,
    parse_angles,
    preset_by_key,
)
from qualify_creative.enums import DraftStatus
from qualify_creative.schemas import BrandKit, ToneAxes

from qualify_api.catalog.service import MediaRecord, ProductRecord, UnknownProduct
from qualify_api.claude_tools import CallStats, ClaudeToolError, MissingAPIKey
from qualify_api.creative.angle_sets import (
    ANGLE_APPROVED,
    ANGLE_DISCARDED,
    ANGLE_FAILED,
    ANGLE_PROPOSED,
    ANGLE_QUEUED,
    ANGLE_RESERVED,
    INTERRUPTED,
    RESERVATION_TIMEOUT,
    SET_ANGLES_READY,
    SET_COMPLETED,
    SET_FAILED,
    SET_GENERATING,
    AngleGenerationFailed,
    AngleNotActionable,
    AngleRecord,
    AngleSetRecord,
    AngleSetService,
    AngleSetWrite,
    PresetNotAvailable,
    brand_fingerprint,
    campaign_name,
    product_facts,
)
from qualify_api.creative.angles_ai import AnglesProviderError
from qualify_api.creative.service import BrandNotReady, DraftDetail, VariantRecord

TENANT = uuid4()
BRAND = uuid4()
USER = uuid4()
PRODUCT_ID = uuid4()
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)

SCENES = [
    "sobre una tabla de madera en una mesa de cafetería con luz de ventana",
    "en la mano de alguien frente a un local de barrio al atardecer",
    "sobre una roca junto a un río con luz dura de mediodía",
    "en un escritorio de oficina entre un portátil y un café",
    "sobre papel kraft en un picnic en el césped con sombra de árbol",
    "en la barra del local con la plancha encendida al fondo",
    "en una bandeja de reparto dentro de una moto con casco al lado",
    "sobre mármol blanco con cubiertos dorados y una copa",
    "en el asiento de un carro con luces de ciudad desenfocadas",
    "sobre una toalla de playa con arena y mar al fondo",
    "en una mesa de reunión con cuatro cajas abiertas",
    "flotando sobre fondo negro con humo y luz lateral",
]


def _angles(n: int, start: int = 0) -> tuple[CreativeAngle, ...]:
    return parse_angles(
        {
            "angles": [
                {
                    "title": f"Ángulo {start + i + 1}",
                    "scene": SCENES[start + i],
                    "composition": "plano medio",
                    "hook": f"Gancho {start + i + 1}",
                    "cta": "Pide ya",
                    "rationale": "vende",
                }
                for i in range(n)
            ]
        },
        count=n,
    )


# -- fakes ---------------------------------------------------------------------------------


class MemoryRepo:
    def __init__(self) -> None:
        self.sets: dict[UUID, AngleSetRecord] = {}
        self.angles: dict[UUID, AngleRecord] = {}

    def insert_set(self, write: AngleSetWrite) -> UUID:
        set_id = uuid4()
        self.sets[set_id] = AngleSetRecord(
            id=set_id,
            tenant_id=write.tenant_id,
            brand_id=write.brand_id,
            product_id=write.product_id,
            preset_key=write.preset_key,
            requested_count=write.requested_count,
            status="drafting",
            product_name=write.product_name,
            price_label=write.price_label,
            price_missing=write.price_missing,
            created_by=write.created_by,
            created_at=NOW,
            brand_kit_fingerprint=write.brand_kit_fingerprint,
        )
        return set_id

    def update_set(self, *, tenant_id: UUID, set_id: UUID, **fields: object) -> None:
        self.sets[set_id] = replace(self.sets[set_id], **fields)  # type: ignore[arg-type]

    def claim_campaign(self, *, tenant_id: UUID, set_id: UUID, campaign_id: UUID) -> UUID:
        if self.sets[set_id].campaign_id is None:
            self.sets[set_id] = replace(self.sets[set_id], campaign_id=campaign_id)
        return self.sets[set_id].campaign_id  # type: ignore[return-value]

    def get_set(self, *, tenant_id: UUID, set_id: UUID) -> AngleSetRecord | None:
        record = self.sets.get(set_id)
        return record if record is not None and record.tenant_id == tenant_id else None

    def list_sets(self, *, tenant_id: UUID, brand_id: UUID, limit: int = 20):
        return tuple(s for s in self.sets.values() if s.brand_id == brand_id)[:limit]

    def insert_angles(self, *, tenant_id: UUID, set_id: UUID, angles) -> tuple[UUID, ...]:
        ids = []
        for a in angles:
            angle_id = uuid4()
            self.angles[angle_id] = AngleRecord(
                id=angle_id,
                set_id=set_id,
                position=a.position,
                title=a.title,
                scene=a.scene,
                composition=a.composition,
                hook=a.hook,
                cta=a.cta,
                rationale=a.rationale,
                status=ANGLE_PROPOSED,
            )
            ids.append(angle_id)
        return tuple(ids)

    def list_angles(self, *, tenant_id: UUID, set_id: UUID) -> tuple[AngleRecord, ...]:
        return tuple(
            sorted(
                (a for a in self.angles.values() if a.set_id == set_id), key=lambda a: a.position
            )
        )

    def get_angle(self, *, tenant_id: UUID, angle_id: UUID) -> AngleRecord | None:
        return self.angles.get(angle_id)

    def update_angle(self, *, tenant_id: UUID, angle_id: UUID, **fields: object) -> None:
        self.angles[angle_id] = replace(self.angles[angle_id], **fields)  # type: ignore[arg-type]

    # the conditional UPDATEs of the Postgres repository, same semantics
    def reserve_angle(
        self, *, tenant_id: UUID, angle_id: UUID, from_statuses, request_key: UUID, at
    ) -> bool:
        angle = self.angles[angle_id]
        if angle.status not in from_statuses:
            return False
        self.angles[angle_id] = replace(
            angle, status=ANGLE_RESERVED, request_key=request_key, reserved_at=at
        )
        return True

    def settle_angle(
        self, *, tenant_id: UUID, angle_id: UUID, request_key: UUID, **fields: object
    ) -> bool:
        angle = self.angles[angle_id]
        if angle.status != ANGLE_RESERVED or angle.request_key != request_key:
            return False
        self.angles[angle_id] = replace(angle, reserved_at=None, **fields)  # type: ignore[arg-type]
        return True


def _product(price: Decimal | None = Decimal("18000"), *, photos: int = 2) -> ProductRecord:
    media = tuple(
        MediaRecord(
            id=uuid4(),
            media_type="image",
            object_key=f"uploads/{TENANT}/p{i}.jpg",
            filename=f"p{i}.jpg",
            content_type="image/jpeg",
            width=1000,
            height=1000,
            duration_sec=None,
            bytes=1,
            is_primary=(i == 1),
            position=i,
        )
        for i in range(photos)
    )
    return ProductRecord(
        id=PRODUCT_ID,
        brand_id=BRAND,
        name="Shawarma mixto",
        slug="shawarma-mixto",
        description="Pollo y carne",
        price_amount=price,
        price_currency="COP" if price is not None else "",
        category="Plato",
        tags=("shawarma",),
        is_active=True,
        position=0,
        media=media,
    )


class FakeCatalog:
    def __init__(self, product: ProductRecord | None) -> None:
        self.product = product
        self.reads = 0

    def get_product(self, *, tenant_id: UUID, product_id: UUID) -> ProductRecord:
        self.reads += 1
        if self.product is None or self.product.id != product_id:
            raise UnknownProduct(str(product_id))
        return self.product


class FakeGenerator:
    def __init__(self, *batches: tuple[CreativeAngle, ...], error: Exception | None = None):
        self.batches = list(batches)
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def __call__(self, product, brand, preset, *, count, avoid=()):
        self.calls.append({"count": count, "avoid": tuple(avoid), "product": product})
        if self.error is not None:
            raise self.error
        batch = self.batches.pop(0) if self.batches else ()
        stats = CallStats("claude-sonnet-5", "claude-sonnet-5-20260601", 1000, 800, 0, 1, 1)
        return batch, stats, "fp-1234"


@dataclass
class FakeDrafts:
    """Stands in for `ContentService`: records briefs, serves scripted details."""

    details: dict[UUID, DraftDetail] = field(default_factory=dict)
    briefs: list[Any] = field(default_factory=list)
    approved: list[tuple[UUID, UUID]] = field(default_factory=list)
    refuse: Exception | None = None
    refuse_titles: tuple[str, ...] = ()
    #: like `ContentService`: a key that already has a draft returns it, no dispatch
    by_key: dict[UUID, UUID] = field(default_factory=dict)
    dispatched: list[UUID] = field(default_factory=list)
    #: raise AFTER the draft exists (a crash between the draft and the angle's update)
    crash_after_create: Exception | None = None
    single_reads: list[UUID] = field(default_factory=list)
    batch_reads: list[tuple[UUID, ...]] = field(default_factory=list)
    lookup_error: Exception | None = None

    def create_draft(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        brief: Any,
        user_id: UUID,
        request_key: UUID | None = None,
    ) -> UUID:
        if request_key is not None and request_key in self.by_key:
            return self.by_key[request_key]
        if self.refuse is not None and any(t in brief.topic for t in self.refuse_titles):
            raise self.refuse
        self.briefs.append(brief)
        draft_id = uuid4()
        self.details[draft_id] = _detail(draft_id, DraftStatus.DRAFTING.value)
        self.dispatched.append(draft_id)
        if request_key is not None:
            self.by_key[request_key] = draft_id
        if self.crash_after_create is not None:
            error, self.crash_after_create = self.crash_after_create, None
            raise error
        return draft_id

    def draft_for_request(self, *, tenant_id: UUID, request_key: UUID) -> UUID | None:
        if self.lookup_error is not None:
            raise self.lookup_error
        return self.by_key.get(request_key)

    def get_draft(self, *, tenant_id: UUID, draft_id: UUID) -> DraftDetail | None:
        self.single_reads.append(draft_id)
        return self.details.get(draft_id)

    def get_drafts(self, *, tenant_id: UUID, draft_ids: Any) -> dict[UUID, DraftDetail]:
        self.batch_reads.append(tuple(draft_ids))
        return {d: self.details[d] for d in draft_ids if d in self.details}

    def approve(self, *, tenant_id: UUID, draft_id: UUID, variant_id: UUID, user_id: UUID):
        self.approved.append((draft_id, variant_id))
        self.details[draft_id] = replace(self.details[draft_id], status=DraftStatus.APPROVED.value)
        return self.details[draft_id]


def _detail(
    draft_id: UUID,
    status: str,
    *,
    hook: str = "Shawarma mixto a $18.000",
    caption: str = "Hoy, en la barra.",
    failure: str | None = None,
) -> DraftDetail:
    variants = (
        (
            VariantRecord(
                id=uuid4(),
                draft_id=draft_id,
                ordinal=0,
                copy={"hook": hook, "caption": caption, "cta": "Pide ya"},
                edited_copy=None,
                fidelity=None,
                model_id="claude-opus-5",
                model_revision=None,
            ),
        )
        if status in (DraftStatus.GENERATED.value, DraftStatus.APPROVED.value)
        else ()
    )
    return DraftDetail(
        id=draft_id,
        brand_id=BRAND,
        brief_id=uuid4(),
        status=status,
        failure_reason=failure,
        selected_variant_id=None,
        voice_profile_version=1,
        pipeline_version="x",
        requires_ai_disclosure=True,
        approved_by=None,
        approved_at=None,
        created_at=NOW,
        variants=variants,
        image=None,
        preview_key=f"generated/{TENANT}/{draft_id}/slide-1.jpg" if variants else None,
    )


class FakeCampaigns:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.assigned: list[tuple[UUID, UUID]] = []

    def create(self, *, tenant_id, brand_id, name, created_by) -> UUID:
        self.created.append(name)
        return uuid4()

    def assign(self, *, tenant_id, draft_id, campaign_id) -> None:
        self.assigned.append((draft_id, campaign_id))


class FakeKits:
    def kit(self, *, tenant_id: UUID, brand_id: UUID) -> BrandKit | None:
        return BrandKit(
            brand_id=brand_id,
            positioning="shawarma de barrio",
            audience="oficinistas",
            tone_axes=ToneAxes(
                formal_casual=70, sober_enthusiastic=60, technical_plain=80, brief_elaborate=40
            ),
            logo_asset_key=f"uploads/{TENANT}/logo.png",
        )


class FakePricing:
    version = "test"

    def unit_price(self, *, model_id: str, unit: str) -> Decimal:
        return Decimal("0.035")


def _service(
    *,
    product: ProductRecord | None = None,
    generator: FakeGenerator | None = None,
    drafts: FakeDrafts | None = None,
) -> tuple[AngleSetService, MemoryRepo, FakeGenerator, FakeDrafts, FakeCampaigns]:
    repo = MemoryRepo()
    generator = generator or FakeGenerator(_angles(10))
    drafts = drafts or FakeDrafts()
    campaigns = FakeCampaigns()
    service = AngleSetService(
        repository=repo,
        catalog=FakeCatalog(product if product is not None else _product()),
        brand_facts=lambda *, tenant_id, brand_id: AngleBrand(name="Bianki"),
        kit_reader=FakeKits(),
        generator=generator,
        drafts=drafts,
        campaigns=campaigns,
        pricing=FakePricing(),
        image_model_id="seedream-5-0-lite-260128",
    )
    return service, repo, generator, drafts, campaigns


def _create(service: AngleSetService, **overrides: Any) -> UUID:
    args: dict[str, Any] = {
        "tenant_id": TENANT,
        "brand_id": BRAND,
        "user_id": USER,
        "product_id": PRODUCT_ID,
        "preset_key": "escena_producto",
    }
    args.update(overrides)
    return service.create_set(**args)


# -- helpers --------------------------------------------------------------------------------


def test_product_facts_put_the_hero_photo_first_and_format_the_price() -> None:
    facts = product_facts(_product(photos=3))
    assert facts.photo_keys[0].endswith("p1.jpg") and len(facts.photo_keys) == 3
    assert facts.price_label == "$18000.00" or facts.price_label.startswith("$")
    assert facts.has_price
    assert not product_facts(_product(None)).has_price


def test_the_campaign_name_is_the_product_and_the_count_within_60_chars() -> None:
    assert campaign_name("Shawarma mixto", 10) == "Shawarma mixto · 10 variaciones"
    assert len(campaign_name("X" * 80, 10)) <= 60


def test_the_plan_quotes_the_image_rate_times_the_count() -> None:
    service, *_ = _service()
    plan = service.plan(10)
    assert plan.images_usd == Decimal("0.350") and plan.count == 10


# -- creating the set -----------------------------------------------------------------------


def test_create_set_freezes_the_catalog_price_and_stores_ten_angles_with_provenance() -> None:
    service, repo, generator, _, _ = _service()
    set_id = _create(service)
    record = repo.sets[set_id]
    assert record.status == SET_ANGLES_READY and record.requested_count == 10
    assert record.price_label.startswith("$") and record.price_missing is False
    assert record.model_id == "claude-sonnet-5" and record.prompt_fingerprint == "fp-1234"
    assert record.input_tokens == 1000 and record.cost_usd > 0
    assert record.failure_detail is None
    angles = repo.list_angles(tenant_id=TENANT, set_id=set_id)
    assert [a.position for a in angles] == list(range(1, 11))
    assert all(a.status == ANGLE_PROPOSED for a in angles)
    (call,) = generator.calls
    assert call["count"] == 10 and call["product"].price_label == record.price_label


def test_a_product_without_price_is_told_and_nothing_is_demanded() -> None:
    service, repo, generator, _, _ = _service(product=_product(None))
    set_id = _create(service)
    assert repo.sets[set_id].price_missing is True and repo.sets[set_id].price_label == ""
    assert not generator.calls[0]["product"].has_price


def test_duplicates_dropped_by_the_parse_trigger_one_top_up_call() -> None:
    generator = FakeGenerator(_angles(7), _angles(3, start=7))
    service, repo, generator, _, _ = _service(generator=generator)
    set_id = _create(service)
    assert len(generator.calls) == 2
    assert generator.calls[1]["count"] == 3 and len(generator.calls[1]["avoid"]) == 7
    angles = repo.list_angles(tenant_id=TENANT, set_id=set_id)
    assert [a.position for a in angles] == list(range(1, 11))
    assert repo.sets[set_id].failure_detail is None


def test_still_short_after_the_top_up_the_set_says_so_but_is_usable() -> None:
    generator = FakeGenerator(_angles(7), ())
    service, repo, _, _, _ = _service(generator=generator)
    set_id = _create(service)
    record = repo.sets[set_id]
    assert record.status == SET_ANGLES_READY
    assert record.failure_detail is not None and "Solo 7" in record.failure_detail


@pytest.mark.parametrize(
    ("error", "reason_word"),
    [
        (MissingAPIKey("no key"), "Anthropic"),
        (ClaudeToolError("claude-sonnet-5 refused the request"), "rechazó"),
        (ClaudeToolError("claude-sonnet-5 hit max_tokens=6000"), "cortó"),
    ],
)
def test_a_failed_angles_call_leaves_a_failed_set_and_a_spanish_detail(
    error: Exception, reason_word: str
) -> None:
    service, repo, _, _, _ = _service(generator=FakeGenerator(error=error))
    with pytest.raises(AngleGenerationFailed) as info:
        _create(service)
    assert reason_word in info.value.detail
    (record,) = repo.sets.values()
    assert record.status == SET_FAILED and record.failure_detail == info.value.detail


def test_another_brands_or_a_missing_product_is_refused_before_any_call() -> None:
    other = replace(_product(), brand_id=uuid4())
    service, repo, generator, _, _ = _service(product=other)
    with pytest.raises(UnknownProduct):
        _create(service)
    assert repo.sets == {} and generator.calls == []
    # the catalog holds another product: the requested id is not there
    service, repo, generator, _, _ = _service(product=replace(_product(), id=uuid4()))
    with pytest.raises(UnknownProduct):
        _create(service)
    assert repo.sets == {} and generator.calls == []
    inactive = replace(_product(), is_active=False)
    service, _, _, _, _ = _service(product=inactive)
    with pytest.raises(UnknownProduct):
        _create(service)


def test_an_unknown_preset_is_refused() -> None:
    from qualify_creative.angles import UnknownPreset

    service, *_ = _service()
    with pytest.raises(UnknownPreset):
        _create(service, preset_key="nope")


# -- generating the pieces -------------------------------------------------------------------


def test_generate_pieces_makes_one_draft_per_kept_angle_in_one_campaign() -> None:
    service, repo, _, drafts, campaigns = _service()
    set_id = _create(service)
    angles = repo.list_angles(tenant_id=TENANT, set_id=set_id)
    service.discard_angle(tenant_id=TENANT, angle_id=angles[0].id)
    outcome = service.generate_pieces(tenant_id=TENANT, set_id=set_id, user_id=USER)
    assert len(outcome.queued) == 9 and outcome.failed == ()
    assert campaigns.created == [f"Shawarma mixto · 10 variaciones · {set_id.hex[:6]}"]
    assert len(campaigns.assigned) == 9 and len(drafts.briefs) == 9
    record = repo.sets[set_id]
    assert record.status == SET_GENERATING and record.campaign_id == outcome.campaign_id
    for angle in repo.list_angles(tenant_id=TENANT, set_id=set_id)[1:]:
        assert angle.status == ANGLE_QUEUED and angle.draft_id is not None
        assert angle.attempts == 1 and angle.brief is not None
    brief = drafts.briefs[0]
    assert brief.kind.value == "static_flyer" and brief.variants_requested == 1
    assert brief.media.price_line == record.price_label
    assert ("precio", record.price_label) in brief.constraints.highlights
    assert brief.media.scene_prompt.startswith(SCENES[1])
    assert brief.media.brand_logo_key == f"uploads/{TENANT}/logo.png"
    # a second call has nothing left to queue and creates no second campaign
    again = service.generate_pieces(tenant_id=TENANT, set_id=set_id, user_id=USER)
    assert again.queued == () and len(campaigns.created) == 1


def test_a_refused_brief_fails_only_its_angle() -> None:
    drafts = FakeDrafts(
        refuse=BrandNotReady(missing=("voice_profile",)), refuse_titles=("Ángulo 3",)
    )
    service, repo, _, drafts, _ = _service(drafts=drafts)
    set_id = _create(service)
    outcome = service.generate_pieces(tenant_id=TENANT, set_id=set_id, user_id=USER)
    assert len(outcome.queued) == 9 and len(outcome.failed) == 1
    failed_id, detail = outcome.failed[0]
    failed = repo.angles[failed_id]
    assert failed.status == ANGLE_FAILED and failed.title == "Ángulo 3"
    assert "Brand Kit" in detail and failed.failure_reason == "invalid_parameters"
    # attempts counts drafts created (0070): a refused brief created none
    assert failed.attempts == 0 and failed.draft_id is None


def test_retry_makes_a_new_draft_for_one_failed_angle_only() -> None:
    drafts = FakeDrafts(
        refuse=BrandNotReady(missing=("voice_profile",)), refuse_titles=("Ángulo 3",)
    )
    service, repo, _, drafts, campaigns = _service(drafts=drafts)
    set_id = _create(service)
    outcome = service.generate_pieces(tenant_id=TENANT, set_id=set_id, user_id=USER)
    failed_id = outcome.failed[0][0]
    drafts.refuse = None  # the brand is ready now
    before = len(drafts.briefs)
    draft_id = service.retry_angle(tenant_id=TENANT, angle_id=failed_id, user_id=USER)
    assert len(drafts.briefs) == before + 1
    angle = repo.angles[failed_id]
    assert angle.status == ANGLE_QUEUED and angle.draft_id == draft_id and angle.attempts == 1
    assert len(campaigns.created) == 1  # the set's campaign is reused


def test_retry_refuses_an_angle_whose_piece_is_in_progress_or_done() -> None:
    service, repo, _, drafts, _ = _service()
    set_id = _create(service)
    service.generate_pieces(tenant_id=TENANT, set_id=set_id, user_id=USER)
    angle = repo.list_angles(tenant_id=TENANT, set_id=set_id)[0]
    with pytest.raises(AngleNotActionable):
        service.retry_angle(tenant_id=TENANT, angle_id=angle.id, user_id=USER)
    # a draft that FAILED can be retried: a new draft, the old one untouched
    assert angle.draft_id is not None
    drafts.details[angle.draft_id] = _detail(
        angle.draft_id, DraftStatus.FAILED.value, failure="timeout"
    )
    new_id = service.retry_angle(tenant_id=TENANT, angle_id=angle.id, user_id=USER)
    assert new_id != angle.draft_id and repo.angles[angle.id].attempts == 2


def test_discard_and_restore_apply_only_before_generation() -> None:
    service, repo, _, _, _ = _service()
    set_id = _create(service)
    angle = repo.list_angles(tenant_id=TENANT, set_id=set_id)[0]
    service.discard_angle(tenant_id=TENANT, angle_id=angle.id)
    assert repo.angles[angle.id].status == ANGLE_DISCARDED
    with pytest.raises(AngleNotActionable):
        service.discard_angle(tenant_id=TENANT, angle_id=angle.id)
    service.restore_angle(tenant_id=TENANT, angle_id=angle.id)
    assert repo.angles[angle.id].status == ANGLE_PROPOSED
    service.generate_pieces(tenant_id=TENANT, set_id=set_id, user_id=USER, angle_ids=[angle.id])
    with pytest.raises(AngleNotActionable):
        service.discard_angle(tenant_id=TENANT, angle_id=angle.id)


# -- the gallery view ---------------------------------------------------------------------------


def test_detail_reads_each_drafts_status_words_and_price_conflicts() -> None:
    service, repo, _, drafts, _ = _service()
    set_id = _create(service)
    service.generate_pieces(tenant_id=TENANT, set_id=set_id, user_id=USER)
    angles = repo.list_angles(tenant_id=TENANT, set_id=set_id)
    label = repo.sets[set_id].price_label
    good, bad = angles[0], angles[1]
    drafts.details[good.draft_id] = _detail(
        good.draft_id, DraftStatus.GENERATED.value, hook=f"Hoy a {label}"
    )  # type: ignore[arg-type]
    drafts.details[bad.draft_id] = _detail(
        bad.draft_id, DraftStatus.GENERATED.value, hook="Solo $9.900 hoy"
    )  # type: ignore[arg-type]
    detail = service.detail(tenant_id=TENANT, set_id=set_id)
    views = {v.angle.id: v for v in detail.angles}
    assert views[good.id].draft_status == "generated" and views[good.id].can_approve
    assert views[good.id].price_conflicts == () and views[good.id].preview_key
    assert views[bad.id].price_conflicts == ("$9.900",)
    assert views[angles[2].id].draft_status == "drafting" and not views[angles[2].id].can_retry
    assert detail.set.status == SET_GENERATING  # eight still drafting


def test_a_set_whose_pieces_all_finished_is_completed_and_approval_goes_through_the_service() -> (
    None
):
    service, repo, _, drafts, _ = _service(generator=FakeGenerator(_angles(3)))
    set_id = _create(service, count=3)
    service.generate_pieces(tenant_id=TENANT, set_id=set_id, user_id=USER)
    angles = repo.list_angles(tenant_id=TENANT, set_id=set_id)
    for a in angles:
        drafts.details[a.draft_id] = _detail(a.draft_id, DraftStatus.GENERATED.value)  # type: ignore[arg-type]
    service.approve_angle(tenant_id=TENANT, angle_id=angles[0].id, user_id=USER)
    assert len(drafts.approved) == 1 and repo.angles[angles[0].id].status == ANGLE_APPROVED
    with pytest.raises(AngleNotActionable):
        service.approve_angle(tenant_id=TENANT, angle_id=angles[0].id, user_id=USER)
    detail = service.detail(tenant_id=TENANT, set_id=set_id)
    assert detail.set.status == SET_COMPLETED
    assert all(v.is_done for v in detail.angles)


def test_angle_presets_are_what_the_service_accepts() -> None:
    from qualify_creative.angles import PRESETS

    assert all(isinstance(p, AnglePreset) for p in PRESETS)
    assert isinstance(product_facts(_product()), AngleProduct)


# -- block 3: never stuck, never paid twice (defects 4, 5, 6, 8, 12, 13, 16, 17) ---------


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def _clocked(
    drafts: FakeDrafts | None = None, generator: FakeGenerator | None = None
) -> tuple[AngleSetService, MemoryRepo, FakeDrafts, FakeCampaigns, Clock, FakeCatalog]:
    repo, campaigns, clock = MemoryRepo(), FakeCampaigns(), Clock()
    drafts = drafts or FakeDrafts()
    catalog = FakeCatalog(_product())
    service = AngleSetService(
        repository=repo,
        catalog=catalog,
        brand_facts=lambda *, tenant_id, brand_id: AngleBrand(name="Bianki"),
        kit_reader=FakeKits(),
        generator=generator or FakeGenerator(_angles(10)),
        drafts=drafts,
        campaigns=campaigns,
        clock=clock,
    )
    return service, repo, drafts, campaigns, clock, catalog


def _angle_at(repo: MemoryRepo, position: int) -> AngleRecord:
    return next(a for a in repo.angles.values() if a.position == position)


def _view_of(service: AngleSetService, set_id: UUID, angle_id: UUID) -> Any:
    detail = service.detail(tenant_id=TENANT, set_id=set_id)
    return next(v for v in detail.angles if v.angle.id == angle_id)


def test_an_unexpected_error_in_the_angles_call_never_leaves_the_set_drafting() -> None:
    # defect 12 / the production TypeError: whatever the call raises, the set says failed
    service, repo, *_ = _service(generator=FakeGenerator(error=TypeError("unexpected kw")))
    with pytest.raises(AngleGenerationFailed) as caught:
        _create(service)
    (record,) = repo.sets.values()
    assert record.status == SET_FAILED and record.failure_detail == caught.value.detail
    assert record.failure_reason is not None


@pytest.mark.parametrize(
    ("retryable", "words"), [(True, "Inténtalo en unos minutos"), (False, "rechazó")]
)
def test_anthropic_not_answering_is_a_failed_set_with_a_clear_reason(
    retryable: bool, words: str
) -> None:
    error = AnglesProviderError("anthropic answered HTTP 529", status=529, retryable=retryable)
    service, repo, *_ = _service(generator=FakeGenerator(error=error))
    with pytest.raises(AngleGenerationFailed, match=words):
        _create(service)
    (record,) = repo.sets.values()
    assert record.status == SET_FAILED and words in (record.failure_detail or "")


def test_a_template_preset_for_a_product_without_photos_is_refused_before_paying() -> None:
    generator = FakeGenerator(_angles(10))
    service, repo, *_ = _service(product=_product(photos=0), generator=generator)
    with pytest.raises(PresetNotAvailable, match="foto"):
        _create(service, preset_key="plantilla_promo")
    assert repo.sets == {} and generator.calls == []


def test_the_set_records_which_brand_kit_facts_the_angles_were_asked_with() -> None:
    # defect 17: provenance of the brand kit (`brand_kits` has no version column)
    service, repo, *_ = _service()
    set_id = _create(service)
    stored = repo.sets[set_id].brand_kit_fingerprint
    assert stored == brand_fingerprint(AngleBrand(name="Bianki"))
    assert brand_fingerprint(AngleBrand(name="Bianki", positioning="otro")) != stored


def test_the_fingerprint_counts_the_typeface_only_when_the_kit_declares_it() -> None:
    """§ request 2026-10-21: the type face is now in the prompt, so it is in its
    provenance — but a kit without one keeps the fingerprint it always had."""
    import hashlib

    plain = AngleBrand(name="Bianki", palette=("#C4622D",))
    before = hashlib.sha256(b"Bianki\n\n\n\n\n#C4622D").hexdigest()[:16]
    assert brand_fingerprint(plain) == before
    baloo = brand_fingerprint(AngleBrand(name="Bianki", palette=("#C4622D",), typeface="Baloo 2"))
    assert baloo != before
    assert baloo != brand_fingerprint(
        AngleBrand(name="Bianki", palette=("#C4622D",), typeface="Nunito")
    )


def test_the_brand_facts_carry_the_kits_one_typeface() -> None:
    """Review 2026-10-21: the production wiring hands the kit's type face to the angles —
    the headline face of a kit saved when the Brand Kit asked two."""
    from qualify_api.creative.composition import _DbBrandFacts

    kit = BrandKit(
        brand_id=uuid4(),
        positioning="Shawarma al carbón",
        audience="Oficinistas",
        tone_axes=ToneAxes(
            formal_casual=60, sober_enthusiastic=60, technical_plain=60, brief_elaborate=40
        ),
        palette_rgb=("#C4622D",),
        font_heading="Baloo 2",
        font_body="Nunito",
    )
    facts = object.__new__(_DbBrandFacts)
    facts._names = lambda *, tenant_id, brand_id: "Bianki"  # type: ignore[attr-defined]
    facts._kits = SimpleNamespace(kit=lambda *, tenant_id, brand_id: kit)  # type: ignore[attr-defined]
    facts._context = SimpleNamespace(context=lambda *, tenant_id, brand_id: None)  # type: ignore[attr-defined]
    brand = facts(tenant_id=uuid4(), brand_id=kit.brand_id)
    assert (brand.name, brand.palette, brand.typeface) == ("Bianki", ("#C4622D",), "Baloo 2")
    facts._kits = SimpleNamespace(kit=lambda *, tenant_id, brand_id: None)  # type: ignore[attr-defined]
    assert facts(tenant_id=uuid4(), brand_id=kit.brand_id).typeface == ""


def test_a_double_click_creates_one_draft_per_angle_not_two() -> None:
    # defect 6: a second generate_pieces arriving while the first is mid-way
    service, repo, drafts, campaigns, *_ = _clocked(generator=FakeGenerator(_angles(3)))
    set_id = _create(service, count=3)
    second: list[Any] = []
    clicked: list[bool] = []
    original = drafts.create_draft

    def create_and_race(**kwargs: Any) -> UUID:
        if not clicked:  # the other tab clicks ONCE while the first draft is being created
            clicked.append(True)
            second.append(service.generate_pieces(tenant_id=TENANT, set_id=set_id, user_id=USER))
        return original(**kwargs)

    drafts.create_draft = create_and_race  # type: ignore[method-assign]
    first = service.generate_pieces(tenant_id=TENANT, set_id=set_id, user_id=USER)
    racing = second[0]
    # the first call lost the race for the angles the other tab took: told, not duplicated
    assert all("ya se está generando" in detail for _, detail in first.failed)
    # every angle got exactly one draft, split between the two calls, none twice
    assert len(drafts.dispatched) == 3
    assert sorted(first.queued + racing.queued) == sorted(a.id for a in repo.angles.values())
    assert not set(first.queued) & set(racing.queued)
    assert len({campaign for _, campaign in campaigns.assigned}) == 1


def test_two_concurrent_retries_of_one_angle_create_one_draft() -> None:
    service, repo, drafts, *_ = _clocked(generator=FakeGenerator(_angles(3)))
    set_id = _create(service, count=3)
    service.generate_pieces(tenant_id=TENANT, set_id=set_id, user_id=USER)
    angle = _angle_at(repo, 1)
    assert angle.draft_id is not None
    drafts.details[angle.draft_id] = _detail(angle.draft_id, DraftStatus.FAILED.value)
    blocked: list[str] = []
    original = drafts.create_draft

    def create_and_race(**kwargs: Any) -> UUID:
        if not blocked:
            try:
                service.retry_angle(tenant_id=TENANT, angle_id=angle.id, user_id=USER)
            except AngleNotActionable as exc:
                blocked.append(exc.detail)
        return original(**kwargs)

    drafts.create_draft = create_and_race  # type: ignore[method-assign]
    before = len(drafts.dispatched)
    service.retry_angle(tenant_id=TENANT, angle_id=angle.id, user_id=USER)
    assert len(drafts.dispatched) == before + 1
    assert blocked and "ya se está generando" in blocked[0]


def test_a_crash_after_the_draft_exists_attaches_it_instead_of_paying_again() -> None:
    # defect 5: the draft was created (and dispatched) but the angle's update never ran
    drafts = FakeDrafts(crash_after_create=RuntimeError("connection reset"))
    service, repo, drafts, *_ = _clocked(drafts=drafts, generator=FakeGenerator(_angles(3)))
    set_id = _create(service, count=3)
    outcome = service.generate_pieces(tenant_id=TENANT, set_id=set_id, user_id=USER)
    assert len(drafts.dispatched) == 3  # one per angle, the crashed one included
    crashed = _angle_at(repo, 1)
    assert crashed.status == ANGLE_QUEUED and crashed.draft_id == drafts.dispatched[0]
    assert outcome.unresolved == ()
    # nothing is left to send again
    again = service.generate_pieces(tenant_id=TENANT, set_id=set_id, user_id=USER)
    assert again.queued == () and len(drafts.dispatched) == 3


def test_a_crash_before_the_draft_marks_it_interrupted_and_the_retry_keeps_the_key() -> None:
    service, repo, drafts, *_ = _clocked(generator=FakeGenerator(_angles(3)))
    set_id = _create(service, count=3)
    original = drafts.create_draft
    calls: list[int] = []

    def fail_first(**kwargs: Any) -> UUID:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("timeout before the insert")
        return original(**kwargs)

    drafts.create_draft = fail_first  # type: ignore[method-assign]
    outcome = service.generate_pieces(tenant_id=TENANT, set_id=set_id, user_id=USER)
    interrupted = _angle_at(repo, 1)
    assert interrupted.status == ANGLE_FAILED and interrupted.failure_reason == INTERRUPTED
    assert interrupted.request_key is not None
    assert [angle_id for angle_id, _ in outcome.failed] == [interrupted.id]
    # a late draft did appear under that key: the retry returns it and pays nothing
    late = uuid4()
    drafts.by_key[interrupted.request_key] = late
    before = len(drafts.dispatched)
    assert service.retry_angle(tenant_id=TENANT, angle_id=interrupted.id, user_id=USER) == late
    assert len(drafts.dispatched) == before
    assert repo.angles[interrupted.id].status == ANGLE_QUEUED


def test_an_unknown_outcome_stays_reserved_until_recovered_by_its_key() -> None:
    drafts = FakeDrafts(
        crash_after_create=RuntimeError("connection reset"),
        lookup_error=RuntimeError("database down"),
    )
    service, repo, drafts, _, clock, _ = _clocked(
        drafts=drafts, generator=FakeGenerator(_angles(3))
    )
    set_id = _create(service, count=3)
    outcome = service.generate_pieces(tenant_id=TENANT, set_id=set_id, user_id=USER)
    stuck = _angle_at(repo, 1)
    assert outcome.unresolved == (stuck.id,) and stuck.status == ANGLE_RESERVED
    assert repo.sets[set_id].status == SET_GENERATING  # the others went through
    # within the timeout nothing touches it — a retry is refused, nothing is paid
    with pytest.raises(AngleNotActionable):
        service.retry_angle(tenant_id=TENANT, angle_id=stuck.id, user_id=USER)
    # the database is back and the reservation expired: the draft is found by its key
    drafts.lookup_error = None
    clock.now = NOW + RESERVATION_TIMEOUT + timedelta(seconds=1)
    service.detail(tenant_id=TENANT, set_id=set_id)
    recovered = repo.angles[stuck.id]
    assert recovered.status == ANGLE_QUEUED and recovered.draft_id == drafts.dispatched[0]
    assert len(drafts.dispatched) == 3


def test_one_failing_angle_never_stops_the_others() -> None:
    # defect 4: a refused brand, an unexpected error and failed grouping in one batch
    service, repo, drafts, campaigns, *_ = _clocked(generator=FakeGenerator(_angles(4)))
    set_id = _create(service, count=4)
    original = drafts.create_draft
    seen: list[int] = []

    def mixed(**kwargs: Any) -> UUID:
        seen.append(1)
        if len(seen) == 2:
            raise BrandNotReady(missing=("voice_profile",))
        if len(seen) == 3:
            raise ValueError("unexpected")
        return original(**kwargs)

    def no_grouping(**_kwargs: Any) -> None:
        raise RuntimeError("campaigns unavailable")

    drafts.create_draft = mixed  # type: ignore[method-assign]
    campaigns.assign = no_grouping  # type: ignore[method-assign]
    outcome = service.generate_pieces(tenant_id=TENANT, set_id=set_id, user_id=USER)
    assert len(outcome.queued) == 2 and len(outcome.failed) == 2
    assert len(outcome.warnings) == 2  # made, but not grouped
    assert repo.sets[set_id].status == SET_GENERATING
    assert {a.status for a in repo.angles.values()} == {ANGLE_QUEUED, ANGLE_FAILED}


def test_a_deleted_draft_makes_its_angle_retryable() -> None:
    # defect 8: content_drafts row gone → the FK sets creative_angles.draft_id NULL
    service, repo, *_ = _clocked(generator=FakeGenerator(_angles(3)))
    set_id = _create(service, count=3)
    service.generate_pieces(tenant_id=TENANT, set_id=set_id, user_id=USER)
    angle = _angle_at(repo, 1)
    repo.angles[angle.id] = replace(angle, draft_id=None)
    assert _view_of(service, set_id, angle.id).can_retry
    new_draft = service.retry_angle(tenant_id=TENANT, angle_id=angle.id, user_id=USER)
    assert repo.angles[angle.id].draft_id == new_draft and repo.angles[angle.id].attempts == 2


def test_a_copy_that_changes_the_price_cannot_be_approved() -> None:
    # defect 16: the catalog says $18.000, the copy says $15.000
    service, repo, drafts, *_ = _clocked(generator=FakeGenerator(_angles(3)))
    set_id = _create(service, count=3)
    service.generate_pieces(tenant_id=TENANT, set_id=set_id, user_id=USER)
    angle = _angle_at(repo, 1)
    assert angle.draft_id is not None
    drafts.details[angle.draft_id] = _detail(
        angle.draft_id, DraftStatus.GENERATED.value, hook="Shawarma mixto a $15.000"
    )
    view = _view_of(service, set_id, angle.id)
    assert view.price_conflicts == ("$15.000",) and not view.can_approve
    with pytest.raises(AngleNotActionable, match=r"\$15\.000"):
        service.approve_angle(tenant_id=TENANT, angle_id=angle.id, user_id=USER)
    assert drafts.approved == [] and repo.angles[angle.id].status == ANGLE_QUEUED


def test_the_product_and_kit_are_read_once_per_batch() -> None:
    # defect 13: ten pieces, one catalog read (plus the one create_set made)
    service, _, _, _, _, catalog = _clocked()
    set_id = _create(service)
    reads_after_create = catalog.reads
    service.generate_pieces(tenant_id=TENANT, set_id=set_id, user_id=USER)
    assert catalog.reads == reads_after_create + 1


def test_the_production_wiring_calls_the_real_generate_angles(monkeypatch: Any) -> None:
    # the contract the TypeError broke: composition's generator → angles_ai.generate_angles
    import qualify_api.creative.angles_ai as angles_ai
    from qualify_api.creative.composition import _PlatformAngleGenerator

    monkeypatch.setenv("QUALIFY_ANTHROPIC_API_KEY", "test-key")
    rows = [
        {
            "title": f"Ángulo {i}",
            "scene": SCENES[i],
            "composition": "plano medio",
            "hook": "h",
            "cta": "c",
            "rationale": "r",
        }
        for i in range(3)
    ]
    block = SimpleNamespace(
        type="tool_use", name="proponer_angulos_visuales", input={"angles": rows}
    )
    usage = SimpleNamespace(input_tokens=10, output_tokens=10, cache_read_input_tokens=0)
    response = SimpleNamespace(
        content=[block], stop_reason="tool_use", model="claude-sonnet-5-20260601", usage=usage
    )
    client = SimpleNamespace(messages=SimpleNamespace(create=lambda **_kwargs: response))
    monkeypatch.setattr(angles_ai, "default_client", lambda _key: client)
    angles, stats, _ = _PlatformAngleGenerator()(
        product_facts(_product()),
        AngleBrand(name="Bianki"),
        preset_by_key("escena_producto"),
        count=3,
        avoid=(),
    )
    assert len(angles) == 3 and stats.tool_calls == 1


def test_the_angle_migration_is_0070_and_follows_the_only_0069() -> None:
    # 0069 was taken by comment_intent_results (PR #178): this migration chains after it
    import re
    from pathlib import Path

    versions = Path(__file__).resolve().parents[3] / "migrations" / "postgres" / "versions"
    source = (versions / "0070_creative_angle_sets.py").read_text(encoding="utf-8")
    assert re.search(r'^revision = "0070"$', source, re.M)
    assert re.search(r'^down_revision = "0069"$', source, re.M)
    assert [p.name for p in versions.glob("0069_*.py")] == ["0069_comment_intent_results.py"]
    assert [p.name for p in versions.glob("0070_*.py")] == ["0070_creative_angle_sets.py"]


# -- review findings of block 3 --------------------------------------------------------


def test_two_sets_of_the_same_product_get_their_own_campaign() -> None:
    # R1: campaigns are unique by name per brand — the name carries the set
    service, repo, _, _, campaigns = _service(generator=FakeGenerator(_angles(3), _angles(3)))
    first = _create(service, count=3)
    second = _create(service, count=3)
    service.generate_pieces(tenant_id=TENANT, set_id=first, user_id=USER)
    service.generate_pieces(tenant_id=TENANT, set_id=second, user_id=USER)
    assert len(set(campaigns.created)) == 2
    assert campaign_name("Shawarma mixto", 3, first) != campaign_name("Shawarma mixto", 3, second)


def test_a_failure_saving_the_angles_marks_the_set_failed_with_what_was_paid() -> None:
    # R2: the angles came back (paid) but storing them failed — never left drafting
    service, repo, *_ = _service(generator=FakeGenerator(_angles(10)))

    def broken_insert(**_kwargs: Any) -> tuple[UUID, ...]:
        raise RuntimeError("connection dropped")

    repo.insert_angles = broken_insert  # type: ignore[method-assign]
    with pytest.raises(AngleGenerationFailed, match="guardar"):
        _create(service)
    (record,) = repo.sets.values()
    assert record.status == SET_FAILED
    assert record.input_tokens == 1000 and record.model_id == "claude-sonnet-5"


def test_a_failed_top_up_keeps_the_first_batch_and_its_cost() -> None:
    # R3: 8 good angles paid for; the top-up for the other 2 fails → the 8 stay
    generator = FakeGenerator(_angles(8))
    calls: list[int] = []
    original = generator.__call__

    def second_call_fails(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        if len(calls) == 2:
            raise AnglesProviderError("anthropic answered HTTP 529", status=529, retryable=True)
        return original(*args, **kwargs)

    service, repo, *_ = _service(generator=second_call_fails)  # type: ignore[arg-type]
    set_id = _create(service)
    record = repo.sets[set_id]
    assert record.status == SET_ANGLES_READY and record.input_tokens == 1000
    assert len(repo.list_angles(tenant_id=TENANT, set_id=set_id)) == 8
    assert record.failure_detail is not None and "Solo 8" in record.failure_detail


def test_a_set_with_no_usable_angles_is_failed_not_ready() -> None:
    # R7: both calls came back empty
    service, repo, *_ = _service(generator=FakeGenerator((), ()))
    with pytest.raises(AngleGenerationFailed, match="utilizables"):
        _create(service)
    (record,) = repo.sets.values()
    assert record.status == SET_FAILED and record.input_tokens == 2000  # both calls recorded


def test_a_database_error_on_one_angle_does_not_stop_the_batch() -> None:
    # R5: reserve_angle raising mid-batch (the database) leaves that angle unresolved only
    service, repo, drafts, *_ = _clocked(generator=FakeGenerator(_angles(3)))
    set_id = _create(service, count=3)
    original = repo.reserve_angle
    seen: list[int] = []

    def flaky_reserve(**kwargs: Any) -> bool:
        seen.append(1)
        if len(seen) == 2:
            raise RuntimeError("database hiccup")
        return original(**kwargs)

    repo.reserve_angle = flaky_reserve  # type: ignore[method-assign]
    outcome = service.generate_pieces(tenant_id=TENANT, set_id=set_id, user_id=USER)
    assert len(outcome.queued) == 2 and len(outcome.unresolved) == 1
    assert len(drafts.dispatched) == 2 and repo.sets[set_id].status == SET_GENERATING


# -- PR 4: the gallery reads its drafts in one batch ------------------------------------


def test_detail_reads_every_draft_of_the_set_in_one_batch() -> None:
    service, repo, drafts, *_ = _clocked(generator=FakeGenerator(_angles(10)))
    set_id = _create(service)
    service.generate_pieces(tenant_id=TENANT, set_id=set_id, user_id=USER)
    drafts.single_reads.clear()
    detail = service.detail(tenant_id=TENANT, set_id=set_id)
    assert len(drafts.batch_reads) == 1 and len(drafts.batch_reads[0]) == 10
    assert drafts.single_reads == []  # no read per angle
    assert all(v.draft_status == DraftStatus.DRAFTING.value for v in detail.angles)


def test_detail_of_a_set_without_drafts_reads_no_draft() -> None:
    service, _, drafts, *_ = _clocked(generator=FakeGenerator(_angles(3)))
    set_id = _create(service, count=3)
    service.detail(tenant_id=TENANT, set_id=set_id)
    assert drafts.batch_reads == [()] and drafts.single_reads == []


def test_product_presets_tell_the_screen_what_each_preset_can_do() -> None:
    service, *_ = _service(product=_product(photos=0))
    facts, choices = service.product_presets(
        tenant_id=TENANT, brand_id=BRAND, product_id=PRODUCT_ID
    )
    assert facts.name == "Shawarma mixto" and facts.photo_keys == ()
    problems = {preset.key: problem for preset, problem in choices}
    assert problems["escena_producto"] is None
    assert problems["plantilla_promo"] is not None and "foto" in problems["plantilla_promo"]


def test_product_presets_refuse_another_brands_product() -> None:
    service, *_ = _service()
    with pytest.raises(UnknownProduct):
        service.product_presets(tenant_id=TENANT, brand_id=uuid4(), product_id=PRODUCT_ID)


# -- PR 5: one price rule on every approval path, warnings, approvals made elsewhere ----


def _generated_angle(
    *, price: Decimal | None = Decimal("18000"), hook: str = "Shawarma mixto a $18.000"
) -> tuple[AngleSetService, MemoryRepo, FakeDrafts, UUID, AngleRecord]:
    service, repo, drafts, _, _, catalog = _clocked(generator=FakeGenerator(_angles(3)))
    catalog.product = _product(price)
    set_id = _create(service, count=3)
    service.generate_pieces(tenant_id=TENANT, set_id=set_id, user_id=USER)
    angle = _angle_at(repo, 1)
    assert angle.draft_id is not None
    drafts.details[angle.draft_id] = _detail(angle.draft_id, DraftStatus.GENERATED.value, hook=hook)
    return service, repo, drafts, set_id, angle


def test_the_view_says_why_a_foreign_price_blocks_the_approval() -> None:
    service, _, _, set_id, angle = _generated_angle(hook="Shawarma mixto a $15.000")
    view = _view_of(service, set_id, angle.id)
    assert view.price_problem is not None
    assert "$15.000" in view.price_problem and "precio del catálogo ($" in view.price_problem


def test_without_a_catalog_price_a_quoted_figure_is_refused_as_invented() -> None:
    service, repo, drafts, set_id, angle = _generated_angle(price=None, hook="Solo $9.900 hoy")
    view = _view_of(service, set_id, angle.id)
    assert not view.can_approve and "no tiene precio en el catálogo" in (view.price_problem or "")
    with pytest.raises(AngleNotActionable, match="no tiene precio en el catálogo"):
        service.approve_angle(tenant_id=TENANT, angle_id=angle.id, user_id=USER)
    assert drafts.approved == [] and repo.angles[angle.id].status == ANGLE_QUEUED


def test_without_a_catalog_price_a_copy_without_figures_is_approved() -> None:
    service, repo, drafts, set_id, angle = _generated_angle(price=None, hook="Para 6 personas")
    assert _view_of(service, set_id, angle.id).price_problem is None
    service.approve_angle(tenant_id=TENANT, angle_id=angle.id, user_id=USER)
    assert drafts.approved and repo.angles[angle.id].status == ANGLE_APPROVED


def test_an_angle_approved_in_the_drafts_screen_is_recorded_as_approved() -> None:
    service, repo, drafts, set_id, angle = _generated_angle()
    assert angle.draft_id is not None
    # /drafts/{id} approved it through the content service, not through approve_angle
    drafts.details[angle.draft_id] = replace(
        drafts.details[angle.draft_id], status=DraftStatus.APPROVED.value
    )
    view = _view_of(service, set_id, angle.id)
    assert view.angle.status == ANGLE_APPROVED and view.is_done and not view.can_approve
    assert repo.angles[angle.id].status == ANGLE_APPROVED
    # a draft still waiting for review leaves its angle alone
    other = _angle_at(repo, 2)
    assert repo.angles[other.id].status == ANGLE_QUEUED


def test_the_view_carries_the_composition_warnings_of_the_piece() -> None:
    from qualify_api.creative.media import PRICE_NOT_PRINTED, PRICE_NOT_PRINTED_TEXT
    from qualify_api.creative.service import COMPOSITION_WARNINGS_PARAM, ImageRecord

    service, _, drafts, set_id, angle = _generated_angle()
    assert angle.draft_id is not None
    cover = ImageRecord(
        id=uuid4(),
        media_url="m/0.jpg",
        width=None,
        height=None,
        aspect_ratio=None,
        params={
            COMPOSITION_WARNINGS_PARAM: [
                {"code": PRICE_NOT_PRINTED, "detail": PRICE_NOT_PRINTED_TEXT, "fields": {}}
            ]
        },
        object_key="t/x/m/0.jpg",
    )
    drafts.details[angle.draft_id] = replace(drafts.details[angle.draft_id], media=(cover,))
    assert _view_of(service, set_id, angle.id).warnings == (PRICE_NOT_PRINTED_TEXT,)


@pytest.mark.parametrize(
    ("price_label", "hook", "refused"),
    [
        (None, "Antes $99.000", None),  # not an angle's draft: never checked
        ("$18.000", "Hoy $18.000", None),  # the catalog's own price
        ("$18.000", "Hoy $15.000", "que no es el precio del catálogo"),
        ("", "Sin cifras, para 4", None),  # no price and no figure
        ("", "Hoy $9.900", "no tiene precio en el catálogo"),
    ],
)
def test_the_price_guard_holds_only_an_angles_draft_to_the_catalog(
    price_label: str | None, hook: str, refused: str | None
) -> None:
    from qualify_api.creative.angle_sets import AnglePriceGuard
    from qualify_api.creative.service import ApprovalBlocked

    asked: list[tuple[UUID, UUID]] = []

    def lookup(tenant_id: UUID, draft_id: UUID) -> str | None:
        asked.append((tenant_id, draft_id))
        return price_label

    guard, draft_id = AnglePriceGuard(lookup), uuid4()
    copy = {"hook": hook, "caption": "", "cta": "Pide ya"}
    if refused is None:
        guard.check(tenant_id=TENANT, draft_id=draft_id, copy=copy)
    else:
        with pytest.raises(ApprovalBlocked, match=refused):
            guard.check(tenant_id=TENANT, draft_id=draft_id, copy=copy)
    assert asked == [(TENANT, draft_id)]
