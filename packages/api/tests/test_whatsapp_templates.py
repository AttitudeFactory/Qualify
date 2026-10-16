"""WA-18 — templates: the service over a memory repository + a fake client, and the
template webhook handler driven by the doc-derived fixtures. Fully offline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_shared.social.wa_shapes import WATemplateStatusUpdate

from qualify_api.webhooks.repository import (
    STATUS_AMBIGUOUS,
    STATUS_DEAD,
    STATUS_ORPHAN,
    STATUS_PROCESSED,
    STATUS_UNSUPPORTED,
    ClaimedEvent,
)
from qualify_api.whatsapp.client import TemplateCreateResult, TemplateInfo
from qualify_api.whatsapp.resolve import (
    PhoneResolution,
    PhoneResolutionOutcome,
    pick_waba_resolution,
)
from qualify_api.whatsapp.templates import (
    MemoryTemplateRepository,
    NoWhatsAppNumber,
    TemplateAlreadyExists,
    TemplateRecord,
    TemplateService,
    rejected_reason_from,
    template_status_handler,
)

FIXTURES = Path(__file__).resolve().parents[2] / "shared" / "tests" / "fixtures"
TENANT = UUID("a0000000-0000-4000-8000-0000000018aa")
CONNECTION = uuid4()
PHONE_ROW = uuid4()
WABA = "102290129340398"  # the fixtures' entry.id
BODY = [{"type": "BODY", "text": "Hola {{1}}"}]


class FakeClient:
    def __init__(self) -> None:
        self.created: list[tuple[str, str, str, str]] = []
        self.deleted: list[tuple[str, str]] = []
        self.listing: list[TemplateInfo] = []

    async def create_template(
        self, waba_id: str, name: str, language: str, category: str, components: list[Any]
    ) -> TemplateCreateResult:
        self.created.append((waba_id, name, language, category))
        return TemplateCreateResult(id="9001", status="PENDING", category=category.lower())

    async def list_templates(self, waba_id: str) -> list[TemplateInfo]:
        return list(self.listing)

    async def delete_template(self, waba_id: str, name: str) -> None:
        self.deleted.append((waba_id, name))


@pytest.fixture
def repo() -> MemoryTemplateRepository:
    r = MemoryTemplateRepository()
    r.add_number(tenant_id=TENANT, connection_id=CONNECTION, waba_id=WABA, phone_row_id=PHONE_ROW)
    return r


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def service(repo: MemoryTemplateRepository, client: FakeClient) -> TemplateService:
    async def factory(*, tenant_id: UUID, connection_id: UUID) -> FakeClient:
        return client

    return TemplateService(repo, factory)  # type: ignore[arg-type]


# --- service ------------------------------------------------------------------------


async def test_create_calls_meta_then_mirrors_its_answer(service, client, repo) -> None:
    record = await service.create(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        name="promo_2x1",
        language="es",
        category="MARKETING",
        components=BODY,
    )
    assert client.created == [(WABA, "promo_2x1", "es", "MARKETING")]
    assert (record.meta_template_id, record.status, record.category) == (
        "9001",
        "PENDING",
        "marketing",
    )
    assert record.phone_number_row_id == PHONE_ROW
    assert not record.is_sendable
    assert service.list(tenant_id=TENANT, connection_id=CONNECTION) == [record]


async def test_create_refuses_a_duplicate_before_calling_meta(service, client) -> None:
    kwargs = dict(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        name="promo",
        language="es",
        category="marketing",
        components=BODY,
    )
    await service.create(**kwargs)
    with pytest.raises(TemplateAlreadyExists):
        await service.create(**kwargs)
    assert len(client.created) == 1


async def test_create_validates_locally_and_needs_a_number(service, client) -> None:
    with pytest.raises(ValueError):
        await service.create(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            name="Bad Name",
            language="es",
            category="marketing",
            components=BODY,
        )
    with pytest.raises(NoWhatsAppNumber):
        await service.create(
            tenant_id=TENANT,
            connection_id=uuid4(),
            name="ok",
            language="es",
            category="marketing",
            components=BODY,
        )
    assert client.created == []


async def test_sync_upserts_by_natural_key(service, client, repo) -> None:
    await service.create(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        name="promo",
        language="es",
        category="marketing",
        components=BODY,
    )
    client.listing = [
        TemplateInfo(
            id="9001", name="promo", language="es", status="APPROVED", category="marketing"
        ),
        TemplateInfo(
            id="9002",
            name="order_ready",
            language="es",
            status="APPROVED",
            category="utility",
            quality="GREEN",
        ),
        TemplateInfo(id="9003", name="odd", language="es", status="APPROVED", category="weird"),
    ]
    report = await service.sync_from_meta(tenant_id=TENANT, connection_id=CONNECTION)
    assert (report.listed, report.created) == (3, 1)
    rows = {r.name: r for r in service.list(tenant_id=TENANT)}
    assert set(rows) == {"promo", "order_ready"}
    assert rows["promo"].status == "APPROVED" and rows["promo"].is_sendable
    assert rows["order_ready"].quality == "GREEN"


async def test_delete_is_by_name_and_marks_every_language(service, client, repo) -> None:
    for language in ("es", "en"):
        repo.insert(
            TemplateRecord(
                id=uuid4(),
                tenant_id=TENANT,
                waba_id=WABA,
                name="promo",
                language=language,
                category="marketing",
                status="APPROVED",
            )
        )
    target = service.list(tenant_id=TENANT)[0]
    marked = await service.delete(tenant_id=TENANT, connection_id=CONNECTION, template_id=target.id)
    assert marked == 2
    assert client.deleted == [(WABA, "promo")]
    assert {r.status for r in service.list(tenant_id=TENANT)} == {"DELETED"}


# --- handler ------------------------------------------------------------------------


def _event(fixture: str, *, value: dict[str, Any] | None = None) -> ClaimedEvent:
    body = json.loads((FIXTURES / fixture).read_text())
    (entry,) = body["entry"]
    (change,) = entry["changes"]
    return ClaimedEvent(
        id=uuid4(),
        delivery_id=uuid4(),
        object=body["object"],
        entry_id=entry["id"],
        field=change["field"],
        value=change["value"] if value is None else value,
        attempts=1,
    )


def _resolved(waba_id: str) -> PhoneResolution:
    assert waba_id == WABA
    return PhoneResolution(
        outcome=PhoneResolutionOutcome.RESOLVED,
        tenant_id=TENANT,
        connection_id=CONNECTION,
        phone_row_id=PHONE_ROW,
    )


def _mirror(repo: MemoryTemplateRepository, **overrides: Any) -> TemplateRecord:
    base = dict(
        id=uuid4(),
        tenant_id=TENANT,
        waba_id=WABA,
        name="order_confirmation",
        language="en-US",
        category="utility",
        status="PENDING",
        meta_template_id="1689556908129832",
    )
    return repo.insert(TemplateRecord(**{**base, **overrides}))


async def test_status_update_approves_the_mirrored_template(repo) -> None:
    row = _mirror(repo)
    handler = template_status_handler(resolve=_resolved, repo=repo)
    outcome = await handler(_event("whatsapp_template_status_approved_doc.json"))
    assert outcome.status == STATUS_PROCESSED
    updated = repo.rows[row.id]
    assert (updated.status, updated.rejected_reason) == ("APPROVED", None)
    assert updated.is_sendable


async def test_status_update_records_the_rejection(repo) -> None:
    row = _mirror(repo, name="abandoned_cart", language="en", meta_template_id="1689556908129835")
    handler = template_status_handler(resolve=_resolved, repo=repo)
    await handler(_event("whatsapp_template_status_rejected_doc.json"))
    updated = repo.rows[row.id]
    assert updated.status == "REJECTED"
    assert updated.rejected_reason is not None
    assert updated.rejected_reason.startswith("INVALID_FORMAT: ")


async def test_status_update_falls_back_to_name_and_language(repo) -> None:
    row = _mirror(repo, meta_template_id=None)
    handler = template_status_handler(resolve=_resolved, repo=repo)
    await handler(_event("whatsapp_template_status_approved_doc.json"))
    assert repo.rows[row.id].status == "APPROVED"


async def test_quality_update_sets_the_score(repo) -> None:
    row = _mirror(
        repo, name="welcome_template", language="en-US", meta_template_id="806312974732579"
    )
    handler = template_status_handler(resolve=_resolved, repo=repo)
    assert (await handler(_event("whatsapp_template_quality_doc.json"))).status == (
        STATUS_PROCESSED
    )
    assert repo.rows[row.id].quality == "YELLOW"


async def test_unknown_template_is_processed_and_writes_nothing(repo) -> None:
    handler = template_status_handler(resolve=_resolved, repo=repo)
    outcome = await handler(_event("whatsapp_template_status_approved_doc.json"))
    assert outcome.status == STATUS_PROCESSED
    assert repo.rows == {}


async def test_another_tenants_template_is_never_touched(repo) -> None:
    row = _mirror(repo, tenant_id=uuid4())
    handler = template_status_handler(resolve=_resolved, repo=repo)
    await handler(_event("whatsapp_template_status_approved_doc.json"))
    assert repo.rows[row.id].status == "PENDING"


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (PhoneResolutionOutcome.ORPHAN, STATUS_ORPHAN),
        (PhoneResolutionOutcome.AMBIGUOUS, STATUS_AMBIGUOUS),
    ],
)
async def test_unresolved_waba_writes_nothing(repo, outcome, expected) -> None:
    row = _mirror(repo)
    handler = template_status_handler(resolve=lambda _: PhoneResolution(outcome=outcome), repo=repo)
    assert (await handler(_event("whatsapp_template_status_approved_doc.json"))).status == expected
    assert repo.rows[row.id].status == "PENDING"


async def test_off_contract_value_is_dead_and_other_fields_unsupported(repo) -> None:
    handler = template_status_handler(resolve=_resolved, repo=repo)
    dead = await handler(_event("whatsapp_template_status_approved_doc.json", value={"x": 1}))
    assert (dead.status, dead.error) == (STATUS_DEAD, "contract_violation")
    other = _event("whatsapp_template_status_approved_doc.json")
    other = ClaimedEvent(**{**other.__dict__, "field": "account_update"})
    assert (await handler(other)).status == STATUS_UNSUPPORTED


def test_rejected_reason_none_is_null() -> None:
    update = WATemplateStatusUpdate.model_validate(
        {
            "event": "APPROVED",
            "message_template_id": 1,
            "message_template_name": "x",
            "message_template_language": "es",
            "reason": "NONE",
        }
    )
    assert rejected_reason_from(update) is None


def test_pick_waba_resolution() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    assert pick_waba_resolution([]).outcome is PhoneResolutionOutcome.ORPHAN
    resolved = pick_waba_resolution([(a, TENANT, c), (b, TENANT, c)])
    assert (resolved.outcome, resolved.tenant_id, resolved.phone_row_id) == (
        PhoneResolutionOutcome.RESOLVED,
        TENANT,
        a,
    )
    assert (
        pick_waba_resolution([(a, TENANT, c), (b, uuid4(), c)]).outcome
        is PhoneResolutionOutcome.AMBIGUOUS
    )
