"""Every path a bio or a caption takes out of the tenant carries its phone numbers masked
(m-24854323, OL2-7; founder decision 7): the Brand Kit prefill (Alta and wizard) — what
Claude reads, the tenant's profile cache, the stored proposal and its provenance, the
logs —, the Langfuse traces of every Claude turn, the prompt builders the wizard calls on
its own (Tu rubro, the catalog choice, the referentes review), what «Aprobar» promotes,
and the business context generation reads (`build_context`, Claude and BytePlus)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from qualify_shared import observability

from qualify_api.claude_tools import Meter, ModelConfig, create_turn, strict_tool
from qualify_api.creative import brand_prefill_review
from qualify_api.creative.brand_context import build_context
from qualify_api.creative.brand_kit_store import BrandKitDetails
from qualify_api.hashtags import catalog as hashtag_catalog
from qualify_api.hashtags import from_profile
from qualify_api.privacy import MASK_BODY
from qualify_api.referentes import ai as referentes_ai
from qualify_api.referentes.discovery_seed import DiscoverySeed

BIO = "Pedidos WhatsApp +57 300 123 4548 · wa.me/573001234548"
CAPTION = "Domicilios al 3 1 5 6 7 8 9 0 1 2 #helados"
#: What must never appear once masked: the numbers as written, and their digits.
RAW = ("300 123 4548", "3001234548", "573001234548", "3 1 5 6 7 8 9 0 1 2", "3156789012")
MASKED_BIO = f"Pedidos WhatsApp +57 {MASK_BODY}48 · wa.me/+57 {MASK_BODY}48"


def _clean(blob: Any) -> None:
    text = blob if isinstance(blob, str) else json.dumps(blob, ensure_ascii=False, default=str)
    for raw in RAW:
        assert raw not in text


@pytest.fixture
def tb() -> ModuleType:
    from . import test_brand_prefill as module  # the prefill's in-memory world

    return module


@pytest.fixture
def world(tb: ModuleType, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "sk_test_prefill")
    monkeypatch.delenv("QUALIFY_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(hashtag_catalog, "_seeded", False)
    monkeypatch.setattr(hashtag_catalog, "_choices", {})
    world = tb.World()
    user = world.vendor.profile["data"]["user"]
    user["biography"] = BIO
    user["external_url"] = "https://wa.me/573001234548"
    world.vendor.posts["items"][0]["caption"] = {"text": CAPTION}
    return world


# --------------------------------------------------------------------------------------
# The Brand Kit prefill: the Alta's run and the wizard's read
# --------------------------------------------------------------------------------------


def test_the_prefill_masks_what_claude_the_cache_the_proposal_and_the_logs_get(
    world: Any, tb: ModuleType, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    result = world.run(source={"kind": "alta", "meegle_work_item_id": 24854323})
    assert result.ok and result.written

    # Claude read the account masked
    [account] = world.claude.calls
    assert account.bio == MASKED_BIO
    assert any(f"{MASK_BODY}12" in caption for caption in account.captions)
    _clean([account.bio, *account.captions])
    # the tenant's cache keeps no full number either (decision 7: only `connect.contact`)
    [cached] = world.cache.entries.values()
    _clean(cached)
    assert cached["bio"] == MASKED_BIO
    # the stored proposal, its provenance and its usage
    prefill = world.prefill()
    _clean(prefill)
    assert prefill["proposal"]["profile"]["bio"] == MASKED_BIO
    # what the wizard maps onto its screen (and saves as the profile)
    _clean(result.profile)
    assert result.profile["externalUrl"] == f"https://wa.me/+57 {MASK_BODY}48"
    # the picture's CDN link is not a phone: it still points at the picture
    assert result.profile["profilePicUrl"] == tb.PICTURE
    # nothing logged carries the bio or a caption's number, at any level
    _clean(caplog.text)


def test_a_snapshot_cached_before_the_masking_is_masked_on_read(world: Any, tb: ModuleType) -> None:
    world.run()
    [key] = world.cache.entries
    world.cache.entries[key] = dict(world.cache.entries[key], bio=BIO)  # an older snapshot
    world.claude.calls.clear()

    result = world.run()

    assert result.ok and not result.fetched_live
    assert world.claude.calls[0].bio == MASKED_BIO
    _clean(result.profile)
    _clean(world.prefill())


def test_the_wizards_read_returns_the_profile_masked(world: Any) -> None:
    result = world.run(propose=False)
    assert result.ok and result.profile is not None
    assert result.profile["bio"] == MASKED_BIO
    _clean(result.profile)


# --------------------------------------------------------------------------------------
# The prompt builders (the wizard calls them with whatever bio it holds)
# --------------------------------------------------------------------------------------


def test_tu_rubro_prompt_masks_the_bio_and_the_captions() -> None:
    account = from_profile.AccountText(handle="heladeria", bio=BIO, captions=(CAPTION,))
    message = from_profile._message(account, 5)  # noqa: SLF001 - the prompt is the contract
    assert MASKED_BIO in message
    _clean(message)


def test_the_catalog_choice_reads_the_bio_masked() -> None:
    seed = DiscoverySeed(handle="heladeria", niches=("food_drink",))
    profile = hashtag_catalog._brand_profile(seed, BIO, "Heladería")  # noqa: SLF001
    assert profile.bio == MASKED_BIO


def test_the_referentes_review_masks_the_brand_and_the_accounts() -> None:
    block = referentes_ai._brand_block(referentes_ai.BrandBrief(handle="heladeria", bio=BIO))  # noqa: SLF001
    _clean(block)
    assert f"+57 {MASK_BODY}48" in block
    _clean(referentes_ai._clip(CAPTION, 20))  # noqa: SLF001 - a cut never leaves digits


# --------------------------------------------------------------------------------------
# Langfuse: every Claude turn's request and answer
# --------------------------------------------------------------------------------------


def test_a_claude_turn_is_traced_with_its_phones_masked() -> None:
    config = ModelConfig("claude-sonnet-5", effort="low")
    response = SimpleNamespace(
        model="claude-sonnet-5",
        stop_reason="tool_use",
        content=[
            SimpleNamespace(type="text", text=f"Vi el número {RAW[0]}"),
            SimpleNamespace(type="tool_use", name="proponer", input={"rubro": CAPTION}),
        ],
        usage=SimpleNamespace(
            input_tokens=10,
            output_tokens=5,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )
    client = SimpleNamespace(messages=SimpleNamespace(create=lambda **_: response))
    with observability.capture_spans() as exporter:
        with observability.trace("rubro desde la cuenta"):
            create_turn(
                client,
                config,
                Meter(config),
                system=f"Cuenta con bio: {BIO}",
                messages=[{"role": "user", "content": [{"type": "text", "text": BIO}]}],
                tools=[strict_tool("proponer", "d", {"rubro": {"type": "string"}})],
                tool_choice={"type": "auto"},
                max_tokens=1000,
            )
        observability.flush()
        [span] = [s for s in exporter.get_finished_spans() if s.name == "claude"]
    attrs = dict(span.attributes)
    sent = json.loads(attrs["langfuse.observation.input"])
    assert sent["messages"][0]["content"][0]["text"] == MASKED_BIO
    assert sent["system"] == f"Cuenta con bio: {MASKED_BIO}"
    _clean(attrs["langfuse.observation.input"])
    _clean(attrs["langfuse.observation.output"])


# --------------------------------------------------------------------------------------
# «Aprobar» and what generation reads
# --------------------------------------------------------------------------------------


def test_aprobar_promotes_a_proposal_written_before_the_masking_masked() -> None:
    from uuid import uuid4

    profile = brand_prefill_review.approved_profile(uuid4(), uuid4(), {"bio": BIO, "pic": ""})
    assert profile["bio"] == MASKED_BIO


@dataclass
class _Label:
    network: str
    handle: str
    label: str
    position: int | None = None


@dataclass
class _Found:
    card: dict[str, Any] = field(default_factory=dict)
    bio: str = ""


def test_generation_context_never_carries_a_full_number() -> None:
    """`build_context` feeds every generation prompt — Claude's copy and angles and the
    BytePlus scenes — so a bio saved before the masking is masked here too."""
    details = BrandKitDetails(
        connect={"rubro_text": "heladería", "city": "Cúcuta", "country_code": "CO"},
        profile={"bio": BIO, "category": "Heladería"},
    )
    found = {("instagram", "vecino"): _Found(card={"blurb": CAPTION}, bio=BIO)}
    context = build_context(details, [], [_Label("instagram", "vecino", "referente")], found)
    assert context is not None
    assert context.account_bio == MASKED_BIO
    _clean(context.model_dump())
