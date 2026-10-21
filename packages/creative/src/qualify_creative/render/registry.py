"""Where the published templates are found: one `manifest.json` per directory under the
render package (`packages/render/templates/<id>/`), versioned in git.

Git is the publication mechanism for the MVP (plan §2.2): a manifest in `main` is a
published version. The registry is read-only and cheap; callers construct it per request
or cache it — it holds a few kilobytes.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Iterator
from pathlib import Path

from qualify_creative.render.manifest import TemplateManifest

ENV_TEMPLATES_DIR = "QUALIFY_RENDER_TEMPLATES_DIR"


def default_templates_dir() -> Path:
    """`packages/render/templates` next to this workspace member, unless the env var
    points elsewhere (the container mounts them at `/app/templates`)."""
    override = os.environ.get(ENV_TEMPLATES_DIR)
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[4] / "render" / "templates"


class TemplateNotFound(KeyError):
    pass


class TemplateRegistry:
    def __init__(self, manifests: Iterable[TemplateManifest]) -> None:
        self._by_key: dict[str, TemplateManifest] = {}
        self._latest: dict[str, TemplateManifest] = {}
        for m in manifests:
            if m.key in self._by_key:
                raise ValueError(f"duplicate template manifest {m.key}")
            self._by_key[m.key] = m
            current = self._latest.get(m.id)
            if current is None or m.version > current.version:
                self._latest[m.id] = m

    @classmethod
    def from_dir(cls, root: Path | None = None) -> TemplateRegistry:
        root = root or default_templates_dir()
        return cls(_load_manifests(root))

    def __iter__(self) -> Iterator[TemplateManifest]:
        return iter(sorted(self._by_key.values(), key=lambda m: (m.id, m.version)))

    def __len__(self) -> int:
        return len(self._by_key)

    def get(self, template_id: str, version: int | None = None) -> TemplateManifest:
        if version is None:
            try:
                return self._latest[template_id]
            except KeyError:
                raise TemplateNotFound(template_id) from None
        try:
            return self._by_key[f"{template_id}@{version}"]
        except KeyError:
            raise TemplateNotFound(f"{template_id}@{version}") from None

    def latest(self) -> list[TemplateManifest]:
        return sorted(self._latest.values(), key=lambda m: m.id)

    def for_post(self, *, angle: str, niche: str | None) -> list[TemplateManifest]:
        """Latest versions that declare they serve this angle and fit this niche."""
        return [m for m in self.latest() if m.serves(angle) and m.fits_niche(niche)]


_MANIFEST_NAME = re.compile(r"^manifest(\.v\d+)?\.json$")


def _load_manifests(root: Path) -> list[TemplateManifest]:
    if not root.is_dir():
        return []
    out: list[TemplateManifest] = []
    # `manifest.json` is the latest; an older published version is kept beside it as
    # `manifest.v<N>.json` (CONTRACT §1) so a run pinned to it still resolves
    for path in sorted(root.glob("*/manifest*.json")):
        if not _MANIFEST_NAME.match(path.name):
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        manifest = TemplateManifest.model_validate(raw)
        if manifest.id != path.parent.name:
            raise ValueError(
                f"{path}: manifest id {manifest.id!r} does not match its directory "
                f"{path.parent.name!r}"
            )
        out.append(manifest)
    return out
