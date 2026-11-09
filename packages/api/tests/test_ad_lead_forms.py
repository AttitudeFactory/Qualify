"""Offline lead form validation, one-shot writes and bounded Meta contracts."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from qualify_api.ads import lead_forms_service as service
from qualify_api.ads.lead_forms import LeadFormDraft, LeadFormQuestion, LeadFormUnavailable
from qualify_api.ads.lead_forms_client import LeadFormsClient
from qualify_api.ads.lead_forms_webhook import leadgen_handler
from qualify_api.webhooks.repository import ClaimedEvent


def draft() -> LeadFormDraft:
    return LeadFormDraft(
        "Información de viajes",
        "https://example.invalid/privacidad",
        "Gracias",
        "Recibimos tus datos.",
        "https://example.invalid",
        (LeadFormQuestion("FULL_NAME"), LeadFormQuestion("EMAIL")),
    )


def raw_lead(**changes: object) -> dict:
    return {
        "id": "900",
        "form_id": "800",
        "created_time": "2026-01-01T00:00:00+0000",
        "field_data": [{"name": "email", "values": ["synthetic@example.invalid"]}],
        **changes,
    }


def test_spanish_policy_always_sent_and_no_whatsapp_consent_inferred() -> None:
    payload = draft().payload()
    assert payload["locale"] == "ES_LA"
    assert payload["privacy_policy"] == {"url": "https://example.invalid/privacidad"}
    assert "custom_disclaimer" not in payload
    parsed = service.parse_lead(raw_lead(), form_id="800")
    assert parsed["phone"] is None and parsed["email"] == "synthetic@example.invalid"
    assert "consent_at" not in parsed and "whatsapp_opt_in" not in parsed


@pytest.mark.parametrize(
    "changes",
    [
        {"privacy_policy_url": ""},
        {"privacy_policy_url": "http://example.invalid"},
        {"privacy_policy_url": "https://user:secret@example.invalid"},
        {"locale": "en_US"},
        {"questions": ()},
        {"questions": (LeadFormQuestion("FULL_NAME"),)},
        {"questions": (LeadFormQuestion("EMAIL"), LeadFormQuestion("EMAIL"))},
        {"thank_you_title": "x" * 61},
        {"questions": (LeadFormQuestion("EMAIL"), LeadFormQuestion("CUSTOM", "BAD", "Zona"))},
    ],
)
def test_invalid_editor_values_fail_before_remote_write(changes: dict) -> None:
    with pytest.raises(LeadFormUnavailable):
        replace(draft(), **changes).payload()


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "other"},
        {"form_id": "801"},
        {"created_time": "not-a-date"},
        {"created_time": "2026-01-01"},
        {"field_data": "bad"},
        {"field_data": [{"name": "email", "values": "one"}]},
        {"field_data": [{"name": "email", "values": ["a"]}, {"name": "email", "values": ["b"]}]},
        {"field_data": [{"name": "email", "values": [True]}]},
        {"ad_id": "https://evil.invalid"},
    ],
)
def test_off_contract_lead_does_not_enter_crm(changes: dict) -> None:
    with pytest.raises(LeadFormUnavailable):
        service.parse_lead(raw_lead(**changes), form_id="800", leadgen_id="900")


@pytest.mark.asyncio
async def test_cursor_only_fixed_graph_host_and_no_token_in_url() -> None:
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(
                200,
                json={
                    "data": [raw_lead()],
                    "paging": {
                        "cursors": {"after": "next_cursor"},
                        "next": "https://evil.invalid/?access_token=bad",
                    },
                },
            )
        return httpx.Response(200, json={"data": []})

    client = LeadFormsClient(
        httpx.AsyncClient(
            transport=httpx.MockTransport(handle), headers={"Authorization": "Bearer synthetic"}
        )
    )
    first = await client.leads("800", since=0)
    await client.leads("800", since=0, after=first.after)
    await client.aclose()
    assert len(calls) == 2 and all(call.url.host == "graph.facebook.com" for call in calls)
    assert calls[1].url.params["after"] == "next_cursor"
    assert all("access_token" not in str(call.url) for call in calls)
    assert json.loads(calls[0].url.params["filtering"])[0]["field"] == "time_created"


@pytest.mark.asyncio
async def test_subscription_unions_fields_and_rechecks_before_post() -> None:
    calls, guards = [], []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={"data": [{"id": "100", "subscribed_fields": ["messages", "feed"]}]}
            if request.method == "GET"
            else {"success": True},
        )

    client = LeadFormsClient(httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    await client.subscribe_leadgen("200", app_id="100", before_write=lambda: guards.append(True))
    await client.aclose()
    assert guards == [True]
    assert calls[1].content == b"subscribed_fields=feed%2Cleadgen%2Cmessages"


@pytest.mark.asyncio
async def test_subscription_revoked_after_read_has_no_post() -> None:
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"data": []})

    def revoked() -> None:
        raise LeadFormUnavailable("revoked")

    client = LeadFormsClient(httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    with pytest.raises(LeadFormUnavailable):
        await client.subscribe_leadgen("200", app_id="100", before_write=revoked)
    await client.aclose()
    assert [call.method for call in calls] == ["GET"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["timeout", "foreign_page", "missing_id", "revoked_after_claim"]
)
async def test_claimed_publication_unknown_is_not_blindly_retried(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    tenant, form_id, connection = uuid4(), uuid4(), uuid4()
    form = {
        "id": form_id,
        "connection_id": connection,
        "page_id": "200",
        "credential_version": 1,
        "brand_id": uuid4(),
        "status": "draft",
        "approved_snapshot": asdict(draft()),
    }
    calls = []
    monkeypatch.setattr(service, "_member", lambda *_: None)
    monkeypatch.setattr(service, "_form_guard", lambda *_: {"id": connection})
    monkeypatch.setattr(service.repository, "get_form", lambda *_: form)

    def claim(*args: object) -> dict:
        if form["status"] != "draft":
            raise LeadFormUnavailable("already claimed")
        form["status"] = "publishing"
        if failure == "revoked_after_claim":
            monkeypatch.setattr(
                service,
                "_form_guard",
                lambda *_: (_ for _ in ()).throw(LeadFormUnavailable("revoked")),
            )
        return form

    monkeypatch.setattr(service.repository, "claim_publication", claim)

    def finish(*args: object, meta_form_id: str | None) -> str:
        assert meta_form_id is None
        form["status"] = "unknown"
        return "unknown"

    monkeypatch.setattr(service.repository, "finish_publication", finish)

    async def create(*args: object) -> str:
        calls.append("POST")
        if failure == "timeout":
            raise TimeoutError
        if failure == "missing_id":
            raise LeadFormUnavailable("missing id")
        return "800"

    fake = AsyncMock()
    fake.read.return_value = {"id": "800", "page_id": "999"}
    fake.create_form.side_effect = create
    monkeypatch.setattr(service, "_client", AsyncMock(return_value=fake))
    monkeypatch.setattr(service, "_page_access", AsyncMock())
    assert (
        await service.publish_lead_form(
            tenant_id=tenant, form_id=form_id, confirmed=True, expected_revision=1
        )
        == "unknown"
    )
    if failure != "revoked_after_claim":
        with pytest.raises(LeadFormUnavailable):
            await service.publish_lead_form(
                tenant_id=tenant, form_id=form_id, confirmed=True, expected_revision=1
            )
    assert len(calls) <= 1


@pytest.mark.asyncio
async def test_no_confirmation_no_claim_or_remote_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "_member", lambda *_: None)
    with pytest.raises(LeadFormUnavailable):
        await service.publish_lead_form(
            tenant_id=uuid4(), form_id=uuid4(), confirmed=False, expected_revision=1
        )


@pytest.mark.asyncio
async def test_unowned_webhook_never_resolves_current_tenant_or_fetches() -> None:
    event = ClaimedEvent(
        uuid4(),
        None,
        "page",
        "200",
        "leadgen",
        {"leadgen_id": "900", "form_id": "800", "page_id": "200"},
        1,
        owners=(),
    )
    result = await leadgen_handler(event)
    assert result.status == "orphan"


@pytest.mark.asyncio
async def test_webhook_entry_page_mismatch_is_dead() -> None:
    event = ClaimedEvent(
        uuid4(),
        None,
        "page",
        "200",
        "leadgen",
        {"leadgen_id": "900", "form_id": "800", "page_id": "201"},
        1,
        owners=(),
    )
    result = await leadgen_handler(event)
    assert result.status == "dead" and result.error == "leadgen_page_mismatch"
