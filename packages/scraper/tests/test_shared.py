from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest

from qualify_scraper.client import FixtureScrapingClient
from qualify_scraper.shared import (
    PAYLOAD_SCHEMA_VERSION,
    LocalDiskRawPayloadStore,
    Platform,
    RawPayloadEnvelope,
    ScrapeProvenance,
    build_envelope,
    canonical_bytes,
    content_signature,
    make_natural_key,
    persist_envelope,
    raw_payload_key,
)


def _envelope(hydration: dict[str, object], **overrides: object) -> RawPayloadEnvelope:
    kwargs: dict[str, object] = dict(
        platform=Platform.TIKTOK,
        source_url="https://tiktok.example/video",
        hydration=hydration,
        fetched_at=datetime.fromtimestamp(0),
    )
    kwargs.update(overrides)
    return build_envelope(**kwargs)  # type: ignore[arg-type]


def test_natural_key_shape() -> None:
    brand = UUID("11111111-1111-1111-1111-111111111111")
    assert make_natural_key(brand, Platform.TIKTOK, "abc") == (
        "11111111-1111-1111-1111-111111111111",
        Platform.TIKTOK,
        "abc",
    )


def test_raw_payload_key_is_stable_per_url() -> None:
    url = "https://www.tiktok.com/@x/video/1"
    assert raw_payload_key(Platform.TIKTOK, url) == raw_payload_key(Platform.TIKTOK, url)
    assert raw_payload_key(Platform.TIKTOK, url).startswith("hydration/tiktok/")


def test_local_disk_store_writes_body_verbatim(tmp_path: Path) -> None:
    store = LocalDiskRawPayloadStore(tmp_path)
    body = b'{"a":1}'
    key = store.persist(Platform.INSTAGRAM, "https://instagram.com/p/1", body)
    assert key.startswith("hydration/instagram/")
    # Pure bytes sink: what was handed in is exactly what lands on disk.
    assert (tmp_path / key).read_bytes() == body


def test_canonical_bytes_is_deterministic_and_compact() -> None:
    a = canonical_bytes({"b": 2, "a": 1})
    b = canonical_bytes({"a": 1, "b": 2})
    assert a == b
    assert a == b'{"a":1,"b":2}'  # keys sorted, no ambiguous whitespace


def test_canonical_bytes_preserves_array_order() -> None:
    # Arrays are NOT reordered — order is significant (derives MediaItem.ordinal).
    assert canonical_bytes({"m": [3, 1, 2]}) == b'{"m":[3,1,2]}'


def test_canonical_bytes_rejects_nan_and_infinity() -> None:
    with pytest.raises(ValueError):
        canonical_bytes({"x": float("nan")})
    with pytest.raises(ValueError):
        canonical_bytes({"x": float("inf")})


def test_content_signature_has_sha256_prefix() -> None:
    sig = content_signature({"a": 1})
    assert sig.startswith("sha256:")
    hex_part = sig.removeprefix("sha256:")
    assert len(hex_part) == 64
    assert hex_part == hashlib.sha256(canonical_bytes({"a": 1})).hexdigest()


def test_content_signature_ignores_key_order() -> None:
    ordered = {"a": 1, "b": {"x": 1, "y": 2}}
    reordered = {"b": {"y": 2, "x": 1}, "a": 1}
    assert content_signature(ordered) == content_signature(reordered)


def test_content_signature_changes_when_content_changes() -> None:
    assert content_signature({"a": 1}) != content_signature({"a": 2})


def test_build_envelope_is_brand_agnostic_and_signed() -> None:
    env = _envelope({"a": 1, "b": 2})
    assert env.payload_schema_version == PAYLOAD_SCHEMA_VERSION == 1
    assert env.platform == Platform.TIKTOK
    assert env.source_url == "https://tiktok.example/video"
    assert env.zyte_request_meta == {}
    assert env.content_signature == content_signature(env.hydration)
    # Brand-agnostic: no brand_id / post_id / r2_key / natural_key on the envelope.
    for absent in ("brand_id", "post_id", "r2_key", "natural_key"):
        assert not hasattr(env, absent)


def test_dedup_on_identical_content_signature() -> None:
    same_content = {
        _envelope({"a": 1, "b": 2}).content_signature,
        _envelope({"b": 2, "a": 1}).content_signature,
    }
    assert len(same_content) == 1  # identical content dedups regardless of key order

    changed = same_content | {_envelope({"a": 1, "b": 3}).content_signature}
    assert len(changed) == 2  # changed content is a distinct artifact


def test_payload_schema_version_independent_of_content_signature() -> None:
    hydration = {"k": "v"}
    env_v1 = _envelope(hydration, payload_schema_version=1)
    env_v2 = _envelope(hydration, payload_schema_version=2)
    # Input-shape version is not part of the signed content.
    assert env_v1.content_signature == env_v2.content_signature
    assert env_v1.payload_schema_version != env_v2.payload_schema_version
    # parser_version is a separate axis living on the parsed layer.
    provenance = ScrapeProvenance(
        hydration_json_r2_key="hydration/x.json",
        content_signature=env_v1.content_signature,
        source_url="https://tiktok.example/video",
        scraped_at=datetime.fromtimestamp(0),
        parser_version="tiktok-parser-v2",
        pipeline_version="0.1.0",
    )
    assert provenance.parser_version != str(env_v1.payload_schema_version)


def test_provenance_content_signature_round_trips() -> None:
    sig = content_signature({"a": 1})
    provenance = ScrapeProvenance(
        hydration_json_r2_key="hydration/x.json",
        content_signature=sig,
        source_url="https://tiktok.example/video",
        scraped_at=datetime.fromtimestamp(0),
        parser_version="tiktok-parser-0.1.0",
        pipeline_version="0.1.0",
    )
    reloaded = ScrapeProvenance.model_validate(provenance.model_dump(mode="json"))
    assert reloaded.content_signature == sig


def test_persisted_envelope_is_self_verifiable(tmp_path: Path) -> None:
    # Verification invariant: recompute the signature from the stored artifact alone.
    store = LocalDiskRawPayloadStore(tmp_path)
    env = _envelope({"b": 2, "a": 1, "nested": {"y": 1, "x": 2}})
    key = persist_envelope(store, env)

    stored = (tmp_path / key).read_bytes()
    # Persisted bytes are the canonical bytes of the whole envelope, verbatim.
    assert stored == canonical_bytes(env.model_dump(mode="json"))

    reloaded = RawPayloadEnvelope.model_validate_json(stored)
    assert reloaded.content_signature == content_signature(reloaded.hydration)
    assert reloaded.content_signature == env.content_signature


def test_build_envelope_end_to_end_via_fixture_client(fixtures_dir: Path) -> None:
    url = "https://tiktok.example/video"
    client = FixtureScrapingClient(
        {url: fixtures_dir / "tiktok" / "video.json"}, platform=Platform.TIKTOK
    )
    env = client.fetch_hydration(url)

    assert env.platform == Platform.TIKTOK
    assert env.source_url == url
    assert env.payload_schema_version == 1
    assert env.content_signature == content_signature(env.hydration)
    assert env.zyte_request_meta == {}
