"""Unit tests for the leads service: phone normalization, the wa.me handoff, the
memory repository's upsert-merge semantics, and the order of guards in `submit`."""

from __future__ import annotations

from uuid import uuid4

import pytest

from qualify_api.leads.rate_limit import AllowAllLimiter
from qualify_api.leads.repository import (
    FormSettingsRow,
    MemoryLeadRepository,
    normalize_phone,
)
from qualify_api.leads.service import (
    FormNotFound,
    LeadIntakeService,
    LeadSubmission,
    RateLimited,
    build_whatsapp_url,
)

TENANT = uuid4()

SETTINGS = FormSettingsRow(
    business_name="Arepas La Nona",
    whatsapp_phone="+573001112233",
    whatsapp_greeting=None,
    promo_text="2x1 los viernes",
    interest_options=["arepas", "jugos"],
    consent_text="Autorizo el tratamiento de mis datos.",
    consent_policy_version="v1-2026-08",
    custom_fields=[{"key": "zona", "label": "Zona"}],
)


class DenyAllLimiter:
    def allow(self, key: str) -> bool:
        return False


def make_service(
    repo: MemoryLeadRepository | None = None, *, limiter=None
) -> tuple[LeadIntakeService, MemoryLeadRepository]:
    repo = repo or MemoryLeadRepository()
    return LeadIntakeService(repository=repo, limiter=limiter or AllowAllLimiter()), repo


def test_normalize_phone_collapses_punctuation() -> None:
    assert normalize_phone("+57 300-111 (22)33") == "+573001112233"


@pytest.mark.parametrize("raw", ["573001112233", "+57abc", "+1", "++57300111223344556677"])
def test_normalize_phone_rejects_non_e164(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_phone(raw)


def test_whatsapp_url_default_greeting_encodes_and_strips_plus() -> None:
    url = build_whatsapp_url(SETTINGS, lead_name="Ana María")
    assert url.startswith("https://wa.me/573001112233?text=")
    assert "Ana%20Mar%C3%ADa" in url
    assert "2x1%20los%20viernes" in url


def test_whatsapp_url_custom_template_survives_stray_braces() -> None:
    settings = FormSettingsRow(
        business_name=SETTINGS.business_name,
        whatsapp_phone=SETTINGS.whatsapp_phone,
        whatsapp_greeting="Hola {name} {esto no es placeholder}",
        promo_text=None,
        interest_options=[],
        consent_text="Acepto.",
        consent_policy_version="v1",
    )
    url = build_whatsapp_url(settings, lead_name="Luis")
    # `.replace`, not `.format`: the tenant-authored brace must not raise.
    assert "Luis" in url
    assert "%7Besto%20no%20es%20placeholder%7D" in url


def test_submit_unknown_tenant_is_form_not_found() -> None:
    service, _ = make_service()
    with pytest.raises(FormNotFound):
        service.submit(
            tenant_id=TENANT,
            submission=LeadSubmission(full_name="Ana", whatsapp_phone="+573001112233"),
            client_key="ip",
        )


def test_rate_limit_fires_before_any_repository_read() -> None:
    class ExplodingRepo:
        def get_active_settings(self, *, tenant_id):
            raise AssertionError("repository touched after rate limit")

        def upsert_lead(self, *, tenant_id, record):
            raise AssertionError("repository touched after rate limit")

    service = LeadIntakeService(repository=ExplodingRepo(), limiter=DenyAllLimiter())
    with pytest.raises(RateLimited):
        service.submit(
            tenant_id=TENANT,
            submission=LeadSubmission(full_name="Ana", whatsapp_phone="+573001112233"),
            client_key="ip",
        )


def test_submit_stamps_consent_from_active_settings() -> None:
    service, repo = make_service()
    repo.settings[TENANT] = SETTINGS
    accepted = service.submit(
        tenant_id=TENANT,
        submission=LeadSubmission(full_name=" Ana ", whatsapp_phone="+57 300 111 2233"),
        client_key="ip",
    )
    ((_, record),) = repo.leads.values()
    assert record.full_name == "Ana"  # trimmed
    assert record.whatsapp_phone == "+573001112233"  # normalized
    assert record.consent_policy_version == "v1-2026-08"
    assert record.consent_at.tzinfo is not None
    assert accepted.promo_text == "2x1 los viernes"


def test_extra_keeps_declared_keys_and_drops_the_rest() -> None:
    service, repo = make_service()
    repo.settings[TENANT] = SETTINGS
    service.submit(
        tenant_id=TENANT,
        submission=LeadSubmission(
            full_name="Ana",
            whatsapp_phone="+573001112233",
            extra={"zona": " oeste ", "hackfield": "x", "vacia": "  "},
        ),
        client_key="ip",
    )
    ((_, record),) = repo.leads.values()
    # Declared key kept (trimmed); undeclared and blank ones never reach storage.
    assert record.extra == {"zona": "oeste"}


def test_memory_upsert_merges_optionals_and_keeps_id() -> None:
    service, repo = make_service()
    repo.settings[TENANT] = SETTINGS
    first = service.submit(
        tenant_id=TENANT,
        submission=LeadSubmission(
            full_name="Ana",
            whatsapp_phone="+573001112233",
            email="ana@x.co",
            extra={"zona": "oeste"},
        ),
        client_key="ip",
    )
    second = service.submit(
        tenant_id=TENANT,
        submission=LeadSubmission(
            full_name="Ana María", whatsapp_phone="+573001112233", interest="arepas"
        ),
        client_key="ip",
    )
    assert first.lead_id == second.lead_id
    ((_, record),) = repo.leads.values()
    assert record.full_name == "Ana María"  # identity fields overwrite
    assert record.email == "ana@x.co"  # omitted optional survives
    assert record.interest == "arepas"  # new optional lands
    assert record.extra == {"zona": "oeste"}  # earlier custom answers survive too
