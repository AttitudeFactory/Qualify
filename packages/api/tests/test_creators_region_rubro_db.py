"""Migration 0182 + `creators.region_rubro` against Postgres (RF-04, m-25119461).

Pins:

- `creators` stays global: the new columns name no tenant, no RLS on the table, and the
  provenance checks refuse a value that does not say where it came from;
- the backfill reads only what the pool already stores, ranks the sources (a free one
  over the AI's; within the free ones, the account's own data over a search's country),
  and a second run writes nothing;
- the review's rubro / country: AI never overrides a free country, the same answer twice
  is a no-op, a new prompt version rewrites;
- tenant isolation: a business's coverage counts its own labels and nobody else's, read
  through `tenant_session`.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from qualify_api.creators import region_rubro as rr
from qualify_api.tenancy.models import Brand, Tenant

pytestmark = pytest.mark.db

NOW = datetime(2026, 11, 25, 12, tzinfo=UTC)


def _world() -> tuple[UUID, UUID]:
    tenant, brand = uuid4(), uuid4()
    with admin_session() as session:
        session.add(
            Tenant(id=tenant, name="RF-04", country="CO", timezone="America/Bogota", currency="COP")
        )
        session.flush()
        session.add(Brand(id=brand, tenant_id=tenant, name="RF-04 brand"))
    return tenant, brand


@pytest.fixture
def world() -> Iterator[tuple[UUID, UUID]]:
    yield _world()


def _handle(tag: str) -> str:
    return f"rf04{tag}{uuid4().hex[:8]}"


def _creator(session, network: str, handle: str, country: str = "") -> None:  # noqa: ANN001
    session.execute(
        text(
            "INSERT INTO creators (network, handle, country_code, seen_at) "
            "VALUES (:n, :h, :c, now())"
        ),
        {"n": network, "h": handle, "c": country},
    )


def _sighting(session, network: str, handle: str, country: str, times: int = 1) -> None:  # noqa: ANN001
    session.execute(
        text(
            "INSERT INTO creator_sightings (network, handle, kind, term, country_code, times, "
            "seen_at) VALUES (:n, :h, 'keyword', :t, :c, :times, now())"
        ),
        {"n": network, "h": handle, "t": f"t-{uuid4().hex[:6]}", "c": country, "times": times},
    )


def _payload(session, path: str, params: dict, payload: dict) -> str:  # noqa: ANN001
    return str(
        session.scalar(
            text(
                "INSERT INTO vendor_payloads (vendor, path, params_key, payload, fetched_at, "
                "expires_at) VALUES ('scrapecreators', :p, :k, CAST(:b AS jsonb), :f, :e) "
                "RETURNING id"
            ),
            {
                "p": path,
                "k": json.dumps(params),
                "b": json.dumps(payload),
                "f": NOW,
                "e": NOW + timedelta(days=7),
            },
        )
    )


def _row(session, network: str, handle: str) -> dict:  # noqa: ANN001
    return dict(
        session.execute(
            text(
                "SELECT region_code, region_source, region_source_ref, region_model, "
                "region_version, region_inferred_at, rubro, rubro_source, rubro_model, "
                "rubro_version, rubro_source_ref FROM creators "
                "WHERE network = :n AND handle = :h"
            ),
            {"n": network, "h": handle},
        )
        .mappings()
        .one()
    )


# --------------------------------------------------------------------------------------
# schema
# --------------------------------------------------------------------------------------


def test_creators_stays_global_and_the_new_columns_name_no_tenant() -> None:
    with admin_session() as session:
        columns = set(
            session.scalars(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'creators'"
                )
            )
        )
        rls = session.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = 'creators' AND relkind = 'r'"
            )
        ).one()
    assert {"region_code", "region_source", "region_version", "rubro", "rubro_model"} <= columns
    assert not any(c in columns for c in ("tenant_id", "brand_id", "user_id", "label"))
    assert tuple(rls) == (False, False)


def test_a_value_without_provenance_is_refused(world) -> None:  # noqa: ANN001
    tenant, _ = world
    handle = _handle("ck")
    with tenant_session(tenant) as session:
        _creator(session, "tiktok", handle)
    for sql in (
        # a region with no source
        "UPDATE creators SET region_code = 'CO', region_inferred_at = now() WHERE handle = :h",
        # an AI region with no model
        "UPDATE creators SET region_code = 'CO', region_source = 'ai', "
        "region_inferred_at = now() WHERE handle = :h",
        # a rubro with no model
        "UPDATE creators SET rubro = 'food_drink', rubro_source = 'ai', "
        "rubro_inferred_at = now() WHERE handle = :h",
        # not a country code
        "UPDATE creators SET region_code = 'Colombia', region_source = 'sightings', "
        "region_inferred_at = now() WHERE handle = :h",
    ):
        with pytest.raises(IntegrityError), tenant_session(tenant) as session:
            session.execute(text(sql), {"h": handle})


# --------------------------------------------------------------------------------------
# the backfill
# --------------------------------------------------------------------------------------


def test_the_backfill_ranks_the_free_sources_and_a_rerun_writes_nothing(world) -> None:  # noqa: ANN001
    tenant, _ = world
    own, video, reel, seen, none = (_handle(t) for t in ("own", "vid", "reel", "seen", "none"))
    with tenant_session(tenant) as session:
        for handle in (video, seen, none):
            _creator(session, "tiktok", handle)
        _creator(session, "tiktok", own, country="uy")
        _creator(session, "instagram", reel)
        # the account's own country beats a search's
        _sighting(session, "tiktok", own, "CO")
        # TikTok's per-video region beats the search country, whatever the counts
        payload_id = _payload(
            session,
            "/v1/tiktok/search/keyword",
            {"query": f"q-{video}"},
            {
                "search_item_list": [
                    {"aweme_info": {"region": "VE", "author": {"unique_id": video}}}
                ]
            },
        )
        _sighting(session, "tiktok", video, "CO", times=9)
        _payload(
            session,
            "/v1/instagram/user/reels",
            {"handle": reel},
            {"items": [{"media": {"location": {"address_json": '{"country_code": "MX"}'}}}]},
        )
        # the search's country is the last free resort: the heaviest one wins
        _sighting(session, "tiktok", seen, "CO", times=1)
        _sighting(session, "tiktok", seen, "VE", times=3)
    keys = [("tiktok", own), ("tiktok", video), ("instagram", reel), ("tiktok", seen),
            ("tiktok", none)]  # fmt: skip

    with tenant_session(tenant) as session:
        first = rr.backfill(session, keys=keys, now=NOW)
        rows = {h: _row(session, n, h) for n, h in keys}
    assert first.updated == 4 and first.resolved == 4
    assert (rows[own]["region_code"], rows[own]["region_source"]) == ("UY", "profile")
    assert (rows[video]["region_code"], rows[video]["region_source"]) == ("VE", "tiktok_region")
    assert rows[video]["region_source_ref"] == f"vendor_payloads:{payload_id}"
    assert (rows[reel]["region_code"], rows[reel]["region_source"]) == ("MX", "reel_location")
    assert (rows[seen]["region_code"], rows[seen]["region_source"]) == ("VE", "sightings")
    assert rows[seen]["region_source_ref"].startswith("creator_sightings:")
    assert rows[none]["region_code"] == "" and rows[none]["region_inferred_at"] is None
    for handle in (own, video, reel, seen):
        assert rows[handle]["region_model"] == ""
        assert rows[handle]["region_version"] == rr.FREE_PIPELINE_VERSION
        assert rows[handle]["region_inferred_at"] == NOW

    with tenant_session(tenant) as session:
        again = rr.backfill(session, keys=keys, now=NOW + timedelta(days=1))
        after = {h: _row(session, n, h) for n, h in keys}
    assert again.updated == 0  # idempotent: nothing new, not even the timestamp
    assert after == rows


# --------------------------------------------------------------------------------------
# what the review writes
# --------------------------------------------------------------------------------------


def _inference(handle: str, rubro: str, country: str, version: str = "v2") -> rr.ReviewInference:
    return rr.ReviewInference(
        network="tiktok",
        handle=handle,
        rubro=rubro,
        country=country,
        model="claude-sonnet-5",
        version=version,
        source_ref="review-input:abc",
    )


def test_the_review_fills_what_the_free_sources_could_not(world) -> None:  # noqa: ANN001
    tenant, _ = world
    free, empty = _handle("free"), _handle("empty")
    with tenant_session(tenant) as session:
        _creator(session, "tiktok", free)
        _creator(session, "tiktok", empty)
        _sighting(session, "tiktok", free, "CO")

    rows = [_inference(free, "food_drink", "MX"), _inference(empty, "real_estate", "UY")]
    assert rr.record_inferences(tenant, rows) == 2
    with tenant_session(tenant) as session:
        got_free, got_empty = _row(session, "tiktok", free), _row(session, "tiktok", empty)
    # a free country first; the AI's country only where none answered
    assert (got_free["region_code"], got_free["region_source"]) == ("CO", "sightings")
    assert (got_empty["region_code"], got_empty["region_source"]) == ("UY", "ai")
    assert (got_empty["region_model"], got_empty["region_version"]) == ("claude-sonnet-5", "v2")
    assert (got_free["rubro"], got_free["rubro_source"], got_free["rubro_model"]) == (
        "food_drink",
        "ai",
        "claude-sonnet-5",
    )
    assert got_empty["rubro_source_ref"] == "review-input:abc"

    # the same answers again: nothing written (no re-pay, no churn)
    assert rr.record_inferences(tenant, rows) == 0
    # a different answer under the same prompt version does not flap the stored one
    assert rr.record_inferences(tenant, [_inference(empty, "education", "VE")]) == 0
    # a new prompt version rewrites the AI's own values
    assert rr.record_inferences(tenant, [_inference(empty, "education", "VE", "v3")]) == 1
    with tenant_session(tenant) as session:
        rewritten = _row(session, "tiktok", empty)
    assert (rewritten["rubro"], rewritten["region_code"]) == ("education", "VE")


def test_a_free_country_replaces_the_ai_one_but_never_the_reverse(world) -> None:  # noqa: ANN001
    tenant, _ = world
    handle = _handle("ai")
    with tenant_session(tenant) as session:
        _creator(session, "tiktok", handle)
    rr.record_inferences(tenant, [_inference(handle, "food_drink", "MX")])
    with tenant_session(tenant) as session:
        _sighting(session, "tiktok", handle, "CO")
        assert rr.backfill(session, keys=[("tiktok", handle)], now=NOW).updated == 1
        row = _row(session, "tiktok", handle)
    assert (row["region_code"], row["region_source"], row["region_model"]) == (
        "CO",
        "sightings",
        "",
    )
    assert row["rubro"] == "food_drink"  # the rubro the review gave stays
    assert rr.record_inferences(tenant, [_inference(handle, "food_drink", "MX", "v9")]) == 1
    with tenant_session(tenant) as session:
        row = _row(session, "tiktok", handle)
    assert (row["region_code"], row["region_source"]) == ("CO", "sightings")


def test_a_real_rubro_replaces_otro_but_not_the_reverse(world) -> None:  # noqa: ANN001
    tenant, _ = world
    handle = _handle("otro")
    with tenant_session(tenant) as session:
        _creator(session, "tiktok", handle)
    assert rr.record_inferences(tenant, [_inference(handle, "otro", "")]) == 1
    assert rr.record_inferences(tenant, [_inference(handle, "food_drink", "")]) == 1
    assert rr.record_inferences(tenant, [_inference(handle, "otro", "")]) == 0
    with tenant_session(tenant) as session:
        assert _row(session, "tiktok", handle)["rubro"] == "food_drink"


def test_an_account_outside_the_pool_is_skipped(world) -> None:  # noqa: ANN001
    tenant, _ = world
    assert rr.record_inferences(tenant, [_inference(_handle("ghost"), "food_drink", "CO")]) == 0


# --------------------------------------------------------------------------------------
# tenant isolation: each business counts its own labels
# --------------------------------------------------------------------------------------


def _label(tenant: UUID, brand: UUID, handle: str, label: str) -> None:
    with tenant_session(tenant) as session:
        session.execute(
            text(
                "INSERT INTO brand_account_labels (tenant_id, brand_id, network, handle, label) "
                "VALUES (:t, :b, 'tiktok', :h, :l)"
            ),
            {"t": tenant, "b": brand, "h": handle, "l": label},
        )


def test_each_business_sees_and_counts_only_its_own_accounts() -> None:
    (tenant_a, brand_a), (tenant_b, brand_b) = _world(), _world()
    mine, theirs, hater = _handle("a"), _handle("b"), _handle("d")
    with tenant_session(tenant_a) as session:
        for handle in (mine, theirs, hater):
            _creator(session, "tiktok", handle)
            _sighting(session, "tiktok", handle, "CO")
    _label(tenant_a, brand_a, mine, "referente")
    _label(tenant_a, brand_a, hater, "detractor")  # detractors are out of the epic
    _label(tenant_b, brand_b, theirs, "competencia")

    before_a, report_a, after_a = rr.run_backfill(tenant_a)
    assert (before_a.accounts, before_a.with_region) == (1, 0)
    assert report_a.updated == 1  # only its own label was resolved
    assert (after_a.accounts, after_a.with_region, after_a.with_rubro) == (1, 1, 0)
    with tenant_session(tenant_a) as session:
        assert rr.labeled_accounts(session) == [("tiktok", mine)]
        assert _row(session, "tiktok", theirs)["region_code"] == ""
    with tenant_session(tenant_b) as session:
        assert rr.labeled_accounts(session) == [("tiktok", theirs)]
        # the GUC reset to '' (a pooled connection): the NULLIF policy shows no label
        session.execute(text("SELECT set_config('app.tenant_id', '', true)"))
        assert rr.labeled_accounts(session) == []
    _, _, after_b = rr.run_backfill(tenant_b)
    assert (after_b.accounts, after_b.with_region) == (1, 1)


def test_account_facts_is_the_read_the_filters_use(world) -> None:  # noqa: ANN001
    tenant, _ = world
    handle = _handle("read")
    with tenant_session(tenant) as session:
        _creator(session, "tiktok", handle)
    rr.record_inferences(tenant, [_inference(handle, "food_drink", "CO")])
    with tenant_session(tenant) as session:
        facts = rr.account_facts(session, [("tiktok", handle.upper()), ("tiktok", "nadie")])
    assert facts == {
        ("tiktok", handle): rr.AccountFacts("tiktok", handle, "CO", "ai", "food_drink", "ai")
    }
