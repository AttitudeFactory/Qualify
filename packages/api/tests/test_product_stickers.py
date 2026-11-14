"""Product «tierno» stickers (m-25017372), offline: the owner's service (creations, every
character kept, double approval), the creative-worker executor (price guard, never paid
twice, idempotent finish, failures give the creation back), the media-worker branch that
draws the stickers, and the library order (seasons first). Vendor, R2 and the render
service are fakes; no network, no database."""

from __future__ import annotations

import io
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import numpy as np
import pytest
from PIL import Image
from qualify_creative.seasonal.look import BrandLook
from qualify_creative.seasonal.recipes import RecipeOutput

from qualify_api.creative import product_stickers as ps
from qualify_api.creative.creations import InMemoryCreationsLedger
from qualify_api.creative.product_sticker_ai import (
    BUDGET_CAP,
    UNCERTAIN,
    VENDOR_FAILED,
    Budget,
    PriceGuardRefused,
    ProductCharacterExecutor,
    SubmissionAborted,
    task_id_of,
)
from qualify_api.creative.seasonal_job import (
    SeasonalJob,
    SeasonalMediaJobHandler,
)
from qualify_api.creative.worker.executor import SUCCEEDED, JobContext
from qualify_api.whatsapp.seasonal import (
    PRODUCT_SEASON_KEY,
    STATUS_APPROVED,
    STATUS_READY,
    MemorySeasonalRepository,
    MemorySourceReads,
    SeasonalMedia,
    SeasonalMediaService,
)

TENANT = UUID("00000000-0000-0000-0000-0000000000a1")
BRAND = UUID("00000000-0000-0000-0000-0000000000b1")
OTHER_BRAND = UUID("00000000-0000-0000-0000-0000000000b2")
PRODUCT = UUID("00000000-0000-0000-0000-0000000000c1")
MEDIA = UUID("00000000-0000-0000-0000-0000000000d1")
USER = UUID("00000000-0000-0000-0000-0000000000e1")
NOW = datetime(2026, 11, 12, 15, 0, tzinfo=UTC)


def _photo_jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (640, 480), (150, 100, 50)).save(buf, format="JPEG")
    return buf.getvalue()


def _character_jpeg(size: int = 200) -> bytes:
    yy, xx = np.mgrid[0:size, 0:size]
    image = np.zeros((size, size, 3), dtype=np.uint8)
    image[:] = (243, 37, 173)
    r = ((xx - size / 2) / (size * 0.3)) ** 2 + ((yy - size / 2) / (size * 0.35)) ** 2
    image[r <= 1] = (40, 30, 30)
    image[r <= 0.8] = (180, 120, 60)
    buf = io.BytesIO()
    Image.fromarray(image).save(buf, format="JPEG", quality=95)
    return buf.getvalue()


# --- the service ----------------------------------------------------------------------------


def _service(
    *, used: int = 0, ledger: InMemoryCreationsLedger | None = None
) -> tuple[ps.ProductStickerService, ps.MemoryCharacterRepository, InMemoryCreationsLedger, Any]:
    repo = ps.MemoryCharacterRepository()
    products = ps.MemoryProductReads()
    products.photos.append(
        ps.ProductPhoto(
            product_id=PRODUCT, name="Shawarma mixto", media_id=MEDIA, object_key="t/x.jpg"
        )
    )
    products.brand_of[PRODUCT] = BRAND
    products.without_photo = 2
    ledger = ledger or InMemoryCreationsLedger(used=used)
    library = SeasonalMediaService(MemorySeasonalRepository(), MemorySourceReads())
    clock = iter(NOW + timedelta(seconds=i) for i in range(1000))
    service = ps.ProductStickerService(
        repo=repo, products=products, ledger=ledger, library=library, clock=lambda: next(clock)
    )
    return service, repo, ledger, library


def test_step_one_lists_products_with_a_photo_and_counts_the_rest() -> None:
    service, *_ = _service()
    choices = service.products(TENANT, BRAND)
    assert [p.name for p in choices.products] == ["Shawarma mixto"]
    assert choices.without_photo == 2
    assert service.products(TENANT, OTHER_BRAND).products == ()


def test_the_cost_is_one_creation_from_the_weights_table_never_money() -> None:
    service, *_ = _service(used=7)
    quote = service.quote(TENANT, BRAND)
    assert quote.creations == ps.product_sticker_price().weight == 1
    assert quote.left == 23 and quote.can_pay and quote.message == ""
    assert not hasattr(quote, "usd")


def test_requesting_charges_one_creation_and_queues_one_job() -> None:
    service, repo, ledger, _ = _service()
    character = service.request_character(TENANT, BRAND, PRODUCT, USER, accepted_creations=1)
    assert character.status == ps.STATUS_PENDING
    assert character.product_name == "Shawarma mixto" and character.source_media_id == MEDIA
    assert character.prompt_version == "kawaii-v3" and character.pricing_table_version == "v9"
    assert character.quoted_usd == Decimal("0.045")
    assert character.creation_charge_id is not None
    assert repo.jobs == [character.id]
    assert ledger.balance(tenant_id=TENANT, brand_id=BRAND).used == 1


def test_pedir_otro_keeps_every_character_and_has_no_count_cap() -> None:
    service, repo, ledger, _ = _service()
    made = [
        service.request_character(TENANT, BRAND, PRODUCT, USER, accepted_creations=1)
        for _ in range(5)
    ]
    assert len({c.id for c in made}) == 5
    assert len(service.characters(TENANT, BRAND)) == 5
    assert ledger.balance(tenant_id=TENANT, brand_id=BRAND).used == 5


def test_the_month_is_the_only_limit() -> None:
    service, *_ = _service(used=30)
    assert not service.quote(TENANT, BRAND).can_pay
    assert service.quote(TENANT, BRAND).message.startswith("Te falta 1 creación este mes.")
    with pytest.raises(ps.NotEnoughCreationsLeft) as refused:
        service.request_character(TENANT, BRAND, PRODUCT, USER, accepted_creations=1)
    assert "Te falta 1 creación este mes." in refused.value.message


def test_a_changed_cost_or_a_product_without_photo_charges_nothing() -> None:
    service, repo, ledger, _ = _service()
    with pytest.raises(ps.CostChanged):
        service.request_character(TENANT, BRAND, PRODUCT, USER, accepted_creations=2)
    with pytest.raises(ps.NoProductPhoto) as refused:
        service.request_character(TENANT, BRAND, uuid4(), USER, accepted_creations=1)
    assert "Sube la foto en Galería" in refused.value.message
    assert ledger.balance(tenant_id=TENANT, brand_id=BRAND).used == 0
    assert repo.rows == {}


def test_a_failed_start_gives_the_creation_back() -> None:
    service, repo, ledger, _ = _service()

    def boom(_c: Any) -> Any:
        raise RuntimeError("db down")

    repo.insert_with_job = boom  # type: ignore[method-assign]
    with pytest.raises(ps.StartFailed) as refused:
        service.request_character(TENANT, BRAND, PRODUCT, USER, accepted_creations=1)
    assert "No se te cobró" in refused.value.message
    assert ledger.balance(tenant_id=TENANT, brand_id=BRAND).used == 0


def _ready(service: ps.ProductStickerService, repo: ps.MemoryCharacterRepository) -> Any:
    c = service.request_character(TENANT, BRAND, PRODUCT, USER, accepted_creations=1)
    key = f"seasonal/{TENANT}/{BRAND}/personajes/{c.id}-1.webp"
    return service.mark_character_ready(
        tenant_id=TENANT,
        brand_id=BRAND,
        character_id=c.id,
        object_key=key,
        raw_object_key=key.replace("-1.webp", "-2.webp"),
        width=300,
        height=320,
    )


def test_a_failure_gives_the_creation_back_once() -> None:
    service, repo, ledger, _ = _service()
    c = service.request_character(TENANT, BRAND, PRODUCT, USER, accepted_creations=1)
    failed = service.mark_character_failed(
        tenant_id=TENANT, brand_id=BRAND, character_id=c.id, reason="vendor_failed"
    )
    assert failed is not None and failed.status == ps.STATUS_FAILED
    assert failed.failure_text == "Este dibujo no salió y no se te cobró. Puedes pedir otro."
    assert ledger.balance(tenant_id=TENANT, brand_id=BRAND).used == 0
    again = service.mark_character_failed(
        tenant_id=TENANT, brand_id=BRAND, character_id=c.id, reason="vendor_failed"
    )
    assert again is None and ledger.balance(tenant_id=TENANT, brand_id=BRAND).used == 0


def test_stickers_need_a_picked_character_and_cost_nothing() -> None:
    service, repo, ledger, library = _service()
    ready = _ready(service, repo)
    with pytest.raises(ps.CharacterNotApproved):
        service.make_stickers(TENANT, BRAND, ready.id, ["Bienvenido"], USER)
    picked = service.approve_character(TENANT, BRAND, ready.id, USER)
    assert picked.status == ps.STATUS_APPROVED and picked.approved_at is not None
    rows = service.make_stickers(
        TENANT, BRAND, ready.id, ["Bienvenido", "  En   camino "], USER, animated=True, still=True
    )
    assert {(r.recipe, r.source_ref) for r in rows} == {
        (ps.RECIPE_ANIMATED, f"{ready.id}:Bienvenido"),
        (ps.RECIPE_STATIC, f"{ready.id}:Bienvenido"),
        (ps.RECIPE_ANIMATED, f"{ready.id}:En camino"),
        (ps.RECIPE_STATIC, f"{ready.id}:En camino"),
    }
    assert all(r.season_key == PRODUCT_SEASON_KEY and r.source_kind == "character" for r in rows)
    assert ledger.balance(tenant_id=TENANT, brand_id=BRAND).used == 1  # only the drawing
    again = service.make_stickers(TENANT, BRAND, ready.id, ["Bienvenido"], USER)
    assert [r.id for r in again] == [r.id for r in rows if r.recipe == ps.RECIPE_ANIMATED][:1]
    assert len(service.stickers(TENANT, BRAND)) == 4


@pytest.mark.parametrize(
    ("messages", "error"),
    [([], ps.NoMessages), (["   "], ps.MessageEmpty), (["x" * 26], ps.MessageTooLong)],
)
def test_messages_are_checked_in_the_owner_words(messages: list[str], error: type) -> None:
    service, repo, *_ = _service()
    ready = _ready(service, repo)
    service.approve_character(TENANT, BRAND, ready.id, USER)
    with pytest.raises(error) as refused:
        service.make_stickers(TENANT, BRAND, ready.id, messages, USER)
    assert refused.value.message


def test_another_brand_cannot_touch_a_character() -> None:
    service, repo, *_ = _service()
    ready = _ready(service, repo)
    with pytest.raises(ps.CharacterNotFound):
        service.approve_character(TENANT, OTHER_BRAND, ready.id, USER)


def test_discarding_hides_a_character_but_keeps_the_row() -> None:
    service, repo, *_ = _service()
    ready = _ready(service, repo)
    service.discard_character(TENANT, BRAND, ready.id, USER)
    assert service.characters(TENANT, BRAND) == []
    assert repo.rows[ready.id].status == ps.STATUS_DISCARDED


def test_restoring_brings_a_discarded_character_back_as_it_was() -> None:
    """m-25019604: «Deshacer» — the status comes back from the row itself (ready, approved
    or failed); idempotent; only this business; nothing is charged or refunded."""
    service, repo, ledger, _ = _service()
    ready = _ready(service, repo)
    service.discard_character(TENANT, BRAND, ready.id, USER)
    back = service.restore_character(TENANT, BRAND, ready.id, USER)
    assert back.status == ps.STATUS_READY
    assert [c.id for c in service.characters(TENANT, BRAND)] == [ready.id]
    assert service.restore_character(TENANT, BRAND, ready.id, USER).status == ps.STATUS_READY

    service.approve_character(TENANT, BRAND, ready.id, USER)
    service.discard_character(TENANT, BRAND, ready.id, USER)
    assert service.restore_character(TENANT, BRAND, ready.id, USER).status == ps.STATUS_APPROVED

    failed = service.request_character(TENANT, BRAND, PRODUCT, USER, accepted_creations=1)
    service.mark_character_failed(
        tenant_id=TENANT, brand_id=BRAND, character_id=failed.id, reason="vendor_failed"
    )
    before = repr(ledger.__dict__)
    service.discard_character(TENANT, BRAND, failed.id, USER)
    assert service.restore_character(TENANT, BRAND, failed.id, USER).status == ps.STATUS_FAILED
    assert repr(ledger.__dict__) == before  # no charge, no refund

    service.discard_character(TENANT, BRAND, ready.id, USER)
    with pytest.raises(ps.CharacterNotFound):
        service.restore_character(TENANT, OTHER_BRAND, ready.id, USER)
    assert repo.rows[ready.id].status == ps.STATUS_DISCARDED


# --- the executor -------------------------------------------------------------------------


class FakeObjects:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {"t/photo.jpg": _photo_jpeg()}
        self.fail_puts = 0

    def open_object(self, tenant_id: UUID, key: str) -> Any:
        if key not in self.files:
            from qualify_shared.objects.gate import ObjectNotFound

            raise ObjectNotFound(key)
        return io.BytesIO(self.files[key])

    def put_seasonal_media(
        self, tenant_id, brand_id, season_key, media_id, ext, fileobj, ct, attempt=1
    ):  # noqa: ANN001, ANN201, E501
        if self.fail_puts:
            self.fail_puts -= 1
            raise OSError("r2 hiccup")
        key = f"seasonal/{tenant_id}/{brand_id}/{season_key}/{media_id}-{attempt}.{ext}"
        self.files[key] = fileobj.read()
        return key


class FakeReads:
    def __init__(self, service: ps.ProductStickerService, budget: Budget | None) -> None:
        self.service = service
        self._budget = budget

    def character(self, tenant_id: UUID, character_id: UUID) -> Any:
        try:
            return self.service.character(tenant_id, BRAND, character_id)
        except ps.CharacterNotFound:
            return None

    def photo_key(self, tenant_id, brand_id, product_id, media_id):  # noqa: ANN001, ANN201
        return "t/photo.jpg" if media_id == MEDIA and brand_id == BRAND else None

    def budget(self, tenant_id: UUID, brand_id: UUID) -> Budget | None:
        return self._budget


class FakeLedger:
    def __init__(self) -> None:
        self.booked: dict[UUID, Decimal] = {}

    def record(self, *, character_id: UUID, cost_usd: Decimal, **_: Any) -> bool:
        if character_id in self.booked:
            return False
        self.booked[character_id] = cost_usd
        return True


class FakeSeedream:
    def __init__(self, *, error: Exception | None = None, images: int = 1) -> None:
        self.calls = 0
        self.requests: list[Any] = []
        self._error = error
        self._images = images

    def generate(self, request: Any, *, api_key: str) -> Any:
        self.calls += 1
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        return SimpleNamespace(
            payload={"images": [_character_jpeg()] * self._images},
            usage=SimpleNamespace(pieces=self._images),
            model_revision="dola-seedream-5-0-pro-260628",
        )


def _executor(
    *, budget: Budget | None = Budget(Decimal("5")), adapter: FakeSeedream | None = None
) -> tuple[ProductCharacterExecutor, Any, Any, FakeObjects, FakeLedger, FakeSeedream, Any]:
    service, repo, ledger, _ = _service()
    objects = FakeObjects()
    usage = FakeLedger()
    seedream = adapter or FakeSeedream()
    executor = ProductCharacterExecutor(
        adapter=seedream,
        reads=FakeReads(service, budget),
        requests=repo,
        marks=service,
        objects=objects,
        ledger=usage,
        api_key=lambda t, b: "platform-key",
        clock=lambda: NOW,
        sleep=lambda s: None,
    )
    return executor, service, ledger, objects, usage, seedream, repo


def _job(character_id: UUID) -> JobContext:
    return JobContext(
        job_id=uuid4(),
        tenant_id=TENANT,
        draft_id=None,
        kind="sticker_character",
        revision=1,
        position=0,
        vendor_model="byteplus:seedream-5-0-pro",
        lane="now",
        vendor_priority=0,
        deadline=None,
        pricing_version="v9",
        sticker_character_id=character_id,
    )


def test_one_paid_call_then_a_ready_character_with_its_cost_and_files() -> None:
    executor, service, ledger, objects, usage, seedream, _ = _executor()
    c = service.request_character(TENANT, BRAND, PRODUCT, USER, accepted_creations=1)
    task = executor.submit(_job(c.id))
    assert task == task_id_of(c.id) and seedream.calls == 1
    params = seedream.requests[0].params
    assert params["size"] == "1K" and params["model"] == "dola-seedream-5-0-pro-260628"
    assert params["images"][0].startswith("data:image/jpeg;base64,")
    assert usage.booked == {c.id: Decimal("0.045")}
    assert executor.poll(_job(c.id), task).status == SUCCEEDED
    executor.finish(_job(c.id), task, SUCCEEDED)
    done = service.character(TENANT, BRAND, c.id)
    assert done.status == ps.STATUS_READY and done.cost_usd == Decimal("0.045")
    assert done.object_key == f"seasonal/{TENANT}/{BRAND}/personajes/{c.id}-1.webp"
    assert done.raw_object_key == f"seasonal/{TENANT}/{BRAND}/personajes/{c.id}-2.webp"
    with Image.open(io.BytesIO(objects.files[done.object_key])) as cut:
        assert cut.mode == "RGBA" and cut.getpixel((0, 0))[3] == 0
    assert ledger.balance(tenant_id=TENANT, brand_id=BRAND).used == 1  # kept: it came out
    executor.finish(_job(c.id), task, SUCCEEDED)  # idempotent
    assert seedream.calls == 1


def test_the_price_guard_refuses_before_any_call_and_gives_the_creation_back() -> None:
    # a configured HARD cap the quote does not fit in: refused, nothing reaches BytePlus
    executor, service, ledger, _, usage, seedream, _ = _executor(
        budget=Budget(Decimal("0.01"), hard_stop=True)
    )
    c = service.request_character(TENANT, BRAND, PRODUCT, USER, accepted_creations=1)
    with pytest.raises(PriceGuardRefused):
        executor.submit(_job(c.id))
    assert seedream.calls == 0 and usage.booked == {}
    failed = service.character(TENANT, BRAND, c.id)
    assert failed.status == ps.STATUS_FAILED and failed.fail_reason == BUDGET_CAP
    assert "No se te cobró" in failed.failure_text
    assert ledger.balance(tenant_id=TENANT, brand_id=BRAND).used == 0


@pytest.mark.parametrize(
    "budget",
    [None, Budget(Decimal("0.01"), hard_stop=False), Budget(Decimal("-3"), hard_stop=False)],
    ids=["no-config-row", "soft-cap-over", "soft-cap-overspent"],
)
def test_no_config_row_or_a_soft_cap_is_no_dollar_cap(budget: Budget | None) -> None:
    # m-25018822: like the generator (`service._UNLIMITED_BUDGET`, `parts.py`) — the owner's
    # limit is the creaciones quota, already charged by `create_character`
    executor, service, ledger, _, usage, seedream, _ = _executor(budget=budget)
    c = service.request_character(TENANT, BRAND, PRODUCT, USER, accepted_creations=1)
    task = executor.submit(_job(c.id))
    assert task == task_id_of(c.id) and seedream.calls == 1
    assert usage.booked == {c.id: Decimal("0.045")}  # the real cost is still booked
    executor.finish(_job(c.id), task, SUCCEEDED)
    assert service.character(TENANT, BRAND, c.id).status == ps.STATUS_READY
    assert ledger.balance(tenant_id=TENANT, brand_id=BRAND).used == 1


def test_a_hard_cap_with_room_proceeds() -> None:
    executor, service, _, _, _, seedream, _ = _executor(
        budget=Budget(Decimal("0.05"), hard_stop=True)
    )
    c = service.request_character(TENANT, BRAND, PRODUCT, USER, accepted_creations=1)
    executor.submit(_job(c.id))
    assert seedream.calls == 1


def test_the_legacy_no_budget_cap_reason_still_reads_for_old_rows() -> None:
    assert "no se te cobró" in ps.REASON_TEXT["no_budget_cap"].lower()


def test_a_claim_after_a_started_post_never_posts_again() -> None:
    executor, service, ledger, _, usage, seedream, repo = _executor()
    c = service.request_character(TENANT, BRAND, PRODUCT, USER, accepted_creations=1)
    assert repo.start_request(tenant_id=TENANT, character_id=c.id, at=NOW)  # a dead claim
    with pytest.raises(SubmissionAborted):
        executor.submit(_job(c.id))
    assert seedream.calls == 0
    assert usage.booked == {c.id: Decimal("0.045")}  # it may have been billed: booked
    failed = service.character(TENANT, BRAND, c.id)
    assert failed.fail_reason == UNCERTAIN
    assert ledger.balance(tenant_id=TENANT, brand_id=BRAND).used == 0  # the owner pays nothing


def test_busy_vendor_clears_the_stamp_so_the_deferred_job_can_post() -> None:
    from qualify_creative.adapters.byteplus_ark import VendorBusy

    busy = VendorBusy(429, "ServerOverloaded", "busy", 5.0)
    executor, service, _, _, usage, seedream, repo = _executor(adapter=FakeSeedream(error=busy))
    c = service.request_character(TENANT, BRAND, PRODUCT, USER, accepted_creations=1)
    with pytest.raises(VendorBusy):
        executor.submit(_job(c.id))
    assert repo.rows[c.id].vendor_request_started_at is None
    assert repo.rows[c.id].status == ps.STATUS_PENDING and usage.booked == {}


def test_a_vendor_error_is_not_booked_and_gives_the_creation_back() -> None:
    from qualify_creative.adapters.byteplus_ark import ArkAPIError

    refusal = ArkAPIError(400, "OutputImageSensitiveContentDetected", "moderated")
    executor, service, ledger, _, usage, _, _ = _executor(adapter=FakeSeedream(error=refusal))
    c = service.request_character(TENANT, BRAND, PRODUCT, USER, accepted_creations=1)
    with pytest.raises(ArkAPIError):
        executor.submit(_job(c.id))
    assert usage.booked == {}
    assert service.character(TENANT, BRAND, c.id).fail_reason == VENDOR_FAILED
    assert ledger.balance(tenant_id=TENANT, brand_id=BRAND).used == 0


def test_a_dropped_connection_books_the_quote_but_charges_the_owner_nothing() -> None:
    from qualify_creative.adapters.byteplus_ark import SeedreamDisconnected

    executor, service, ledger, _, usage, _, _ = _executor(
        adapter=FakeSeedream(error=SeedreamDisconnected("ReadTimeout"))
    )
    c = service.request_character(TENANT, BRAND, PRODUCT, USER, accepted_creations=1)
    with pytest.raises(SeedreamDisconnected):
        executor.submit(_job(c.id))
    assert usage.booked == {c.id: Decimal("0.045")}
    assert ledger.balance(tenant_id=TENANT, brand_id=BRAND).used == 0


def test_a_lost_raw_image_fails_without_paying_again() -> None:
    executor, service, ledger, objects, _, seedream, _ = _executor()
    c = service.request_character(TENANT, BRAND, PRODUCT, USER, accepted_creations=1)
    task = executor.submit(_job(c.id))
    objects.files = {k: v for k, v in objects.files.items() if not k.endswith("-2.webp")}
    executor.finish(_job(c.id), task, SUCCEEDED)
    assert service.character(TENANT, BRAND, c.id).fail_reason == "lost_result"
    assert seedream.calls == 1 and ledger.balance(tenant_id=TENANT, brand_id=BRAND).used == 0


def test_a_failed_job_without_task_fails_the_character() -> None:
    executor, service, ledger, *_ = _executor()
    c = service.request_character(TENANT, BRAND, PRODUCT, USER, accepted_creations=1)
    executor.finish(_job(c.id), None, "failed")
    assert service.character(TENANT, BRAND, c.id).status == ps.STATUS_FAILED
    assert ledger.balance(tenant_id=TENANT, brand_id=BRAND).used == 0


def test_r2_writes_are_retried() -> None:
    executor, service, _, objects, *_ = _executor()
    objects.fail_puts = 2
    c = service.request_character(TENANT, BRAND, PRODUCT, USER, accepted_creations=1)
    task = executor.submit(_job(c.id))
    assert any(k.endswith(f"{c.id}-2.webp") for k in objects.files)
    executor.finish(_job(c.id), task, SUCCEEDED)
    assert service.character(TENANT, BRAND, c.id).status == ps.STATUS_READY


# --- the media-worker branch --------------------------------------------------------------


class FakeSources:
    def __init__(self, row: Any, art_key: str | None) -> None:
        self.row = row
        self.art_key = art_key

    def media_row(self, tenant_id: UUID, media_id: UUID) -> Any:
        return self.row

    def character_art_key(self, tenant_id: UUID, brand_id: UUID, character_id: UUID) -> Any:
        return self.art_key

    def palette(self, tenant_id: UUID, brand_id: UUID) -> list[str]:
        return ["#c5093b", "#ffcd00"]

    def heading_font(self, tenant_id: UUID, brand_id: UUID) -> tuple[None, str]:
        return None, "Unbounded"

    def logo_key(self, tenant_id: UUID, brand_id: UUID) -> None:
        return None

    def piece_image_keys(self, *a: Any) -> list[str]:
        return []


class FakeMarks:
    def __init__(self) -> None:
        self.ready: list[dict[str, Any]] = []
        self.failed: list[dict[str, Any]] = []

    def mark_ready(self, **kw: Any) -> None:
        self.ready.append(kw)

    def mark_failed(self, **kw: Any) -> None:
        self.failed.append(kw)


def _sticker_job(character_id: UUID, recipe: str = "k-animado") -> tuple[SeasonalJob, Any]:
    media_id = uuid4()
    job = SeasonalJob(
        media_id=media_id,
        tenant_id=TENANT,
        brand_id=BRAND,
        kind="sticker",
        recipe=recipe,
        source_kind="character",
        source_ref=f"{character_id}:¡Gracias por tu pedido!",
        season_key=PRODUCT_SEASON_KEY,
    )
    row = SimpleNamespace(
        brand_id=BRAND,
        status="pending",
        attempt=1,
        object_key=None,
        agrees_with=lambda j: True,
    )
    return job, row


def _cut_key(character_id: UUID) -> str:
    return f"seasonal/{TENANT}/{BRAND}/personajes/{character_id}-1.webp"


def test_the_media_worker_draws_a_character_sticker_with_its_message(tmp_path: Path) -> None:
    from qualify_creative.seasonal.kawaii import cut_out

    character_id = uuid4()
    job, row = _sticker_job(character_id)
    objects = FakeObjects()
    objects.files[_cut_key(character_id)] = cut_out(_character_jpeg()).data
    marks = FakeMarks()
    calls: list[dict[str, Any]] = []

    def product_render(
        recipe: str, look: BrandLook, work: Path, *, art: Image.Image, message: str
    ) -> RecipeOutput:
        calls.append({"recipe": recipe, "message": message, "mode": art.mode})
        return RecipeOutput(
            data=b"RIFF....WEBP",
            kind="sticker",
            recipe=recipe,
            content_type="image/webp",
            ext="webp",
            width=512,
            height=512,
            duration_ms=2000,
            frames=30,
            bytes=12,
            pipeline_version="kawaii-sticker-1",
            encoding="remotion+pillow q=70",
            engine="remotion",
        )

    handler = SeasonalMediaJobHandler(
        objects=objects,  # type: ignore[arg-type]
        marks=marks,
        sources=FakeSources(row, _cut_key(character_id)),  # type: ignore[arg-type]
        product_render=product_render,
        tmp_root=tmp_path,
    )
    outcome = handler.handle(job)
    assert outcome.status == "done", outcome
    assert calls == [{"recipe": "k-animado", "message": "¡Gracias por tu pedido!", "mode": "RGBA"}]
    assert marks.ready and marks.ready[0]["cost_usd"] == 0.0


def test_without_the_render_service_the_job_retries_never_pillow(tmp_path: Path) -> None:
    from qualify_creative.seasonal.kawaii import cut_out

    character_id = uuid4()
    job, row = _sticker_job(character_id, "k-quieto")
    objects = FakeObjects()
    objects.files[_cut_key(character_id)] = cut_out(_character_jpeg()).data
    handler = SeasonalMediaJobHandler(
        objects=objects,  # type: ignore[arg-type]
        marks=FakeMarks(),
        sources=FakeSources(row, _cut_key(character_id)),  # type: ignore[arg-type]
        product_render=None,
        tmp_root=tmp_path,
    )
    outcome = handler.handle(job)
    assert outcome.status == "retry" and outcome.reason == "render_unavailable"


def test_a_character_no_longer_approved_fails_the_sticker(tmp_path: Path) -> None:
    job, row = _sticker_job(uuid4())
    marks = FakeMarks()
    handler = SeasonalMediaJobHandler(
        objects=FakeObjects(),  # type: ignore[arg-type]
        marks=marks,
        sources=FakeSources(row, None),  # type: ignore[arg-type]
        product_render=lambda *a, **k: None,  # type: ignore[arg-type,return-value]
        tmp_root=tmp_path,
    )
    outcome = handler.handle(job)
    assert outcome.status == "failed" and outcome.reason == "character_unavailable"
    assert marks.failed[0]["reason"] == "character_unavailable"


# --- the library order --------------------------------------------------------------------


def _approved(season_key: str, label: str, at: datetime) -> SeasonalMedia:
    return SeasonalMedia(
        id=uuid4(),
        tenant_id=TENANT,
        brand_id=BRAND,
        season_key=season_key,
        season_label=label,
        kind="sticker",
        recipe="k-animado" if season_key == PRODUCT_SEASON_KEY else "e-latido",
        source_kind="character" if season_key == PRODUCT_SEASON_KEY else "logo",
        source_ref=f"{uuid4()}:Hola" if season_key == PRODUCT_SEASON_KEY else "logo.png",
        status=STATUS_APPROVED,
        object_key=f"seasonal/x/{uuid4()}-1.webp",
        created_at=at,
        approved_at=at,
    )


def test_the_chat_and_the_library_list_the_seasons_first() -> None:
    repo = MemorySeasonalRepository()
    newest_product = _approved(PRODUCT_SEASON_KEY, "De tus productos", NOW)
    older_season = _approved("navidad-2026", "Navidad", NOW - timedelta(days=3))
    for media in (newest_product, older_season):
        repo.rows[media.id] = media
    library = SeasonalMediaService(repo, MemorySourceReads())
    chat = library.list_approved_for_chat(TENANT, BRAND)
    assert [m.season_key for m in chat] == ["navidad-2026", PRODUCT_SEASON_KEY]
    seasons = library.list_seasons(TENANT, BRAND)
    assert [s.season_key for s in seasons] == ["navidad-2026", PRODUCT_SEASON_KEY]


def test_a_ready_product_sticker_is_approved_with_the_library_approve() -> None:
    service, repo, _, library = _service()
    ready = _ready(service, repo)
    service.approve_character(TENANT, BRAND, ready.id, USER)
    (row,) = service.make_stickers(TENANT, BRAND, ready.id, ["Entregado"], USER)
    key = f"seasonal/{TENANT}/{BRAND}/{PRODUCT_SEASON_KEY}/{row.id}-1.webp"
    library.mark_ready(
        tenant_id=TENANT,
        brand_id=BRAND,
        media_id=row.id,
        attempt=1,
        object_key=key,
        bytes=1000,
        width=512,
        height=512,
        duration_ms=2000,
    )
    (approved,) = library.approve(TENANT, BRAND, [row.id], USER)
    assert approved.status == STATUS_APPROVED
    assert [m.id for m in library.list_approved_for_chat(TENANT, BRAND)] == [row.id]
    assert replace(approved, status=STATUS_READY).status == STATUS_READY
