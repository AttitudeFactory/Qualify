"""MARCA-5 (m-24842968): the house tenant's interest form — the service guards and the
public `POST /api/leads/interest`, with zero network and zero DB."""

from __future__ import annotations

import logging
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from qualify_api.http import leads_routes
from qualify_api.http.app import create_app
from qualify_api.leads.interest import (
    BUSINESS_KEY,
    INTEREST_CONSENT_VERSION,
    INTEREST_TENANT_ENV,
    AccessInterestService,
    InterestInvalid,
    InterestNotConfigured,
    InterestRateLimited,
    InterestRequest,
    interest_tenant_id,
    normalize_interest_phone,
)
from qualify_api.leads.rate_limit import AllowAllLimiter, InProcessFixedWindowLimiter
from qualify_api.leads.repository import MemoryLeadRepository

HOUSE = UUID("22222222-2222-4222-8222-222222222222")
PHONE = "+58 414 123 4567"

VALID = InterestRequest(
    full_name="  Ana   Pérez ",
    business_name="Heladería La Esquina",
    whatsapp_phone=PHONE,
    consent=True,
)


class DenyAllLimiter:
    def allow(self, key: str) -> bool:
        return False


def _service(*, limiter=None, tenant: UUID | None = HOUSE):
    repo = MemoryLeadRepository()
    service = AccessInterestService(
        repository=repo, limiter=limiter or AllowAllLimiter(), tenant_id=lambda: tenant
    )
    return service, repo


# ---- the setting ------------------------------------------------------------------


def test_the_house_tenant_comes_from_the_setting() -> None:
    assert interest_tenant_id({INTEREST_TENANT_ENV: str(HOUSE)}) == HOUSE
    assert interest_tenant_id({INTEREST_TENANT_ENV: f"  {HOUSE}\n"}) == HOUSE


@pytest.mark.parametrize("value", ["", "   ", "not-a-uuid"])
def test_an_unset_or_bad_setting_is_none_never_a_guess(value: str) -> None:
    assert interest_tenant_id({INTEREST_TENANT_ENV: value}) is None
    assert interest_tenant_id({}) is None


# ---- the phone --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("+58 414 123 4567", "+584141234567"),
        ("0058 414-123-4567", "+584141234567"),
        ("58 414 123 4567", "+584141234567"),
        ("57 300 111 2233", "+573001112233"),
        ("598 94 123 456", "+59894123456"),
        ("(+57) 300.111.2233", "+573001112233"),
    ],
)
def test_the_whatsapp_is_read_the_way_owners_type_it(typed: str, expected: str) -> None:
    assert normalize_interest_phone(typed) == expected


@pytest.mark.parametrize("typed", ["0414 123 4567", "300 111 2233", "abc", ""])
def test_a_number_without_its_country_is_refused_not_guessed(typed: str) -> None:
    with pytest.raises(ValueError):
        normalize_interest_phone(typed)


# ---- the service ------------------------------------------------------------------


def test_a_consented_entry_lands_in_the_house_tenant_leads() -> None:
    service, repo = _service()
    assert service.submit(VALID, client_key="1.2.3.4").saved is True
    ((tenant, phone), (_, record)) = next(iter(repo.leads.items()))
    assert (tenant, phone) == (HOUSE, "+584141234567")
    assert record.full_name == "Ana Pérez"
    assert record.extra == {BUSINESS_KEY: "Heladería La Esquina"}
    assert record.consent_policy_version == INTEREST_CONSENT_VERSION
    assert record.consent_at is not None
    assert record.source_declared


def test_without_consent_nothing_is_stored() -> None:
    service, repo = _service()
    with pytest.raises(InterestInvalid) as excinfo:
        service.submit(InterestRequest("Ana", "La Esquina", PHONE, consent=False), client_key="k")
    assert excinfo.value.field == "consent"
    assert repo.leads == {}


def test_the_honeypot_answers_success_and_writes_nothing() -> None:
    service, repo = _service()
    bot = InterestRequest("Ana", "La Esquina", PHONE, consent=True, honeypot="http://x")
    assert service.submit(bot, client_key="k").saved is False
    assert repo.leads == {}


def test_over_the_limit_is_refused_before_anything_else() -> None:
    service, repo = _service(limiter=DenyAllLimiter())
    with pytest.raises(InterestRateLimited):
        service.submit(VALID, client_key="k")
    assert repo.leads == {}


def test_an_unset_house_tenant_stores_nothing() -> None:
    service, repo = _service(tenant=None)
    with pytest.raises(InterestNotConfigured):
        service.submit(VALID, client_key="k")
    assert repo.leads == {}


@pytest.mark.parametrize(
    ("request_", "field"),
    [
        (InterestRequest("  ", "La Esquina", PHONE, consent=True), "full_name"),
        (InterestRequest("Ana", "", PHONE, consent=True), "business_name"),
        (InterestRequest("Ana", "x" * 121, PHONE, consent=True), "business_name"),
        (InterestRequest("Ana", "La Esquina", "0414 123 4567", consent=True), "whatsapp_phone"),
    ],
)
def test_each_missing_field_is_named(request_: InterestRequest, field: str) -> None:
    service, repo = _service()
    with pytest.raises(InterestInvalid) as excinfo:
        service.submit(request_, client_key="k")
    assert excinfo.value.field == field
    assert repo.leads == {}


def test_the_number_never_reaches_the_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    service, _ = _service()
    service.submit(VALID, client_key="k")
    bad, _ = _service()
    with pytest.raises(InterestInvalid) as excinfo:
        bad.submit(InterestRequest("Ana", "La Esquina", "0414 123 4567", True), client_key="k")
    assert "4567" not in caplog.text
    assert "4567" not in str(excinfo.value)


def test_the_in_process_window_resets_after_its_time() -> None:
    now = [0.0]
    limiter = InProcessFixedWindowLimiter(limit=2, window_seconds=60, clock=lambda: now[0])
    assert limiter.allow("a") and limiter.allow("a")
    assert not limiter.allow("a")
    assert limiter.allow("b")  # buckets are per key
    now[0] = 61.0
    assert limiter.allow("a")


# ---- the public route -------------------------------------------------------------


BODY = {
    "full_name": "Ana Pérez",
    "business_name": "Heladería La Esquina",
    "whatsapp_phone": PHONE,
    "consent": True,
}


def _client(*, limiter=None, tenant: UUID | None = HOUSE):
    service, repo = _service(limiter=limiter, tenant=tenant)
    app = create_app(configure_production=False)
    app.dependency_overrides[leads_routes.get_interest_service] = lambda: service
    return TestClient(app), repo


def test_the_route_stores_one_entry() -> None:
    client, repo = _client()
    response = client.post("/api/leads/interest", json=BODY)
    assert response.status_code == 201
    assert len(repo.leads) == 1


def test_the_route_rejects_a_missing_or_false_consent() -> None:
    client, repo = _client()
    no_consent = {k: v for k, v in BODY.items() if k != "consent"}
    assert client.post("/api/leads/interest", json=no_consent).status_code == 422
    assert client.post("/api/leads/interest", json={**BODY, "consent": False}).status_code == 422
    assert repo.leads == {}


def test_the_route_honeypot_looks_like_success() -> None:
    client, repo = _client()
    response = client.post("/api/leads/interest", json={**BODY, "website": "spam"})
    assert response.status_code == 201
    assert repo.leads == {}


def test_the_route_rate_limits() -> None:
    client, repo = _client(limiter=DenyAllLimiter())
    assert client.post("/api/leads/interest", json=BODY).status_code == 429
    assert repo.leads == {}


def test_the_route_never_echoes_the_number() -> None:
    client, _ = _client()
    response = client.post("/api/leads/interest", json={**BODY, "whatsapp_phone": "0414 123 4567"})
    assert response.status_code == 422
    assert "4567" not in response.text


def test_the_route_without_the_setting_is_503_and_stores_nothing() -> None:
    client, repo = _client(tenant=None)
    assert client.post("/api/leads/interest", json=BODY).status_code == 503
    assert repo.leads == {}


def test_the_tenant_is_never_taken_from_the_request() -> None:
    client, repo = _client()
    other = "33333333-3333-4333-8333-333333333333"
    client.post(f"/api/leads/interest?e={other}", json={**BODY, "tenant_id": other})
    assert {tenant for tenant, _ in repo.leads} == {HOUSE}
