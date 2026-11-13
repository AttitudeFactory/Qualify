"""An explicit fake promotion lifecycle: no credentials, network or paid delivery."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from qualify_api.ads.activation_repository import MemoryActivationRepository
from qualify_api.ads.errors import MarketingError
from qualify_api.ads.fake import FakeMarketingClient
from qualify_api.ads.promotion_repository import MemoryPromotionRepository, RequestConflict
from qualify_api.ads.promotions import AccountAccess, PromotionService
from qualify_api.ads.wizard import PromotionSource, WizardForm, WizardUnavailable
from qualify_api.ads.wizard_workflow import PromotionWizard, VerifiedChecks

NOW = datetime(2030, 1, 1, tzinfo=UTC)


class Sources:
    def __init__(self, tenant, source) -> None:
        self.tenant, self.source = tenant, source

    def get(self, tenant_id, source_id):
        if tenant_id != self.tenant or source_id != self.source.publish_attempt_id:
            raise WizardUnavailable("Esta publicación ya no está disponible.")
        return self.source


class Gateway:
    def __init__(self) -> None:
        # This is normalized, explicit test evidence, not a simulated Meta schema.
        self.checks = VerifiedChecks(
            100_00, True, True, True, "city-key", NOW + timedelta(minutes=15)
        )

    async def preflight(self, source, form):
        return self.checks


class Binding:
    def __init__(self, tenant, source, client) -> None:
        self.tenant, self.source, self.client = tenant, source, client

    async def resolve(self, tenant, brand, account):
        assert (tenant, brand, account) == (self.tenant, self.source.brand_id, "12")
        return AccountAccess(tenant, brand, account, "COP", self.client)


def setup():
    tenant, actor = uuid4(), uuid4()
    source = PromotionSource(
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        "99",
        "88",
        "Published caption",
        "Example IG",
        meta_ad_account_id="12",
        currency="COP",
    )
    sources = Sources(tenant, source)
    client = FakeMarketingClient(account_id="12")
    client.responses["GET", "4/previews"] = {
        "data": [
            {
                "body": '<iframe src="https://www.facebook.com/ads/api/preview_iframe.php?d=test"></iframe>'
            }
        ]
    }
    gateway = Gateway()
    repository = MemoryPromotionRepository()
    activations = MemoryActivationRepository()
    authors = []

    def authorize(t, a):
        assert (t, a) == (tenant, actor)
        authors.append((t, a))

    wizard = PromotionWizard(
        creation=PromotionService(repository, Binding(tenant, source, client)),
        activations=activations,
        sources=sources,
        gateway=gateway,
        authorize=authorize,
        clock=lambda: NOW,
    )
    form = WizardForm(
        "https://example.org/landing",
        "Bogotá",
        NOW + timedelta(days=1),
        NOW + timedelta(days=3),
        city_key="city-key",
        budget_minor=150_00,
    )
    args = dict(
        tenant_id=tenant,
        publish_attempt_id=source.publish_attempt_id,
        form=form,
        approved_by=actor,
        request_key="test-request",
    )
    return wizard, client, gateway, source, args, authors


@pytest.mark.asyncio
async def test_fake_full_lifecycle_paused_preview_then_explicit_charge_active() -> None:
    wizard, client, _, source, args, authors = setup()
    preview = await wizard.prepare(**args)
    assert preview.status == "paused" and "$150,00 COP" in preview.charge_notice
    assert all(client.objects[k]["status"] == "PAUSED" for k in ("1", "2", "4"))
    creative = client.objects["3"]
    assert creative["source_instagram_media_id"] == source.source_media_id
    assert creative["instagram_user_id"] == source.instagram_user_id
    assert creative["call_to_action"] == {
        "type": "LEARN_MORE",
        "value": {"link": args["form"].link_url},
    }
    assert "lifetime_budget" in client.objects["2"] and "daily_budget" not in client.objects["2"]
    result = await wizard.confirm(
        tenant_id=args["tenant_id"],
        promotion_id=preview.promotion_id,
        review_id=preview.review_id,
        approved_by=args["approved_by"],
        confirm_charge=True,
    )
    assert result.status == "active" and "pendientes" in result.message
    writes = [
        path
        for method, path, params in client.calls
        if method == "POST" and params.get("status") == "ACTIVE"
    ]
    assert writes == ["4", "2", "1"]  # campaign enables delivery only after children.
    before = len(client.calls)
    again = await wizard.confirm(
        tenant_id=args["tenant_id"],
        promotion_id=preview.promotion_id,
        review_id=preview.review_id,
        approved_by=args["approved_by"],
        confirm_charge=True,
    )
    assert again.status == "active" and len(client.calls) == before
    assert len(authors) >= 6


@pytest.mark.asyncio
async def test_missing_confirmation_does_not_claim_or_update() -> None:
    wizard, client, _, _, args, _ = setup()
    preview = await wizard.prepare(**args)
    calls = list(client.calls)
    with pytest.raises(WizardUnavailable, match="Confirma"):
        await wizard.confirm(
            tenant_id=args["tenant_id"],
            promotion_id=preview.promotion_id,
            review_id=preview.review_id,
            approved_by=args["approved_by"],
            confirm_charge=False,
        )
    assert client.calls == calls
    assert wizard.activations.get(args["tenant_id"], preview.review_id).state == "ready"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("billing_ready", None),
        ("billing_ready", False),
        ("eligible", None),
        ("instagram_assigned", False),
        ("minimum_budget_minor", None),
        ("minimum_budget_minor", 0),
        ("city_key", "wrong"),
    ],
)
async def test_unknown_or_failed_checks_never_create(field, value) -> None:
    wizard, client, gateway, _, args, _ = setup()
    gateway.checks = replace(gateway.checks, **{field: value})
    with pytest.raises(WizardUnavailable):
        await wizard.prepare(**args)
    assert not client.calls and not client.objects


@pytest.mark.asyncio
async def test_under_minimum_rejected_before_any_meta_write() -> None:
    wizard, client, _, _, args, _ = setup()
    with pytest.raises(WizardUnavailable, match="mínimo"):
        await wizard.prepare(**{**args, "form": replace(args["form"], budget_minor=99_99)})
    assert not client.calls and not client.objects


@pytest.mark.asyncio
async def test_same_request_is_immutable_and_duplicate_prepare_does_not_create() -> None:
    wizard, client, _, _, args, _ = setup()
    first = await wizard.prepare(**args)
    assert await wizard.prepare(**args) == first
    assert len(client.objects) == 4
    before = len(client.calls)
    with pytest.raises(RequestConflict):
        await wizard.prepare(**{**args, "form": replace(args["form"], budget_minor=200_00)})
    assert len(client.calls) == before


@pytest.mark.asyncio
async def test_expired_review_or_changed_source_cannot_enable_spending() -> None:
    wizard, client, gateway, source, args, _ = setup()
    preview = await wizard.prepare(**args)
    wizard.clock = lambda: NOW + timedelta(minutes=16)
    gateway.checks = replace(gateway.checks, expires_at=NOW + timedelta(minutes=30))
    with pytest.raises(WizardUnavailable, match="venció"):
        await wizard.confirm(
            tenant_id=args["tenant_id"],
            promotion_id=preview.promotion_id,
            review_id=preview.review_id,
            approved_by=args["approved_by"],
            confirm_charge=True,
        )
    wizard.clock = lambda: NOW
    wizard.sources.source = replace(source, source_media_id="999")
    with pytest.raises(WizardUnavailable, match="cambió"):
        await wizard.confirm(
            tenant_id=args["tenant_id"],
            promotion_id=preview.promotion_id,
            review_id=preview.review_id,
            approved_by=args["approved_by"],
            confirm_charge=True,
        )
    assert not any(params.get("status") == "ACTIVE" for method, path, params in client.calls)


@pytest.mark.asyncio
async def test_unknown_activation_is_only_reconciled_never_resent_or_recreated() -> None:
    wizard, client, _, _, args, _ = setup()
    preview = await wizard.prepare(**args)
    client.failures.append(MarketingError("unknown", outcome_unknown=True))
    kwargs = dict(
        tenant_id=args["tenant_id"],
        promotion_id=preview.promotion_id,
        review_id=preview.review_id,
        approved_by=args["approved_by"],
        confirm_charge=True,
    )
    assert (await wizard.confirm(**kwargs)).status == "unknown"
    before = len([call for call in client.calls if call[0] == "POST"])
    assert (await wizard.confirm(**kwargs)).status == "unknown"
    assert len([call for call in client.calls if call[0] == "POST"]) == before
    # Simulate a response-lost operation that actually activated the existing objects.
    for key in ("1", "2", "4"):
        client.objects[key]["status"] = "ACTIVE"
    assert (await wizard.confirm(**kwargs)).status == "active"
    assert len(client.objects) == 4


@pytest.mark.asyncio
async def test_membership_removed_between_children_prevents_campaign_enable() -> None:
    wizard, client, _, _, args, _ = setup()
    preview = await wizard.prepare(**args)

    def authorize(tenant, actor):
        if client.objects["2"].get("status") == "ACTIVE":
            raise PermissionError("removed")

    wizard.authorize = authorize
    result = await wizard.confirm(
        tenant_id=args["tenant_id"],
        promotion_id=preview.promotion_id,
        review_id=preview.review_id,
        approved_by=args["approved_by"],
        confirm_charge=True,
    )
    assert result.status == "unknown"
    assert client.objects["1"]["status"] == "PAUSED"
    assert wizard.activations.get(args["tenant_id"], preview.review_id).state == "unknown"


@pytest.mark.asyncio
async def test_review_is_bound_to_same_local_actor_and_promotion() -> None:
    wizard, client, _, _, args, _ = setup()
    preview = await wizard.prepare(**args)
    wizard.authorize = lambda tenant, actor: (
        None
    )  # Both actors are members; consent is still personal.
    before = len(client.calls)
    kwargs = dict(
        tenant_id=args["tenant_id"],
        promotion_id=preview.promotion_id,
        review_id=preview.review_id,
        approved_by=args["approved_by"],
        confirm_charge=True,
    )
    for changed in (
        {"approved_by": uuid4()},
        {"review_id": uuid4()},
        {"promotion_id": uuid4()},
        {"tenant_id": uuid4()},
    ):
        with pytest.raises(WizardUnavailable, match="confirmación"):
            await wizard.confirm(**{**kwargs, **changed})
    assert len(client.calls) == before


@pytest.mark.asyncio
async def test_unknown_activation_can_be_read_back_after_quote_and_start_expire() -> None:
    wizard, client, _, _, args, _ = setup()
    preview = await wizard.prepare(**args)
    client.failures.append(MarketingError("unknown", outcome_unknown=True))
    kwargs = dict(
        tenant_id=args["tenant_id"],
        promotion_id=preview.promotion_id,
        review_id=preview.review_id,
        approved_by=args["approved_by"],
        confirm_charge=True,
    )
    assert (await wizard.confirm(**kwargs)).status == "unknown"
    before = len([call for call in client.calls if call[0] == "POST"])
    for key in ("1", "2", "4"):
        client.objects[key]["status"] = "ACTIVE"
    wizard.clock = lambda: NOW + timedelta(days=2)
    assert (await wizard.confirm(**kwargs)).status == "active"
    assert len([call for call in client.calls if call[0] == "POST"]) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["expiry", "start"])
async def test_slow_child_cannot_enable_campaign_after_consent_boundary(boundary) -> None:
    wizard, client, gateway, _, args, _ = setup()
    now = [NOW]
    wizard.clock = lambda: now[0]
    if boundary == "start":
        gateway.checks = replace(gateway.checks, expires_at=NOW + timedelta(days=10))
    preview = await wizard.prepare(**args)
    original_update = client.update

    async def slow_update(object_id, *, params, before_write=None):
        await original_update(object_id, params=params, before_write=before_write)
        if object_id == "4":
            now[0] = NOW + (timedelta(minutes=16) if boundary == "expiry" else timedelta(days=2))

    client.update = slow_update
    result = await wizard.confirm(
        tenant_id=args["tenant_id"],
        promotion_id=preview.promotion_id,
        review_id=preview.review_id,
        approved_by=args["approved_by"],
        confirm_charge=True,
    )
    assert result.status == "unknown"
    assert client.objects["1"]["status"] == "PAUSED"
    assert client.objects["2"]["status"] == "PAUSED"
    assert wizard.activations.get(args["tenant_id"], preview.review_id).state == "unknown"


@pytest.mark.asyncio
async def test_expiry_inside_campaign_wait_is_fenced_before_its_transport_write() -> None:
    wizard, client, _, _, args, _ = setup()
    now = [NOW]
    wizard.clock = lambda: now[0]
    preview = await wizard.prepare(**args)
    original_update = client.update

    async def waiting_update(object_id, *, params, before_write=None):
        if object_id == "1":
            # Simulates the update adapter awaiting its account cooldown before POST.
            now[0] = NOW + timedelta(minutes=16)
        await original_update(object_id, params=params, before_write=before_write)

    client.update = waiting_update
    result = await wizard.confirm(
        tenant_id=args["tenant_id"],
        promotion_id=preview.promotion_id,
        review_id=preview.review_id,
        approved_by=args["approved_by"],
        confirm_charge=True,
    )
    assert result.status == "unknown"
    assert client.objects["1"]["status"] == "PAUSED"
    assert not any(
        method == "POST" and path == "1" and params.get("status") == "ACTIVE"
        for method, path, params in client.calls
    )


@pytest.mark.asyncio
async def test_public_production_seams_require_authenticated_actor(monkeypatch) -> None:
    from qualify_api.ads import wizard as public

    _, _, _, source, args, _ = setup()
    monkeypatch.setattr(public, "require_acting_member", lambda tenant: None)
    source = replace(source, unavailable_reason="")
    monkeypatch.setattr(public, "list_promotion_sources", lambda **kwargs: (source,))
    with pytest.raises(WizardUnavailable, match="Vuelve a entrar"):
        await public.prepare_promotion_preview(content_draft_id=source.content_draft_id, **args)
    with pytest.raises(WizardUnavailable, match="Vuelve a entrar"):
        await public.confirm_promotion(
            tenant_id=args["tenant_id"],
            promotion_id=uuid4(),
            review_id=uuid4(),
            approved_by=args["approved_by"],
            confirm_charge=True,
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"link_url": "http://example.org"},
        {"link_url": "https://u:p@example.org"},
        {"budget_minor": True},
        {"currency": "USD"},
        {"radius_km": 0},
        {"age_min": 17},
        {"city_name": ""},
        {"start_time": NOW.replace(tzinfo=None)},
    ],
)
def test_local_preparation_rejects_invalid_input_without_network(changes) -> None:
    *_, args, authors = setup()
    with pytest.raises(WizardUnavailable):
        replace(args["form"], **changes).validate()


def lead_setup(**target_changes):
    from qualify_api.ads.lead_ads import LeadFormTarget

    wizard, client, gateway, source, args, authors = setup()
    source = replace(source, linked_page_id="77", credential_version=1)
    wizard.sources.source = source
    target = LeadFormTarget(uuid4(), "555", "77", source.connection_id, source.brand_id, 1)
    target = replace(target, **target_changes)
    form = replace(args["form"], link_url="", lead_form=target, lead_cta="SIGN_UP")
    return wizard, client, source, {**args, "form": form}, target


@pytest.mark.asyncio
async def test_lead_campaign_uses_published_form_paused_then_explicit_activation() -> None:
    wizard, client, source, args, target = lead_setup()
    preview = await wizard.prepare(**args)
    campaign, adset, creative, ad = (client.objects[k] for k in ("1", "2", "3", "4"))
    assert campaign["objective"] == "OUTCOME_LEADS"
    assert adset["optimization_goal"] == "LEAD_GENERATION"
    assert adset["destination_type"] == "ON_AD"
    assert adset["promoted_object"] == {"page_id": "77"}
    assert creative["object_id"] == "77"
    assert creative["source_instagram_media_id"] == source.source_media_id
    assert creative["call_to_action"] == {"type": "SIGN_UP", "value": {"lead_gen_form_id": "555"}}
    assert all(row["status"] == "PAUSED" for row in (campaign, adset, ad))
    stored = wizard.creation.repository.get(args["tenant_id"], preview.promotion_id)
    assert stored.request["lead_form_snapshot"] == target.snapshot()
    assert stored.request["link_url"] == ""
    result = await wizard.confirm(
        tenant_id=args["tenant_id"],
        promotion_id=preview.promotion_id,
        review_id=preview.review_id,
        approved_by=args["approved_by"],
        confirm_charge=True,
    )
    assert result.status == "active"
    assert await wizard.prepare(**args) == preview and len(client.objects) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes,cta",
    [
        ({"connection_id": uuid4()}, "SIGN_UP"),
        ({"page_id": "78"}, "SIGN_UP"),
        ({"brand_id": uuid4()}, "SIGN_UP"),
        ({"credential_version": 2}, "SIGN_UP"),
        ({}, "SHOP_NOW"),
        ({}, ""),
    ],
)
async def test_lead_form_of_another_account_or_unsupported_button_never_creates(
    changes, cta
) -> None:
    wizard, client, _, args, _ = lead_setup(**changes)
    args = {**args, "form": replace(args["form"], lead_cta=cta)}
    with pytest.raises(WizardUnavailable):
        await wizard.prepare(**args)
    assert not client.calls and not client.objects


# --- The website promotion's button (m-24828976) ---


def test_default_button_keeps_the_exact_approval_hash_from_before_the_choice() -> None:
    from uuid import UUID

    from qualify_api.ads.promotions import fingerprint
    from qualify_api.ads.wizard_workflow import _request

    ids = [UUID(int=i) for i in range(1, 7)]
    source = PromotionSource(
        *ids[:4], "99", "88", "c", "l", meta_ad_account_id="12", currency="COP"
    )
    form = WizardForm(
        "https://example.org/landing",
        "Bogotá",
        NOW + timedelta(days=1),
        NOW + timedelta(days=3),
        city_key="city-key",
        budget_minor=150_00,
    )
    request = _request(ids[4], source, form, ids[5], "test-request", NOW)
    # Pinned against origin/main's `_request` (hard-coded LEARN_MORE) for the same inputs.
    assert (
        fingerprint(request.snapshot())
        == "d82ed0280fc623fbf05c04c754d4eeee8e053f50e63b6e673912dbbc64a94d7a"
    )
    chosen = _request(
        ids[4], source, replace(form, cta_type="SHOP_NOW"), ids[5], "test-request", NOW
    )
    assert fingerprint(chosen.snapshot()) != fingerprint(request.snapshot())


@pytest.mark.asyncio
async def test_chosen_website_button_is_created_approved_and_activated() -> None:
    wizard, client, _, _, args, _ = setup()
    args["form"] = replace(args["form"], cta_type="SHOP_NOW")
    preview = await wizard.prepare(**args)
    assert client.objects["3"]["call_to_action"] == {
        "type": "SHOP_NOW",
        "value": {"link": args["form"].link_url},
    }
    promotion = wizard.creation.repository.get(args["tenant_id"], preview.promotion_id)
    assert promotion.request["cta_type"] == "SHOP_NOW"
    result = await wizard.confirm(
        tenant_id=args["tenant_id"],
        promotion_id=preview.promotion_id,
        review_id=preview.review_id,
        approved_by=args["approved_by"],
        confirm_charge=True,
    )
    assert result.status == "active"


@pytest.mark.asyncio
@pytest.mark.parametrize("cta", ["CALL_NOW", "WHATSAPP_MESSAGE", "MESSAGE_PAGE", "", "learn_more"])
async def test_button_outside_the_website_allowlist_is_refused_before_meta(cta: str) -> None:
    wizard, client, _, _, args, _ = setup()
    with pytest.raises(WizardUnavailable, match="botón"):
        await wizard.prepare(**{**args, "form": replace(args["form"], cta_type=cta)})
    assert not client.calls and not client.objects


@pytest.mark.asyncio
async def test_button_changed_after_approval_cannot_be_activated() -> None:
    wizard, client, _, _, args, _ = setup()
    preview = await wizard.prepare(**args)
    # Tamper with the stored row itself (the repository hands out copies).
    promotion = wizard.creation.repository.promotions[preview.promotion_id]
    promotion.request["cta_type"] = "SHOP_NOW"
    promotion.request["creative"]["call_to_action"]["type"] = "SHOP_NOW"
    with pytest.raises(WizardUnavailable, match="no corresponde"):
        await wizard.confirm(
            tenant_id=args["tenant_id"],
            promotion_id=preview.promotion_id,
            review_id=preview.review_id,
            approved_by=args["approved_by"],
            confirm_charge=True,
        )
    assert not any(params.get("status") == "ACTIVE" for _, _, params in client.calls)


@pytest.mark.asyncio
async def test_a_website_button_never_rides_a_lead_ad() -> None:
    wizard, client, _, args, _ = lead_setup()
    with pytest.raises(WizardUnavailable, match="botón"):
        await wizard.prepare(**{**args, "form": replace(args["form"], cta_type="SHOP_NOW")})
    assert not client.calls and not client.objects
