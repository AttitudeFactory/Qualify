from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from qualify_scraper.client import FixtureScrapingClient
from qualify_scraper.shared import (
    PAYLOAD_SCHEMA_VERSION,
    LocalDiskRawPayloadStore,
    Platform,
    RawPayloadEnvelope,
    ScrapeProvenance,
    SourceClass,
    build_first_party_envelope,
    build_scrape_envelope,
    canonical_bytes,
    content_signature,
    make_natural_key,
    persist_envelope,
    raw_payload_key,
    sanitize_source_url,
    sanitize_transport_meta,
)

TENANT = UUID("22222222-2222-2222-2222-222222222222")
CONNECTION = UUID("33333333-3333-3333-3333-333333333333")


def _scrape(hydration: dict[str, object], **overrides: object) -> RawPayloadEnvelope:
    kwargs: dict[str, object] = dict(
        platform=Platform.TIKTOK,
        source_url="https://tiktok.example/video",
        hydration=hydration,
        fetched_at=datetime.fromtimestamp(0),
    )
    kwargs.update(overrides)
    return build_scrape_envelope(**kwargs)  # type: ignore[arg-type]


def _first_party(hydration: dict[str, object], **overrides: object) -> RawPayloadEnvelope:
    kwargs: dict[str, object] = dict(
        platform=Platform.INSTAGRAM,
        source_url="https://graph.facebook.com/v21.0/17895",
        hydration=hydration,
        fetched_at=datetime.fromtimestamp(0),
        tenant_id=TENANT,
        connection_id=CONNECTION,
        object_id="17895",
    )
    kwargs.update(overrides)
    return build_first_party_envelope(**kwargs)  # type: ignore[arg-type]


def test_natural_key_shape() -> None:
    brand = UUID("11111111-1111-1111-1111-111111111111")
    assert make_natural_key(brand, Platform.TIKTOK, "abc") == (
        "11111111-1111-1111-1111-111111111111",
        Platform.TIKTOK,
        "abc",
    )


# --- key derivation: two disjoint spaces, derived above the store (C-02.2 / R5) ---


def test_scrape_key_is_brand_agnostic_and_stable() -> None:
    env = _scrape({"a": 1})
    key = raw_payload_key(env)
    assert key.startswith("scrape/tiktok/")
    # URL-derived + overwrite-latest: same URL → same key regardless of content.
    assert raw_payload_key(_scrape({"a": 1})) == raw_payload_key(_scrape({"b": 2}))


def test_first_party_key_is_tenant_prefixed_and_object_addressed() -> None:
    # R5: t/{tenant}/fp/{platform}/{connection}/{object_id}, NOT content-addressed.
    env = _first_party({"a": 1})
    assert raw_payload_key(env) == f"t/{TENANT}/fp/instagram/{CONNECTION}/17895"
    # Overwrite-latest: identical object id → identical key even if the bytes differ
    # (Graph responses carry volatile cursors/timestamps).
    assert raw_payload_key(_first_party({"a": 1})) == raw_payload_key(_first_party({"x": 9}))


def test_key_spaces_never_overlap() -> None:
    scrape_key = raw_payload_key(_scrape({"a": 1}))
    fp_key = raw_payload_key(_first_party({"a": 1}))
    assert scrape_key.startswith("scrape/")
    assert fp_key.startswith(f"t/{TENANT}/fp/")
    # Disjoint by construction of the path, not by incidental URL non-collision.
    assert not scrape_key.startswith("t/")
    assert not fp_key.startswith("scrape/")


def test_edge_object_id_survives_into_key() -> None:
    env = _first_party({"a": 1}, object_id="17895/comments/p2")
    assert raw_payload_key(env) == f"t/{TENANT}/fp/instagram/{CONNECTION}/17895/comments/p2"


# --- object_id traversal guard: multi-segment ids are legitimate, `..`/empty are not ---


@pytest.mark.parametrize(
    "object_id",
    [
        "../../etc/passwd",
        "17895/../../../etc/passwd",
        "..",
        ".",
        "17895/.",
        "17895/..",
        "",
        "17895//comments",  # empty segment via double slash
        "/17895",  # leading slash -> empty first segment, and would jump to fs root
        "17895/",  # trailing slash -> empty last segment
        "17895\x00comments",  # control character (NUL)
        "17895\ncomments",  # control character (newline)
    ],
)
def test_object_id_rejects_traversal_and_control_chars(object_id: str) -> None:
    with pytest.raises(ValidationError):
        _first_party({"a": 1}, object_id=object_id)


def test_object_id_allows_legitimate_multi_segment_ids() -> None:
    # Sanity check that the guard above didn't overcorrect into rejecting the shape
    # test_edge_object_id_survives_into_key depends on.
    env = _first_party({"a": 1}, object_id="17895/comments/p2")
    assert env.object_id == "17895/comments/p2"


# --- unconstructibility: consented data can never emit an un-prefixed key (C-02.4) ---


def test_first_party_without_tenant_is_unconstructible() -> None:
    with pytest.raises((ValidationError, TypeError)):
        RawPayloadEnvelope(
            source_class=SourceClass.FIRST_PARTY_API,
            transport="graph_api",
            platform=Platform.INSTAGRAM,
            source_url="https://graph.facebook.com/v21.0/17895",
            fetched_at=datetime.fromtimestamp(0),
            content_signature=content_signature({"a": 1}),
            hydration={"a": 1},
            # tenant_id / connection_id / object_id deliberately omitted
        )


def test_scrape_may_not_carry_tenant_scoped_fields() -> None:
    # ADR 18: a scrape is tenant-free; forcing tenant fields onto it is rejected.
    with pytest.raises(ValidationError):
        RawPayloadEnvelope(
            source_class=SourceClass.SCRAPE,
            transport="zyte",
            platform=Platform.TIKTOK,
            source_url="https://tiktok.example/video",
            tenant_id=TENANT,
            fetched_at=datetime.fromtimestamp(0),
            content_signature=content_signature({"a": 1}),
            hydration={"a": 1},
        )


# --- no credential ever survives into the artifact (C-02.4, integracion §2.6) ---


def test_sanitize_source_url_strips_access_token() -> None:
    dirty = "https://graph.facebook.com/v21.0/me?fields=id&access_token=SECRET123"
    clean = sanitize_source_url(dirty)
    assert "SECRET123" not in clean
    assert "access_token" not in clean
    assert "fields=id" in clean  # non-credential params preserved


def test_sanitize_transport_meta_drops_credential_keys_recursively() -> None:
    meta = {"request_id": "r1", "access_token": "SECRET", "auth": {"client_secret": "NOPE"}}
    clean = sanitize_transport_meta(meta)
    assert clean == {"request_id": "r1", "auth": {}}


def test_token_never_appears_anywhere_in_first_party_envelope() -> None:
    env = build_first_party_envelope(
        platform=Platform.INSTAGRAM,
        source_url="https://graph.facebook.com/v21.0/17895?access_token=LEAKED_TOKEN",
        hydration={"id": "17895"},
        fetched_at=datetime.fromtimestamp(0),
        tenant_id=TENANT,
        connection_id=CONNECTION,
        object_id="17895",
        transport_meta={"access_token": "LEAKED_TOKEN", "cost": 0.0},
    )
    serialized = env.model_dump_json()
    key = raw_payload_key(env)
    body = canonical_bytes(env.model_dump(mode="json"))
    for surface in (serialized, env.source_url, key, body.decode("utf-8")):
        assert "LEAKED_TOKEN" not in surface


# --- content_signature: pure content identity, no tenant salt, golden-anchored ---


def test_canonical_bytes_is_deterministic_and_compact() -> None:
    a = canonical_bytes({"b": 2, "a": 1})
    b = canonical_bytes({"a": 1, "b": 2})
    assert a == b == b'{"a":1,"b":2}'


def test_canonical_bytes_preserves_array_order() -> None:
    # Arrays are NOT reordered — order is significant (derives MediaItem.ordinal).
    assert canonical_bytes({"m": [3, 1, 2]}) == b'{"m":[3,1,2]}'


def test_canonical_bytes_rejects_nan_and_infinity() -> None:
    with pytest.raises(ValueError):
        canonical_bytes({"x": float("nan")})
    with pytest.raises(ValueError):
        canonical_bytes({"x": float("inf")})


def test_content_signature_golden_anchor() -> None:
    # Absolute anchor: pins the signature algorithm (canonical bytes + sha256) so a
    # silent change to either is caught. `canonical_bytes({"a": 1}) == b'{"a":1}'`.
    assert content_signature({"a": 1}) == (
        "sha256:015abd7f5cc57a2dd94b7590f04ad8084273905ee33ec5cebeae62276a97f862"
    )
    assert content_signature({"a": 1}) == "sha256:" + hashlib.sha256(b'{"a":1}').hexdigest()


def test_content_signature_ignores_key_order() -> None:
    ordered = {"a": 1, "b": {"x": 1, "y": 2}}
    reordered = {"b": {"y": 2, "x": 1}, "a": 1}
    assert content_signature(ordered) == content_signature(reordered)


def test_content_signature_is_not_tenant_salted() -> None:
    # Same content under two tenants → identical signature (isolation is the key path,
    # not the content identity; R5). Dedup/re-parse/staleness depend on this.
    a = _first_party({"same": "content"}, tenant_id=TENANT)
    b = _first_party(
        {"same": "content"},
        tenant_id=UUID("44444444-4444-4444-4444-444444444444"),
    )
    assert a.content_signature == b.content_signature


# --- envelope shape (v2) ---


def test_scrape_envelope_shape() -> None:
    env = _scrape({"a": 1, "b": 2})
    assert env.payload_schema_version == PAYLOAD_SCHEMA_VERSION == 2
    assert env.source_class is SourceClass.SCRAPE
    assert env.transport == "zyte"
    assert env.transport_meta == {}
    assert env.content_signature == content_signature(env.hydration)
    assert env.tenant_id is None and env.connection_id is None and env.object_id is None
    # Brand-agnostic: no brand_id / post_id / r2_key on the envelope.
    for absent in ("brand_id", "post_id", "r2_key", "natural_key"):
        assert not hasattr(env, absent)


def test_first_party_envelope_shape() -> None:
    env = _first_party({"id": "17895"})
    assert env.source_class is SourceClass.FIRST_PARTY_API
    assert env.transport == "graph_api"
    assert env.tenant_id == TENANT
    assert env.connection_id == CONNECTION
    assert env.object_id == "17895"


def test_dedup_on_identical_content_signature() -> None:
    same = {
        _scrape({"a": 1, "b": 2}).content_signature,
        _scrape({"b": 2, "a": 1}).content_signature,
    }
    assert len(same) == 1  # identical content dedups regardless of key order
    changed = same | {_scrape({"a": 1, "b": 3}).content_signature}
    assert len(changed) == 2


def test_payload_schema_version_independent_of_content_signature() -> None:
    hydration = {"k": "v"}
    env_v2 = _scrape(hydration, payload_schema_version=2)
    env_v3 = _scrape(hydration, payload_schema_version=3)
    assert env_v2.content_signature == env_v3.content_signature
    assert env_v2.payload_schema_version != env_v3.payload_schema_version


# --- store is a pure (key, body) sink; persist derives the key above the store ---


def test_local_disk_store_writes_body_verbatim(tmp_path: Path) -> None:
    store = LocalDiskRawPayloadStore(tmp_path)
    body = b'{"a":1}'
    key = store.persist("scrape/instagram/deadbeef", body)
    assert key == "scrape/instagram/deadbeef"
    assert (tmp_path / key).read_bytes() == body


def test_persisted_envelope_is_self_verifiable(tmp_path: Path) -> None:
    store = LocalDiskRawPayloadStore(tmp_path)
    env = _scrape({"b": 2, "a": 1, "nested": {"y": 1, "x": 2}})
    key = persist_envelope(store, env)

    assert key == raw_payload_key(env)
    stored = (tmp_path / key).read_bytes()
    # Persisted bytes are the canonical bytes of the whole envelope, verbatim.
    assert stored == canonical_bytes(env.model_dump(mode="json"))

    reloaded = RawPayloadEnvelope.model_validate_json(stored)
    assert reloaded.content_signature == content_signature(reloaded.hydration)
    assert reloaded.content_signature == env.content_signature


def test_first_party_persist_round_trips(tmp_path: Path) -> None:
    store = LocalDiskRawPayloadStore(tmp_path)
    env = _first_party({"id": "17895"})
    key = persist_envelope(store, env)
    assert key == f"t/{TENANT}/fp/instagram/{CONNECTION}/17895"
    reloaded = RawPayloadEnvelope.model_validate_json((tmp_path / key).read_bytes())
    assert reloaded.source_class is SourceClass.FIRST_PARTY_API
    assert reloaded.tenant_id == TENANT


def test_provenance_content_signature_round_trips() -> None:
    sig = content_signature({"a": 1})
    provenance = ScrapeProvenance(
        hydration_json_r2_key="scrape/tiktok/x",
        content_signature=sig,
        source_url="https://tiktok.example/video",
        scraped_at=datetime.fromtimestamp(0),
        parser_version="tiktok-parser-0.1.0",
        pipeline_version="0.1.0",
    )
    reloaded = ScrapeProvenance.model_validate(provenance.model_dump(mode="json"))
    assert reloaded.content_signature == sig


def test_build_envelope_end_to_end_via_fixture_client(fixtures_dir: Path) -> None:
    url = "https://tiktok.example/video"
    client = FixtureScrapingClient(
        {url: fixtures_dir / "tiktok" / "video.json"}, platform=Platform.TIKTOK
    )
    env = client.fetch_hydration(url)
    assert env.source_class is SourceClass.SCRAPE
    assert env.platform == Platform.TIKTOK
    assert env.source_url == url
    assert env.payload_schema_version == 2
    assert env.content_signature == content_signature(env.hydration)
    assert env.transport_meta == {}
