"""The read-only door to the effects' example videos in R2 (m-25120474).

EF-12 (m-25026587, Deivid 2026-11-25) keeps the «Así se ve» video of a «Con IA» effect —
its winning bench video — in R2 under a PLATFORM key, never in the repository:
exactly `platform/effects/<id>/v<version>/preview.mp4`
(`qualify_creative.effects.platform_preview_key`). No tenant, no business in the key, and
outside the bucket lock on `t/`.

`ObjectGate` only knows `t/{tenant}/…`, so these keys need a door of their own instead of
a hole in the tenant one — the same reasoning as `qualify_shared.objects.public`. This door
is closed by construction:

- it only READS (`size`, `open`, `open_range`): no put, no delete, no listing;
- the caller never hands it a key: it builds the one key shape from an effect id and a
  version that `preview_key` checks with a strict expression first (`EFFECT_ID_RE`, the
  library's own `EFFECT_ID_PATTERN`; a version `1..9999` with no leading zero), so `..`,
  `/`, `%`, a backslash or anything else never reaches the store;
- the file inside `v<n>/` is fixed: `preview.mp4`, served as `video/mp4`.
"""

from __future__ import annotations

import re
from typing import IO

from qualify_shared.objects.gate import ObjectStore

PLATFORM_EFFECTS_PREFIX = "platform/effects/"
#: The one file of a version folder that is the «Así se ve» video.
PREVIEW_FILE = "preview.mp4"
PREVIEW_CONTENT_TYPE = "video/mp4"

#: `qualify_creative.schemas.EFFECT_ID_PATTERN`, copied (shared imports no creative; a test
#: keeps the two equal).
EFFECT_ID_RE = re.compile(r"[a-z][a-z0-9_]{0,39}")
#: A library version: 1..9999, no sign, no leading zero.
VERSION_RE = re.compile(r"[1-9][0-9]{0,3}")


class NotAnEffectPreview(ValueError):
    """The id or the version is not one this door names (always answered as a 404)."""


def preview_key(effect_id: object, version: object) -> str:
    """`platform/effects/<id>/v<version>/preview.mp4`, or `NotAnEffectPreview`.

    `version` is the number alone (`"1"` or `1`), never `"v1"`."""
    if not isinstance(effect_id, str) or not EFFECT_ID_RE.fullmatch(effect_id):
        raise NotAnEffectPreview("effect id")
    text = str(version) if isinstance(version, int) and not isinstance(version, bool) else version
    if not isinstance(text, str) or not VERSION_RE.fullmatch(text):
        raise NotAnEffectPreview("version")
    return f"{PLATFORM_EFFECTS_PREFIX}{effect_id}/v{text}/{PREVIEW_FILE}"


def is_effect_preview_key(key: object) -> bool:
    """Whether `key` is exactly a key `preview_key` builds (nothing more under it)."""
    if not isinstance(key, str) or not key.startswith(PLATFORM_EFFECTS_PREFIX):
        return False
    parts = key[len(PLATFORM_EFFECTS_PREFIX) :].split("/")
    if len(parts) != 3 or parts[2] != PREVIEW_FILE or not parts[1].startswith("v"):
        return False
    try:
        return preview_key(parts[0], parts[1][1:]) == key
    except NotAnEffectPreview:
        return False


class PlatformEffectsReader:
    """Reads one effect's example video; every method takes (id, version), never a key."""

    def __init__(self, store: ObjectStore) -> None:
        self._store = store

    def size(self, effect_id: str, version: str | int) -> int:
        return self._store.size(preview_key(effect_id, version))  # type: ignore[attr-defined]

    def open(self, effect_id: str, version: str | int) -> IO[bytes]:
        return self._store.open(preview_key(effect_id, version))

    def open_range(self, effect_id: str, version: str | int, start: int, end: int) -> IO[bytes]:
        key = preview_key(effect_id, version)
        return self._store.open_range(key, start, end)  # type: ignore[attr-defined]
