"""`db`-marked tests for `BrandKitService` + `VoiceProfileService` (S1 manual scope).

The kit contract under test is round-trip fidelity: pydantic → ORM → pydantic must be
lossless for every field, asserted as whole-model equality (frozen pydantic models
compare by value). The voice contract is the lifecycle: propose → approve → active,
with the single-ACTIVE invariant surviving a second approve.

Seeding goes through the BYPASSRLS admin door (R8) and is idempotent insert-if-absent —
the app role has no DELETE grant, so re-runs must coexist with prior rows (which is why
versions are asserted relatively, never as absolute numbers)."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_creative.enums import EmojiPolicy, ImageRoute, VoiceProfileStatus, VoiceSourceKind
from qualify_creative.schemas import (
    BrandKit,
    HashtagPolicy,
    ImagePolicy,
    LengthTargets,
    ToneAxes,
)
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import func, select

from qualify_api.creative.brand_service import BrandKitService
from qualify_api.creative.models import BrandKit as BrandKitRow
from qualify_api.creative.models import BrandVoiceProfile as VoiceProfileRow
from qualify_api.creative.readiness import readiness
from qualify_api.creative.voice_service import (
    NotProposed,
    UnknownBrandKit,
    UnknownVersion,
    VoiceProfileService,
)
from qualify_api.tenancy.models import Brand, Tenant, User

pytestmark = pytest.mark.db

# Distinct from the tenants of every other db test module so suites stay independent.
TENANT_A = UUID("c0000000-0000-4000-8000-0000000000e1")
TENANT_B = UUID("d0000000-0000-4000-8000-0000000000e2")


@pytest.fixture
def seeded() -> tuple[UUID, UUID, UUID, UUID, UUID]:
    """Two tenants with a brand each, plus a user in A. Idempotent for local re-runs.

    Returns (tenant_a, brand_a, user_a, tenant_b, brand_b). Tenant B's brand never
    receives a kit in this module — `test_propose_without_kit` depends on that.
    """
    with admin_session() as session:
        for tid, name in ((TENANT_A, "A"), (TENANT_B, "B")):
            if session.get(Tenant, tid) is None:
                session.add(
                    Tenant(
                        id=tid,
                        name=f"creative-svc-t-{name}",
                        country="CO",
                        timezone="America/Bogota",
                        currency="COP",
                    )
                )
                session.flush()
        brand_ids: dict[UUID, UUID] = {}
        for tid, name in ((TENANT_A, "A"), (TENANT_B, "B")):
            brand = session.scalar(select(Brand).where(Brand.tenant_id == tid))
            if brand is None:
                brand = Brand(tenant_id=tid, name=f"creative-svc-brand-{name}")
                session.add(brand)
                session.flush()
            brand_ids[tid] = brand.id
        user = User(tenant_id=TENANT_A, email=f"creative-svc-{uuid4()}@a.co", display_name="U")
        session.add(user)
        session.flush()
        user_id = user.id
    return TENANT_A, brand_ids[TENANT_A], user_id, TENANT_B, brand_ids[TENANT_B]


def _rich_kit(brand_id: UUID) -> BrandKit:
    """Every field populated away from its default, so equality proves each column."""
    return BrandKit(
        brand_id=brand_id,
        positioning="artisan arepas, zero shortcuts",
        audience="walk-in customers in Cali",
        language="es",
        regional_variant="es-CO",
        tone_axes=ToneAxes(
            formal_casual=30, sober_enthusiastic=70, technical_plain=80, brief_elaborate=40
        ),
        do_examples=("¡Llegó la arepa de chócolo!", "Ven por la tuya antes de las 6"),
        dont_examples=("Estimado cliente, le informamos...",),
        banned_words=("gourmet", "premium"),
        forbidden_claims=("la mejor de Colombia",),
        emoji_policy=EmojiPolicy.NONE,
        hashtag_policy=HashtagPolicy(minimum=1, maximum=5, always=("arepas",), never=("ad",)),
        cta_patterns=("Pide por WhatsApp",),
        length_targets=LengthTargets(caption_min_chars=100, caption_max_chars=500),
        palette_rgb=("#FFD100", "#1A1A1A"),
        logo_asset_key="brand/logo.png",
        template_asset_key="brand/template.png",
        reference_image_keys=("brand/ref-1.jpg", "brand/ref-2.jpg"),
        image_policy=ImagePolicy(
            allowed_routes=frozenset({ImageRoute.TEMPLATE_ONLY, ImageRoute.FROM_UPLOAD}),
            blocked_reason={ImageRoute.GENERATE: "no inventar el producto"},
        ),
    )


def test_kit_round_trip_is_lossless(seeded: tuple[UUID, UUID, UUID, UUID, UUID]) -> None:
    tenant_a, brand_a, user_a, _, _ = seeded
    service = BrandKitService()
    kit = _rich_kit(brand_a)

    service.upsert_kit(tenant_id=tenant_a, brand_id=brand_a, kit=kit, user_id=user_a)
    stored = service.get_kit(tenant_id=tenant_a, brand_id=brand_a)
    # Whole-model equality: pydantic compares field-by-field, so this IS the fidelity
    # contract — any column that dropped, reordered or coerced a value fails here.
    assert stored == kit

    # The update path: same row, new values, still lossless.
    updated = kit.model_copy(
        update={
            "positioning": "arepas de chócolo, hechas al momento",
            "banned_words": ("gourmet", "premium", "delicatessen"),
            "emoji_policy": EmojiPolicy.SPARSE,
            "logo_asset_key": None,
        }
    )
    service.upsert_kit(tenant_id=tenant_a, brand_id=brand_a, kit=updated, user_id=user_a)
    assert service.get_kit(tenant_id=tenant_a, brand_id=brand_a) == updated

    with tenant_session(tenant_a) as session:
        count = session.scalar(
            select(func.count()).select_from(BrandKitRow).where(BrandKitRow.brand_id == brand_a)
        )
        assert count == 1  # upsert, never a second row


def test_kit_mismatched_brand_id_rejected(seeded: tuple[UUID, UUID, UUID, UUID, UUID]) -> None:
    tenant_a, brand_a, user_a, _, _ = seeded
    with pytest.raises(ValueError):
        BrandKitService().upsert_kit(
            tenant_id=tenant_a, brand_id=brand_a, kit=_rich_kit(uuid4()), user_id=user_a
        )


def test_kit_is_tenant_isolated(seeded: tuple[UUID, UUID, UUID, UUID, UUID]) -> None:
    tenant_a, brand_a, user_a, tenant_b, _ = seeded
    service = BrandKitService()
    service.upsert_kit(tenant_id=tenant_a, brand_id=brand_a, kit=_rich_kit(brand_a), user_id=user_a)
    # Same brand id, other tenant's RLS scope: nothing comes back.
    assert service.get_kit(tenant_id=tenant_b, brand_id=brand_a) is None


def test_voice_propose_approve_active_flow(seeded: tuple[UUID, UUID, UUID, UUID, UUID]) -> None:
    tenant_a, brand_a, user_a, _, _ = seeded
    kit = _rich_kit(brand_a)
    BrandKitService().upsert_kit(tenant_id=tenant_a, brand_id=brand_a, kit=kit, user_id=user_a)
    voice = VoiceProfileService()

    v1 = voice.propose_from_kit(tenant_id=tenant_a, brand_id=brand_a, user_id=user_a)
    voice.approve(tenant_id=tenant_a, brand_id=brand_a, version=v1, user_id=user_a)

    active = voice.active_profile(tenant_id=tenant_a, brand_id=brand_a)
    assert active is not None
    assert active.version == v1
    assert active.status is VoiceProfileStatus.ACTIVE
    # Deterministic S1 distillation: tone axes copied, lexicon = CTA patterns verbatim
    # plus 4+-letter tokens mined from the do-examples, avoid = banned words.
    assert active.tone_axes == kit.tone_axes
    assert active.lexicon == ("Pide por WhatsApp", "llegó", "arepa", "chócolo", "tuya", "antes")
    assert active.avoid_lexicon == kit.banned_words
    assert len(active.sources) == 1
    assert active.sources[0].kind is VoiceSourceKind.MANUAL_KIT
    assert active.sources[0].ref == "brand_kit"
    assert active.sources[0].excerpt == kit.positioning
    assert active.distilled_by_model == ""  # S1 is manual: no model ran

    # With a full kit and an approved voice, the §6.1 gate opens end-to-end.
    verdict = readiness(tenant_id=tenant_a, brand_id=brand_a)
    assert verdict.can_generate is True
    assert verdict.kit_completeness == 1.0


def test_second_approve_supersedes_first(seeded: tuple[UUID, UUID, UUID, UUID, UUID]) -> None:
    tenant_a, brand_a, user_a, _, _ = seeded
    BrandKitService().upsert_kit(
        tenant_id=tenant_a, brand_id=brand_a, kit=_rich_kit(brand_a), user_id=user_a
    )
    voice = VoiceProfileService()

    v1 = voice.propose_from_kit(tenant_id=tenant_a, brand_id=brand_a, user_id=user_a)
    voice.approve(tenant_id=tenant_a, brand_id=brand_a, version=v1, user_id=user_a)
    v2 = voice.propose_from_kit(tenant_id=tenant_a, brand_id=brand_a, user_id=user_a)
    assert v2 == v1 + 1
    voice.approve(tenant_id=tenant_a, brand_id=brand_a, version=v2, user_id=user_a)

    active = voice.active_profile(tenant_id=tenant_a, brand_id=brand_a)
    assert active is not None
    assert active.version == v2

    with tenant_session(tenant_a) as session:
        active_count = session.scalar(
            select(func.count())
            .select_from(VoiceProfileRow)
            .where(
                VoiceProfileRow.brand_id == brand_a,
                VoiceProfileRow.status == VoiceProfileStatus.ACTIVE.value,
            )
        )
        assert active_count == 1  # the invariant, measured in the database itself
        v1_row = session.scalar(
            select(VoiceProfileRow).where(
                VoiceProfileRow.brand_id == brand_a, VoiceProfileRow.version == v1
            )
        )
        assert v1_row is not None
        assert v1_row.status == VoiceProfileStatus.SUPERSEDED.value
        assert v1_row.approved_by == user_a  # supersession does not erase who approved it


def test_voice_typed_exceptions(seeded: tuple[UUID, UUID, UUID, UUID, UUID]) -> None:
    tenant_a, brand_a, user_a, tenant_b, brand_b = seeded
    voice = VoiceProfileService()

    # Tenant B's brand never gets a kit in this module.
    with pytest.raises(UnknownBrandKit):
        voice.propose_from_kit(tenant_id=tenant_b, brand_id=brand_b, user_id=user_a)

    with pytest.raises(UnknownVersion):
        voice.approve(tenant_id=tenant_a, brand_id=brand_a, version=10**6, user_id=user_a)

    BrandKitService().upsert_kit(
        tenant_id=tenant_a, brand_id=brand_a, kit=_rich_kit(brand_a), user_id=user_a
    )
    version = voice.propose_from_kit(tenant_id=tenant_a, brand_id=brand_a, user_id=user_a)
    voice.approve(tenant_id=tenant_a, brand_id=brand_a, version=version, user_id=user_a)
    with pytest.raises(NotProposed):  # already ACTIVE — approving again rewrites history
        voice.approve(tenant_id=tenant_a, brand_id=brand_a, version=version, user_id=user_a)


# -- saving the kit adopts the voice (§ 2026-09-30: no approval step) --------------------


def _fresh_brand(tenant_id: UUID) -> UUID:
    """A brand of its own per test: the voice tests count versions and ACTIVE rows, so
    they must not see what other tests (or earlier runs) left on the shared brand."""
    with admin_session() as session:
        brand = Brand(tenant_id=tenant_id, name=f"voice-adopt-{uuid4()}")
        session.add(brand)
        session.flush()
        return brand.id


def _statuses(tenant_id: UUID, brand_id: UUID) -> dict[int, str]:
    with tenant_session(tenant_id) as session:
        rows = session.scalars(
            select(VoiceProfileRow).where(VoiceProfileRow.brand_id == brand_id)
        ).all()
        return {row.version: row.status for row in rows}


def test_adopting_the_kit_activates_the_voice_once_per_change(
    seeded: tuple[UUID, UUID, UUID, UUID, UUID],
) -> None:
    tenant_a, _, user_a, _, _ = seeded
    brand = _fresh_brand(tenant_a)
    kits = BrandKitService()
    voice = VoiceProfileService()
    kit = _rich_kit(brand)
    kits.upsert_kit(tenant_id=tenant_a, brand_id=brand, kit=kit, user_id=user_a)

    v1 = voice.adopt_from_kit(tenant_id=tenant_a, brand_id=brand, user_id=user_a)
    active = voice.active_profile(tenant_id=tenant_a, brand_id=brand)
    assert active is not None and active.version == v1 == 1
    assert active.tone_axes == kit.tone_axes  # the voice follows the kit, no approval
    assert readiness(tenant_id=tenant_a, brand_id=brand).can_generate is True

    # the same kit again: nothing new is written
    assert voice.adopt_from_kit(tenant_id=tenant_a, brand_id=brand, user_id=user_a) == v1
    assert _statuses(tenant_a, brand) == {1: VoiceProfileStatus.ACTIVE.value}

    # a tone change: v2 goes ACTIVE, v1 is SUPERSEDED, the saver is the approver
    louder = kit.model_copy(
        update={"tone_axes": kit.tone_axes.model_copy(update={"sober_enthusiastic": 95})}
    )
    kits.upsert_kit(tenant_id=tenant_a, brand_id=brand, kit=louder, user_id=user_a)
    v2 = voice.adopt_from_kit(tenant_id=tenant_a, brand_id=brand, user_id=user_a)
    assert v2 == 2
    assert _statuses(tenant_a, brand) == {
        1: VoiceProfileStatus.SUPERSEDED.value,
        2: VoiceProfileStatus.ACTIVE.value,
    }
    active = voice.active_profile(tenant_id=tenant_a, brand_id=brand)
    assert active is not None and active.tone_axes.sober_enthusiastic == 95
    with tenant_session(tenant_a) as session:
        row = session.scalar(
            select(VoiceProfileRow).where(
                VoiceProfileRow.brand_id == brand, VoiceProfileRow.version == v2
            )
        )
        assert row is not None and row.approved_by == user_a and row.approved_at is not None


def test_adopting_never_replaces_a_voice_distilled_from_other_sources(
    seeded: tuple[UUID, UUID, UUID, UUID, UUID],
) -> None:
    tenant_a, _, user_a, _, _ = seeded
    brand = _fresh_brand(tenant_a)
    BrandKitService().upsert_kit(
        tenant_id=tenant_a, brand_id=brand, kit=_rich_kit(brand), user_id=user_a
    )
    with tenant_session(tenant_a) as session:
        session.add(
            VoiceProfileRow(
                tenant_id=tenant_a,
                brand_id=brand,
                version=1,
                status=VoiceProfileStatus.ACTIVE.value,
                profile={"tone_axes": _rich_kit(brand).tone_axes.model_dump()},
                sources=[
                    {"kind": VoiceSourceKind.OWNED_MEDIA.value, "ref": "ig:1", "excerpt": "x"}
                ],
                distilled_by_model="some-model",
                approved_by=user_a,
            )
        )
    assert (
        VoiceProfileService().adopt_from_kit(tenant_id=tenant_a, brand_id=brand, user_id=user_a)
        == 1
    )
    assert _statuses(tenant_a, brand) == {1: VoiceProfileStatus.ACTIVE.value}


def test_the_database_refuses_a_second_active_voice(
    seeded: tuple[UUID, UUID, UUID, UUID, UUID],
) -> None:
    from sqlalchemy.exc import IntegrityError

    tenant_a, _, user_a, _, _ = seeded
    brand = _fresh_brand(tenant_a)
    BrandKitService().upsert_kit(
        tenant_id=tenant_a, brand_id=brand, kit=_rich_kit(brand), user_id=user_a
    )
    VoiceProfileService().adopt_from_kit(tenant_id=tenant_a, brand_id=brand, user_id=user_a)
    with pytest.raises(IntegrityError):
        with tenant_session(tenant_a) as session:
            session.add(
                VoiceProfileRow(
                    tenant_id=tenant_a,
                    brand_id=brand,
                    version=99,
                    status=VoiceProfileStatus.ACTIVE.value,
                    profile={},
                    sources=[],
                )
            )
            session.flush()


# -- the brand's HeyGen voice clone (0032) ------------------------------------------------


def test_the_voice_clone_is_one_per_brand_and_tenant_isolated(
    seeded: tuple[UUID, UUID, UUID, UUID, UUID],
) -> None:
    from qualify_api.creative.voice_clone import COMPLETE, PROCESSING, VoiceCloneService

    tenant_a, _, user_a, tenant_b, _ = seeded
    brand = _fresh_brand(tenant_a)
    clones = VoiceCloneService()
    assert clones.current(tenant_id=tenant_a, brand_id=brand) is None

    assert (
        clones.record(
            tenant_id=tenant_a,
            brand_id=brand,
            heygen_voice_id="vc_1",
            name="Voz",
            consent_by=user_a,
        )
        is None
    )
    clone = clones.current(tenant_id=tenant_a, brand_id=brand)
    assert clone is not None and clone.status == PROCESSING and not clone.is_ready

    done = clones.update_status(
        tenant_id=tenant_a,
        brand_id=brand,
        heygen_voice_id="vc_1",
        status=COMPLETE,
        gender="female",
        preview_audio_url="https://files.heygen.ai/p.mp3",
    )
    assert done is not None and done.is_ready and done.gender == "female"

    # a new clone replaces it and hands back the old HeyGen id to delete there
    assert (
        clones.record(
            tenant_id=tenant_a,
            brand_id=brand,
            heygen_voice_id="vc_2",
            name="Voz",
            consent_by=user_a,
        )
        == "vc_1"
    )
    # a late poll of the old clone changes nothing
    assert (
        clones.update_status(
            tenant_id=tenant_a, brand_id=brand, heygen_voice_id="vc_1", status=COMPLETE
        )
        is None
    )
    current = clones.current(tenant_id=tenant_a, brand_id=brand)
    assert current is not None and current.heygen_voice_id == "vc_2"
    assert current.status == PROCESSING and current.gender == ""
    # another tenant sees nothing
    assert clones.current(tenant_id=tenant_b, brand_id=brand) is None
