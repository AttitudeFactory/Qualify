"""Audience normalization and read-only wire contracts, without Meta credentials."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from qualify_api.ads import audience_service as service
from qualify_api.ads.activation_repository import ActivationReview
from qualify_api.ads.audience import (
    AudienceDraft,
    AudienceUnavailable,
    InterestOption,
    LocationOption,
    ReachEstimate,
)
from qualify_api.ads.fake import FakeMarketingClient
from qualify_api.ads.promotions import Promotion
from qualify_api.ads.wizard import PromotionSource, WizardForm, WizardUnavailable
from qualify_api.ads.wizard_workflow import VerifiedChecks, _form, _guard_checks, _request
from qualify_api.connections.ad_accounts import AdConnection


def audience(**changes):
    return replace(AudienceDraft(LocationOption("123", "Cúcuta", "city", "CO")), **changes)


@pytest.mark.parametrize(
    "location,geo",
    [
        (LocationOption("CO", "Colombia", "country", "CO"), {"countries": ["CO"]}),
        (LocationOption("12", "Norte de Santander", "region", "CO"), {"regions": [{"key": "12"}]}),
        (LocationOption("123", "Cúcuta", "city", "CO"), {"cities": [{"key": "123"}]}),
    ],
)
def test_exact_selection_roundtrip_and_compiled_geography(location, geo):
    draft = audience(
        location=location,
        interests=(InterestOption("9", "Café"),),
        placements=("instagram_story", "facebook_feed"),
    )
    assert AudienceDraft.from_snapshot(draft.snapshot()) == draft
    target = draft.targeting()
    assert target["geo_locations"] == geo
    assert target["targeting_automation"] == {"advantage_audience": 0}
    assert target["publisher_platforms"] == ["facebook", "instagram"]
    assert target["instagram_positions"] == ["story"]
    assert target["facebook_positions"] == ["feed"]
    assert target["flexible_spec"] == [{"interests": [{"id": "9"}]}]


def test_housing_allowlist_drops_all_restricted_fields_even_stale_values():
    draft = audience(
        housing=True,
        age_min=30,
        age_max=40,
        gender="women",
        interests=(InterestOption("9", "Café", "unavailable"),),
    )
    target = draft.targeting()
    assert set(target) == {"geo_locations", "targeting_automation", "publisher_platforms"}
    assert target["publisher_platforms"] == ["facebook", "instagram"]


@pytest.mark.parametrize(
    "changes",
    [
        {"age_min": True},
        {"age_max": 99},
        {"gender": []},
        {"radius_km": True},
        {"radius_km": 0},
        {"placements": (["instagram_feed"],)},
        {"placements": ("whatsapp_status",)},
        {"placements": ("instagram_feed", "instagram_feed")},
        {"housing": 1},
        {"interests": (InterestOption("9", "Café"), InterestOption("9", "Café"))},
        {"location": LocationOption(None, "City", "city", "CO")},
        {"location": LocationOption("1", "City", "city", None)},
        {"location": LocationOption("1", "City", [], "CO")},
        {"interests": (InterestOption("9", "Café", []),)},
    ],
)
def test_invalid_untrusted_primitive_is_safe_error(changes):
    with pytest.raises(AudienceUnavailable):
        audience(**changes).targeting()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"estimate_ready": False, "users_lower_bound": 10, "users_upper_bound": 20},
        {"estimate_ready": True, "users": 100},
        {"estimate_ready": True, "users_lower_bound": True, "users_upper_bound": 20},
        {"estimate_ready": True, "users_lower_bound": "10", "users_upper_bound": 20},
        {"estimate_ready": True, "users_lower_bound": -1, "users_upper_bound": 20},
        {"estimate_ready": True, "users_lower_bound": 21, "users_upper_bound": 20},
    ],
)
def test_unready_or_unknown_reach_is_not_fabricated(payload):
    estimate = ReachEstimate.from_graph(payload, "hash")
    assert not estimate.ready and estimate.lower is None and estimate.upper is None
    assert estimate.audience_hash == "hash"


def test_reach_verified_bounds_and_fingerprint_changes():
    assert ReachEstimate.from_graph(
        {"estimate_ready": True, "users_lower_bound": 0, "users_upper_bound": 20}, "hash"
    ).ready
    assert audience().fingerprint != audience(gender="women").fingerprint
    assert audience().fingerprint != audience(placements=("instagram_reels",)).fingerprint


@pytest.mark.asyncio
async def test_read_only_wire_calls_and_safe_normalized_results(monkeypatch):
    ids = {
        key: uuid4()
        for key in ("tenant_id", "content_draft_id", "publish_attempt_id", "ad_account_id")
    }
    scope = service.AudienceScope(
        **ids,
        brand_id=uuid4(),
        connection=AdConnection(
            uuid4(), uuid4(), "42", 1, "active", ("ads_management",), None, True
        ),
        meta_account_id="12",
    )
    monkeypatch.setattr(service, "_scope", lambda **kwargs: scope)
    monkeypatch.setattr(service, "_same", lambda value: None)
    api = FakeMarketingClient(account_id="12")
    api.responses[("GET", "search")] = {
        "data": [
            {"key": "123", "name": "Cúcuta", "type": "city", "country_code": "CO"},
            {"key": None},
        ]
    }
    original = service._read

    async def fake_read(target, operation, params):
        return await original(target, operation, params, api=api)

    monkeypatch.setattr(service, "_read", fake_read)
    found = await service.search_audience_locations(**ids, query="Cúc", location_type="city")
    assert found == (audience().location,)
    assert api.calls[-1][2]["location_types"] == ["city"]
    api.responses[("GET", "act_12/reachestimate")] = {
        "data": [{"estimate_ready": True, "users_lower_bound": 10, "users_upper_bound": 20}]
    }
    estimate = await service.estimate_audience(**ids, audience=audience())
    assert estimate.ready and (estimate.lower, estimate.upper) == (10, 20)
    assert api.calls[-1][2]["targeting_spec"] == audience().targeting()
    calls = len(api.calls)
    for draft in (audience(housing=True), audience(radius_km=10)):
        assert not (await service.estimate_audience(**ids, audience=draft)).ready
    assert len(api.calls) == calls
    assert all(method == "GET" for method, _, _ in api.calls)


@pytest.mark.asyncio
async def test_stale_scoped_response_rejected(monkeypatch):
    scope = service.AudienceScope(
        *(uuid4() for _ in range(5)),
        AdConnection(uuid4(), uuid4(), "42", 1, "active", (), None, True),
        "12",
    )
    api = FakeMarketingClient(account_id="12")
    api.responses[("GET", "search")] = {"data": []}
    calls = []

    def guard(value):
        calls.append(value)
        if len(calls) == 2:
            raise AudienceUnavailable("La cuenta cambió.")

    monkeypatch.setattr(service, "_same", guard)
    with pytest.raises(AudienceUnavailable, match="cambió"):
        await service._read(scope, "search", {"type": "adinterest", "q": "café"}, api=api)


def test_no_acting_user_rejected_before_database():
    with pytest.raises(AudienceUnavailable, match="entrar"):
        service.load_audience(
            **{
                key: uuid4()
                for key in ("tenant_id", "content_draft_id", "publish_attempt_id", "ad_account_id")
            }
        )


def test_load_rechecks_scope_after_read(monkeypatch):
    ids = {
        key: uuid4()
        for key in ("tenant_id", "content_draft_id", "publish_attempt_id", "ad_account_id")
    }
    scope = service.AudienceScope(
        **ids,
        brand_id=uuid4(),
        connection=AdConnection(uuid4(), uuid4(), "42", 1, "active", (), None, True),
        meta_account_id="12",
    )
    monkeypatch.setattr(service, "_scope", lambda **kwargs: scope)

    @contextmanager
    def session(_tenant):
        yield SimpleNamespace(
            execute=lambda *args: SimpleNamespace(
                first=lambda: SimpleNamespace(audience=audience().snapshot(), version=1)
            )
        )

    monkeypatch.setattr(service, "tenant_session", session)

    def changed(_scope):
        raise AudienceUnavailable("La cuenta cambió.")

    monkeypatch.setattr(service, "_same", changed)
    with pytest.raises(AudienceUnavailable, match="cambió"):
        service.load_audience(**ids)


@pytest.mark.asyncio
async def test_interest_validity_uses_exact_bool_keyed_by_id(monkeypatch):
    async def read(scope, operation, params):
        assert operation == "validate" and params == {"ids": ["1", "2", "3", "4"]}
        return (
            {"id": "1", "valid": True},
            {"id": "2", "valid": False},
            {"id": "3", "valid": "true"},
            {"id": "4", "is_valid": True},
        )

    monkeypatch.setattr(service, "_read", read)
    options = tuple(InterestOption(str(i), "Name") for i in range(1, 5))
    actual = await service._interest_status(None, options)
    assert [i.status for i in actual] == ["active", "unavailable", "unknown", "unknown"]


def test_immutable_promotion_targeting_and_selection_restore_and_policy_gate():
    now = datetime.now(UTC)
    source = PromotionSource(
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        "42",
        "777",
        "caption",
        "IG",
        meta_ad_account_id="12",
        currency="COP",
    )
    selected = audience(location=LocationOption("CO", "Colombia", "country", "CO"), housing=True)
    form = WizardForm(
        "https://example.org",
        "Colombia",
        now + timedelta(days=1),
        now + timedelta(days=2),
        housing=True,
        budget_minor=10000,
        audience=selected,
    )
    request = _request(uuid4(), source, form, uuid4(), str(uuid4()), now)
    snapshot = request.snapshot()
    assert snapshot["targeting"] == selected.targeting()
    assert not {"age_min", "age_max", "genders", "exclusions"} & snapshot["targeting"].keys()
    review = ActivationReview(
        uuid4(),
        request.tenant_id,
        uuid4(),
        "hash",
        "preview",
        "hash",
        {"city_name": "Colombia"},
        now + timedelta(minutes=1),
        request.approved_by,
    )
    restored = _form(Promotion(review.promotion_id, snapshot), review)
    assert restored.audience == selected
    checks = VerifiedChecks(
        100, True, True, True, "", now + timedelta(minutes=1), housing_targeting_verified=True
    )
    with pytest.raises(WizardUnavailable, match="reglas"):
        _guard_checks(source, form, checks, now)
    _guard_checks(
        source,
        form,
        replace(checks, audience_policy_verified=True, audience_fingerprint=selected.fingerprint),
        now,
    )
    with pytest.raises(ValueError, match="differs"):
        replace(request, targeting={}).snapshot()
