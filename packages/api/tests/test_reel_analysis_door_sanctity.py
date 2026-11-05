"""Static guards for the shared reel analysis (ADR 44, m-24921056 VE-04a). Pure AST.

- The `qualify_reels_worker` door is imported only by the analysis queue and its worker:
  no request path can write a result every business reads.
- The public R2 door is imported only by `referentes.reel_analysis*` (R12/R13 join when
  they land, as reviewed additions).
- The analysis never charges a business (decision #10: the cost lives on the global row
  and in Langfuse) and never calls ScrapeCreators (it reads the networks' CDNs only).
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src" / "qualify_api"
_REPO_SRC = Path(__file__).resolve().parents[3] / "packages"

_WORKER_DOOR_USERS = {"referentes/reel_analysis_queue.py", "referentes/reel_analysis_worker.py"}


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


def _every_source() -> list[Path]:
    roots = [_REPO_SRC / p / "src" for p in ("api", "shared", "scraper", "creative", "models")]
    return [path for root in roots if root.exists() for path in root.rglob("*.py")]


def test_the_reels_worker_door_is_imported_only_by_the_queue_and_the_worker() -> None:
    offenders = []
    for path in _SRC.rglob("*.py"):
        relative = path.relative_to(_SRC).as_posix()
        names = _imports(path)
        uses = "reels_worker_session" in names or any(n.endswith("db.reels_worker") for n in names)
        if uses and relative not in _WORKER_DOOR_USERS:
            offenders.append(relative)
    assert offenders == []


def test_the_public_r2_door_is_used_only_by_the_reel_analysis() -> None:
    offenders = []
    for path in _every_source():
        names = _imports(path)
        if not any(n.endswith("objects.public") for n in names):
            continue
        if path.parent.name == "referentes" and path.name.startswith("reel_analysis"):
            continue
        offenders.append(path.as_posix())
    assert offenders == []


def test_the_analysis_charges_no_business_and_calls_no_vendor() -> None:
    for path in (_SRC / "referentes").glob("reel_analysis*.py"):
        names = _imports(path)
        text = path.read_text(encoding="utf-8")
        assert not any("consumption" in n for n in names), path.name
        assert "consumption_scope" not in text and "record_consumption" not in text, path.name
        assert not any("scrapecreators" in n or n.endswith("vendors") for n in names), path.name
        assert "metered_get" not in text, path.name
