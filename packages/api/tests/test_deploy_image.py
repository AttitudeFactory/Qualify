"""Static guards on `deploy/Dockerfile`'s local sentiment model (robertuito on the VPS).

Text checks on purpose: importing `qualify_models.sentiment` would drag the `ml` tree into
the default test run (R11(b)).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = (REPO_ROOT / "deploy" / "Dockerfile").read_text()


def test_baked_sentiment_model_is_the_one_the_code_loads() -> None:
    # The image pre-downloads SENTIMENT_MODEL_ID; the service loads MODEL_ID. If they drift,
    # production silently downloads the other model on the first analysis (or cannot).
    sentiment_py = (
        REPO_ROOT / "packages" / "models" / "src" / "qualify_models" / "sentiment.py"
    ).read_text()
    model_id = re.search(r'^MODEL_ID = "([^"]+)"', sentiment_py, re.M)
    baked = re.search(r"^ARG SENTIMENT_MODEL_ID=(\S+)$", DOCKERFILE, re.M)
    assert model_id and baked
    assert baked.group(1) == model_id.group(1)


def test_image_installs_the_sentiment_runtime_on_every_sync() -> None:
    # `SentimentService` refuses with SentimentModelUnavailable unless torch + transformers
    # are importable; both `uv sync` layers must carry the group or the second one prunes it.
    syncs = re.findall(r"uv sync --frozen[^\n]*", DOCKERFILE)
    assert len(syncs) == 2
    assert all("--group sentiment" in sync for sync in syncs)


def _stage(name: str) -> str:
    match = re.search(rf"^FROM \S+ AS {name}$(.*?)(?=^FROM |\Z)", DOCKERFILE, re.M | re.S)
    assert match, f"no {name} stage"
    return match.group(1)


def test_app_image_has_ffmpeg_for_clip_normalization() -> None:
    # m-24957792: `FfmpegVideoNormalizer` shells out to ffmpeg/ffprobe from the reflex
    # container (catalog upload); without the binaries every product clip upload failed with
    # «No pudimos abrir este video». CI's image smoke also runs `ffmpeg -version`.
    installs = re.findall(r"apt-get install[^\n]*", _stage("app"))
    assert any(re.search(r"\bffmpeg\b", line) for line in installs)


def test_reflex_has_room_for_the_clip_ffmpeg() -> None:
    # m-24957792: product clips are normalized inside `reflex`; ~260 MiB measured in prod
    # (2026-11-06) plus ~245 MiB ffmpeg peak does not fit the old 512m cap.
    yaml = pytest.importorskip("yaml")
    compose = (REPO_ROOT / "deploy" / "docker-compose.prod.yml").read_text(encoding="utf-8")
    reflex = yaml.safe_load(compose)["services"]["reflex"]
    assert reflex["mem_limit"] == reflex["memswap_limit"] == "768m"
