"""Audience normalization and read-only wire contracts, without Meta credentials."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from qualify_api.ads import audience_service as service
from qualify_api.ads import client as client_module
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
    found = await service.search_audience_locations(**ids, query="Cúc", location_types=("city",))
    assert found == (audience().location,)
    assert api.calls[-1][2]["location_types"] == ["city"]
    # «En una ciudad o región»: one Meta call for both kinds, each row keeps its own type.
    api.responses[("GET", "search")] = {
        "data": [
            {"key": "456", "name": "Táchira", "type": "region", "country_code": "VE"},
            {"key": "123", "name": "Cúcuta", "type": "city", "country_code": "CO"},
            {"key": "456", "name": "Táchira city", "type": "city", "country_code": "VE"},
            {"key": "CO", "name": "Colombia", "type": "country", "country_code": "CO"},
        ]
    }
    calls = len(api.calls)
    found = await service.search_audience_locations(
        **ids, query="ta", location_types=("city", "region")
    )
    assert len(api.calls) == calls + 1
    assert api.calls[-1][2]["type"] == "adgeolocation"
    assert api.calls[-1][2]["location_types"] == ["city", "region"]
    assert api.calls[-1][2]["limit"] == 50  # the page is shared by both kinds
    # On the wire: GET search?type=adgeolocation&location_types=["city","region"]
    assert client_module._encode(api.calls[-1][2])["location_types"] == '["city","region"]'
    # Deduped by (type, key): the same key as a city and a region are two places.
    assert [(row.key, row.type) for row in found] == [
        ("456", "region"),
        ("123", "city"),
        ("456", "city"),
    ]
    with pytest.raises(AudienceUnavailable):
        await service.search_audience_locations(**ids, query="ta", location_types=())
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
    ids = ["1", "2", "3", "4", "5", "6", "7"]

    async def read(scope, operation, params):
        if operation == "validate":
            assert params == {"ids": ids}
            return (
                {"id": "1", "valid": True},
                {"id": "2", "valid": False},
                {"id": "3", "valid": "true"},
                {"id": "4", "is_valid": True},
                {"id": "5", "valid": True},
                {"id": "6", "valid": True},
                {"id": "7", "valid": True},
            )
        assert operation == "search"
        assert params == {"type": "targetingoptionstatus", "targeting_option_list": ids}
        return (
            {"id": "1", "current_status": "NORMAL"},
            {"id": "2", "current_status": "NORMAL"},
            {"id": "3", "current_status": "NORMAL"},
            {"id": "5", "current_status": "DEPRECATING"},
            {"id": "6", "current_status": "NON-DELIVERABLE"},
            {"id": "7", "current_status": "UNKNOWN"},
        )

    shared = use_shared_api(monkeypatch)
    monkeypatch.setattr(service, "_read", lambda *a, api: (shared.append(api), read(*a))[1])
    options = tuple(InterestOption(i, "Name") for i in ids)
    actual = await service._interest_status(None, options)
    assert [i.status for i in actual] == [
        "active",
        "unavailable",
        "unknown",
        "unknown",
        "retiring",
        "unavailable",
        "unknown",
    ]
    assert shared == ["opened", "api", "api", "closed"]  # one client for both reads


def use_shared_api(monkeypatch):
    from contextlib import asynccontextmanager

    events = []

    @asynccontextmanager
    async def api(scope):
        events.append("opened")
        yield "api"
        events.append("closed")

    monkeypatch.setattr(service, "_api", api)
    return events


@pytest.mark.asyncio
async def test_status_read_failure_keeps_the_validation_answer(monkeypatch):
    async def read(scope, operation, params, *, api):
        if operation == "search":
            raise AudienceUnavailable("No pudimos consultar el público en Meta.")
        return ({"id": "1", "valid": True}, {"id": "2", "valid": False})

    use_shared_api(monkeypatch)
    monkeypatch.setattr(service, "_read", read)
    options = (InterestOption("1", "Café"), InterestOption("2", "Té"))
    actual = await service._interest_status(None, options)
    # valid=false stays "unavailable"; valid=true without a NORMAL status is not "active".
    assert [i.status for i in actual] == ["unknown", "unavailable"]


@pytest.mark.asyncio
async def test_validation_read_failure_is_not_evidence(monkeypatch):
    async def read(scope, operation, params, *, api):
        raise AudienceUnavailable("No pudimos consultar el público en Meta.")

    use_shared_api(monkeypatch)
    monkeypatch.setattr(service, "_read", read)
    monkeypatch.setattr(service, "_same", lambda scope: None)
    options = (InterestOption("1", "Café", "active"),)
    assert await service._interest_status(None, options) == options


@pytest.mark.asyncio
async def test_interest_search_wire_is_meta_targeting_search_with_spanish_errors(monkeypatch):
    from qualify_api.ads.errors import MarketingError

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
    monkeypatch.setattr(service, "_same", lambda value: None)
    from contextlib import asynccontextmanager

    api = FakeMarketingClient(account_id="12")

    @asynccontextmanager
    async def shared(target):
        yield api

    monkeypatch.setattr(service, "_api", shared)
    api.responses[("GET", "search")] = {
        "data": [
            {"id": "6003", "name": "Café", "path": ["Interests"]},
            {"id": "café libre", "name": "Texto"},  # not a Meta id: dropped
            {"id": "6004", "name": "Té", "current_status": "DEPRECATING"},
        ]
    }
    api.responses[("GET", "act_12/targetingvalidation")] = {
        "data": [{"id": "6003", "valid": True}, {"id": "6004", "valid": True}]
    }
    found = await service.search_audience_interests(**ids, query="café")
    # The fake answers every search with the same rows: 6004's DEPRECATING comes from the
    # status read, 6003 has no NORMAL there, so it stays unknown rather than active.
    assert [(i.id, i.status) for i in found] == [("6003", "unknown"), ("6004", "retiring")]
    assert api.calls[0][2] == {"type": "adinterest", "q": "café", "limit": 25}
    assert api.calls[2][2]["type"] == "targetingoptionstatus"
    api.failures.append(MarketingError("secret provider body"))
    with pytest.raises(AudienceUnavailable, match="No pudimos consultar el público"):
        await service.search_audience_interests(**ids, query="café")
    with pytest.raises(AudienceUnavailable, match="entre dos y cien"):
        await service.search_audience_interests(**ids, query="c")
    retired = audience(interests=(found[1],))
    with pytest.raises(AudienceUnavailable, match="ya no permite"):
        retired.targeting()


POINT = {"latitude": 7.893907, "longitude": -72.507821, "name": "Calle 10 # 5-20, Cúcuta"}


def pointed(**changes):
    from qualify_api.ads.audience import MapPoint

    return audience(
        **{
            "location": LocationOption("CO", "Colombia", "country", "CO"),
            "point": MapPoint(**POINT),
            "radius_km": 3,
            **changes,
        }
    )


def test_point_radius_compiles_to_custom_location_only_and_roundtrips():
    draft = pointed(interests=(InterestOption("6003", "Café", "active"),))
    assert draft.targeting()["geo_locations"] == {
        "custom_locations": [
            {
                "latitude": 7.893907,
                "longitude": -72.507821,
                "radius": 3,
                "distance_unit": "kilometer",
            }
        ]
    }
    assert draft.targeting()["flexible_spec"] == [{"interests": [{"id": "6003"}]}]
    assert draft.snapshot()["point"] == POINT
    assert AudienceDraft.from_snapshot(draft.snapshot()) == draft
    assert pointed().fingerprint != pointed(radius_km=4).fingerprint


@pytest.mark.parametrize(
    "changes",
    [
        {"radius_km": None},
        {"radius_km": 0},
        {"radius_km": 81},
        {"radius_km": 2.5},
        {"location": LocationOption("123", "Cúcuta", "city", "CO")},
        {"point_latitude": 91},
        {"point_latitude": True},
        {"point_latitude": float("nan")},
        {"point_longitude": -180.5},
        {"point_longitude": 1.1234567},
        {"point_name": ""},
    ],
)
def test_point_rules_reject_out_of_range_or_untrusted_values(changes):
    from qualify_api.ads.audience import MapPoint

    point = {k.removeprefix("point_"): v for k, v in changes.items() if k.startswith("point_")}
    rest = {k: v for k, v in changes.items() if not k.startswith("point_")}
    with pytest.raises(AudienceUnavailable):
        pointed(point=MapPoint(**{**POINT, **point}), **rest).targeting()


def test_pre_existing_audience_and_request_fingerprints_are_byte_identical():
    """Pinned on main before m-24828977: adding the optional map point changes no hash."""
    from uuid import UUID

    from qualify_api.ads.enhancements import BrandEnhancementSettings
    from qualify_api.ads.lead_ads import LeadFormTarget
    from qualify_api.ads.messaging import MessagingTarget
    from qualify_api.ads.promotions import fingerprint

    city = AudienceDraft(location=LocationOption("123", "Bogotá", "city", "CO"))
    country = AudienceDraft(location=LocationOption("CO", "Colombia", "country", "CO"))
    rich = AudienceDraft(
        location=LocationOption("123", "Bogotá", "city", "CO"),
        radius_km=20,
        interests=(InterestOption("6003", "Café", "active"),),
        placements=("instagram_feed",),
    )
    assert [a.fingerprint for a in (city, country, rich)] == [
        "b593c7a11a634a224f9357005fecf292d258b0f46ddfa75ab67a6ca24a5ebd94",
        "6496f68ad15c16bebb455fb70ca22e39b0c5238425c8c714cbeb7c14b6be6561",
        "87fca34c52b1f1068d4b0fe8b6ae18d09431bf14af014a55467cbef1d69b71b8",
    ]
    u = UUID(int=1)
    source = PromotionSource(
        u,
        u,
        u,
        u,
        "99",
        "88",
        "Published",
        "IG",
        meta_ad_account_id="12",
        currency="COP",
        timezone_name="America/Bogota",
        ad_account_id=u,
        credential_version=1,
        linked_page_id="77",
        unavailable_reason="",
    )
    t = datetime(2030, 1, 1, tzinfo=UTC)
    website = WizardForm(
        "https://example.org/offer",
        "Bogotá",
        t,
        datetime(2030, 1, 3, tzinfo=UTC),
        city_key="123",
        budget_minor=1_000_000,
        enhancements=BrandEnhancementSettings(u, u),
        audience=city,
    )
    lead = replace(
        website,
        link_url="",
        lead_form=LeadFormTarget(u, "555", "77", u, u, 1),
        lead_cta="GET_QUOTE",
    )
    chat = replace(
        website,
        link_url="",
        messaging=MessagingTarget("WHATSAPP", u, u, "77", 1, 1, "555", "573001112233"),
    )
    hashes = [
        fingerprint(_request(u, source, form, u, "k", t, currency_offset=1).snapshot())
        for form in (website, lead, chat)
    ]
    assert hashes == [
        "116d1e8dbf4a34285ca4fc90063abd2d957e919b3257e2a05b6fc3d62dc1c793",
        "096e791fa2c4a9aa007c6ed45d6945e8c73042f646109d3a5a5ece80b1917e31",
        "b081e64dd57aa8b814077ea432b1d8e2507919a1f26a39817837c150fe674e40",
    ]
    # The exact-validation receipt's form hash, also pinned on main before the change.
    from qualify_api.ads.validation import context

    assert (
        context(source, website)["form_hash"]
        == "264dc9263503bec4a5521da70f82213b4eec991de46c8cac165a3f32b6ed2381"
    )


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
