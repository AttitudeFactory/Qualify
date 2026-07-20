import json
from pathlib import Path

import pytest

from qualify_models.eval.schema import load_golden_set

FIXTURES = Path(__file__).parent / "fixtures"


def _write_manifest(tmp_path: Path, rows: list[dict]) -> Path:
    manifest = tmp_path / "golden.jsonl"
    manifest.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return manifest


def _row(**overrides: object) -> dict:
    row = {
        "post_id": "tiktok_1",
        "platform": "tiktok",
        "image_path": "img.jpg",
        "audio_path": "aud.wav",
        "caption": "hola mundo",
        "filter_relevant": True,
        "reference_transcript": "hola mundo",
        "sentiment_label": "NEU",
        "labeler": "datasci",
        "labeled_at": "2026-07-19",
    }
    row.update(overrides)
    return row


def test_load_resolves_paths_relative_to_manifest(tmp_path: Path) -> None:
    (tmp_path / "img.jpg").write_bytes(b"x")
    (tmp_path / "aud.wav").write_bytes(b"x")
    manifest = _write_manifest(tmp_path, [_row()])

    golden_set = load_golden_set(manifest)

    assert len(golden_set.items) == 1
    item = golden_set.items[0]
    assert item.image_path == (tmp_path / "img.jpg").resolve()
    assert item.filter_relevant is True
    assert item.sentiment_label == "NEU"


def test_load_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    (tmp_path / "img.jpg").write_bytes(b"x")
    (tmp_path / "aud.wav").write_bytes(b"x")
    manifest = tmp_path / "golden.jsonl"
    manifest.write_text("# header comment\n\n" + json.dumps(_row()) + "\n")

    golden_set = load_golden_set(manifest)
    assert len(golden_set.items) == 1


def test_load_missing_fixture_raises(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path, [_row()])  # no img/aud files written
    with pytest.raises(FileNotFoundError):
        load_golden_set(manifest)


def test_load_captures_manifest_version_and_hash(tmp_path: Path) -> None:
    (tmp_path / "img.jpg").write_bytes(b"x")
    (tmp_path / "aud.wav").write_bytes(b"x")
    manifest = tmp_path / "golden.jsonl"
    manifest.write_text("# manifest_version: 7\n" + json.dumps(_row()) + "\n")

    golden_set = load_golden_set(manifest)
    assert golden_set.manifest_version == "7"
    assert golden_set.manifest_id == "golden"
    # sha256 hex digest is 64 chars and reproducible from the file bytes.
    assert golden_set.manifest_sha256 is not None
    assert len(golden_set.manifest_sha256) == 64


def test_shipped_golden_set_v1_loads() -> None:
    manifest = Path(__file__).parents[1] / "eval_data" / "golden_set_v1.jsonl"
    golden_set = load_golden_set(manifest)
    assert len(golden_set.items) == 1
    assert golden_set.manifest_version == "1"
    assert golden_set.manifest_id == "golden_set_v1"
    item = golden_set.items[0]
    assert item.image_path == (FIXTURES / "sample_frame.jpg").resolve()
    assert item.audio_path == (FIXTURES / "sample_audio.wav").resolve()
    assert item.filter_relevant is True
