"""The public leads routes, end-to-end with zero network and zero DB — everything
below the routes is real code (service, memory repository, limiter doubles)."""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from qualify_api.http import leads_routes
from qualify_api.http.app import create_app
from qualify_api.leads.rate_limit import AllowAllLimiter
from qualify_api.leads.repository import FormSettingsRow, MemoryLeadRepository
from qualify_api.leads.service import LeadIntakeService

TENANT = UUID("11111111-1111-4111-8111-111111111111")

SETTINGS = FormSettingsRow(
    business_name="Arepas La Nona",
    whatsapp_phone="+573001112233",
    whatsapp_greeting=None,
    promo_text="2x1 los viernes",
    interest_options=["arepas", "jugos"],
    consent_text="Autorizo el tratamiento de mis datos.",
    consent_policy_version="v1-2026-08",
    custom_fields=[{"key": "zona", "label": "Zona", "options": ["norte", "oeste"]}],
)

VALID_BODY = {
    "full_name": "Ana María",
    "whatsapp_phone": "+57 300 111 2233",
    "consent": True,
    "source_declared": "instagram",
    "utm_source": "ig",
    "utm_campaign": "promo-viernes",
}


class DenyAllLimiter:
    def allow(self, key: str) -> bool:
        return False


def make_client(*, limiter=None, provision: bool = True) -> tuple[TestClient, MemoryLeadRepository]:
    repo = MemoryLeadRepository()
    if provision:
        repo.settings[TENANT] = SETTINGS
    service = LeadIntakeService(repository=repo, limiter=limiter or AllowAllLimiter())
    app = create_app(configure_production=False)
    app.dependency_overrides[leads_routes.get_leads_service] = lambda: service
    return TestClient(app), repo


def test_form_renders_public_config() -> None:
    client, _ = make_client()
    response = client.get(f"/api/leads/form?e={TENANT}")
    assert response.status_code == 200
    assert response.json() == {
        "business_name": "Arepas La Nona",
        "promo_text": "2x1 los viernes",
        "interest_options": ["arepas", "jugos"],
        "consent_text": "Autorizo el tratamiento de mis datos.",
        "consent_policy_version": "v1-2026-08",
        "custom_fields": [
            {"key": "zona", "label": "Zona", "options": ["norte", "oeste"], "required": False}
        ],
    }


def test_form_unknown_tenant_is_one_opaque_404() -> None:
    client, _ = make_client()
    response = client.get(f"/api/leads/form?e={uuid4()}")
    assert response.status_code == 404
    assert response.json()["detail"] == "no such form"


def test_form_rejects_non_uuid_param() -> None:
    client, _ = make_client()
    assert client.get("/api/leads/form?e=arepas").status_code == 422


def test_intake_writes_lead_and_returns_handoff() -> None:
    client, repo = make_client()
    response = client.post(f"/api/leads/intake?e={TENANT}", json=VALID_BODY)
    assert response.status_code == 201
    body = response.json()
    assert body["promo_text"] == "2x1 los viernes"
    assert body["whatsapp_url"].startswith("https://wa.me/573001112233?text=")
    ((_, record),) = repo.leads.values()
    assert record.whatsapp_phone == "+573001112233"
    assert record.utm_campaign == "promo-viernes"
    assert record.source_declared == "instagram"


def test_intake_stores_declared_extra_and_drops_undeclared() -> None:
    client, repo = make_client()
    response = client.post(
        f"/api/leads/intake?e={TENANT}",
        json={**VALID_BODY, "extra": {"zona": "oeste", "inventado": "x"}},
    )
    assert response.status_code == 201
    ((_, record),) = repo.leads.values()
    assert record.extra == {"zona": "oeste"}


def test_intake_oversized_extra_fails_validation() -> None:
    client, repo = make_client()
    response = client.post(
        f"/api/leads/intake?e={TENANT}", json={**VALID_BODY, "extra": {"zona": "x" * 501}}
    )
    assert response.status_code == 422
    assert not repo.leads


def test_intake_without_consent_fails_validation() -> None:
    client, repo = make_client()
    response = client.post(f"/api/leads/intake?e={TENANT}", json={**VALID_BODY, "consent": False})
    assert response.status_code == 422  # Literal[True]: the type is the policy
    assert not repo.leads


def test_intake_unknown_tenant_is_same_404_as_form() -> None:
    client, _ = make_client()
    response = client.post(f"/api/leads/intake?e={uuid4()}", json=VALID_BODY)
    assert response.status_code == 404
    assert response.json()["detail"] == "no such form"


def test_intake_bad_phone_is_422() -> None:
    client, repo = make_client()
    response = client.post(
        f"/api/leads/intake?e={TENANT}", json={**VALID_BODY, "whatsapp_phone": "3001112233"}
    )
    assert response.status_code == 422
    assert not repo.leads


def test_intake_rate_limited_is_429() -> None:
    client, repo = make_client(limiter=DenyAllLimiter())
    response = client.post(f"/api/leads/intake?e={TENANT}", json=VALID_BODY)
    assert response.status_code == 429
    assert not repo.leads


def test_honeypot_answers_plausible_success_and_writes_nothing() -> None:
    client, repo = make_client()
    response = client.post(
        f"/api/leads/intake?e={TENANT}", json={**VALID_BODY, "website": "https://spam.example"}
    )
    # Indistinguishable from success on the surface: 201 with the same shape.
    assert response.status_code == 201
    assert response.json()["whatsapp_url"] is None
    assert not repo.leads


def test_routes_are_public_no_principal_required() -> None:
    # create_app(configure_production=False) never wires the dev principal resolver, so
    # if these routes depended on `current_principal` they would 500 — passing without
    # an Authorization header IS the assertion.
    client, _ = make_client()
    assert client.get(f"/api/leads/form?e={TENANT}").status_code == 200
