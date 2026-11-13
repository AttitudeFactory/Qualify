"""Product stickers (m-25017372), the failure paths found in review: nothing stays charged,
nothing is paid twice, a paid image is not thrown away. Offline, with the fakes of
`test_product_stickers`."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from packages.api.tests.test_product_stickers import (
    BRAND,
    PRODUCT,
    TENANT,
    USER,
    FakeSeedream,
    _executor,
    _job,
    _service,
)

from qualify_api.creative import product_stickers as ps
from qualify_api.creative.worker.executor import SUCCEEDED


def test_give_up_fails_a_pending_character_and_gives_the_creation_back() -> None:
    executor, service, ledger, *_ = _executor()
    c = service.request_character(TENANT, BRAND, PRODUCT, USER, accepted_creations=1)
    executor.give_up(_job(c.id))
    assert service.character(TENANT, BRAND, c.id).status == ps.STATUS_FAILED
    assert ledger.balance(tenant_id=TENANT, brand_id=BRAND).used == 0
    executor.give_up(_job(c.id))  # idempotent
    assert ledger.balance(tenant_id=TENANT, brand_id=BRAND).used == 0


def test_the_router_forwards_give_up() -> None:
    from qualify_api.creative.product_sticker_ai import UnknownKindExecutor
    from qualify_api.creative.seasonal_ai import KindRoutedExecutor

    executor, service, *_ = _executor()
    routed = KindRoutedExecutor(UnknownKindExecutor(), {"sticker_character": executor})
    c = service.request_character(TENANT, BRAND, PRODUCT, USER, accepted_creations=1)
    routed.give_up(_job(c.id))
    assert service.character(TENANT, BRAND, c.id).status == ps.STATUS_FAILED


def test_the_runner_gives_up_when_finish_keeps_failing() -> None:
    from qualify_api.creative.worker import runner as r

    calls: list[Any] = []

    class Exploding:
        def finish(self, *a: Any) -> None:
            raise OSError("r2 down")

        def give_up(self, ctx: Any) -> None:
            calls.append(ctx)

    class Store:
        def settle(self, *a: Any, **k: Any) -> bool:
            return True

        def release(self, *a: Any, **k: Any) -> None:
            return None

    worker = r.CreativeWorker.__new__(r.CreativeWorker)
    worker.store = Store()  # type: ignore[assignment]
    worker.clock = lambda: None  # type: ignore[assignment]
    worker.downloads = r.DownloadGate(1)
    hint = type("Row", (), {"attempts": r.MAX_FINISH_ATTEMPTS})()
    claim = type("Claim", (), {"job_id": "j"})()
    outcome = worker._end(claim, Exploding(), "ctx", "t", "failed", attempts_hint=hint)  # type: ignore[arg-type]
    assert outcome == r.FAILED_OUTCOME and calls == ["ctx"]


def test_a_refund_that_raises_leaves_the_character_pending_for_the_next_attempt() -> None:
    service, repo, ledger, _ = _service()
    c = service.request_character(TENANT, BRAND, PRODUCT, USER, accepted_creations=1)
    real_refund = ledger.refund

    def flaky(**kw: Any) -> bool:
        raise RuntimeError("db hiccup")

    ledger.refund = flaky  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        service.mark_character_failed(
            tenant_id=TENANT, brand_id=BRAND, character_id=c.id, reason="vendor_failed"
        )
    assert repo.rows[c.id].status == ps.STATUS_PENDING
    ledger.refund = real_refund  # type: ignore[method-assign]
    service.mark_character_failed(
        tenant_id=TENANT, brand_id=BRAND, character_id=c.id, reason="vendor_failed"
    )
    assert ledger.balance(tenant_id=TENANT, brand_id=BRAND).used == 0


def test_a_gateway_5xx_is_booked_as_maybe_billed() -> None:
    from qualify_creative.adapters.byteplus_ark import ArkAPIError

    executor, service, ledger, _, usage, _, _ = _executor(
        adapter=FakeSeedream(error=ArkAPIError(502, None, "bad gateway"))
    )
    c = service.request_character(TENANT, BRAND, PRODUCT, USER, accepted_creations=1)
    with pytest.raises(ArkAPIError):
        executor.submit(_job(c.id))
    assert usage.booked == {c.id: Decimal("0.045")}
    assert ledger.balance(tenant_id=TENANT, brand_id=BRAND).used == 0


def test_a_lost_claim_whose_image_reached_r2_is_finished_not_thrown_away() -> None:
    executor, service, ledger, _, _, seedream, _ = _executor()
    c = service.request_character(TENANT, BRAND, PRODUCT, USER, accepted_creations=1)
    task = executor.submit(_job(c.id))  # paid, booked, raw in R2 — then the claim was lost
    assert executor.submit(_job(c.id)) == task  # the next claim resumes, never posts again
    assert seedream.calls == 1
    executor.finish(_job(c.id), task, SUCCEEDED)
    assert service.character(TENANT, BRAND, c.id).status == ps.STATUS_READY
    assert ledger.balance(tenant_id=TENANT, brand_id=BRAND).used == 1
