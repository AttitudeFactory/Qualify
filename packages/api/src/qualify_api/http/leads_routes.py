"""Public HTTP surface for lead capture — the first anonymous-POST surface in the app.

No `Principal` here, deliberately (the exception that proves C1): this surface serves
strangers filling a form, and `?e=<tenant_id>` is never believed as authorization — the
service only uses it to scope an RLS session, so an unknown tenant, a wrong tenant and
an inactive form all collapse into the same 404. One 404 for every miss, one 403-style
opacity rule as the callback: telling a scraper WHICH uuids have live forms is a free
tenant-enumeration oracle.

Defense here is layered and cheap: `consent: Literal[True]` (a lead without consent is
unrepresentable at the type level, matching the NOT NULL in migration 0005), a honeypot
field bots fill and humans never see, and the service-side rate limit per (tenant, ip).
"""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from qualify_api.leads.service import (
    FormNotFound,
    LeadIntakeService,
    LeadSubmission,
    RateLimited,
)

router = APIRouter(prefix="/api/leads", tags=["leads"])


def get_leads_service() -> LeadIntakeService:
    """Overridden in tests and wired at app startup — same seam as `get_connect_service`."""
    raise NotImplementedError("leads service dependency is not configured")


def _client_key(request: Request) -> str:
    """Rate-limit key. First X-Forwarded-For hop when present (the deployment target is
    behind a reverse proxy), else the socket peer. A spoofed XFF only lets an attacker
    throttle a bucket of their own invention — never widen someone else's."""
    forwarded = request.headers.get("x-forwarded-for", "")
    first_hop = forwarded.split(",")[0].strip()
    return first_hop or (request.client.host if request.client else "unknown")


class CustomFieldSpec(BaseModel):
    key: str
    label: str
    options: list[str] | None = None
    required: bool = False


class PublicFormResponse(BaseModel):
    business_name: str
    promo_text: str | None
    interest_options: list[str]
    consent_text: str
    consent_policy_version: str
    custom_fields: list[CustomFieldSpec]


class LeadIntakeRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    whatsapp_phone: str = Field(min_length=8, max_length=32)
    # Not `bool`: a request that says consent=false must fail VALIDATION, not reach the
    # service and be judged there. The type is the policy.
    consent: Literal[True]
    email: str | None = Field(default=None, max_length=254, pattern=r".+@.+\..+")
    birthday: date | None = None
    interest: str | None = Field(default=None, max_length=120)
    source_declared: str | None = Field(default=None, max_length=120)
    utm_source: str | None = Field(default=None, max_length=200)
    utm_medium: str | None = Field(default=None, max_length=200)
    utm_campaign: str | None = Field(default=None, max_length=200)
    utm_content: str | None = Field(default=None, max_length=200)
    utm_term: str | None = Field(default=None, max_length=200)
    # Answers to the tenant's custom fields; the service drops undeclared keys.
    extra: dict[str, str] = Field(default_factory=dict)
    # Honeypot. Rendered hidden by the form; a human never fills it.
    website: str = ""

    @field_validator("extra")
    @classmethod
    def _bound_extra(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 20 or any(len(k) > 60 or len(v) > 500 for k, v in value.items()):
            raise ValueError("extra: at most 20 entries, keys <= 60 chars, values <= 500")
        return value


class IntakeResponse(BaseModel):
    lead_id: UUID
    promo_text: str | None
    whatsapp_url: str | None


@router.get("/form", response_model=PublicFormResponse)
def public_form(
    e: UUID = Query(...),
    service: LeadIntakeService = Depends(get_leads_service),
) -> PublicFormResponse:
    try:
        form = service.public_form(tenant_id=e)
    except FormNotFound:
        raise HTTPException(status_code=404, detail="no such form") from None
    return PublicFormResponse(
        business_name=form.business_name,
        promo_text=form.promo_text,
        interest_options=form.interest_options,
        consent_text=form.consent_text,
        consent_policy_version=form.consent_policy_version,
        custom_fields=[CustomFieldSpec(**spec) for spec in form.custom_fields],
    )


@router.post("/intake", response_model=IntakeResponse, status_code=201)
def intake(
    body: LeadIntakeRequest,
    request: Request,
    e: UUID = Query(...),
    service: LeadIntakeService = Depends(get_leads_service),
) -> IntakeResponse:
    if body.website:
        # Bot tripped the honeypot: answer a plausible success and write nothing.
        # A 4xx would tell the bot author which field to stop filling.
        return IntakeResponse(lead_id=uuid4(), promo_text=None, whatsapp_url=None)
    try:
        accepted = service.submit(
            tenant_id=e,
            submission=LeadSubmission(
                full_name=body.full_name,
                whatsapp_phone=body.whatsapp_phone,
                email=body.email,
                birthday=body.birthday,
                interest=body.interest,
                source_declared=body.source_declared,
                utm_source=body.utm_source,
                utm_medium=body.utm_medium,
                utm_campaign=body.utm_campaign,
                utm_content=body.utm_content,
                utm_term=body.utm_term,
                extra=body.extra,
            ),
            client_key=_client_key(request),
        )
    except RateLimited:
        raise HTTPException(status_code=429, detail="too many requests") from None
    except FormNotFound:
        raise HTTPException(status_code=404, detail="no such form") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return IntakeResponse(
        lead_id=accepted.lead_id,
        promo_text=accepted.promo_text,
        whatsapp_url=accepted.whatsapp_url,
    )
