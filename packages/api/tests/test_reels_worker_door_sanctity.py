"""Static guard on the reels-worker's door (ADR 42 R8, m-24854855): `reels_worker_session`
(`qualify_reels_worker`) is imported only by the worker's own modules — `reel_queue`
(it reads across businesses and decides which run is next), `reel_analysis` and
`reel_retention` (they write the two GLOBAL analysis tables: the copy of each idea's video
and its 30-day purge) — never by the screen, a request path or another worker. And
`reel_queue` opens no other door: every write about a business goes through
`tenant_session` elsewhere. Pure AST, no database."""

from __future__ import annotations

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_ROOTS = (_REPO / "packages", _REPO / "Qualify")
_DOOR_MODULE = "qualify_shared.db.reels_worker"
_ALLOWED = _REPO / "packages/api/src/qualify_api/referentes/reel_queue.py"
_WRITERS = {
    _REPO / "packages/api/src/qualify_api/referentes/reel_analysis.py",
    _REPO / "packages/api/src/qualify_api/referentes/reel_retention.py",
}
_DOOR_FILE = _REPO / "packages/shared/src/qualify_shared/db/reels_worker.py"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.name for alias in node.names)
            if node.module:
                names.add(node.module)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def _sources() -> list[Path]:
    return [
        path
        for root in _ROOTS
        for path in root.rglob("*.py")
        if "/tests/" not in path.as_posix()
        and not path.name.startswith("test_")
        and ".venv" not in path.parts
        and "node_modules" not in path.parts
    ]


def test_only_the_reel_queue_imports_the_reels_worker_door() -> None:
    offenders = sorted(
        str(path.relative_to(_REPO))
        for path in _sources()
        if path not in {_ALLOWED, _DOOR_FILE, *_WRITERS}
        and (
            "reels_worker_session" in (names := _imports(path))
            or _DOOR_MODULE in names
            or any(name.endswith("db.reels_worker") for name in names)
        )
    )
    assert offenders == [], f"the reels-worker's door is used outside reel_queue: {offenders}"


def test_the_reel_queue_opens_no_other_door() -> None:
    names = _imports(_ALLOWED)
    assert "reels_worker_session" in names
    others = {"tenant_session", "admin_session", "credential_session", "global_session"}
    assert names & others == set()
    assert not any(name.startswith("qualify_shared.db.") and name != _DOOR_MODULE for name in names)
