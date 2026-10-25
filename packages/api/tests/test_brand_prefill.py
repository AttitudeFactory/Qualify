"""`brand_prefill.prefill_brand_kit` (m-24852197, PB-3): the Brand Kit proposed from the
brand's own account, without Reflex.

Offline: Scrape Creators and the profile picture's CDN answer from recorded-shape bodies
(`fixtures/scrapecreators/`) through an `httpx.MockTransport`; Claude is a fake with the
`from_profile.generate` signature; the claim, the cache and the Brand Kit store are
in-memory. What is pinned: the outcomes PB-4 writes its comment from, the per-run cap,
that the proposal goes only to `connect.prefill`, the provenance and the usage counts,
and that every outside call carries the run's own tenant. The real store and claim
under RLS are the `db` test at the bottom."""

from __future__ import annotations

import io
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from PIL import Image, ImageDraw

from qualify_api.claude_tools import CallStats, MissingAPIKey
from qualify_api.creative import brand_prefill, brand_prefill_review
from qualify_api.creative.account_claims import AccountTaken
from qualify_api.creative.brand_kit_store import BrandKitDetails, carry_reserved
from qualify_api.creative.brand_prefill import (
    CallCaps,
    PrefillOutcome,
    PrefillPorts,
    prefill_brand_kit,
)
from qualify_api.hashtags import MemoryHashtagRepository, from_profile
from qualify_api.hashtags import ai as hashtag_ai
from qualify_api.hashtags import catalog as hashtag_catalog

FIXTURES = Path(__file__).parent / "fixtures" / "scrapecreators"
TENANT = UUID("c0000000-0000-4000-8000-0000000000b3")
BRAND = UUID("b0000000-0000-4000-8000-0000000000b3")
PICTURE = "https://scontent.cdninstagram.com/v/t51.2885-19/heladeria_demo.jpg"
STATS = CallStats("claude-sonnet-5", "claude-sonnet-5-20261001", 1200, 300, 0, 1, 1)


@pytest.fixture(autouse=True)
def _keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "sk_test_prefill")
    # the catalog's own Claude key and its process memory: never the developer's
    monkeypatch.delenv("QUALIFY_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(hashtag_catalog, "_seeded", False)
    monkeypatch.setattr(hashtag_catalog, "_choices", {})


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _png(*fills: str) -> bytes:
    image = Image.new("RGB", (100 * len(fills), 100), "white")
    draw = ImageDraw.Draw(image)
    for i, fill in enumerate(fills):
        draw.rectangle((i * 100 + 10, 10, i * 100 + 90, 90), fill=fill)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


class Vendor:
    """Scrape Creators + the CDN, replayed from the fixtures; every request recorded."""

    def __init__(self, profile: str = "instagram_profile_heladeria.json") -> None:
        self.profile = _fixture(profile)
        self.posts = _fixture("instagram_posts_heladeria.json")
        now = int(time.time())
        for item in self.posts["items"]:  # relative hours → inside the 7-day window
            item["taken_at"] = now + int(item["taken_at"]) * 3600
        self.requests: list[str] = []
        self.status: dict[str, int] = {}
        self.picture = _png("#be123c", "#0f766e")

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(f"{request.url.host}{request.url.path}")
        path = request.url.path
        if request.url.host == "scontent.cdninstagram.com":
            return httpx.Response(200, content=self.picture, headers={"content-type": "image/png"})
        if path in self.status:
            return httpx.Response(self.status[path], json={"success": False, "error": "nope"})
        if path == "/v1/instagram/profile":
            return httpx.Response(200, json=self.profile)
        if path == "/v2/instagram/user/posts":
            return httpx.Response(200, json=self.posts)
        return httpx.Response(404, json={"success": False})

    @property
    def vendor_requests(self) -> list[str]:
        return [r for r in self.requests if r.startswith("api.scrapecreators.com")]


class Claims:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.taken = False
        self.newly = True

    def claim(self, *a: Any) -> bool:
        self.calls.append(("claim", a))
        if self.taken:
            raise AccountTaken("instagram")
        return self.newly

    def release(self, *a: Any) -> None:
        self.calls.append(("release", a))

    def keep_only(self, *a: Any) -> None:
        self.calls.append(("keep_only", a))


class Cache:
    def __init__(self) -> None:
        self.entries: dict[tuple[UUID, str, str], dict[str, Any]] = {}
        self.tenants: list[UUID] = []

    def get(self, tenant_id: UUID, network: str, handle: str) -> dict[str, Any] | None:
        self.tenants.append(tenant_id)
        return self.entries.get((tenant_id, network, handle))

    def put(self, tenant_id: UUID, network: str, handle: str, profile: dict[str, Any]) -> None:
        self.tenants.append(tenant_id)
        self.entries[(tenant_id, network, handle)] = profile


class Store:
    """`BrandKitStore`'s details half, in memory, with the same reserved-key rule."""

    def __init__(self) -> None:
        self.rows: dict[tuple[UUID, UUID], BrandKitDetails] = {}
        self.tenants: list[UUID] = []
        self.saved: list[dict[str, Any]] = []
        self.before_write: Callable[[], None] | None = None

    def load_details(self, *, tenant_id: UUID, brand_id: UUID) -> BrandKitDetails:
        self.tenants.append(tenant_id)
        return self.rows.get((tenant_id, brand_id), BrandKitDetails())

    def save_details(
        self, *, tenant_id: UUID, brand_id: UUID, user_id: UUID | None, documents: dict
    ) -> None:
        self.tenants.append(tenant_id)
        self.saved.append(dict(documents))
        row = self.rows.get((tenant_id, brand_id), BrandKitDetails())
        values = {
            name: carry_reserved(name, getattr(row, name), documents.get(name, getattr(row, name)))
            for name in ("logo_brief", "connect", "profile")
        }
        self.rows[(tenant_id, brand_id)] = BrandKitDetails(**values)

    def set_document_key(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        document: str,
        key: str,
        value: Any,
        keep_current: Any = None,
    ) -> bool:
        """One key, over what the row holds NOW (the real one locks the row)."""
        self.tenants.append(tenant_id)
        if self.before_write is not None:
            self.before_write()  # e.g. the owner saving while the run was working
        row = self.rows.get((tenant_id, brand_id), BrandKitDetails())
        values = {name: dict(getattr(row, name)) for name in ("logo_brief", "connect", "profile")}
        if keep_current is not None and keep_current(values[document].get(key)):
            return False
        self.saved.append({document: {key: value}})
        values[document][key] = value
        self.rows[(tenant_id, brand_id)] = BrandKitDetails(**values)
        return True


class Claude:
    """`from_profile.generate`'s signature; the answer is set per test."""

    def __init__(self, rubro: str = "heladería de yogur", tags: tuple[str, ...] = ()) -> None:
        self.calls: list[from_profile.AccountText] = []
        self.rubro = rubro
        self.tags = tags

    def __call__(
        self, account: from_profile.AccountText, *, api_key: str, max_tags: int
    ) -> from_profile.Proposal:
        assert api_key == "sk-ant-test"
        self.calls.append(account)
        tags = tuple(from_profile.ProposedTag(t, "Lo dice la cuenta.") for t in self.tags)
        return from_profile.Proposal(tags, STATS, "ai", STATS.model_revision or "", self.rubro)


class World:
    def __init__(self, profile: str = "instagram_profile_heladeria.json") -> None:
        self.vendor = Vendor(profile)
        self.claims = Claims()
        self.cache = Cache()
        self.store = Store()
        self.claude = Claude()
        self.api_key: Callable[[], str] = lambda: "sk-ant-test"
        #: None skips the catalog step; tests of that step set a `CatalogHashtags`.
        self.catalog: Any = None

    def ports(self, **overrides: Any) -> PrefillPorts:
        values: dict[str, Any] = {
            "claims": self.claims,
            "cache": self.cache,
            "store": self.store,
            "generate": self.claude,
            "api_key": lambda: self.api_key(),
            "transport": httpx.MockTransport(self.vendor.handler),
            "catalog": self.catalog,
        }
        return PrefillPorts(**(values | overrides))

    def run(self, handle: str = "@Heladeria.Demo", **kw: Any) -> brand_prefill.PrefillResult:
        ports = kw.pop("ports", None) or self.ports()
        return prefill_brand_kit(TENANT, BRAND, "instagram", handle, ports=ports, **kw)

    def prefill(self) -> dict[str, Any]:
        return self.store.rows[(TENANT, BRAND)].connect[brand_prefill.PREFILL_KEY]


@pytest.fixture
def world() -> World:
    return World()


# --------------------------------------------------------------------------------------
# ok: what is proposed, and where
# --------------------------------------------------------------------------------------


def test_a_public_account_becomes_a_proposal_in_connect_prefill_only(world: World) -> None:
    world.store.rows[(TENANT, BRAND)] = BrandKitDetails(
        connect={"rubro_text": "lo que el dueño escribió", "voice_configured": True},
        profile={"username": "anterior"},
    )
    result = world.run(source={"kind": "alta", "meegle_work_item_id": 24852197})

    assert result.outcome is PrefillOutcome.OK and result.written
    details = world.store.rows[(TENANT, BRAND)]
    # what generation reads is untouched: the proposal waits for the owner's approval
    assert details.connect["rubro_text"] == "lo que el dueño escribió"
    assert details.connect["voice_configured"] is True
    assert details.profile == {"username": "anterior"}
    # one key of one document, never `profile`
    assert [(set(d), set(next(iter(d.values())))) for d in world.store.saved] == [
        ({"connect"}, {brand_prefill.PREFILL_KEY})
    ]

    prefill = world.prefill()
    assert prefill["status"] == "ok" and prefill["state"] == brand_prefill.STATE_PROPOSED
    assert prefill["network"] == "instagram" and prefill["username"] == "heladeria.demo"
    proposal = prefill["proposal"]
    assert proposal["connect"] | {"hashtags": []} == {
        "network": "instagram",
        "username": "heladeria.demo",
        "sector": "food_drink",
        "rubro_text": "heladería de yogur",  # Claude named it
        "country_code": "CO",
        "city": "Cúcuta",
        "hashtags": [],
    }
    # the account's own hashtags (case 2) — no second Claude run
    assert {p["tag"] for p in proposal["connect"]["hashtags"]} == {
        "cucuta",
        "helados",
        "postres",
        "yogurt",
    }
    assert {p["origin"] for p in proposal["connect"]["hashtags"]} == {"catalog"}
    assert proposal["profile"]["username"] == "heladeria.demo"
    assert proposal["profile"]["followers"] == "12.400"
    assert proposal["profile"]["followers_count"] == 12_400
    assert proposal["profile"]["pic"] == PICTURE
    assert proposal["profile"]["metrics"]  # three posts inside the window
    # the profile picture's colours, as «Mi foto de perfil es mi logo» would put them
    palette = proposal["palette"]
    assert palette["logo_source"] == brand_prefill.LOGO_SOURCE_PROFILE
    assert len(palette["logo_colors"]) == 2
    assert palette["palette"] == ",".join(palette["logo_colors"])


def test_the_provenance_and_the_usage_ride_with_the_proposal(world: World) -> None:
    result = world.run(source={"kind": "alta", "meegle_work_item_id": 24852197})
    prefill = world.prefill()
    provenance = prefill["provenance"]
    assert provenance["pipeline_version"] == brand_prefill.PREFILL_VERSION
    assert provenance["source"] == {"kind": "alta", "meegle_work_item_id": 24852197}
    read = provenance["read"]
    assert read["provider"] == "scrapecreators"
    assert read["client"] == "qualify_api.referentes.scrapecreators_client"
    assert read["snapshot_schema"] == 4 and read["from_cache"] is False
    assert read["endpoints"] == ["/v1/instagram/profile", "/v2/instagram/user/posts"]
    assert isinstance(read["fetched_at"], float)
    [rubro] = provenance["claude"]
    assert rubro["step"] == "rubro"
    assert rubro["model_id"] == "claude-sonnet-5"
    assert rubro["model_revision"] == "claude-sonnet-5-20261001"
    assert rubro["prompt_version"] == brand_prefill.rubro_prompt_version()
    assert rubro["prompt_version"].startswith("from_profile:")
    assert (rubro["input_tokens"], rubro["output_tokens"]) == (1200, 300)

    usage = result.usage
    assert usage.scrapecreators_requests == usage.scrapecreators_credits == 2
    assert usage.claude_calls == 1
    assert (usage.claude_input_tokens, usage.claude_output_tokens) == (1200, 300)
    assert usage.claude_cost_usd == pytest.approx(STATS.cost_usd)
    assert usage.claude_tokens_complete is True
    assert prefill["usage"] == usage.as_document()


def test_without_own_hashtags_the_rubro_runs_tags_are_used_without_a_second_call(
    world: World,
) -> None:
    for item in world.vendor.posts["items"]:
        item["caption"] = {"text": "Sin etiquetas"}
    world.vendor.profile["data"]["user"]["biography"] = "Heladería de yogur en Cúcuta 🇨🇴"
    world.claude.tags = ("heladeriadeyogur", "postrescucuta")
    result = world.run()
    hashtags = world.prefill()["proposal"]["connect"]["hashtags"]
    assert [(p["tag"], p["origin"]) for p in hashtags] == [
        ("heladeriadeyogur", "ai"),
        ("postrescucuta", "ai"),
    ]
    assert len(world.claude.calls) == 1 and result.usage.claude_calls == 1


def test_without_a_claude_key_the_category_names_the_rubro(world: World) -> None:
    def missing() -> str:
        raise MissingAPIKey("QUALIFY_ANTHROPIC_API_KEY is not set")

    world.api_key = missing
    result = world.run()
    assert result.ok
    assert world.prefill()["proposal"]["connect"]["rubro_text"] == "restaurante"
    assert result.usage.claude_calls == 0 and world.prefill()["provenance"]["claude"] == []


def test_a_default_picture_proposes_no_palette(world: World) -> None:
    world.vendor.picture = (FIXTURES.parent / "instagram_default_avatar.jpg").read_bytes()
    world.run()
    assert world.prefill()["proposal"]["palette"] is None


def test_a_wizard_save_keeps_the_proposal(world: World) -> None:
    """The key is reserved: a wizard writing `connect` whole does not erase it."""
    world.run()
    world.store.save_details(
        tenant_id=TENANT, brand_id=BRAND, user_id=None, documents={"connect": {"city": "Cali"}}
    )
    connect = world.store.rows[(TENANT, BRAND)].connect
    assert connect["city"] == "Cali" and connect[brand_prefill.PREFILL_KEY]["status"] == "ok"


# --------------------------------------------------------------------------------------
# the shared hashtag catalog (case 1) — the wizard's path, with its tokens
# --------------------------------------------------------------------------------------

CATALOG_STATS = CallStats("claude-sonnet-5", "claude-sonnet-5-20261001", 4000, 500, 100, 3, 2)


class Selector:
    """`hashtag_ai.select_hashtags`' signature: Claude choosing from the catalog."""

    def __init__(self, fails: bool = False) -> None:
        self.calls = 0
        self.fails = fails

    def __call__(self, profile: Any, tools: Any, niches: Any, **kw: Any) -> Any:
        self.calls += 1
        if self.fails:
            raise RuntimeError("overloaded")
        picks = [hashtag_ai.HashtagPick("helados", "alta", "Es lo que vende.")]
        return picks, CATALOG_STATS


def _catalog(selector: Selector | None = None) -> brand_prefill.CatalogHashtags:
    return brand_prefill.CatalogHashtags(
        repository=MemoryHashtagRepository(),
        selector=selector,
        api_key="sk-ant-test" if selector else None,
    )


def test_the_default_ports_use_the_shared_catalog() -> None:
    ports = PrefillPorts()
    assert isinstance(ports.catalog, brand_prefill.CatalogHashtags)
    assert brand_prefill.HashtagChoice is hashtag_catalog.HashtagChoice


def test_the_catalogs_claude_choice_comes_first_and_its_tokens_are_counted(
    world: World,
) -> None:
    selector = Selector()
    world.catalog = _catalog(selector)
    result = world.run()

    hashtags = world.prefill()["proposal"]["connect"]["hashtags"]
    assert [(p["tag"], p["origin"]) for p in hashtags] == [("helados", "ai")]
    assert hashtags[0]["model"] == "claude-sonnet-5-20261001"
    assert selector.calls == 1
    usage = result.usage
    assert usage.claude_calls == 2  # the rubro, then the catalog choice
    assert usage.claude_input_tokens == 1200 + 4000
    assert usage.claude_output_tokens == 300 + 500
    assert usage.claude_cache_read_tokens == 100
    assert usage.claude_cost_usd == pytest.approx(STATS.cost_usd + CATALOG_STATS.cost_usd)
    assert usage.claude_tokens_complete is True
    runs = world.prefill()["provenance"]["claude"]
    assert [r["step"] for r in runs] == ["rubro", "hashtags_catalog"]
    assert runs[1]["prompt_version"] == brand_prefill.catalog_prompt_version()
    assert (runs[1]["input_tokens"], runs[1]["turns"]) == (4000, 3)


def test_the_catalogs_rule_path_makes_no_claude_call(world: World) -> None:
    world.catalog = _catalog()  # no key: the rule path over the seeded taxonomy
    result = world.run()
    hashtags = world.prefill()["proposal"]["connect"]["hashtags"]
    assert hashtags and {p["origin"] for p in hashtags} == {"catalog"}
    assert result.usage.claude_calls == 1  # only the rubro
    assert result.usage.claude_tokens_complete is True
    assert [r["step"] for r in world.prefill()["provenance"]["claude"]] == ["rubro"]


def test_a_choice_served_from_memory_costs_no_call(world: World) -> None:
    selector = Selector()
    world.catalog = _catalog(selector)
    world.run()
    world.cache.entries.clear()
    result = world.run()
    assert selector.calls == 1
    assert result.usage.claude_calls == 1 and result.usage.claude_tokens_complete is True


def test_a_catalog_run_that_fails_is_counted_with_its_tokens_unknown(world: World) -> None:
    world.catalog = _catalog(Selector(fails=True))
    result = world.run()
    assert result.ok  # the rule path answered instead
    assert result.usage.claude_calls == 2
    assert result.usage.claude_tokens_complete is False


def test_the_catalog_is_never_taught_by_a_proposal(world: World) -> None:
    for item in world.vendor.posts["items"]:
        item["caption"] = {"text": "Sin etiquetas"}
    world.claude.tags = ("heladeriadeyogur",)
    catalog = _catalog()
    catalog.repository = MemoryHashtagRepository()
    world.catalog = catalog
    world.vendor.profile["data"]["user"]["category_name"] = None
    world.vendor.profile["data"]["user"]["biography"] = "Xilófonos hechos a mano"
    world.claude.rubro = "xilófonos artesanales"
    world.run()
    assert catalog.repository.get(TENANT, "heladeriadeyogur") is None


class _BreaksAfterTheRun(MemoryHashtagRepository):
    """The catalog's database fails once Claude has run (the rule path's fallback)."""

    broken = False

    def resolve(self, *a: Any, **kw: Any) -> Any:
        if self.broken:
            from sqlalchemy.exc import OperationalError

            raise OperationalError("SELECT 1", {}, Exception("connection refused"))
        return super().resolve(*a, **kw)


def test_a_catalog_run_followed_by_a_database_failure_stays_spent(world: World) -> None:
    """Review of PB-3: the run was made, so its call is not given back — a cap of 2 then
    stops the third (the creation) instead of letting it through."""
    repository = _BreaksAfterTheRun()

    class Breaking(Selector):
        def __call__(self, *a: Any, **kw: Any) -> Any:
            self.calls += 1
            repository.broken = True
            raise RuntimeError("overloaded")

    selector = Breaking()
    world.catalog = brand_prefill.CatalogHashtags(
        repository=repository, selector=selector, api_key="sk-ant-test"
    )
    for item in world.vendor.posts["items"]:
        item["caption"] = {"text": "Sin etiquetas"}  # no own tags: case 3 would run
    result = world.run(caps=CallCaps(claude_calls=2))

    assert selector.calls == 1
    assert result.outcome is PrefillOutcome.CAP_REACHED
    assert result.usage.claude_calls == 2  # the rubro + the catalog run, nothing given back
    assert result.usage.claude_tokens_complete is False
    assert len(world.claude.calls) == 1  # the creation never ran


def test_a_catalog_that_fails_before_any_run_gives_the_call_back(world: World) -> None:
    repository = _BreaksAfterTheRun()
    repository.broken = True  # unreadable from the start: no Claude run at all
    world.catalog = brand_prefill.CatalogHashtags(
        repository=repository, selector=Selector(), api_key="sk-ant-test"
    )
    result = world.run()
    assert result.ok and result.usage.claude_calls == 1
    assert result.usage.claude_tokens_complete is True


def test_an_owners_save_during_the_run_is_kept(world: World) -> None:
    """Review of PB-3: the proposal is written as ONE key over what the row holds at the
    write — an owner's rubro, hashtags and city saved meanwhile are not reverted."""
    world.store.rows[(TENANT, BRAND)] = BrandKitDetails(connect={"city": "Bogotá"})

    def owner_saves() -> None:
        world.store.save_details(
            tenant_id=TENANT,
            brand_id=BRAND,
            user_id=None,
            documents={
                "connect": {"city": "Cali", "rubro_text": "heladería", "hashtags": [{"tag": "x"}]}
            },
        )

    world.store.before_write = owner_saves
    world.run()
    connect = world.store.rows[(TENANT, BRAND)].connect
    assert connect["city"] == "Cali" and connect["rubro_text"] == "heladería"
    assert connect["hashtags"] == [{"tag": "x"}]
    assert connect[brand_prefill.PREFILL_KEY]["status"] == "ok"


# --------------------------------------------------------------------------------------
# the profile picture: only the CDN, at most 3 MB
# --------------------------------------------------------------------------------------

CDN = "https://scontent.cdninstagram.com/v/pic.jpg"


def _picture(handler: Callable[[httpx.Request], httpx.Response]) -> tuple[bytes | None, list]:
    seen: list[str] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return handler(request)

    with httpx.Client(transport=httpx.MockTransport(record)) as client:
        return brand_prefill.fetch_picture(CDN, client), seen


def test_a_redirect_off_the_cdn_is_never_followed() -> None:
    data, seen = _picture(
        lambda r: httpx.Response(302, headers={"location": "https://evil.example/x.png"})
    )
    assert data is None and seen == [CDN]


def test_a_redirect_inside_the_cdn_is_followed() -> None:
    other = "https://scontent-lga3-2.cdninstagram.com/v/pic.jpg"

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == CDN:
            return httpx.Response(302, headers={"location": other})
        return httpx.Response(200, content=b"img", headers={"content-type": "image/jpeg"})

    data, seen = _picture(handler)
    assert data == b"img" and seen == [CDN, other]


def test_redirects_stop_after_a_few_hops() -> None:
    data, seen = _picture(lambda r: httpx.Response(302, headers={"location": CDN}))
    assert data is None and len(seen) == 4


def test_a_picture_over_the_limit_is_dropped_while_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(brand_prefill, "_PICTURE_MAX_BYTES", 10)
    pulled: list[int] = []

    def chunks() -> Any:
        for i in range(100):
            pulled.append(i)
            yield b"123456"

    data, _ = _picture(
        lambda r: httpx.Response(200, content=chunks(), headers={"content-type": "image/png"})
    )
    assert data is None and len(pulled) < 100  # stopped reading, not read then measured
    declared, _ = _picture(
        lambda r: httpx.Response(200, content=b"x" * 11, headers={"content-type": "image/png"})
    )
    assert declared is None


def test_a_body_that_is_not_an_image_is_refused() -> None:
    data, _ = _picture(
        lambda r: httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"})
    )
    assert data is None


# --------------------------------------------------------------------------------------
# the outcomes PB-4 comments on
# --------------------------------------------------------------------------------------


def test_a_private_account_is_its_own_outcome_and_proposes_nothing() -> None:
    world = World("instagram_profile_private.json")
    result = world.run("cuenta.privada.demo")
    assert result.outcome is PrefillOutcome.PRIVATE_ACCOUNT and result.read
    assert world.claude.calls == []
    prefill = world.prefill()
    assert prefill["status"] == "private_account" and prefill["proposal"] is None
    assert prefill["state"] == ""
    assert ("keep_only", (TENANT, BRAND, "instagram", "cuenta.privada.demo")) in world.claims.calls


def test_an_account_the_vendor_does_not_find_is_not_found_and_frees_the_claim(
    world: World,
) -> None:
    world.vendor.status["/v1/instagram/profile"] = 404
    result = world.run("heladeria.demoo")
    assert result.outcome is PrefillOutcome.NOT_FOUND and not result.read
    assert [name for name, _ in world.claims.calls] == ["claim", "release"]
    assert world.cache.entries == {}
    assert world.prefill()["status"] == "not_found"


def test_a_vendor_failure_is_read_failed_and_keeps_an_account_already_held(
    world: World,
) -> None:
    world.vendor.status["/v1/instagram/profile"] = 500
    world.claims.newly = False
    result = world.run()
    assert result.outcome is PrefillOutcome.READ_FAILED
    assert "release" not in [name for name, _ in world.claims.calls]
    assert "HTTP 500" in result.detail


def test_another_brands_account_is_refused_before_anything_is_read(world: World) -> None:
    world.claims.taken = True
    result = world.run()
    assert result.outcome is PrefillOutcome.ACCOUNT_TAKEN
    assert world.vendor.requests == [] and world.cache.tenants == []
    assert world.prefill()["status"] == "account_taken"


def test_a_claim_that_cannot_be_checked_reads_nothing(world: World) -> None:
    from sqlalchemy.exc import OperationalError

    def down(*_a: Any) -> bool:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    world.claims.claim = down  # type: ignore[method-assign]
    result = world.run()
    assert result.outcome is PrefillOutcome.READ_FAILED and world.vendor.requests == []


def test_an_unexpected_error_is_an_outcome_not_an_exception(world: World) -> None:
    def broken(*_a: Any) -> dict[str, Any]:
        raise RuntimeError("bug")

    result = world.run(ports=world.ports(read_profile=broken))
    assert result.outcome is PrefillOutcome.READ_FAILED and "RuntimeError" in result.detail


def test_an_unsupported_network_or_an_empty_handle_reads_nothing(world: World) -> None:
    assert world.run("  @ ").outcome is PrefillOutcome.READ_FAILED
    result = prefill_brand_kit(TENANT, BRAND, "myspace", "x", ports=world.ports())
    assert result.outcome is PrefillOutcome.READ_FAILED
    assert world.claims.calls == [] and world.vendor.requests == []


# --------------------------------------------------------------------------------------
# the per-run cap
# --------------------------------------------------------------------------------------


def test_the_default_cap_is_the_most_a_run_can_need() -> None:
    from qualify_api.referentes import scrapecreators_client

    assert brand_prefill.DEFAULT_CAPS.scrapecreators_requests == (
        1 + scrapecreators_client._MAX_POST_PAGES
    )
    assert brand_prefill.DEFAULT_CAPS.claude_calls == 3


def test_a_scrapecreators_cap_of_zero_sends_no_request(world: World) -> None:
    result = world.run(caps=CallCaps(scrapecreators_requests=0))
    assert result.outcome is PrefillOutcome.CAP_REACHED
    assert world.vendor.vendor_requests == []
    assert result.usage.scrapecreators_requests == 0
    assert [name for name, _ in world.claims.calls] == ["claim", "release"]


def test_a_cap_reached_on_the_posts_stops_and_caches_nothing(world: World) -> None:
    result = world.run(caps=CallCaps(scrapecreators_requests=1))
    assert result.outcome is PrefillOutcome.CAP_REACHED
    assert world.vendor.vendor_requests == ["api.scrapecreators.com/v1/instagram/profile"]
    assert result.usage.scrapecreators_credits == 1
    assert world.cache.entries == {}  # a truncated read is not the account's week
    prefill = world.prefill()
    assert prefill["status"] == "cap_reached" and prefill["proposal"] is None
    assert prefill["usage"]["scrapecreators_requests"] == 1


def test_a_claude_cap_stops_before_the_call(world: World) -> None:
    result = world.run(caps=CallCaps(claude_calls=0))
    assert result.outcome is PrefillOutcome.CAP_REACHED and result.profile is not None
    assert world.claude.calls == []
    assert world.prefill()["status"] == "cap_reached"


def test_a_cached_account_costs_no_credit(world: World) -> None:
    world.run()
    world.vendor.requests.clear()
    result = world.run()
    assert result.ok and world.vendor.vendor_requests == []
    assert result.usage.scrapecreators_credits == 0
    assert world.prefill()["provenance"]["read"]["from_cache"] is True


# --------------------------------------------------------------------------------------
# the wizard's read
# --------------------------------------------------------------------------------------


def test_the_wizards_read_writes_nothing_and_calls_no_claude(world: World) -> None:
    result = world.run(propose=False)
    assert result.outcome is PrefillOutcome.OK and not result.written
    assert world.store.saved == [] and world.claude.calls == []
    assert result.profile is not None and result.profile["username"] == "heladeria.demo"
    assert (result.sector, result.country_code, result.city) == ("food_drink", "CO", "Cúcuta")
    assert [m["label"] for m in result.metrics]
    assert result.fetched_live is True
    assert not any("cdninstagram" in r for r in world.vendor.requests)  # no picture fetch


# --------------------------------------------------------------------------------------
# tenant isolation (offline): every outside call carries the run's tenant
# --------------------------------------------------------------------------------------


def test_every_outside_call_carries_the_runs_own_tenant(world: World) -> None:
    world.run()
    assert world.store.tenants and set(world.store.tenants) == {TENANT}
    assert set(world.cache.tenants) == {TENANT}
    assert {args[0] for _, args in world.claims.calls} == {TENANT}
    assert set(world.store.rows) == {(TENANT, BRAND)}


def test_the_module_reaches_the_database_only_through_tenant_scoped_doors() -> None:
    source = Path(brand_prefill.__file__).read_text(encoding="utf-8")
    for forbidden in ("admin_session", "credential_session", "create_engine", "sessionmaker"):
        assert forbidden not in source


# --------------------------------------------------------------------------------------
# steps the wizard shares
# --------------------------------------------------------------------------------------


def test_logo_colours_replace_the_previous_logos_and_keep_hand_picked_ones() -> None:
    palette, colours = brand_prefill.logo_colours_update(
        "#111111,#aaaaaa", ["#aaaaaa"], _png("#0f766e")
    )
    assert palette.split(",")[0] == "#111111" and "#aaaaaa" not in palette
    assert colours and palette.endswith(colours[-1])


def test_pills_from_a_choice_are_deduplicated_and_capped() -> None:
    choice = brand_prefill.HashtagChoice(
        tags=("Helados", "helados", "postres", "a", "b", "c", "d"),
        by="ai",
        picks={"Helados": {"reason": "r", "model": "m"}},
    )
    pills = brand_prefill.pills_from_choice(choice)
    assert [p["tag"] for p in pills] == ["Helados", "postres", "a", "b", "c"]
    assert pills[0] == {"tag": "Helados", "origin": "ai", "reason": "r", "model": "m"}


def test_the_prompt_version_follows_the_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    before = brand_prefill.rubro_prompt_version()
    monkeypatch.setattr(from_profile, "SYSTEM", from_profile.SYSTEM + " ")
    assert brand_prefill.rubro_prompt_version() != before


# --------------------------------------------------------------------------------------
# db: the real store, claim and cache under RLS
# --------------------------------------------------------------------------------------


@pytest.mark.db
def test_a_run_writes_only_its_own_tenants_brand_kit(seeded_ab: tuple[UUID, UUID]) -> None:
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import select

    from qualify_api.creative.brand_kit_store import BrandKitStore
    from qualify_api.creative.models import BrandKitDetails as DetailsRow
    from qualify_api.tenancy.models import Brand

    tenant_a, tenant_b = seeded_ab
    brands: dict[UUID, UUID] = {}
    for tenant in (tenant_a, tenant_b):
        with tenant_session(tenant) as session:
            brands[tenant] = session.scalar(select(Brand.id).where(Brand.tenant_id == tenant))
    store = BrandKitStore()
    store.save_details(
        tenant_id=tenant_b,
        brand_id=brands[tenant_b],
        user_id=None,
        documents={"connect": {"city": "Montevideo"}},
    )
    vendor = Vendor()
    handle = f"heladeria.{uuid4().hex[:8]}"  # a fresh account: the claim is global
    vendor.profile["data"]["user"]["username"] = handle
    ports = PrefillPorts(
        generate=Claude(),
        api_key=lambda: "sk-ant-test",
        transport=httpx.MockTransport(vendor.handler),
    )

    result = prefill_brand_kit(tenant_a, brands[tenant_a], "instagram", handle, ports=ports)

    assert result.ok and result.written
    mine = store.load_details(tenant_id=tenant_a, brand_id=brands[tenant_a]).connect
    assert mine[brand_prefill.PREFILL_KEY]["status"] == "ok"
    theirs = store.load_details(tenant_id=tenant_b, brand_id=brands[tenant_b]).connect
    assert theirs == {"city": "Montevideo"}
    # RLS: tenant B's session sees no row of tenant A's brand
    with tenant_session(tenant_b) as session:
        assert session.get(DetailsRow, brands[tenant_a]) is None


@pytest.mark.db
def test_an_owners_save_during_the_run_survives_in_postgres(
    seeded_ab: tuple[UUID, UUID],
) -> None:
    """Review of PB-3, against the real store: the owner saves `connect` (their own
    session, committed) while the run is working; the run's write adds `prefill` over
    THAT row, and the owner's next save keeps the proposal."""
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import select

    from qualify_api.creative.brand_kit_store import BrandKitStore
    from qualify_api.tenancy.models import Brand

    tenant_a, _tenant_b = seeded_ab
    with tenant_session(tenant_a) as session:
        brand = session.scalar(select(Brand.id).where(Brand.tenant_id == tenant_a))
    store = BrandKitStore()
    store.save_details(
        tenant_id=tenant_a, brand_id=brand, user_id=None, documents={"connect": {"city": "Bogotá"}}
    )

    class OwnerSavesMeanwhile(BrandKitStore):
        def set_document_key(self, **kw: Any) -> None:
            BrandKitStore().save_details(
                tenant_id=tenant_a,
                brand_id=brand,
                user_id=None,
                documents={"connect": {"city": "Cali", "rubro_text": "heladería"}},
            )
            super().set_document_key(**kw)

    vendor = Vendor()
    handle = f"heladeria.{uuid4().hex[:8]}"
    vendor.profile["data"]["user"]["username"] = handle
    ports = PrefillPorts(
        store=OwnerSavesMeanwhile(),
        generate=Claude(),
        api_key=lambda: "sk-ant-test",
        transport=httpx.MockTransport(vendor.handler),
        catalog=None,
    )
    result = prefill_brand_kit(tenant_a, brand, "instagram", handle, ports=ports)

    assert result.written
    connect = store.load_details(tenant_id=tenant_a, brand_id=brand).connect
    assert connect["city"] == "Cali" and connect["rubro_text"] == "heladería"
    assert connect[brand_prefill.PREFILL_KEY]["status"] == "ok"
    # the owner saving again (a wizard writing `connect` whole) keeps the proposal
    store.save_details(
        tenant_id=tenant_a, brand_id=brand, user_id=None, documents={"connect": {"city": "Lima"}}
    )
    again = store.load_details(tenant_id=tenant_a, brand_id=brand).connect
    assert again["city"] == "Lima" and again[brand_prefill.PREFILL_KEY]["status"] == "ok"


# --------------------------------------------------------------------------------------
# m-24852199: a re-run never undoes the owner's decision
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("state", ["approved", "changed", "discarded", "superseded"])
def test_a_rerun_keeps_a_proposal_the_owner_already_decided(world: World, state: str) -> None:
    decided = {"status": "ok", "state": state, "proposal": {"connect": {}, "profile": {}}}
    world.store.rows[(TENANT, BRAND)] = BrandKitDetails(
        connect={brand_prefill.PREFILL_KEY: decided}
    )
    result = world.run()
    assert result.ok and not result.written
    assert world.prefill() == decided


def test_a_rerun_replaces_a_proposal_still_waiting(world: World) -> None:
    waiting = {"status": "ok", "state": "proposed", "proposal": {"connect": {}, "profile": {}}}
    world.store.rows[(TENANT, BRAND)] = BrandKitDetails(
        connect={brand_prefill.PREFILL_KEY: waiting}
    )
    assert world.run().written
    assert world.prefill()["proposal"]["connect"]["username"] == "heladeria.demo"


@pytest.mark.db
def test_a_rerun_in_postgres_keeps_the_decision(seeded_ab: tuple[UUID, UUID]) -> None:
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import select

    from qualify_api.creative.brand_kit_store import BrandKitStore
    from qualify_api.tenancy.models import Brand

    tenant_a, _tenant_b = seeded_ab
    with tenant_session(tenant_a) as session:
        brand = session.scalar(select(Brand.id).where(Brand.tenant_id == tenant_a))
    store = BrandKitStore()
    decided = {"status": "ok", "state": "approved", "proposal": None}
    store.set_document_key(
        tenant_id=tenant_a, brand_id=brand, document="connect", key="prefill", value=decided
    )
    try:
        assert not store.set_document_key(
            tenant_id=tenant_a,
            brand_id=brand,
            document="connect",
            key="prefill",
            value={"status": "ok", "state": "proposed"},
            keep_current=brand_prefill_review.is_decided,
        )
        kept = store.load_details(tenant_id=tenant_a, brand_id=brand).connect["prefill"]
        assert kept == decided
    finally:  # the shared tenant's next run starts from a waiting proposal
        store.set_document_key(
            tenant_id=tenant_a, brand_id=brand, document="connect", key="prefill", value={}
        )
