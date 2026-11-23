"""Production composition against mocked HTTP, never a fake readiness gateway."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import pytest

from qualify_api.ads.activation_repository import MemoryActivationRepository
from qualify_api.ads.audience import AudienceDraft, LocationOption
from qualify_api.ads.client import MarketingClient
from qualify_api.ads.enhancements import BrandEnhancementSettings
from qualify_api.ads.live_wizard import production_currency_offset
from qualify_api.ads.promotion_repository import MemoryPromotionRepository
from qualify_api.ads.promotions import AccountAccess
from qualify_api.ads.validation import valid_receipt
from qualify_api.ads.wizard import PromotionSource, WizardForm, WizardUnavailable
from qualify_api.auth.business import NotAMember
from qualify_api.connections.resolver import build_authenticated_client


class MetaHTTP:
    def __init__(self):
        self.objects = {}
        self.calls = []
        self.payment = True
        self.owner = "99"
        self.reject = ""
        self.drop_cta = False
        self.ambiguous = ""
        self.revoked = False
        self.before_request = None
        self.spent = 0  # whole COP the ad set has already spent
        self.min_daily = 1500  # whole COP, act_12/minimum_budgets
        # act_12 spend_cap / amount_spent in whole COP; None = Meta's "0", no cap.
        self.spend_cap: int | None = None
        self.amount_spent = 0
        self.account_error = False  # act_12 answers a Graph error (MarketingError)
        # interest id -> (targetingvalidation `valid`, targetingoptionstatus `current_status`)
        self.interests: dict[str, tuple[bool, str]] = {}
        self.currency = "COP"  # the ad account's currency (m-25091394)

    def respond(self, request):
        assert "secret" not in str(request.url)
        assert request.headers["authorization"] == "Bearer secret"
        path = request.url.path.removeprefix("/v26.0/")
        params = {}
        for key, values in parse_qs(request.content.decode()).items():
            value = values[0]
            params[key] = json.loads(value) if value.startswith(("{", "[")) else value
        self.calls.append((request.method, path, deepcopy(params)))
        if self.before_request:
            self.before_request(request.method, path, params)
        if request.method == "GET":
            if path == "me/permissions":
                data = [
                    {
                        "permission": "ads_management",
                        "status": "declined" if self.revoked else "granted",
                    }
                ]
            elif path == "me/adaccounts":
                data = [
                    {
                        "account_id": "12",
                        "currency": self.currency,
                        "timezone_name": "America/Bogota",
                        "account_status": 1,
                        "disable_reason": 0,
                        "funding_source": "55" if self.payment else None,
                    }
                ]
            elif path == "act_12/connected_instagram_accounts":
                data = [{"id": "99"}]
            elif path == "act_12/targetingvalidation":
                data = [{"id": k, "valid": v[0]} for k, v in self.interests.items()]
            elif path == "search":
                assert request.url.params["type"] == "targetingoptionstatus"
                data = [{"id": k, "current_status": v[1]} for k, v in self.interests.items()]
            elif path == "act_12" and self.account_error:
                return httpx.Response(400, json={"error": {"code": 1, "message": "secret"}})
            elif path == "act_12":
                return httpx.Response(
                    200,
                    json={
                        "account_id": "12",
                        "currency": self.currency,
                        "failed_delivery_checks": [],
                        "spend_cap": str(self.spend_cap or 0),
                        "amount_spent": str(self.amount_spent),
                    },
                )
            elif path == "88":
                return httpx.Response(
                    200,
                    json={
                        "id": "88",
                        "owner": {"id": self.owner},
                        "media_type": "IMAGE",
                        "media_product_type": "FEED",
                    },
                )
            elif path.endswith("/previews"):
                data = [
                    {
                        "body": '<iframe src="https://www.facebook.com/ads/api/preview_iframe.php?d=test"></iframe>'
                    }
                ]
            elif path in {"100/adsets", "101/ads"}:
                parent, edge = path.split("/")
                relation = "campaign_id" if edge == "adsets" else "adset_id"
                data = [
                    {"id": row["id"]}
                    for row in self.objects.values()
                    if row["_resource"] == edge and row.get(relation) == parent
                ]
            elif path == "act_12/minimum_budgets":
                data = [
                    {"currency": "USD", "min_daily_budget_imp": 1},
                    {
                        "currency": "COP",
                        "min_daily_budget_imp": self.min_daily,
                        "min_daily_budget_low_freq": self.min_daily - 500,
                    },
                ]
            elif path in self.objects:
                # Like Graph, return only the requested fields (unrequested ones are absent).
                fields = request.url.params.get("fields")
                row = self.objects[path]
                if row["_resource"] == "adsets":
                    remaining = int(row["lifetime_budget"]) - self.spent
                    row = {**row, "budget_remaining": str(remaining)}
                if fields:
                    row = {k: row[k] for k in fields.split(",") if k in row}
                return httpx.Response(200, json=row)
            elif path.startswith("act_12/"):
                data = [
                    row for row in self.objects.values() if row["_resource"] == path.split("/")[-1]
                ]
            else:
                raise AssertionError(path)
            return httpx.Response(200, json={"data": data})
        resource = path.split("/")[-1]
        if params.get("execution_options") == ["validate_only"]:
            if resource == self.reject:
                return httpx.Response(
                    400, json={"error": {"code": 100, "message": "secret provider body"}}
                )
            return httpx.Response(200, json={"success": True})
        if path.startswith("act_12/"):
            identifier = str(100 + len(self.objects))
            self.objects[identifier] = {
                **params,
                "id": identifier,
                "account_id": "12",
                "_resource": resource,
            }
            if resource == "ads":
                self.objects[identifier]["campaign_id"] = self.objects[params["adset_id"]][
                    "campaign_id"
                ]
                self.objects[identifier]["creative"] = {"id": params["creative"]["creative_id"]}
            if resource == "adcreatives" and self.drop_cta:
                self.objects[identifier].pop("call_to_action", None)
            if resource == self.ambiguous:
                raise httpx.ReadTimeout("ambiguous", request=request)
            return httpx.Response(200, json={"id": identifier})
        assert path in self.objects
        self.objects[path].update(params)
        return httpx.Response(200, json={"success": True})

    @property
    def actual_creates(self):
        return [
            call
            for call in self.calls
            if call[0] == "POST"
            and call[1].startswith("act_12/")
            and "execution_options" not in call[2]
        ]

    @property
    def activations(self):
        return [
            call for call in self.calls if call[0] == "POST" and call[2].get("status") == "ACTIVE"
        ]


@pytest.fixture
def live(monkeypatch):
    from qualify_api.ads import activation_repository, live_wizard, promotion_repository, wizard
    from qualify_api.connections import ad_accounts

    tenant, actor, brand = uuid4(), uuid4(), uuid4()
    now = [datetime.now(UTC)]
    source = PromotionSource(
        uuid4(),
        uuid4(),
        uuid4(),
        brand,
        "99",
        "88",
        "Published",
        "IG",
        meta_ad_account_id="12",
        currency="COP",
        timezone_name="America/Bogota",
        ad_account_id=uuid4(),
        credential_version=1,
        linked_page_id="77",
        unavailable_reason="",
    )
    source_holder = [source]
    remote = MetaHTTP()
    clients = []
    active_actor = [True]
    active_credential = [True]
    shift = [0.0]
    cooldown = [0.0]
    ticks = [0.0]

    class ClockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(seconds=shift[0])

    from qualify_api.ads import wizard_workflow

    monkeypatch.setattr(live_wizard, "datetime", ClockDateTime)
    monkeypatch.setattr(wizard_workflow, "datetime", ClockDateTime)

    class Sources:
        def get(self, tid, sid):
            assert tid == tenant and sid == source.publish_attempt_id
            return source_holder[0]

    def authorize(tid, uid):
        assert tid == tenant and uid == actor
        if not active_actor[0]:
            raise NotAMember()

    async def authenticated(tid, cid, *, expected_version):
        assert tid == tenant and cid == source.connection_id and expected_version == 1
        client = build_authenticated_client(
            "secret", scheme="Bearer", transport=httpx.MockTransport(remote.respond)
        )
        clients.append(client)
        return client

    class Binding:
        async def resolve(self, tid, bid, aid):
            assert (tid, bid, aid) == (tenant, brand, "12")

            async def sleep(seconds):
                ticks[0] += seconds
                shift[0] += seconds

            client = MarketingClient(
                client=await authenticated(tid, source.connection_id, expected_version=1),
                account_id=aid,
                sleep=sleep,
                monotonic=lambda: ticks[0],
            )
            client._not_before = ticks[0] + cooldown[0]
            cooldown[0] = 0.0
            return AccountAccess(
                tenant,
                brand,
                aid,
                source_holder[0].currency,
                client,
            )

    repository = MemoryPromotionRepository()
    activations = MemoryActivationRepository()
    monkeypatch.setattr(live_wizard, "PersistedWizardSources", Sources)
    monkeypatch.setattr(live_wizard, "authorize_actor", authorize)

    def credential_guard(tid, current):
        assert tid == tenant
        if not active_credential[0]:
            raise WizardUnavailable("El acceso o la cuenta cambió.")

    monkeypatch.setattr(live_wizard, "credential_guard", credential_guard)
    monkeypatch.setattr(live_wizard, "_authenticated_client", authenticated)
    monkeypatch.setattr(ad_accounts, "PostgresAccountBinding", Binding)
    monkeypatch.setattr(promotion_repository, "PostgresPromotionRepository", lambda: repository)
    monkeypatch.setattr(activation_repository, "PostgresActivationRepository", lambda: activations)
    monkeypatch.setattr(wizard, "require_acting_member", lambda tenant: None)
    monkeypatch.setattr(wizard, "list_promotion_sources", lambda **kwargs: (source_holder[0],))
    policy = BrandEnhancementSettings(tenant, brand)
    form = WizardForm(
        "https://example.org/offer",
        "Bogotá",
        now[0] + timedelta(days=1),
        now[0] + timedelta(days=3),
        city_key="123",
        budget_minor=1_000_000,
        enhancements=policy,
        audience=AudienceDraft(location=LocationOption("123", "Bogotá", "city", "CO")),
    )
    args = dict(
        tenant_id=tenant,
        content_draft_id=source.content_draft_id,
        publish_attempt_id=source.publish_attempt_id,
        form=form,
        approved_by=actor,
        request_key="principal-live-test",
    )
    return dict(
        remote=remote,
        args=args,
        source=source,
        sources=source_holder,
        repo=repository,
        reviews=activations,
        clients=clients,
        actor=active_actor,
        credential=active_credential,
        cooldown=cooldown,
    )


async def prepare(live):
    from qualify_api.ads.wizard import prepare_promotion_preview

    return await asyncio.wait_for(prepare_promotion_preview(**live["args"]), 5)


async def confirm(live, preview):
    from qualify_api.ads.wizard import confirm_promotion

    return await asyncio.wait_for(
        confirm_promotion(
            tenant_id=live["args"]["tenant_id"],
            promotion_id=preview.promotion_id,
            review_id=preview.review_id,
            approved_by=live["args"]["approved_by"],
            confirm_charge=True,
        ),
        5,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["budget", "budget_down", "end_time", "resume"])
@pytest.mark.parametrize(
    "failure", [None, "credential_after_write", "audit_failure", "spend_grew", "cap_grew"]
)
async def test_paid_management_real_http_receipt_and_full_chain_verification(
    live, monkeypatch, action, failure
):
    from contextlib import contextmanager
    from types import SimpleNamespace

    from qualify_api.ads import live_management as management
    from qualify_api.ads.edit_ledger import revision
    from qualify_api.ads.live_wizard import production_wizard
    from qualify_api.ads.results import ResultsUnavailable

    if failure == "spend_grew" and action != "budget_down":
        pytest.skip("the confirm-time floor applies only to a budget decrease")
    if failure == "cap_grew" and action != "budget":
        pytest.skip("the confirm-time spend cap applies only to a budget raise")
    if failure == "cap_grew":
        # 25.000 COP left: the 10.000 unspent + 10.000 raise fits at prepare.
        live["remote"].spend_cap, live["remote"].amount_spent = 30_000, 5_000

    preview = await prepare(live)
    await confirm(live, preview)
    tenant = live["args"]["tenant_id"]
    actor = live["args"]["approved_by"]
    promotion = live["repo"].get(tenant, preview.promotion_id)
    scope = SimpleNamespace(
        tenant_id=tenant,
        promotion_id=promotion.id,
        connection=SimpleNamespace(connection_id=live["source"].connection_id, version=1),
        account_id=live["source"].ad_account_id,
    )
    if action == "resume":
        for resource in ("campaigns", "adsets", "ads"):
            live["remote"].objects[promotion.ids[resource]]["status"] = "PAUSED"

    @contextmanager
    def session(*args, **kwargs):
        yield SimpleNamespace(
            execute=lambda *args, **kwargs: SimpleNamespace(
                mappings=lambda: SimpleNamespace(first=lambda: None)
            )
        )

    monkeypatch.setenv("QUALIFY_OAUTH_STATE_SECRET", "test-management-signing-secret-32-characters")
    monkeypatch.setattr(management, "tenant_session", session)
    monkeypatch.setattr(management, "_scope", lambda *args: scope)
    monkeypatch.setattr(management, "_actor", lambda *args: actor)
    monkeypatch.setattr(management, "current_acting_login", lambda: actor)
    monkeypatch.setattr(management, "PostgresPromotionRepository", lambda: live["repo"])
    monkeypatch.setattr(management, "_load", lambda *args: None)
    audits = []
    monkeypatch.setattr(
        management,
        "_claim_pause",
        lambda *args, **kwargs: (audits.append(kwargs) or uuid4(), "claimed"),
    )
    monkeypatch.setattr(management, "_dispatch", lambda *args: None)
    monkeypatch.setattr(management, "_finish_pause", lambda scope, op, state: audits.append(state))
    async with production_wizard(tenant, actor) as wizard:
        gateway = wizard.gateway
        monkeypatch.setattr(
            management, "_context", lambda scope: (promotion, revision([]), gateway, live["source"])
        )
        monkeypatch.setattr(management, "_local", lambda *args: gateway.local_guard(live["source"]))
        options = {
            "budget": {"budget_minor": 2_000_000},
            # Floor: 0 spent + 1.500 COP x 2 days (not started yet) = 3.000 COP.
            "budget_down": {"budget_minor": 600_000},
            "end_time": {"end_time": live["args"]["form"].end_time + timedelta(days=1)},
        }.get(action, {})
        meta_action = "budget" if action == "budget_down" else action
        start = len(live["remote"].calls)
        review = await management.prepare_promotion_edit(
            tenant_id=tenant,
            promotion_id=promotion.id,
            request_key="edit-actual",
            action=meta_action,
            **options,
        )
        reviewed_calls = live["remote"].calls[start:]
        assert all(
            call[0] == "GET" or call[2].get("execution_options") == ["validate_only"]
            for call in reviewed_calls
        )
        if failure == "credential_after_write":

            def revoke(method, path, params):
                if method == "POST" and "execution_options" not in params:
                    live["credential"][0] = False

            live["remote"].before_request = revoke
        if failure == "audit_failure":

            def fail_audit(*args):
                raise RuntimeError("database unavailable")

            monkeypatch.setattr(management, "_finish_pause", fail_audit)
        if failure == "cap_grew":
            # Other ads spent 7.000 more while the owner read the review: 18.000 left < 20.000.
            live["remote"].amount_spent = 12_000
            with pytest.raises(ResultsUnavailable, match=r"límite de gasto.*\$18\.000 COP"):
                await management.confirm_promotion_edit(
                    tenant_id=tenant,
                    promotion_id=promotion.id,
                    request_key="edit-actual",
                    approval_token=review.approval_token,
                    confirm_change=True,
                )
            assert audits == []  # refused before _claim_pause
            assert not [
                call
                for call in live["remote"].calls[start:]
                if call[0] == "POST" and "execution_options" not in call[2]
            ]
            return
        if failure == "spend_grew":
            # 9.000 of 10.000 spent while the owner read the review: floor is now 12.000.
            live["remote"].spent = 9000
            with pytest.raises(ResultsUnavailable, match=r"Puedes bajarlo hasta \$12\.000 COP\."):
                await management.confirm_promotion_edit(
                    tenant_id=tenant,
                    promotion_id=promotion.id,
                    request_key="edit-actual",
                    approval_token=review.approval_token,
                    confirm_change=True,
                )
            assert audits == []  # never claimed, never logged as sent
            assert not [
                call
                for call in live["remote"].calls[start:]
                if call[0] == "POST" and "execution_options" not in call[2]
            ]
            return
        result = await management.confirm_promotion_edit(
            tenant_id=tenant,
            promotion_id=promotion.id,
            request_key="edit-actual",
            approval_token=review.approval_token,
            confirm_change=True,
        )
    if failure:
        assert result.status == "unknown"
        if failure == "credential_after_write" and action == "resume":
            assert live["remote"].objects[promotion.ids["campaigns"]]["status"] == "PAUSED"
        return
    assert result.status == "completed" and audits[-1] == "completed"
    assert audits[0]["evidence"]["confirmed"] is True
    writes = [
        call
        for call in live["remote"].calls[start:]
        if call[0] == "POST" and "execution_options" not in call[2]
    ]
    if action == "resume":
        assert [call[1] for call in writes] == [
            promotion.ids[r] for r in ("ads", "adsets", "campaigns")
        ]
    elif action == "budget":
        assert writes == [("POST", promotion.ids["adsets"], {"lifetime_budget": "20000"})]
        assert live["repo"].get(tenant, promotion.id).request["budget_minor"] == 1_000_000
    elif action == "budget_down":
        assert writes == [("POST", promotion.ids["adsets"], {"lifetime_budget": "6000"})]
        assert audits[0]["evidence"]["floor"]["floor"] == 300_000
        # The immutable initial approval keeps the original amount.
        assert live["repo"].get(tenant, promotion.id).request["budget_minor"] == 1_000_000


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("spent", "budget_minor", "allowed"),
    [(0, 300_000, True), (0, 290_000, False), (7000, 1_000_000, True), (7000, 990_000, False)],
)
async def test_budget_decrease_floors_on_spent_and_meta_daily_minimum(
    live, monkeypatch, spent, budget_minor, allowed
):
    """Never below what the ad set already spent plus Meta's daily minimum for the days
    left; refused before any validate or write reaches Meta."""
    from types import SimpleNamespace

    from qualify_api.ads import live_management as management
    from qualify_api.ads.edit_ledger import revision
    from qualify_api.ads.live_wizard import production_wizard
    from qualify_api.ads.results import ResultsUnavailable

    preview = await prepare(live)
    await confirm(live, preview)
    tenant, actor = live["args"]["tenant_id"], live["args"]["approved_by"]
    promotion = live["repo"].get(tenant, preview.promotion_id)
    if spent:
        # Spent 7.000 of 10.000: test a decrease from a raised 20.000 COP lifetime budget.
        live["remote"].objects[promotion.ids["adsets"]]["lifetime_budget"] = "20000"
        promotion = replace(promotion, request=promotion.request | {"budget_minor": 2_000_000})
    live["remote"].spent = spent
    scope = SimpleNamespace(
        tenant_id=tenant,
        promotion_id=promotion.id,
        connection=SimpleNamespace(connection_id=live["source"].connection_id, version=1),
        account_id=live["source"].ad_account_id,
    )
    monkeypatch.setenv("QUALIFY_OAUTH_STATE_SECRET", "test-management-signing-secret-32-characters")
    monkeypatch.setattr(management, "_scope", lambda *args: scope)
    monkeypatch.setattr(management, "current_acting_login", lambda: actor)
    monkeypatch.setattr(management, "PostgresPromotionRepository", lambda: live["repo"])
    async with production_wizard(tenant, actor) as wizard:
        gateway = wizard.gateway
        monkeypatch.setattr(
            management, "_context", lambda scope: (promotion, revision([]), gateway, live["source"])
        )
        monkeypatch.setattr(management, "_local", lambda *args: None)
        monkeypatch.setattr(gateway, "remote_guard", _no_remote_guard)
        start = len(live["remote"].calls)
        call = management.prepare_promotion_edit(
            tenant_id=tenant,
            promotion_id=promotion.id,
            request_key="edit-down",
            action="budget",
            budget_minor=budget_minor,
        )
        if allowed:
            review = await call
            assert review.new_budget_minor == budget_minor
        else:
            with pytest.raises(ResultsUnavailable, match="Puedes bajarlo hasta"):
                await call
        posts = [c for c in live["remote"].calls[start:] if c[0] == "POST"]
        assert bool(posts) is allowed
        assert all(c[2].get("execution_options") == ["validate_only"] for c in posts)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cap,spent,allowed",
    [(None, 0, True), (60_000, 50_000, True), (60_000, 50_001, False), (5_000, 9_000, False)],
)
async def test_budget_over_the_account_spend_cap_is_refused_before_any_meta_post(
    live, cap, spent, allowed
):
    """The 10.000 COP budget against `spend_cap - amount_spent`, read live in preflight;
    no cap ("0") changes nothing, equal passes, over is refused with no POST at all."""
    remote = live["remote"]
    remote.spend_cap, remote.amount_spent = cap, spent
    if allowed:
        preview = await prepare(live)
        assert preview.promotion_id
        return
    with pytest.raises(WizardUnavailable) as error:
        await prepare(live)
    remaining = "9.999" if cap == 60_000 else "0"
    assert str(error.value) == (
        "Este presupuesto supera lo que le queda al límite de gasto de tu cuenta publicitaria "
        f"(quedan ${remaining} COP). Bájalo o sube el límite en Meta."
    )
    failed = error.value.diagnostics[-1]
    assert failed["key"] == "currency"
    # m-25078366: a machine-readable reason and the billing page of THIS ad account.
    assert failed["reason"] == "spend_cap_exceeded"
    assert failed["billing_url"] == (
        "https://business.facebook.com/billing_hub/accounts?asset_id=12"
    )
    assert not any("reason" in row for row in error.value.diagnostics[:-1])
    assert not [call for call in remote.calls if call[0] == "POST"]


@pytest.mark.asyncio
async def test_spend_cap_is_checked_again_right_before_the_real_create(live):
    """Preflight passes; spend grows before the create: refused with no object created."""
    remote = live["remote"]
    remote.spend_cap = 60_000

    def spend(method, path, params):
        if method == "POST" and path == "act_12/ads" and "execution_options" in params:
            remote.amount_spent = 55_000  # 5.000 left < 10.000

    remote.before_request = spend
    with pytest.raises(WizardUnavailable, match=r"quedan \$5\.000 COP"):
        await prepare(live)
    assert not remote.actual_creates and not remote.activations


@pytest.mark.parametrize(
    "account,room",
    [
        ({"spend_cap": "0", "amount_spent": "5"}, None),
        ({"amount_spent": "5"}, None),
        ({"spend_cap": "10", "amount_spent": None}, None),
        ({"spend_cap": "10", "amount_spent": "4"}, 6),
        ({"spend_cap": "10", "amount_spent": "12"}, 0),
    ],
)
def test_spend_cap_room_follows_meta_semantics(account, room):
    from qualify_api.ads.live_wizard import spend_cap_room

    assert spend_cap_room(account) == room


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "budget_minor,cap,allowed",
    [
        (2_000_000, None, True),  # no cap: unchanged
        (2_000_000, 30_000, True),  # 10.000 unspent + 10.000 raise = 20.000 <= 25.000 left
        (2_000_000, 24_000, False),  # 20.000 > 19.000 left
        (600_000, 5_000, True),  # a decrease is never blocked by the cap
    ],
)
async def test_live_budget_raise_over_the_spend_cap_is_refused_and_a_decrease_never(
    live, monkeypatch, budget_minor, cap, allowed
):
    from types import SimpleNamespace

    from qualify_api.ads import live_management as management
    from qualify_api.ads.edit_ledger import revision
    from qualify_api.ads.live_wizard import production_wizard
    from qualify_api.ads.results import ResultsUnavailable

    preview = await prepare(live)
    await confirm(live, preview)
    tenant, actor = live["args"]["tenant_id"], live["args"]["approved_by"]
    promotion = live["repo"].get(tenant, preview.promotion_id)
    live["remote"].spend_cap, live["remote"].amount_spent = cap, 5_000
    scope = SimpleNamespace(
        tenant_id=tenant,
        promotion_id=promotion.id,
        connection=SimpleNamespace(connection_id=live["source"].connection_id, version=1),
        account_id=live["source"].ad_account_id,
    )
    monkeypatch.setenv("QUALIFY_OAUTH_STATE_SECRET", "test-management-signing-secret-32-characters")
    monkeypatch.setattr(management, "_scope", lambda *args: scope)
    monkeypatch.setattr(management, "current_acting_login", lambda: actor)
    monkeypatch.setattr(management, "PostgresPromotionRepository", lambda: live["repo"])
    async with production_wizard(tenant, actor) as wizard:
        gateway = wizard.gateway
        monkeypatch.setattr(
            management, "_context", lambda scope: (promotion, revision([]), gateway, live["source"])
        )
        monkeypatch.setattr(management, "_local", lambda *args: None)
        monkeypatch.setattr(gateway, "remote_guard", _no_remote_guard)
        start = len(live["remote"].calls)
        call = management.prepare_promotion_edit(
            tenant_id=tenant,
            promotion_id=promotion.id,
            request_key="edit-cap",
            action="budget",
            budget_minor=budget_minor,
        )
        if allowed:
            assert (await call).new_budget_minor == budget_minor
        else:
            with pytest.raises(ResultsUnavailable, match=r"límite de gasto.*\$19\.000 COP\)"):
                await call
        posts = [c for c in live["remote"].calls[start:] if c[0] == "POST"]
        assert bool(posts) is allowed


@pytest.mark.asyncio
async def test_budget_raise_is_refused_when_the_spend_cap_cannot_be_read(live, monkeypatch):
    """Fail closed for money: a Graph error reading the account refuses the raise with the
    module's retry message, and nothing is validated or sent."""
    from types import SimpleNamespace

    from qualify_api.ads import live_management as management
    from qualify_api.ads import results_service
    from qualify_api.ads.edit_ledger import revision
    from qualify_api.ads.live_wizard import production_wizard
    from qualify_api.ads.results import ResultsUnavailable

    preview = await prepare(live)
    await confirm(live, preview)
    tenant, actor = live["args"]["tenant_id"], live["args"]["approved_by"]
    promotion = live["repo"].get(tenant, preview.promotion_id)
    scope = SimpleNamespace(
        tenant_id=tenant,
        promotion_id=promotion.id,
        connection=SimpleNamespace(connection_id=live["source"].connection_id, version=1),
        account_id=live["source"].ad_account_id,
    )
    monkeypatch.setenv("QUALIFY_OAUTH_STATE_SECRET", "test-management-signing-secret-32-characters")
    monkeypatch.setattr(management, "_scope", lambda *args: scope)
    monkeypatch.setattr(management, "current_acting_login", lambda: actor)
    monkeypatch.setattr(management, "PostgresPromotionRepository", lambda: live["repo"])
    async with production_wizard(tenant, actor) as wizard:
        gateway = wizard.gateway
        monkeypatch.setattr(
            management, "_context", lambda scope: (promotion, revision([]), gateway, live["source"])
        )
        monkeypatch.setattr(management, "_local", lambda *args: None)
        monkeypatch.setattr(gateway, "remote_guard", _no_remote_guard)
        live["remote"].account_error = True
        start = len(live["remote"].calls)
        with pytest.raises(ResultsUnavailable) as error:
            await results_service.prepare_promotion_edit(
                tenant_id=tenant,
                promotion_id=promotion.id,
                request_key="edit-cap-error",
                action="budget",
                budget_minor=2_000_000,
            )
        assert str(error.value) == results_service.UNAVAILABLE
        assert not [c for c in live["remote"].calls[start:] if c[0] == "POST"]


async def _no_remote_guard(*args, **kwargs) -> None:
    return None


@pytest.mark.asyncio
async def test_real_production_composition_validates_paused_preview_and_explicit_activation(live):
    preview = await prepare(live)
    assert "$10.000 COP" in preview.charge_notice
    remote = live["remote"]
    assert len(remote.actual_creates) == 4 and not remote.activations
    adset = next(row for row in remote.objects.values() if row["_resource"] == "adsets")
    assert adset["lifetime_budget"] == "10000"  # Meta COP offset=1, not ISO cents.
    row = live["repo"].get(live["args"]["tenant_id"], preview.promotion_id)
    assert row.request["budget_minor"] == 1_000_000 and row.request["meta_currency_offset"] == 1
    review = live["reviews"].get(live["args"]["tenant_id"], preview.review_id)
    proof = review.checks_snapshot["exact_validation"]
    assert valid_receipt(
        proof, live["source"], live["args"]["form"], datetime.now(UTC), live["args"]["approved_by"]
    )
    assert proof["meta_budget"] == 10000 and len(proof["payload_hashes"]) == 4
    result = await confirm(live, preview)
    assert result.status == "active"
    assert [call[1] for call in remote.activations] == ["103", "101", "100"]
    assert all(client._client.is_closed for client in live["clients"])


def _usd(live) -> None:
    """Switch the fixture to a USD ad account (m-25091394): Meta budgets in cents."""
    live["remote"].currency = "USD"
    live["sources"][0] = live["source"] = replace(live["source"], currency="USD")
    live["args"]["form"] = replace(live["args"]["form"], currency="USD", budget_minor=1_050)


@pytest.mark.asyncio
async def test_usd_account_sends_cents_to_meta_and_shows_dollars(live, monkeypatch):
    _usd(live)
    preview = await prepare(live)
    assert "$10,50 USD" in preview.charge_notice
    adset = next(row for row in live["remote"].objects.values() if row["_resource"] == "adsets")
    assert adset["lifetime_budget"] == "1050"  # Meta USD offset=100: cents
    row = live["repo"].get(live["args"]["tenant_id"], preview.promotion_id)
    assert row.request["currency"] == "USD" and row.request["meta_currency_offset"] == 100
    review = live["reviews"].get(live["args"]["tenant_id"], preview.review_id)
    assert review.checks_snapshot["exact_validation"]["meta_budget"] == 1050
    assert (await confirm(live, preview)).status == "active"

    from types import SimpleNamespace

    from qualify_api.ads import live_management as management
    from qualify_api.ads.edit_ledger import revision
    from qualify_api.ads.live_wizard import production_wizard

    tenant, actor = live["args"]["tenant_id"], live["args"]["approved_by"]
    promotion = live["repo"].get(tenant, preview.promotion_id)
    scope = SimpleNamespace(
        tenant_id=tenant,
        promotion_id=promotion.id,
        connection=SimpleNamespace(connection_id=live["source"].connection_id, version=1),
        account_id=live["source"].ad_account_id,
    )
    monkeypatch.setenv("QUALIFY_OAUTH_STATE_SECRET", "test-management-signing-secret-32-characters")
    monkeypatch.setattr(management, "_scope", lambda *args: scope)
    monkeypatch.setattr(management, "current_acting_login", lambda: actor)
    monkeypatch.setattr(management, "PostgresPromotionRepository", lambda: live["repo"])
    async with production_wizard(tenant, actor) as wizard:
        gateway = wizard.gateway
        monkeypatch.setattr(
            management, "_context", lambda scope: (promotion, revision([]), gateway, live["source"])
        )
        monkeypatch.setattr(management, "_local", lambda *args: gateway.local_guard(live["source"]))
        start = len(live["remote"].calls)
        edit = await management.prepare_promotion_edit(
            tenant_id=tenant,
            promotion_id=promotion.id,
            request_key="edit-usd",
            action="budget",
            budget_minor=2_000,
        )
        live["remote"].spent = 347  # cents, like every USD amount Meta returns
        floor = await management.promotion_budget_floor(tenant_id=tenant, promotion_id=promotion.id)
    assert edit.summary == "Cambiar el presupuesto total a $20 USD."
    # The decrease floor converts Meta cents back to hundredths (USD offset 100, not 1).
    assert floor.current_minor == 1_050 and floor.spent_minor == 347
    assert 347 < floor.floor_minor < 400  # + 1 cent a day of Meta's USD minimum
    validated = [call for call in live["remote"].calls[start:] if call[0] == "POST"]
    assert validated and validated[-1][2]["lifetime_budget"] == "2000"


@pytest.mark.asyncio
async def test_unsupported_account_currency_is_refused_before_any_meta_call(live):
    live["sources"][0] = live["source"] = replace(live["source"], currency="VES")
    live["args"]["form"] = replace(live["args"]["form"], currency="VES")
    with pytest.raises(WizardUnavailable, match="dólares o pesos uruguayos"):
        await prepare(live)
    assert live["remote"].calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,key",
    [
        ("payment", "payment"),
        ("owner", "media"),
        ("revoked", "permissions"),
        ("minimum", "validation"),
    ],
)
async def test_live_negative_evidence_prevents_all_creations(live, failure, key):
    remote = live["remote"]
    if failure == "payment":
        remote.payment = False
    elif failure == "owner":
        remote.owner = "999"
    elif failure == "revoked":
        remote.revoked = True
    else:
        remote.reject = "adsets"
    with pytest.raises(WizardUnavailable) as error:
        await prepare(live)
    assert error.value.diagnostics[-1]["key"] == key
    assert "secret" not in str(error.value)
    assert not remote.actual_creates and not remote.activations


@pytest.mark.asyncio
async def test_meta_ignoring_existing_post_cta_stops_before_preview_and_activation(live):
    live["remote"].drop_cta = True
    with pytest.raises(WizardUnavailable, match="no coincide"):
        await prepare(live)
    assert not live["remote"].activations


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["lifetime_budget", "targeting", "end_time"])
async def test_remote_operator_edit_blocks_activation_even_after_fresh_preflight(live, field):
    preview = await prepare(live)
    adset = live["remote"].objects["101"]
    adset[field] = "999999" if field != "targeting" else {"geo_locations": {"countries": ["US"]}}
    with pytest.raises(WizardUnavailable, match="no coincide"):
        await confirm(live, preview)
    assert not live["remote"].activations


@pytest.mark.asyncio
async def test_same_request_rechecks_without_duplicate_remote_objects(live):
    first, second = await prepare(live), await prepare(live)
    assert first.promotion_id == second.promotion_id and first.review_id == second.review_id
    assert len(live["remote"].actual_creates) == 4


@pytest.mark.asyncio
async def test_ambiguous_creation_recovers_by_reads_without_second_create(live):
    live["remote"].ambiguous = "adsets"
    with pytest.raises(WizardUnavailable, match="pendiente"):
        await prepare(live)
    assert len(live["remote"].actual_creates) == 2
    live["remote"].ambiguous = ""
    preview = await prepare(live)
    assert preview.status == "paused"
    assert len(live["remote"].actual_creates) == 4


@pytest.mark.asyncio
async def test_fractional_cop_is_rejected_without_rounding(live):
    live["args"]["form"] = replace(live["args"]["form"], budget_minor=1_000_001)
    with pytest.raises(WizardUnavailable, match="importe exacto"):
        await prepare(live)
    assert not live["remote"].actual_creates


@pytest.mark.asyncio
async def test_actor_or_credential_change_during_read_validation_prevents_creation(live):
    def revoke(method, path, params):
        if method == "POST" and path == "act_12/ads" and "execution_options" in params:
            live["sources"][0] = replace(live["source"], credential_version=2)

    live["remote"].before_request = revoke
    with pytest.raises(WizardUnavailable, match="cambió"):
        await prepare(live)
    assert not live["remote"].actual_creates


def test_cop_offset_uses_verified_meta_subdivision_not_iso_decimals():
    assert production_currency_offset("COP") == 1
    assert production_currency_offset("USD") == 100
    assert production_currency_offset("UYU") == 100
    assert production_currency_offset("VES") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["budget", "actor", "credential", "extra_adset", "extra_ad"])
async def test_change_after_first_child_activation_audits_unknown_and_never_enables_campaign(
    live, change
):
    preview = await prepare(live)

    def change_after_child(method, path, params):
        if method == "POST" and path == "103" and params.get("status") == "ACTIVE":
            if change == "budget":
                live["remote"].objects["101"]["lifetime_budget"] = "9999999"
            elif change == "actor":
                live["actor"][0] = False
            elif change in {"extra_adset", "extra_ad"}:
                live["remote"].objects["999"] = {
                    "id": "999",
                    "_resource": "adsets" if change == "extra_adset" else "ads",
                    "campaign_id": "100",
                    "adset_id": "101",
                    "status": "ACTIVE",
                }
            else:
                live["credential"][0] = False

    live["remote"].before_request = change_after_child
    result = await confirm(live, preview)
    assert result.status == "unknown"
    assert live["remote"].objects["100"]["status"] == "PAUSED"
    assert [call[1] for call in live["remote"].activations] == ["103"]
    review = live["reviews"].get(live["args"]["tenant_id"], preview.review_id)
    assert review.state == "unknown" and review.claim_token is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["creation", "activation"])
async def test_proof_expiry_during_actual_client_cooldown_stops_post_after_wait(live, stage):
    if stage == "creation":
        live["cooldown"][0] = 360.0
        with pytest.raises(WizardUnavailable, match="venció"):
            await prepare(live)
        assert not live["remote"].actual_creates
    else:
        preview = await prepare(live)
        live["cooldown"][0] = 360.0
        result = await confirm(live, preview)
        assert result.status == "unknown"
        assert not live["remote"].activations


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["credential", "policy"])
async def test_final_validate_response_cannot_race_credential_or_policy_revocation(live, change):
    count = [0]

    def revoke_after_last_validate(method, path, params):
        if method == "POST" and path == "act_12/campaigns" and "execution_options" in params:
            count[0] += 1
            # Initial preflight, actual-step validation, then final after-cooldown validation.
            if count[0] == 3:
                if change == "credential":
                    live["credential"][0] = False
                else:
                    live["repo"].enhancement_policies = lambda tenant, brand: (
                        BrandEnhancementSettings(tenant, brand, version=1)
                    )

    live["remote"].before_request = revoke_after_last_validate
    with pytest.raises(WizardUnavailable):
        await prepare(live)
    assert count[0] == 3 and not live["remote"].actual_creates


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["actor", "meta_budget", "currency_offset", "payload_hashes"])
async def test_exact_validation_receipt_cannot_be_rebound_or_change_money(live, field):
    preview = await prepare(live)
    proof = deepcopy(
        live["reviews"]
        .get(live["args"]["tenant_id"], preview.review_id)
        .checks_snapshot["exact_validation"]
    )
    proof[field] = "wrong" if field == "actor" else {} if field == "payload_hashes" else 100
    assert not valid_receipt(
        proof, live["source"], live["args"]["form"], datetime.now(UTC), live["args"]["approved_by"]
    )


@pytest.mark.asyncio
async def test_unexpected_guard_failure_after_child_activation_returns_typed_unknown(live):
    preview = await prepare(live)
    child_started = [False]

    def fail_after_child(method, path, params):
        if method == "POST" and path == "103" and params.get("status") == "ACTIVE":
            child_started[0] = True
        elif child_started[0] and method == "GET":
            raise RuntimeError("private internal failure must never reach client")

    live["remote"].before_request = fail_after_child
    result = await confirm(live, preview)
    assert result.status == "unknown" and "private" not in result.message
    assert [call[1] for call in live["remote"].activations] == ["103"]
    assert live["remote"].objects["100"]["status"] == "PAUSED"
    assert live["reviews"].get(live["args"]["tenant_id"], preview.review_id).state == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("all_finishes_fail", [False, True])
async def test_audit_failure_after_campaign_active_is_unknown_and_recovery_never_reposts(
    live, all_finishes_fail
):
    preview = await prepare(live)
    finish = live["reviews"].finish

    def failing_finish(tenant_id, review_id, token, state):
        if state == "active" or all_finishes_fail:
            raise RuntimeError("private persistence failure")
        finish(tenant_id, review_id, token, state)

    live["reviews"].finish = failing_finish
    result = await confirm(live, preview)
    assert result.status == "unknown" and "private" not in result.message
    assert live["remote"].objects["100"]["status"] == "ACTIVE"
    assert [call[1] for call in live["remote"].activations] == ["103", "101", "100"]
    review = live["reviews"].get(live["args"]["tenant_id"], preview.review_id)
    assert review.state == ("in_flight" if all_finishes_fail else "unknown")
    before = list(live["remote"].activations)
    again = await confirm(live, preview)
    assert again.status == "unknown" and live["remote"].activations == before


def use_lead_form(live, **changes):
    from qualify_api.ads.lead_ads import LeadFormTarget

    source = live["source"]
    target = LeadFormTarget(uuid4(), "555", "77", source.connection_id, source.brand_id, 1)
    form = replace(
        live["args"]["form"],
        link_url="",
        lead_form=replace(target, **changes),
        lead_cta="GET_QUOTE",
    )
    live["args"]["form"] = form


@pytest.mark.asyncio
async def test_lead_campaign_validates_exact_payloads_creates_paused_and_activates_on_consent(
    live,
):
    use_lead_form(live)
    remote = live["remote"]
    preview = await prepare(live)
    validated = {
        call[1].split("/")[-1]: call[2]
        for call in remote.calls
        if call[2].get("execution_options") == ["validate_only"]
    }
    assert validated["campaigns"]["objective"] == "OUTCOME_LEADS"
    assert validated["adcreatives"]["call_to_action"] == {
        "type": "GET_QUOTE",
        "value": {"lead_gen_form_id": "555"},
    }
    assert len(remote.actual_creates) == 4 and not remote.activations
    adset = next(row for row in remote.objects.values() if row["_resource"] == "adsets")
    assert adset["destination_type"] == "ON_AD"
    assert adset["promoted_object"] == {"page_id": "77"}
    assert adset["optimization_goal"] == "LEAD_GENERATION"
    result = await confirm(live, preview)
    assert result.status == "active"
    assert [call[1] for call in remote.activations] == ["103", "101", "100"]


@pytest.mark.asyncio
async def test_campaign_sends_adset_budget_sharing_false_in_validation_and_create(live):
    """m-25091386: v24+ requires the flag when the budget lives on the ad set."""
    remote = live["remote"]
    await prepare(live)
    validated = {
        call[1].split("/")[-1]: call[2]
        for call in remote.calls
        if call[2].get("execution_options") == ["validate_only"]
    }
    created = next(call[2] for call in remote.actual_creates if call[1] == "act_12/campaigns")
    # On the wire as the literal `false`, both in validate_only and in the real create.
    assert validated["campaigns"]["is_adset_budget_sharing_enabled"] == "false"
    assert created["is_adset_budget_sharing_enabled"] == "false"
    assert {k: v for k, v in validated["campaigns"].items() if k != "execution_options"} == created


@pytest.mark.asyncio
async def test_lead_campaign_remote_form_swap_blocks_activation(live):
    use_lead_form(live)
    preview = await prepare(live)
    creative = live["remote"].objects["102"]
    creative["call_to_action"] = {"type": "GET_QUOTE", "value": {"lead_gen_form_id": "556"}}
    with pytest.raises(WizardUnavailable, match="no coincide"):
        await confirm(live, preview)
    assert not live["remote"].activations


@pytest.mark.asyncio
async def test_lead_form_of_another_page_is_rejected_before_any_meta_call(live):
    use_lead_form(live, page_id="78")
    with pytest.raises(WizardUnavailable, match="formulario"):
        await prepare(live)
    assert not live["remote"].calls


@pytest.mark.asyncio
async def test_budget_floor_read_shows_minimum_and_spent_without_writing(live, monkeypatch):
    """m-25026344: the screen shows the same floor a decrease enforces, before any edit."""
    from types import SimpleNamespace

    from qualify_api.ads import live_management as management
    from qualify_api.ads.edit_ledger import revision
    from qualify_api.ads.live_wizard import production_wizard

    preview = await prepare(live)
    await confirm(live, preview)
    tenant, actor = live["args"]["tenant_id"], live["args"]["approved_by"]
    promotion = live["repo"].get(tenant, preview.promotion_id)
    live["remote"].objects[promotion.ids["adsets"]]["lifetime_budget"] = "20000"
    promotion = replace(promotion, request=promotion.request | {"budget_minor": 2_000_000})
    live["remote"].spent = 7000
    scope = SimpleNamespace(tenant_id=tenant, promotion_id=promotion.id)
    monkeypatch.setattr(management, "_scope", lambda *args: scope)
    async with production_wizard(tenant, actor) as wizard:
        gateway = wizard.gateway
        monkeypatch.setattr(
            management, "_context", lambda scope: (promotion, revision([]), gateway, live["source"])
        )
        start = len(live["remote"].calls)
        floor = await management.promotion_budget_floor(tenant_id=tenant, promotion_id=promotion.id)
    assert floor.current_minor == 2_000_000
    assert floor.spent_minor == 700_000
    # The decrease test above refuses 990_000 and accepts 1_000_000 for this same setup.
    assert floor.floor_minor == 1_000_000
    assert not [c for c in live["remote"].calls[start:] if c[0] == "POST"]


# --- Ads that open a chat (m-24828980) ---


def use_chat(live, monkeypatch, destination="WHATSAPP", *, greeting=True):
    from qualify_api.ads import messaging_destinations
    from qualify_api.ads.messaging import MessagingTarget
    from qualify_api.ads.messaging_greeting import MessageGreeting

    source = live["source"]
    whatsapp = destination == "WHATSAPP"
    target = MessagingTarget(
        destination,
        source.connection_id,
        uuid4() if whatsapp else source.connection_id,
        "77",
        1,
        1,
        "555" if whatsapp else "",
        "573001112233" if whatsapp else "",
    )
    current = [target]

    async def check(*, tenant_id, source, destination):
        if isinstance(current[0], Exception):
            raise current[0]
        return current[0]

    monkeypatch.setattr(messaging_destinations, "resolve_messaging_target", check)
    welcome = (
        MessageGreeting(
            uuid4(), source.brand_id, 1, "¡Hola! ¿En qué te ayudamos?", ("¿Hacen domicilios?",)
        )
        if greeting
        else None
    )
    live["args"]["form"] = replace(
        live["args"]["form"], link_url="", messaging=target, greeting=welcome
    )
    return current


@pytest.mark.asyncio
async def test_whatsapp_chat_campaign_validates_creates_paused_and_activates_on_consent(
    live, monkeypatch
):
    use_chat(live, monkeypatch)
    remote = live["remote"]
    preview = await prepare(live)
    validated = {
        call[1].split("/")[-1]: call[2]
        for call in remote.calls
        if call[2].get("execution_options") == ["validate_only"]
    }
    assert validated["campaigns"]["objective"] == "OUTCOME_ENGAGEMENT"
    creative = validated["adcreatives"]
    assert creative["call_to_action"] == {
        "type": "WHATSAPP_MESSAGE",
        "value": {"link": "https://api.whatsapp.com/send", "app_destination": "WHATSAPP"},
    }
    assert creative["object_id"] == "77" and creative["source_instagram_media_id"] == "88"
    welcome = creative["page_welcome_message"]  # The fake parses the JSON string.
    assert welcome["text_format"]["customer_action_type"] == "ice_breakers"
    assert welcome["text_format"]["message"] == {
        "text": "¡Hola! ¿En qué te ayudamos?",
        "ice_breakers": [{"title": "¿Hacen domicilios?"}],
    }
    assert len(remote.actual_creates) == 4 and not remote.activations
    adset = next(row for row in remote.objects.values() if row["_resource"] == "adsets")
    assert adset["destination_type"] == "WHATSAPP"
    assert adset["optimization_goal"] == "CONVERSATIONS"
    assert adset["billing_event"] == "IMPRESSIONS"
    assert adset["promoted_object"] == {"page_id": "77", "whatsapp_phone_number": "573001112233"}
    assert all(
        row["status"] == "PAUSED"
        for row in remote.objects.values()
        if row["_resource"] != "adcreatives"
    )
    stored = live["repo"].get(live["args"]["tenant_id"], preview.promotion_id)
    assert stored.request["greeting_snapshot"]["questions"] == ["¿Hacen domicilios?"]
    result = await confirm(live, preview)
    assert result.status == "active"
    assert [call[1] for call in remote.activations] == ["103", "101", "100"]


@pytest.mark.asyncio
async def test_instagram_direct_without_greeting_sends_no_welcome_message(live, monkeypatch):
    use_chat(live, monkeypatch, "INSTAGRAM_DIRECT", greeting=False)
    preview = await prepare(live)
    objects = live["remote"].objects.values()
    creative = next(r for r in objects if r["_resource"] == "adcreatives")
    assert creative["call_to_action"] == {
        "type": "INSTAGRAM_MESSAGE",
        "value": {"link": "https://www.instagram.com"},
    }
    assert "page_welcome_message" not in creative
    adset = next(r for r in objects if r["_resource"] == "adsets")
    assert adset["promoted_object"] == {"page_id": "77"}
    assert adset["destination_type"] == "INSTAGRAM_DIRECT"
    assert (await confirm(live, preview)).status == "active"


@pytest.mark.asyncio
async def test_unlinked_whatsapp_number_never_reaches_meta(live, monkeypatch):
    from qualify_api.ads.messaging_destinations import LINK_GUIDE

    current = use_chat(live, monkeypatch)
    current[0] = WizardUnavailable(LINK_GUIDE)
    with pytest.raises(WizardUnavailable, match="no está unido a tu página"):
        await prepare(live)
    assert not live["remote"].calls


@pytest.mark.asyncio
async def test_number_changed_after_approval_blocks_activation(live, monkeypatch):
    current = use_chat(live, monkeypatch)
    preview = await prepare(live)
    current[0] = replace(current[0], whatsapp_phone_number="573009999999")
    with pytest.raises(WizardUnavailable, match="chat del anuncio cambió"):
        await confirm(live, preview)
    assert not live["remote"].activations


@pytest.mark.asyncio
@pytest.mark.parametrize("goal", ["chat", "website", "lead"])
async def test_a_piece_chat_button_only_refuses_goals_that_use_it(live, monkeypatch, goal):
    from qualify_api.ads.wizard import PIECE_BUTTON_LEAD, PIECE_BUTTON_UNSUPPORTED

    live["sources"][0] = replace(live["source"], unavailable_reason=PIECE_BUTTON_UNSUPPORTED)
    if goal == "chat":
        use_chat(live, monkeypatch)
        preview = await prepare(live)
        assert (await confirm(live, preview)).status == "active"
        return
    if goal == "lead":
        use_lead_form(live)
    expected = PIECE_BUTTON_LEAD if goal == "lead" else PIECE_BUTTON_UNSUPPORTED
    with pytest.raises(WizardUnavailable) as error:
        await prepare(live)
    assert str(error.value) == expected and not live["remote"].calls


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["budget", "end_time", "resume"])
async def test_editing_a_chat_promotion_whose_piece_has_a_whatsapp_button(
    live, monkeypatch, action
):
    """The real management `_context` builds the gateway with the promotion's goal."""
    from contextlib import contextmanager
    from types import SimpleNamespace

    from qualify_api.ads import live_management as management
    from qualify_api.ads import live_wizard
    from qualify_api.ads.edit_ledger import revision
    from qualify_api.ads.wizard import PIECE_BUTTON_UNSUPPORTED

    live["sources"][0] = replace(live["source"], unavailable_reason=PIECE_BUTTON_UNSUPPORTED)
    use_chat(live, monkeypatch)
    preview = await prepare(live)
    await confirm(live, preview)
    tenant, actor = live["args"]["tenant_id"], live["args"]["approved_by"]
    promotion = replace(live["repo"].get(tenant, preview.promotion_id), status="active")
    scope = SimpleNamespace(
        tenant_id=tenant,
        promotion_id=promotion.id,
        connection=SimpleNamespace(connection_id=live["source"].connection_id, version=1),
        account_id=live["source"].ad_account_id,
    )
    if action == "resume":
        for resource in ("campaigns", "adsets", "ads"):
            live["remote"].objects[promotion.ids[resource]]["status"] = "PAUSED"

    @contextmanager
    def session(*args, **kwargs):
        yield SimpleNamespace(
            scalar=lambda *args, **kwargs: True,  # The activation consent exists.
            execute=lambda *args, **kwargs: SimpleNamespace(
                mappings=lambda: SimpleNamespace(first=lambda: None)
            ),
        )

    monkeypatch.setenv("QUALIFY_OAUTH_STATE_SECRET", "test-management-signing-secret-32-characters")
    monkeypatch.setattr(management, "tenant_session", session)
    monkeypatch.setattr(management, "_scope", lambda *args: scope)
    monkeypatch.setattr(management, "_actor", lambda *args: actor)
    monkeypatch.setattr(management, "current_acting_login", lambda: actor)
    monkeypatch.setattr(
        management,
        "PostgresPromotionRepository",
        lambda: SimpleNamespace(get=lambda *args: promotion),
    )
    monkeypatch.setattr(management, "effective", lambda tenant, original: (original, revision([])))
    monkeypatch.setattr(management, "PersistedWizardSources", live_wizard.PersistedWizardSources)
    monkeypatch.setattr(management, "authorize_actor", live_wizard.authorize_actor)
    monkeypatch.setattr(management, "_load", lambda *args: None)
    monkeypatch.setattr(
        management, "_local", lambda scope, gateway, source, *rest: gateway.local_guard(source)
    )
    monkeypatch.setattr(management, "_claim_pause", lambda *args, **kwargs: (uuid4(), "claimed"))
    monkeypatch.setattr(management, "_dispatch", lambda *args: None)
    monkeypatch.setattr(management, "_finish_pause", lambda *args: None)
    assert management._context(scope)[2].goal == "chat"
    options = {
        "budget": {"budget_minor": 2_000_000},
        "end_time": {"end_time": live["args"]["form"].end_time + timedelta(days=1)},
    }.get(action, {})
    review = await management.prepare_promotion_edit(
        tenant_id=tenant,
        promotion_id=promotion.id,
        request_key="chat-edit",
        action=action,
        **options,
    )
    result = await management.confirm_promotion_edit(
        tenant_id=tenant,
        promotion_id=promotion.id,
        request_key="chat-edit",
        approval_token=review.approval_token,
        confirm_change=True,
    )
    assert result.status == "completed"


@pytest.mark.asyncio
async def test_read_back_accepts_the_number_echoed_with_a_plus(live, monkeypatch):
    use_chat(live, monkeypatch)
    preview = await prepare(live)
    live["remote"].objects["101"]["promoted_object"] = {
        "page_id": "77",
        "whatsapp_phone_number": "+57 300 111 2233",
    }
    assert (await confirm(live, preview)).status == "active"


@pytest.mark.asyncio
async def test_website_promotion_never_reads_or_compares_a_welcome_message(live):
    preview = await prepare(live)
    # Only a requested field comes back: a stray welcome on a website ad is never read.
    live["remote"].objects["102"]["page_welcome_message"] = "{}"
    assert (await confirm(live, preview)).status == "active"


@pytest.mark.asyncio
async def test_remote_greeting_edit_blocks_activation(live, monkeypatch):
    use_chat(live, monkeypatch)
    preview = await prepare(live)
    creative = live["remote"].objects["102"]
    creative["page_welcome_message"]["text_format"]["message"]["text"] = "Otro saludo"
    with pytest.raises(WizardUnavailable, match="saludo del chat distinto"):
        await confirm(live, preview)
    assert not live["remote"].activations


# m-24828977: a radius around a map point and interests reach the live path.


def use_point_and_interests(live, *, radius_km=3, statuses=("active", "active"), **changes):
    from qualify_api.ads.audience import InterestOption, MapPoint

    interests = tuple(
        InterestOption(key, name, status)
        for (key, name), status in zip((("6003", "Café"), ("6004", "Té")), statuses, strict=True)
    )
    live["remote"].interests = {item.id: (True, "NORMAL") for item in interests}
    audience = AudienceDraft(
        location=LocationOption("CO", "Colombia", "country", "CO"),
        point=MapPoint(7.893907, -72.507821, "Calle 10 # 5-20, Cúcuta"),
        radius_km=radius_km,
        interests=interests,
        **changes,
    )
    live["args"]["form"] = replace(live["args"]["form"], audience=audience)
    return audience


APPROVED_GEO = {
    "custom_locations": [
        {"latitude": 7.893907, "longitude": -72.507821, "radius": 3, "distance_unit": "kilometer"}
    ]
}


@pytest.mark.asyncio
async def test_point_radius_and_interests_validate_create_paused_and_activate(live):
    use_point_and_interests(live)
    remote = live["remote"]
    preview = await prepare(live)
    assert preview.status == "paused" and not remote.activations
    validated = [c for c in remote.calls if c[2].get("execution_options") == ["validate_only"]]
    adset_checks = [c[2]["targeting"] for c in validated if c[1] == "act_12/adsets"]
    created = next(row for row in remote.objects.values() if row["_resource"] == "adsets")
    for targeting in [*adset_checks, created["targeting"]]:
        assert targeting["geo_locations"] == APPROVED_GEO
        assert targeting["flexible_spec"] == [{"interests": [{"id": "6003"}, {"id": "6004"}]}]
    # Both interests were re-confirmed live before any write.
    first_post = next(i for i, c in enumerate(remote.calls) if c[0] == "POST")
    assert any(c[1] == "act_12/targetingvalidation" for c in remote.calls[:first_post])
    row = live["repo"].get(live["args"]["tenant_id"], preview.promotion_id)
    assert row.request["audience_snapshot"]["point"]["latitude"] == 7.893907
    result = await confirm(live, preview)
    # The fake returns only requested fields, so activating proves `targeting` was asked for.
    assert result.status == "active"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "remote_targeting",
    [
        {"geo_locations": {**APPROVED_GEO, "location_types": ["home", "recent"]}},
        {
            "geo_locations": {
                "custom_locations": [
                    {
                        "latitude": "7.8939070000001",
                        "longitude": -72.507821,
                        "radius": 3.0,
                        "distance_unit": "kilometer",
                        "name": "Cúcuta",
                        "country": "CO",
                    }
                ]
            },
            "flexible_spec": [
                {"interests": [{"id": "6004", "name": "Té"}, {"id": "6003", "name": "Café"}]}
            ],
        },
    ],
)
async def test_read_back_accepts_only_documented_normalizations(live, remote_targeting):
    use_point_and_interests(live)
    preview = await prepare(live)
    adset = live["remote"].objects["101"]
    adset["targeting"] = {**adset["targeting"], **remote_targeting}
    assert (await confirm(live, preview)).status == "active"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "radius",
        "unit",
        "point",
        "missing_interest",
        "extra_interest",
        "other_interest",
        "extra_location",
        "location_types",
        "unknown_key",
        "unknown_location_key",
        "interest_extra_key",
    ],
)
async def test_read_back_refuses_another_location_or_interest_set(live, change):
    use_point_and_interests(live)
    preview = await prepare(live)
    targeting = live["remote"].objects["101"]["targeting"]
    place = targeting["geo_locations"]["custom_locations"][0]
    interests = targeting["flexible_spec"][0]["interests"]
    if change == "radius":
        place["radius"] = 4
    elif change == "unit":
        place["distance_unit"] = "mile"
    elif change == "point":
        place["latitude"] = 7.894907
    elif change == "missing_interest":
        interests.pop()
    elif change == "extra_interest":
        interests.append({"id": "6005"})
    elif change == "other_interest":
        interests[1] = {"id": "6005"}
    elif change == "extra_location":
        targeting["geo_locations"]["countries"] = ["CO"]
    elif change == "location_types":
        targeting["geo_locations"]["location_types"] = ["travel_in"]
    elif change == "unknown_key":
        targeting["excluded_custom_audiences"] = [{"id": "1"}]
    elif change == "unknown_location_key":
        place["address_string"] = "Otra dirección"
    else:
        interests[0]["topic"] = "Comida"
    with pytest.raises(WizardUnavailable, match="no coincide"):
        await confirm(live, preview)
    assert not live["remote"].activations


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "remote_status", [(True, "DEPRECATING"), (False, "NORMAL"), (True, "NON-DELIVERABLE")]
)
async def test_retired_interest_on_meta_blocks_before_any_write(live, remote_status):
    use_point_and_interests(live)
    live["remote"].interests["6004"] = remote_status
    with pytest.raises(
        WizardUnavailable,
        match="ya no permite usar estos intereses: Té\\. Vuelve a «¿A quién quieres llegar\\?»",
    ):
        await prepare(live)
    assert not [c for c in live["remote"].calls if c[0] == "POST"]


@pytest.mark.asyncio
async def test_interest_missing_from_status_answer_blocks(live):
    use_point_and_interests(live)
    del live["remote"].interests["6003"]
    with pytest.raises(WizardUnavailable, match="Café"):
        await prepare(live)
    assert not [c for c in live["remote"].calls if c[0] == "POST"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "setup,message",
    [
        ({"statuses": ("active", "retiring")}, "ya no permite usar estos intereses: Té"),
        ({"statuses": ("unavailable", "active")}, "ya no permite usar estos intereses: Café"),
        ({"housing": True}, "Vivienda"),
        ({"advantage_audience": True}, "público ampliado"),
    ],
)
async def test_supported_still_refuses_before_any_meta_call(live, setup, message):
    use_point_and_interests(live, **setup)
    form = live["args"]["form"]
    live["args"]["form"] = replace(
        form,
        housing=form.audience.housing,
        advantage_audience=form.audience.advantage_audience,
    )
    with pytest.raises(WizardUnavailable, match=message):
        await prepare(live)
    assert not live["remote"].calls


@pytest.mark.asyncio
async def test_city_radius_follows_meta_minimum(live):
    city = LocationOption("123", "Bogotá", "city", "CO")
    live["args"]["form"] = replace(
        live["args"]["form"], audience=AudienceDraft(location=city, radius_km=10)
    )
    with pytest.raises(WizardUnavailable, match="la distancia mínima es 17 km"):
        await prepare(live)
    assert not live["remote"].calls
    live["args"]["form"] = replace(
        live["args"]["form"], audience=AudienceDraft(location=city, radius_km=17)
    )
    preview = await prepare(live)
    adset = live["remote"].objects["101"]
    assert adset["targeting"]["geo_locations"] == {
        "cities": [{"key": "123", "radius": 17, "distance_unit": "kilometer"}]
    }
    adset["targeting"]["geo_locations"]["cities"][0].update(
        name="Bogotá", region="Bogotá D.C.", region_id="2", country="CO"
    )
    assert (await confirm(live, preview)).status == "active"


def test_read_back_comparator_without_a_meta_round_trip():
    from qualify_api.ads.live_wizard import same_targeting

    approved = {"geo_locations": deepcopy(APPROVED_GEO), "age_min": 18}
    assert same_targeting(deepcopy(approved), approved)
    assert not same_targeting(None, approved)
    assert not same_targeting({"geo_locations": deepcopy(APPROVED_GEO)}, approved)
    observed = deepcopy(approved)
    observed["geo_locations"]["custom_locations"][0]["longitude"] = True
    assert not same_targeting(observed, approved)
    observed["geo_locations"]["custom_locations"][0]["longitude"] = "nan"
    assert not same_targeting(observed, approved)
    observed["geo_locations"]["custom_locations"][0]["longitude"] = -72.507821 + 4e-7
    assert same_targeting(observed, approved)  # float serialization, same 6-decimal point
    observed["geo_locations"]["custom_locations"][0]["longitude"] = -72.507821 + 6e-7
    assert not same_targeting(observed, approved)
