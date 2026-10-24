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


# -- videos at approval, vistas previas at creation (founder, 2026-10-24) -----------------


def _clip(seconds: int = 5):  # noqa: ANN202
    return make_brief(
        variants=1,
        kind=ContentKind.CLIP,
        format=ContentFormat.REELS_9_16,
        media=MediaInputs(duration_seconds=seconds),
    )


def _balance(ledger: InMemoryCreationsLedger):  # noqa: ANN202
    return ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID)


def test_creating_a_clip_uses_one_vista_previa_and_no_video_yet() -> None:
    ledger = InMemoryCreationsLedger()
    service, _, _ = _service(ledger)
    draft_id = service.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=_clip(10), user_id=USER_ID
    )
    price = ledger.rows[(draft_id, 1)].price
    assert (price.request_kind, price.weight, price.videos) == ("generated_video", 0, 1)
    balance = _balance(ledger)
    assert (balance.left, balance.quota) == (30, 30)
    assert (balance.previews_left, balance.preview_quota) == (19, 20)
    # the video is counted when the owner approves, not now
    assert (balance.videos_left, balance.video_quota) == (4, 4)


def test_the_preview_cap_is_20_then_videos_are_refused_and_images_still_work() -> None:
    ledger = InMemoryCreationsLedger(previews_used=19)
    service, repo, dispatcher = _service(ledger)
    service.create_draft(tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=_clip(5), user_id=USER_ID)
    assert _balance(ledger).previews_left == 0
    with pytest.raises(NotEnoughCreations) as refused:
        service.create_draft(
            tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=_clip(5), user_id=USER_ID
        )
    assert (refused.value.missing, refused.value.missing_previews) == (0, 1)
    assert len(repo.drafts) == 1 and len(dispatcher.calls) == 1
    service.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=make_brief(), user_id=USER_ID
    )
    assert _balance(ledger).left == 29


def test_a_vista_previa_comes_back_only_when_the_generation_fails() -> None:
    ledger = InMemoryCreationsLedger()
    service, repo, _ = _service(ledger, router=FakeRouter([RuntimeError("boom")]))
    draft_id = service.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=_clip(5), user_id=USER_ID
    )
    assert _balance(ledger).previews_left == 19
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft_id)
    assert repo.drafts[draft_id].status == FAILED
    assert _balance(ledger).previews_left == 20


def test_a_carousel_uses_one_vista_previa_per_animated_slide_all_or_nothing() -> None:
    ledger = InMemoryCreationsLedger(previews_used=18)
    three = CreationPrice("carousel", 1, videos=3)
    with pytest.raises(NotEnoughCreations) as refused:
        ledger.charge(
            tenant_id=TENANT_ID, brand_id=BRAND_ID, draft_id=uuid4(), revision=1, price=three
        )
    assert (refused.value.previews, refused.value.previews_left) == (3, 2)
    assert ledger.rows == {}
    two = CreationPrice("carousel", 1, videos=2)
    assert ledger.charge(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, draft_id=uuid4(), revision=1, price=two
    )
    balance = _balance(ledger)
    assert (balance.left, balance.previews_left, balance.videos_left) == (29, 0, 4)


def test_approving_a_carousel_charges_n_videos_all_or_nothing() -> None:
    ledger = InMemoryCreationsLedger(videos_used=2)
    draft = uuid4()
    ledger.charge(
        tenant_id=TENANT_ID,
        brand_id=BRAND_ID,
        draft_id=draft,
        revision=1,
        price=CreationPrice("carousel", 1, videos=3),
    )
    with pytest.raises(NotEnoughCreations) as refused:
        ledger.charge_videos(
            tenant_id=TENANT_ID, brand_id=BRAND_ID, draft_id=draft, revision=1, videos=3
        )
    assert (refused.value.videos, refused.value.videos_left, refused.value.missing) == (3, 2, 0)
    assert ledger.rows[(draft, 1)].videos == 0  # nothing charged
    other = uuid4()
    assert ledger.charge_videos(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, draft_id=other, revision=1, videos=2
    )
    # charged once: approving twice never counts twice
    assert not ledger.charge_videos(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, draft_id=other, revision=1, videos=2
    )
    assert _balance(ledger).videos_left == 0


def test_the_presenter_stays_in_creations() -> None:
    ledger = InMemoryCreationsLedger(videos_used=4, previews_used=20)  # nothing video left
    service, _, _ = _service(ledger)
    draft_id = service.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=_presenter(15), user_id=USER_ID
    )
    price = ledger.rows[(draft_id, 1)].price
    assert (price.request_kind, price.weight, price.videos) == ("presenter", 13, 0)
    assert _balance(ledger).left == 17


def test_refund_final_gives_back_one_video_per_failed_final_once() -> None:
    ledger = InMemoryCreationsLedger()
    draft = uuid4()
    slides = CreationPrice("carousel", 1, videos=2)
    ledger.charge(tenant_id=TENANT_ID, brand_id=BRAND_ID, draft_id=draft, revision=1, price=slides)
    first, second = uuid4(), uuid4()
    # nothing to give before approval: no video was charged yet
    assert not ledger.refund_final(
        tenant_id=TENANT_ID, draft_id=draft, revision=1, reason="x", asset_ids=(first,)
    )
    ledger.charge_videos(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, draft_id=draft, revision=1, videos=2
    )
    assert _balance(ledger).videos_left == 2
    assert ledger.refund_final(
        tenant_id=TENANT_ID, draft_id=draft, revision=1, reason="provider_error", asset_ids=(first,)
    )
    assert (_balance(ledger).left, _balance(ledger).videos_left) == (29, 3)
    row = ledger.rows[(draft, 1)]
    assert (row.status, row.videos_given_back, row.final_reason) == (CHARGED, 1, "provider_error")
    assert not ledger.refund_final(
        tenant_id=TENANT_ID, draft_id=draft, revision=1, reason="again", asset_ids=(first,)
    )
    assert ledger.refund_final(
        tenant_id=TENANT_ID, draft_id=draft, revision=1, reason="x", asset_ids=(second, uuid4())
    )
    assert _balance(ledger).videos_left == 4


def _final_setup(fail: bool, *, videos_used: int = 0):  # noqa: ANN202
    """A generated clip with a draft video waiting for approval (its vista previa is
    already charged, as `create_draft` would)."""
    from . import test_content_service_final as tf

    ledger = InMemoryCreationsLedger(videos_used=videos_used)
    service, repo, dispatcher, draft_id, variant_id, finals = tf._setup(
        finals=tf.FakeFinals(fail=fail)
    )
    service._creations = ledger  # type: ignore[assignment]
    draft = repo.drafts[draft_id]
    repo.briefs[draft.brief_id] = _clip(5)
    ledger.charge(
        tenant_id=TENANT_ID,
        brand_id=draft.brand_id,
        draft_id=draft_id,
        revision=draft.revision,
        price=CreationPrice("generated_video", 0, videos=1),
    )
    return ledger, service, repo, dispatcher, draft_id, variant_id, finals


def _videos_left(ledger: InMemoryCreationsLedger, repo, draft_id) -> int:  # noqa: ANN001
    brand = repo.drafts[draft_id].brand_id
    return ledger.balance(tenant_id=TENANT_ID, brand_id=brand).videos_left


def test_discarding_costs_no_video() -> None:
    ledger, service, repo, _, draft_id, _, _ = _final_setup(fail=False)
    service.reject(tenant_id=TENANT_ID, draft_id=draft_id, reason="no", user_id=USER_ID)
    assert _videos_left(ledger, repo, draft_id) == 4
    assert ledger.rows[(draft_id, 1)].videos == 0


def test_approving_charges_one_video_and_the_final_keeps_it() -> None:
    ledger, service, repo, _, draft_id, variant_id, _ = _final_setup(fail=False)
    assert _videos_left(ledger, repo, draft_id) == 4
    quote = service.approval_videos(tenant_id=TENANT_ID, draft_id=draft_id)
    assert quote is not None and quote[0] == 1 and quote[1].videos_left == 4
    service.approve(tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID)
    assert _videos_left(ledger, repo, draft_id) == 3
    service.run_finalize(tenant_id=TENANT_ID, draft_id=draft_id)
    assert _videos_left(ledger, repo, draft_id) == 3


def test_approval_is_refused_with_no_video_left_and_nothing_is_written() -> None:
    from qualify_api.creative.fsm import APPROVED

    ledger, service, repo, dispatcher, draft_id, variant_id, _ = _final_setup(
        fail=False, videos_used=4
    )
    with pytest.raises(NotEnoughCreations) as refused:
        service.approve(
            tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID
        )
    assert (refused.value.missing_videos, refused.value.videos_left) == (1, 0)
    assert repo.drafts[draft_id].status == GENERATED != APPROVED
    assert dispatcher.finals == []  # no final ordered


def test_a_failed_final_gives_its_video_back_and_its_retry_is_free() -> None:
    ledger, service, repo, _, draft_id, variant_id, finals = _final_setup(fail=True)
    service.approve(tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID)
    assert _videos_left(ledger, repo, draft_id) == 3
    service.run_finalize(tenant_id=TENANT_ID, draft_id=draft_id)
    assert _videos_left(ledger, repo, draft_id) == 4
    (row,) = ledger.rows.values()
    assert row.status == CHARGED and row.videos_given_back == 1
    assert row.final_reason == "ModelArk falló."
    service.retry_final(tenant_id=TENANT_ID, draft_id=draft_id)
    service.run_finalize(tenant_id=TENANT_ID, draft_id=draft_id)
    assert _videos_left(ledger, repo, draft_id) == 4
    finals.fail = False
    service.retry_final(tenant_id=TENANT_ID, draft_id=draft_id)
    service.run_finalize(tenant_id=TENANT_ID, draft_id=draft_id)
    assert _videos_left(ledger, repo, draft_id) == 4


def test_a_final_that_breaks_in_our_code_gives_its_video_back_too() -> None:
    from . import test_content_service_final as tf

    class Exploding(tf.FakeFinals):
        def finalize(self, **_: object):  # noqa: ANN202
            raise RuntimeError("boom")

    ledger, service, repo, _, draft_id, variant_id, _ = _final_setup(fail=False)
    service._media = Exploding()  # type: ignore[assignment]
    service.approve(tenant_id=TENANT_ID, draft_id=draft_id, variant_id=variant_id, user_id=USER_ID)
    service.run_finalize(tenant_id=TENANT_ID, draft_id=draft_id)
    assert _videos_left(ledger, repo, draft_id) == 4
    (row,) = ledger.rows.values()
    assert row.final_reason == "final_failed"


def test_crearla_otra_vez_makes_a_new_piece_from_the_same_request() -> None:
    ledger, service, repo, dispatcher, draft_id, _, _ = _final_setup(fail=False)
    before = _balance(ledger).previews_left
    new_id = service.recreate(tenant_id=TENANT_ID, draft_id=draft_id, user_id=USER_ID)
    assert new_id != draft_id
    assert repo.briefs[repo.drafts[new_id].brief_id].kind is ContentKind.CLIP
    assert ledger.rows[(new_id, 1)].price.videos == 1
    assert _balance(ledger).previews_left == before - 1  # one vista previa
    assert _videos_left(ledger, repo, draft_id) == 4  # no video for either yet


def test_the_quota_lives_in_one_function() -> None:
    from qualify_creative.creations import load_weights

    from qualify_api.creative.creations import MonthlyQuota, quota_for

    quota = quota_for(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, period=date(2026, 10, 1), weights=load_weights()
    )
    assert quota == MonthlyQuota(creations=30, videos=4, previews=20)


def test_the_report_counts_a_refunded_final_as_a_video_given_back() -> None:
    draft = uuid4()
    at = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    charge = ChargeRow(
        brand_id=BRAND_ID,
        draft_id=draft,
        revision=1,
        request_kind="carousel",
        weight=1,
        status=CHARGED,
        weights_version="pesos-creaciones-v2",
        pricing_table_version="v7",
        period_month=date(2026, 10, 1),
        charged_at=at,
        videos=3,
        videos_given_back=1,
        previews=3,
    )
    pieces, months = build_report([charge], {draft: Decimal("7.10")}, quota=30, video_quota=4)
    (piece,) = pieces
    assert (piece.creations_charged, piece.videos_charged, piece.videos_refunded) == (1, 2, 1)
    assert (months[0].creations_used, months[0].videos_used) == (1, 2)
    text = render(pieces, months)
    assert "pesos-creaciones-v2/v7" in text
    assert "videos 2, devueltos 1" in text and "2 de 4 videos" in text
    assert "vistas previas 3" in text


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
