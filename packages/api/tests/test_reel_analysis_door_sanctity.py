"""Static guards for the shared reel analysis (ADR 44, m-24921056 VE-04a) and the
`reels-worker` around it (ADR 42 R8, m-24854855). Pure AST.

- The `qualify_reels_worker` door is imported only by the analysis queue and its worker
  (they write the global analyses) and by R8's `reel_queue` (it reads which brand is due
  and which run is next, 0134): no request path can write a result every business reads.
  `reel_queue` opens no other door: every write about a business goes through
  `tenant_session` elsewhere.
- The public R2 door is imported only by `referentes.reel_analysis*`, the 30-day purge
  (`reel_retention`, the R8 slice of VE-12) and the server-side «Replicar»
  (`reel_reference`, R8); and each module calls only what it needs: the purge
  `delete_public_prefix` and nothing else, «Replicar» `open_public` and nothing else, and
  no analysis module deletes (one owner per prefix, RN14). The screen (`Qualify/`) never
  touches it. R12/R13 join when they land, as reviewed additions.
- The analysis and its purge never charge a business (decision #10: the cost lives on the
  global row and in Langfuse) and never call ScrapeCreators (they read the networks' CDNs
  and R2 only).
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src" / "qualify_api"
_REPO = Path(__file__).resolve().parents[3]
_REPO_SRC = _REPO / "packages"

_WORKER_DOOR_USERS = {
    "packages/api/src/qualify_api/referentes/reel_analysis_queue.py",
    "packages/api/src/qualify_api/referentes/reel_analysis_worker.py",
    "packages/api/src/qualify_api/referentes/reel_queue.py",
}
_DOOR_FILE = "packages/shared/src/qualify_shared/db/reels_worker.py"
_REEL_QUEUE = _SRC / "referentes" / "reel_queue.py"

_PUBLIC_DOOR = "packages/shared/src/qualify_shared/objects/public.py"
_PUBLIC_METHODS = frozenset(
    {"put_public", "open_public", "public_size", "open_public_range", "delete_public_prefix"}
)
#: The only methods of the public door each non-analysis module may call (N4).
_PUBLIC_METHODS_OF = {
    "packages/api/src/qualify_api/referentes/reel_retention.py": {"delete_public_prefix"},
    "packages/api/src/qualify_api/referentes/reel_reference.py": {"open_public"},
}


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


def _public_calls(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in _PUBLIC_METHODS
    }


def _every_source() -> list[Path]:
    """Every module that ships: the packages' `src/` trees and the screen (`Qualify/`),
    without tests."""
    roots = [_REPO_SRC / p / "src" for p in ("api", "shared", "scraper", "creative", "models")]
    files = [path for root in roots if root.exists() for path in root.rglob("*.py")]
    files += [
        path
        for path in (_REPO / "Qualify").rglob("*.py")
        if not path.name.startswith("test_")
        and ".venv" not in path.parts
        and "node_modules" not in path.parts
        and ".web" not in path.parts
    ]
    return sorted(set(files))


def _relative(path: Path) -> str:
    return path.relative_to(_REPO).as_posix()


def _is_analysis(path: Path) -> bool:
    return path.parent.name == "referentes" and path.name.startswith("reel_analysis")


def test_the_reels_worker_door_is_imported_only_by_the_worker_modules() -> None:
    offenders = []
    for path in _every_source():
        relative = _relative(path)
        names = _imports(path)
        uses = "reels_worker_session" in names or any(n.endswith("db.reels_worker") for n in names)
        if uses and relative not in _WORKER_DOOR_USERS | {_DOOR_FILE}:
            offenders.append(relative)
    assert offenders == []


def test_the_queues_do_use_the_door() -> None:
    """Keeps the allowlist honest for the two modules whose SQL is the door's reason to
    exist (the analysis worker reaches it through `PostgresAnalysisQueue`)."""
    for relative in _WORKER_DOOR_USERS - {
        "packages/api/src/qualify_api/referentes/reel_analysis_worker.py"
    }:
        assert "reels_worker_session" in _imports(_REPO / relative), relative


def test_the_reel_queue_opens_no_other_door() -> None:
    names = _imports(_REEL_QUEUE)
    assert "reels_worker_session" in names
    others = {"tenant_session", "admin_session", "credential_session", "global_session"}
    assert names & others == set()
    assert not any(
        n.startswith("qualify_shared.db.") and n != "qualify_shared.db.reels_worker" for n in names
    )


def test_the_public_r2_door_is_used_only_by_the_reel_analysis_purge_and_replicar() -> None:
    offenders = []
    for path in _every_source():
        names = _imports(path)
        if not any(n.endswith("objects.public") for n in names):
            continue
        if _is_analysis(path) or _relative(path) in _PUBLIC_METHODS_OF:
            continue
        offenders.append(_relative(path))
    assert offenders == []


def test_each_module_calls_only_its_own_public_methods() -> None:
    """N4: «Replicar» (a request path) only reads, the purge only deletes, no analysis
    module deletes, and nothing else calls the door at all."""
    offenders = []
    for path in _every_source():
        relative = _relative(path)
        if relative == _PUBLIC_DOOR:
            continue  # where they are defined
        calls = _public_calls(path)
        if not calls:
            continue
        if _is_analysis(path):
            allowed = _PUBLIC_METHODS - {"delete_public_prefix"}
        else:
            allowed = _PUBLIC_METHODS_OF.get(relative, set())
        if calls - allowed:
            offenders.append(f"{relative}: {sorted(calls - allowed)}")
    assert offenders == []
    for relative, allowed in _PUBLIC_METHODS_OF.items():
        assert _public_calls(_REPO / relative) == allowed, relative


def test_the_analysis_charges_no_business_and_calls_no_vendor() -> None:
    paths = [
        *(_SRC / "referentes").glob("reel_analysis*.py"),
        _SRC / "referentes" / "reel_retention.py",
    ]
    for path in paths:
        names = _imports(path)
        text = path.read_text(encoding="utf-8")
        assert not any("consumption" in n for n in names), path.name
        assert "consumption_scope" not in text and "record_consumption" not in text, path.name
        assert not any("scrapecreators" in n or n.endswith("vendors") for n in names), path.name
        assert "metered_get" not in text, path.name
