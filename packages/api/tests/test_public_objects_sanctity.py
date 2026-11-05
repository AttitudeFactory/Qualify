"""Static guard on the public R2 door (ADR 44 F5; the R8 slice of VE-04a/VE-12): the
copies of public reels under `public/reel-analyses/` are written, read and deleted only by
the reels-worker's analysis (`reel_analysis`), its 30-day purge (`reel_retention`) and the
server-side «Replicar» reference (`reel_reference`). The screen (`Qualify/`) never calls
the public door, and nothing builds a URL to it. Pure AST, no network."""

from __future__ import annotations

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_DOOR_METHODS = frozenset({"put_public", "open_public", "delete_public_prefix"})
_ALLOWED = {
    _REPO / "packages/api/src/qualify_api/referentes/reel_analysis.py",
    _REPO / "packages/api/src/qualify_api/referentes/reel_retention.py",
    _REPO / "packages/api/src/qualify_api/referentes/reel_reference.py",
    _REPO / "packages/shared/src/qualify_shared/objects/public.py",  # where they are defined
}


def _sources() -> list[Path]:
    files = list((_REPO / "packages").glob("*/src/**/*.py"))
    files += [
        p
        for p in (_REPO / "Qualify").rglob("*.py")
        if not p.name.startswith("test_") and ".venv" not in p.parts
    ]
    return sorted(set(files))


def _callers(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in _DOOR_METHODS
    ]


def test_only_the_reel_video_modules_use_the_public_door() -> None:
    offenders = [
        f"{path.relative_to(_REPO)}:{line}"
        for path in _sources()
        if path not in _ALLOWED
        for line in _callers(path)
    ]
    assert offenders == [], f"the public R2 door is used outside its modules: {offenders}"


def test_the_allowed_modules_do_use_it() -> None:
    """Keeps the allowlist honest: a module that stops using the door leaves the list."""
    for path in _ALLOWED - {_REPO / "packages/shared/src/qualify_shared/objects/public.py"}:
        assert _callers(path), path
