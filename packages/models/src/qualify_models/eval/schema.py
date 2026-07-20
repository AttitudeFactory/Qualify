from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

SentimentLabel = Literal["POS", "NEU", "NEG"]
Platform = Literal["tiktok", "instagram"]

# Optional first-class version directive in a manifest, e.g. "# manifest_version: 1".
_VERSION_DIRECTIVE = re.compile(r"^#\s*manifest_version:\s*(?P<version>\S+)\s*$")


class GoldenItem(BaseModel):
    """One human-labeled video in the golden set.

    Ground-truth fields are what a human annotator asserts is correct; the
    harness compares the cascade's predictions against them. Label provenance
    (labeler / labeled_at) travels with the item so a report can be traced back
    to who produced its ground truth and when.
    """

    post_id: str
    platform: Platform
    image_path: Path
    audio_path: Path
    caption: str | None = None

    # Ground truth.
    filter_relevant: bool  # should the F2 filter let this through as a candidate
    reference_transcript: str  # human reference used as WER ground truth
    sentiment_label: SentimentLabel | None = None  # ground-truth caption polarity

    # Label provenance.
    labeler: str
    labeled_at: date
    source_notes: str | None = None


class GoldenSet(BaseModel):
    manifest_path: Path | None = None
    manifest_version: str | None = None  # declared "# manifest_version:" directive
    manifest_sha256: str | None = None  # content hash of the manifest file bytes
    items: list[GoldenItem]

    @property
    def manifest_id(self) -> str | None:
        return self.manifest_path.stem if self.manifest_path is not None else None

    def validate_paths(self) -> None:
        """Assert every referenced fixture exists on disk. Called by the loader
        so a bad manifest fails fast rather than mid-run."""
        missing: list[str] = []
        for item in self.items:
            for label, path in (("image", item.image_path), ("audio", item.audio_path)):
                if not path.exists():
                    missing.append(f"{item.post_id}: {label} path not found: {path}")
        if missing:
            raise FileNotFoundError("Golden-set fixture paths missing:\n" + "\n".join(missing))


def load_golden_set(manifest_path: Path, validate_paths: bool = True) -> GoldenSet:
    """Load a JSONL manifest (one GoldenItem per line). Relative image/audio
    paths are resolved against the manifest's parent directory so a manifest is
    portable regardless of the caller's working directory."""
    manifest_path = Path(manifest_path)
    base_dir = manifest_path.parent
    raw_bytes = manifest_path.read_bytes()
    manifest_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    manifest_version: str | None = None
    items: list[GoldenItem] = []
    for line_no, raw in enumerate(raw_bytes.decode("utf-8").splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            match = _VERSION_DIRECTIVE.match(stripped)
            if match:
                manifest_version = match.group("version")
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{manifest_path}:{line_no}: invalid JSON: {exc}") from exc
        item = GoldenItem.model_validate(payload)
        item.image_path = _resolve(base_dir, item.image_path)
        item.audio_path = _resolve(base_dir, item.audio_path)
        items.append(item)

    golden_set = GoldenSet(
        manifest_path=manifest_path,
        manifest_version=manifest_version,
        manifest_sha256=manifest_sha256,
        items=items,
    )
    if validate_paths:
        golden_set.validate_paths()
    return golden_set


def _resolve(base_dir: Path, path: Path) -> Path:
    return path if path.is_absolute() else (base_dir / path).resolve()
