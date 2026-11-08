"""`db`-marked (m-24973636): what /brand reads for an Alta account, against the test
Postgres — the state measured in production (claimed draft, Instagram proposal
`proposed`, nothing typed by the owner) opens the review card, and an Alta whose account
is still being read opens «todavía se está preparando», each only for its own tenant."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from qualify_api.auth import start_brand_kit_draft
from qualify_api.creative.brand_kit_store import PREFILL_KEY, BrandKitStore
from qualify_api.creative.brand_prefill_review import Notice
from qualify_api.meegle.prefill_jobs import NewPrefillJob, PostgresPrefillJobs

from .brand_minimal import _read_entry
from .connections_provider import acting_user_id
from .creative_provider import default_brand_id

pytestmark = pytest.mark.db


def _draft() -> tuple[UUID, UUID, UUID]:
    email = f"hlrd1993+skeleton-{uuid4().hex[:8]}@gmail.com"
    tenant = start_brand_kit_draft(
        email, country="VE", timezone="America/Caracas", currency="USD"
    ).tenant_id
    brand, user = default_brand_id(tenant), acting_user_id(tenant)
    assert brand is not None and user is not None
    return tenant, brand, user


def _proposed() -> dict:
    """`connect` as the Alta left it in production: the proposal and the contact the
    profile gave, nothing the owner typed."""
    return {
        "contact": {"whatsapp": "584220000000"},
        PREFILL_KEY: {
            "status": "ok",
            "state": "proposed",
            "network": "instagram",
            "username": "barprueba",
            "version": 4,
            "proposal": {
                "connect": {
                    "network": "instagram",
                    "username": "barprueba",
                    "rubro_text": "jugos naturales",
                    "sector": "food_drink",
                    "hashtags": [],
                    "city": "",
                    "country_code": "",
                },
                "palette": {"palette": "#ffd920,#71248c", "logo_colors": ["#ffd920", "#71248c"]},
                "profile": {"username": "barprueba", "fullname": "Bar Prueba", "metrics": []},
            },
        },
    }


def _job(ids: tuple[UUID, UUID, UUID]) -> None:
    assert PostgresPrefillJobs().enqueue(
        NewPrefillJob(
            tenant_id=ids[0],
            brand_id=ids[1],
            meegle_work_item_id=int(uuid4().int % 10**9),
            network="instagram",
            handle="barprueba",
            max_usd=Decimal("0.15"),
            pipeline_version="test",
        )
    )


def test_the_production_state_opens_the_review_card() -> None:
    ids = _draft()
    BrandKitStore().save_details(
        tenant_id=ids[0], brand_id=ids[1], user_id=ids[2], documents={"connect": _proposed()}
    )
    entry = _read_entry(ids[0])
    assert entry is not None and not entry.finished
    assert entry.review.pending and entry.review.notice is Notice.PROPOSAL
    assert entry.preparing_network is None


def test_an_alta_still_reading_says_so_only_to_its_own_tenant() -> None:
    owner, other = _draft(), _draft()
    _job(owner)
    now = datetime.now(UTC)
    jobs = PostgresPrefillJobs()
    assert jobs.waiting_network(owner[0], now=now) == "instagram"
    assert jobs.waiting_network(other[0], now=now) is None
    # a job older than the wait no longer holds the page
    assert jobs.waiting_network(owner[0], now=now + timedelta(hours=1)) is None

    entry = _read_entry(owner[0])
    assert entry is not None and entry.preparing_network == "instagram"
    assert not entry.review.pending
    theirs = _read_entry(other[0])
    assert theirs is not None and theirs.preparing_network is None


def test_an_owner_who_already_started_is_never_held() -> None:
    ids = _draft()
    _job(ids)
    BrandKitStore().save_details(
        tenant_id=ids[0],
        brand_id=ids[1],
        user_id=ids[2],
        documents={"connect": {"rubro_text": "Heladería"}},
    )
    entry = _read_entry(ids[0])
    assert entry is not None and entry.preparing_network is None
