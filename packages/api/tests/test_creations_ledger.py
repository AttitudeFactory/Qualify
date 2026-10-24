"""«Creaciones del mes» (CREAR-5, m-24848531): the ledger and how the content service
charges, refuses and refunds — offline, over the in-memory fakes of
`test_content_service`."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from qualify_creative.creations import CreationPrice
from qualify_creative.enums import AvatarSource, ContentFormat, ContentKind, VideoEngine
from qualify_creative.schemas import MediaInputs

from qualify_api.creative.creations import (
    CHARGED,
    REFUNDED,
    InMemoryCreationsLedger,
    NotEnoughCreations,
    month_start,
    next_month_start,
    not_enough_text,
)
from qualify_api.creative.creations_report import ChargeRow, build_report, render
from qualify_api.creative.fsm import DRAFTING, FAILED, GENERATED
from qualify_api.creative.media import MediaOutcome
from qualify_api.creative.service import ContentService

from .test_content_service import (
    BRAND_ID,
    FLYER_MEDIA,
    TENANT_ID,
    USER_ID,
    FakeBrand,
    FakeMedia,
    FakePricing,
    FakeRouter,
    FakeVoice,
    InMemoryRepository,
    KeyedRepository,
    RecordingDispatcher,
    StaticKeyResolver,
    copy_dict,
    make_brief,
    make_kit,
    make_voice,
    ok_outcome,
)

IMAGE = CreationPrice("image", 1)


def _service(
    ledger: InMemoryCreationsLedger,
    *,
    router: FakeRouter | None = None,
    repo: InMemoryRepository | None = None,
    media: object | None = None,
) -> tuple[ContentService, InMemoryRepository, RecordingDispatcher]:
    repo = repo or InMemoryRepository()
    dispatcher = RecordingDispatcher()
    service = ContentService(
        router=router or FakeRouter(),  # type: ignore[arg-type]
        pricing=FakePricing(),
        credentials=StaticKeyResolver(),
        voice_service=FakeVoice(make_voice()),
        brand_service=FakeBrand(make_kit()),
        repository=repo,
        dispatcher=dispatcher,
        media=media,  # type: ignore[arg-type]
        creations=ledger,
    )
    return service, repo, dispatcher


def _presenter(seconds: int):  # noqa: ANN202
    return make_brief(
        variants=1,
        kind=ContentKind.AVATAR_VIDEO,
        format=ContentFormat.REELS_9_16,
        media=MediaInputs(
            video_engine=VideoEngine.OMNIHUMAN,
            avatar_source=AvatarSource.AI,
            avatar_prompt="Una mujer joven, sonriente",
            duration_seconds=seconds,
        ),
    )


# -- the ledger --------------------------------------------------------------------------


def test_the_balance_is_the_quota_minus_what_is_still_charged() -> None:
    ledger = InMemoryCreationsLedger()
    draft = uuid4()
    assert ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).left == 30
    assert ledger.charge(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, draft_id=draft, revision=1, price=IMAGE
    )
    # the same generation is never charged twice
    assert not ledger.charge(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, draft_id=draft, revision=1, price=IMAGE
    )
    assert ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).left == 29
    assert ledger.refund(tenant_id=TENANT_ID, draft_id=draft, revision=1, reason="timeout")
    assert not ledger.refund(tenant_id=TENANT_ID, draft_id=draft, revision=1, reason="timeout")
    assert ledger.rows[(draft, 1)].status == REFUNDED
    assert ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).left == 30


def test_a_charge_the_month_cannot_pay_is_refused_whole() -> None:
    ledger = InMemoryCreationsLedger(used=28)
    with pytest.raises(NotEnoughCreations) as refused:
        ledger.charge(
            tenant_id=TENANT_ID,
            brand_id=BRAND_ID,
            draft_id=uuid4(),
            revision=1,
            price=CreationPrice("generated_video", 3),
        )
    assert refused.value.missing == 1
    assert ledger.rows == {}


def test_the_month_is_the_tenants_month() -> None:
    # 1 Nov 03:00 UTC is still 31 Oct in Bogotá
    now = datetime(2026, 11, 1, 3, 0, tzinfo=UTC)
    assert month_start(now, "America/Bogota") == date(2026, 10, 1)
    assert month_start(now, "UTC") == date(2026, 11, 1)
    assert month_start(now, "Not/AZone") == date(2026, 11, 1)


def test_the_quota_renews_on_the_next_months_first_day() -> None:
    assert next_month_start(date(2026, 10, 1)) == date(2026, 11, 1)
    assert next_month_start(date(2026, 12, 1)) == date(2027, 1, 1)


def test_what_the_owner_reads_when_the_month_cannot_pay() -> None:
    assert not_enough_text(1) == "Te falta 1 creación este mes."
    assert not_enough_text(2) == "Te faltan 2 creaciones este mes."


# -- the content service -------------------------------------------------------------------


def test_creating_charges_its_weight_once_and_dispatches() -> None:
    ledger = InMemoryCreationsLedger()
    service, _, dispatcher = _service(ledger)
    draft_id = service.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=make_brief(), user_id=USER_ID
    )
    row = ledger.rows[(draft_id, 1)]
    assert (row.price.request_kind, row.price.weight, row.status) == ("image", 1, CHARGED)
    assert dispatcher.calls == [(TENANT_ID, draft_id)]
    balance = service.creations_balance(tenant_id=TENANT_ID, brand_id=BRAND_ID)
    assert balance is not None and (balance.left, balance.quota) == (29, 30)


def test_without_enough_creations_nothing_is_created() -> None:
    ledger = InMemoryCreationsLedger(used=30)
    service, repo, dispatcher = _service(ledger)
    with pytest.raises(NotEnoughCreations):
        service.create_draft(
            tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=make_brief(), user_id=USER_ID
        )
    assert repo.drafts == {} and dispatcher.calls == []


def test_the_30_second_presenter_uses_25_and_the_15_second_one_13() -> None:
    ledger = InMemoryCreationsLedger(used=10)  # 20 left
    service, repo, _ = _service(ledger)
    with pytest.raises(NotEnoughCreations) as refused:
        service.create_draft(
            tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=_presenter(30), user_id=USER_ID
        )
    assert (refused.value.weight, refused.value.left) == (25, 20)
    assert repo.drafts == {}
    draft_id = service.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=_presenter(15), user_id=USER_ID
    )
    assert ledger.rows[(draft_id, 1)].price.weight == 13
    assert ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).left == 7


def test_a_request_key_retried_is_charged_once() -> None:
    ledger = InMemoryCreationsLedger()
    service, _, _ = _service(ledger, repo=KeyedRepository())
    key = uuid4()
    for _ in range(2):
        service.create_draft(
            tenant_id=TENANT_ID,
            brand_id=BRAND_ID,
            brief=make_brief(),
            user_id=USER_ID,
            request_key=key,
        )
    assert ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).used == 1


def test_a_failed_generation_gives_its_creations_back() -> None:
    ledger = InMemoryCreationsLedger()
    service, repo, _ = _service(ledger, router=FakeRouter([RuntimeError("boom")]))
    draft_id = service.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=make_brief(variants=1), user_id=USER_ID
    )
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)
    assert repo.drafts[draft_id].status == FAILED
    assert ledger.rows[(draft_id, 1)].status == REFUNDED
    assert ledger.rows[(draft_id, 1)].reason == "provider_error"
    assert ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).left == 30


def test_a_generation_that_came_out_keeps_its_charge() -> None:
    ledger = InMemoryCreationsLedger()
    service, repo, _ = _service(ledger, router=FakeRouter([ok_outcome(copy_dict())]))
    draft_id = service.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=make_brief(variants=1), user_id=USER_ID
    )
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)
    assert repo.drafts[draft_id].status == GENERATED
    assert ledger.rows[(draft_id, 1)].status == CHARGED


def _flyer():  # noqa: ANN202
    return make_brief(
        variants=1,
        kind=ContentKind.STATIC_FLYER,
        media=MediaInputs(product_keys=(f"uploads/{TENANT_ID}/p1.jpg",)),
    )


def test_another_version_is_charged_and_refunded_alone_when_it_does_not_come_out() -> None:
    ledger = InMemoryCreationsLedger()
    router = FakeRouter([ok_outcome(copy_dict()), ok_outcome(copy_dict("Otro hook"))])
    media = FakeMedia(MediaOutcome(media=(FLYER_MEDIA,)))
    service, repo, dispatcher = _service(ledger, router=router, media=media)
    draft_id = service.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=_flyer(), user_id=USER_ID
    )
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)
    service.reject(
        tenant_id=TENANT_ID, draft_id=draft_id, reason="otra", user_id=USER_ID, regenerate=True
    )
    assert ledger.rows[(draft_id, 2)].price.request_kind == "image_redo"
    assert ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).used == 2
    media.outcome = MediaOutcome(failure="provider_error", detail="No pudimos guardar la pieza.")
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)
    assert repo.drafts[draft_id].status == GENERATED  # the previous version stays
    assert ledger.rows[(draft_id, 1)].status == CHARGED
    assert ledger.rows[(draft_id, 2)].status == REFUNDED
    assert dispatcher.calls[-1] == (TENANT_ID, draft_id)


def test_another_version_without_creations_leaves_the_piece_as_it_was() -> None:
    ledger = InMemoryCreationsLedger(used=29)
    service, repo, dispatcher = _service(ledger, router=FakeRouter([ok_outcome(copy_dict())]))
    draft_id = service.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=make_brief(variants=1), user_id=USER_ID
    )
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)
    calls = list(dispatcher.calls)
    with pytest.raises(NotEnoughCreations):
        service.reject(
            tenant_id=TENANT_ID, draft_id=draft_id, reason="otra", user_id=USER_ID, regenerate=True
        )
    assert repo.drafts[draft_id].status == GENERATED and repo.drafts[draft_id].revision == 1
    assert dispatcher.calls == calls


def test_no_ledger_means_no_quota() -> None:
    """Scripts and tests build the service without one: nothing is charged or refused."""
    repo = InMemoryRepository()
    service = ContentService(
        router=FakeRouter(),  # type: ignore[arg-type]
        pricing=FakePricing(),
        credentials=StaticKeyResolver(),
        voice_service=FakeVoice(make_voice()),
        brand_service=FakeBrand(make_kit()),
        repository=repo,
    )
    draft_id = service.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=_presenter(30), user_id=USER_ID
    )
    assert repo.drafts[draft_id].status == DRAFTING
    assert service.creations_balance(tenant_id=TENANT_ID, brand_id=BRAND_ID) is None


# -- the team's report ------------------------------------------------------------------


def test_the_team_sees_the_real_dollars_next_to_the_creations() -> None:
    first, second = uuid4(), uuid4()
    at = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)

    def row(draft, revision, weight, status, kind="image"):  # noqa: ANN001, ANN202
        return ChargeRow(
            brand_id=BRAND_ID,
            draft_id=draft,
            revision=revision,
            request_kind=kind,
            weight=weight,
            status=status,
            weights_version="pesos-creaciones-v1",
            pricing_table_version="v5",
            period_month=date(2026, 10, 1),
            charged_at=at,
        )

    charges = [
        row(first, 1, 1, CHARGED),
        row(first, 2, 1, REFUNDED, "image_redo"),
        row(second, 1, 25, CHARGED, "presenter"),
    ]
    usd = {first: Decimal("0.068"), second: Decimal("3.65")}
    pieces, months = build_report(charges, usd, quota=30)
    by_draft = {p.draft_id: p for p in pieces}
    assert (by_draft[first].creations_charged, by_draft[first].creations_refunded) == (1, 1)
    assert by_draft[second].usd_real == Decimal("3.65")
    (month,) = months
    assert (month.creations_used, month.quota) == (26, 30)
    assert month.usd_real == Decimal("3.718")
    assert month.usd_per_creation == Decimal("0.143")
    text = render(pieces, months)
    assert "26 de 30 creaciones" in text and "USD 3.7180" in text
    assert "pesos-creaciones-v1/v5" in text


# -- v2 (m-24851828): preview + final charged at creation, the final's part refunded ---


def _clip(seconds: int = 5):  # noqa: ANN202
    return make_brief(
        variants=1,
        kind=ContentKind.CLIP,
        format=ContentFormat.REELS_9_16,
        media=MediaInputs(duration_seconds=seconds),
    )


def test_a_clip_is_charged_whole_at_creation_with_its_final_part_recorded() -> None:
    ledger = InMemoryCreationsLedger()
    service, _, _ = _service(ledger)
    draft_id = service.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=_clip(5), user_id=USER_ID
    )
    price = ledger.rows[(draft_id, 1)].price
    # a 5 s clip at its own length: 4 for the 480p preview + 19 for the 1080p final
    assert (price.request_kind, price.weight, price.final_weight) == ("generated_video", 23, 19)
    assert ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).left == 7


def test_a_10_second_clip_does_not_fit_a_whole_month() -> None:
    ledger = InMemoryCreationsLedger()
    service, repo, _ = _service(ledger)
    with pytest.raises(NotEnoughCreations) as refused:
        service.create_draft(
            tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=_clip(10), user_id=USER_ID
        )
    assert (refused.value.weight, refused.value.left) == (46, 30)
    assert repo.drafts == {}


def test_refund_final_gives_back_only_the_final_part_once() -> None:
    ledger = InMemoryCreationsLedger()
    draft = uuid4()
    clip = CreationPrice("generated_video", 23, final_weight=19)
    ledger.charge(tenant_id=TENANT_ID, brand_id=BRAND_ID, draft_id=draft, revision=1, price=clip)
    assert ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).left == 7
    assert ledger.refund_final(
        tenant_id=TENANT_ID, draft_id=draft, revision=1, reason="provider_error"
    )
    # the preview's 4 stay charged; the row stays `charged` with the refund recorded
    assert ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).left == 26
    row = ledger.rows[(draft, 1)]
    assert (row.status, row.final_refunded, row.final_reason) == (
        CHARGED,
        True,
        "provider_error",
    )
    assert not ledger.refund_final(
        tenant_id=TENANT_ID, draft_id=draft, revision=1, reason="provider_error"
    )
    assert ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).left == 26
    # a charge with no final has nothing of the kind to give
    image = uuid4()
    ledger.charge(tenant_id=TENANT_ID, brand_id=BRAND_ID, draft_id=image, revision=1, price=IMAGE)
    assert not ledger.refund_final(tenant_id=TENANT_ID, draft_id=image, revision=1, reason="x")


def _final_setup(fail: bool):  # noqa: ANN202
    from . import test_content_service_final as tf

    ledger = InMemoryCreationsLedger()
    service, repo, dispatcher, draft_id, variant_id, finals = tf._setup(
        finals=tf.FakeFinals(fail=fail)
    )
    service._creations = ledger  # type: ignore[assignment]
    ledger.charge(
        tenant_id=TENANT_ID,
        brand_id=repo.drafts[draft_id].brand_id,
        draft_id=draft_id,
        revision=repo.drafts[draft_id].revision,
        price=CreationPrice("generated_video", 23, final_weight=19),
    )
    return ledger, service, repo, draft_id, variant_id, finals


def _left(ledger: InMemoryCreationsLedger, repo, draft_id) -> int:  # noqa: ANN001
    brand = repo.drafts[draft_id].brand_id
    return ledger.balance(tenant_id=TENANT_ID, brand_id=brand).left


def test_approving_charges_nothing_more_and_a_final_that_comes_out_keeps_it_all() -> None:
    ledger, service, repo, draft_id, variant_id, _ = _final_setup(fail=False)
    assert _left(ledger, repo, draft_id) == 7
    service.approve(tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID)
    assert _left(ledger, repo, draft_id) == 7  # nothing is charged at approval
    service.run_finalize(tenant_id=TENANT_ID, draft_id=draft_id)
    assert _left(ledger, repo, draft_id) == 7


def test_a_failed_final_gives_back_its_part_and_its_retry_is_not_charged_again() -> None:
    ledger, service, repo, draft_id, variant_id, finals = _final_setup(fail=True)
    service.approve(tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID)
    service.run_finalize(tenant_id=TENANT_ID, draft_id=draft_id)
    # the vendor failed the 1080p final: its 19 come back, the preview's 4 stay
    assert _left(ledger, repo, draft_id) == 26
    (row,) = ledger.rows.values()
    assert row.status == CHARGED and row.final_refunded
    assert row.final_reason == "ModelArk falló."
    # failing again gives nothing more; the retry that comes out is not charged again
    service.retry_final(tenant_id=TENANT_ID, draft_id=draft_id)
    service.run_finalize(tenant_id=TENANT_ID, draft_id=draft_id)
    assert _left(ledger, repo, draft_id) == 26
    finals.fail = False
    service.retry_final(tenant_id=TENANT_ID, draft_id=draft_id)
    service.run_finalize(tenant_id=TENANT_ID, draft_id=draft_id)
    assert _left(ledger, repo, draft_id) == 26


def test_a_final_that_breaks_in_our_code_gives_back_its_part_too() -> None:
    from . import test_content_service_final as tf

    class Exploding(tf.FakeFinals):
        def finalize(self, **_: object):  # noqa: ANN202
            raise RuntimeError("boom")

    ledger, service, repo, draft_id, variant_id, _ = _final_setup(fail=False)
    service._media = Exploding()  # type: ignore[assignment]
    service.approve(tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID)
    service.run_finalize(tenant_id=TENANT_ID, draft_id=draft_id)
    assert _left(ledger, repo, draft_id) == 26
    (row,) = ledger.rows.values()
    assert row.final_reason == "final_failed"


def test_the_report_counts_a_refunded_final_as_given_back() -> None:
    draft = uuid4()
    at = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    charge = ChargeRow(
        brand_id=BRAND_ID,
        draft_id=draft,
        revision=1,
        request_kind="generated_video",
        weight=23,
        status=CHARGED,
        weights_version="pesos-creaciones-v2",
        pricing_table_version="v7",
        period_month=date(2026, 10, 1),
        charged_at=at,
        final_weight=19,
        final_refunded=True,
    )
    pieces, months = build_report([charge], {draft: Decimal("0.60")}, quota=30)
    (piece,) = pieces
    assert (piece.creations_charged, piece.creations_refunded) == (4, 19)
    assert months[0].creations_used == 4
    assert "pesos-creaciones-v2/v7" in render(pieces, months)


# -- «Variaciones»: the batch is all or nothing --------------------------------------------


def _angle_service(ledger: InMemoryCreationsLedger):  # noqa: ANN202
    from qualify_api.creative.angle_sets import AngleSetService

    from . import test_angle_sets as ta

    repo = ta.MemoryRepo()
    drafts = ta.FakeDrafts()
    service = AngleSetService(
        repository=repo,
        catalog=ta.FakeCatalog(ta._product()),
        brand_facts=lambda *, tenant_id, brand_id: ta.AngleBrand(name="Bianki"),
        kit_reader=ta.FakeKits(),
        generator=ta.FakeGenerator(ta._angles(10)),
        drafts=drafts,
        campaigns=ta.FakeCampaigns(),
        pricing=ta.FakePricing(),
        image_model_id="seedream-5-0-lite-260128",
        creations=ledger,
    )
    return service, repo, drafts, ta


def test_a_batch_the_month_cannot_pay_creates_no_piece() -> None:
    from qualify_api.creative.angle_sets import AngleNotActionable

    ledger = InMemoryCreationsLedger(used=22)  # 8 left, 10 ideas
    service, repo, drafts, ta = _angle_service(ledger)
    set_id = ta._create(service)
    with pytest.raises(AngleNotActionable, match="Te faltan 2 creaciones este mes."):
        service.generate_pieces(tenant_id=ta.TENANT, set_id=set_id, user_id=ta.USER)
    assert drafts.briefs == []
    assert all(a.status == "proposed" for a in repo.list_angles(tenant_id=ta.TENANT, set_id=set_id))


def test_another_take_without_creations_keeps_the_piece() -> None:
    from qualify_api.creative.angle_sets import AngleNotActionable

    ledger = InMemoryCreationsLedger(used=20)
    service, repo, drafts, ta = _angle_service(ledger)
    set_id = ta._create(service)
    service.generate_pieces(tenant_id=ta.TENANT, set_id=set_id, user_id=ta.USER)
    angle = repo.list_angles(tenant_id=ta.TENANT, set_id=set_id)[0]
    ta._land(drafts, angle)
    ledger._opening = 30  # the month ran out meanwhile
    with pytest.raises(AngleNotActionable, match="Te falta"):
        service.regenerate_angle(tenant_id=ta.TENANT, angle_id=angle.id, user_id=ta.USER)
    assert drafts.rejected == []
