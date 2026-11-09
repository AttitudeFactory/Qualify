"""Static guard (ADR 42 §4, slice R2, m-24854847): every request to ScrapeCreators goes
through the metered gate, `qualify_api.vendors.scrapecreators.metered_get`.

Same shape as `test_session_sanctity.py`: a pure AST walk, no import side effects, no
network. Outside the gate module, no code may

- hold a string naming a vendor host (`*scrapecreators.com`), whole or joined from pieces
  with `+` or an f-string — that is how an `httpx.get("https://api.scrapecreators.com/…")`
  would be written;
- reach the gate's `BASE_URL` or its raw request `_vendor_request`, by import, by
  attribute or by `getattr` — that is how an `httpx.get(f"{sc.BASE_URL}/…")` would be
  written.

**This is a tripwire, not a proof.** Code determined to hide a URL (built from bytes, read
from the environment, `importlib`) gets past an AST walk; what it guards against is the
honest mistake of a new module calling the vendor directly. Review still applies.

**No exceptions** besides the gate itself: the referentes search and the Brand Kit
(`Qualify/creator_discovery.py`), the avatar proxy (`Qualify/avatar_proxy.py`), the
trending reads and any future `referentes/reel_analysis*` module (ADR 44: the analysis
downloads from the CDN, it never calls the vendor) are all scanned. Docstrings and
comments may name the host; code may not.

The tenant-less DB door the gate uses (`global_session`) is pinned here too: only
`qualify_api.vendors.balance` may import it — and `referentes.reel_reference`, whose
«Replicar» looks an idea's video up in the two GLOBAL reel tables (`public_reels`,
`public_reel_analyses`: no tenant, no RLS) without a tenant at hand (R8, 2026-11-04), and
`referentes.reel_covers`, whose 30-day purge reads and clears the idea covers' R2 copies
on `public_reels` with no business at hand (R12, m-24854859).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GATE = _REPO_ROOT / "packages/api/src/qualify_api/vendors/scrapecreators.py"
_GATE_MODULE = "qualify_api.vendors.scrapecreators"
#: The only file allowed to talk to the vendor. Nothing else, ever.
_ALLOWED = frozenset({_GATE})

#: Any host of the vendor, not only `api.`: a URL split in pieces is caught once joined.
_HOST = re.compile(r"scrapecreators\.com", re.IGNORECASE)
_FORBIDDEN_NAMES = frozenset({"BASE_URL", "_vendor_request"})

_BALANCE = _REPO_ROOT / "packages/api/src/qualify_api/vendors/balance.py"
_REEL_REFERENCE = _REPO_ROOT / "packages/api/src/qualify_api/referentes/reel_reference.py"
_REEL_COVERS = _REPO_ROOT / "packages/api/src/qualify_api/referentes/reel_covers.py"
_SESSION = _REPO_ROOT / "packages/shared/src/qualify_shared/db/session.py"


def _scanned_files() -> list[Path]:
    files = [p for p in (_REPO_ROOT / "packages").glob("*/src/**/*.py")]
    files += list((_REPO_ROOT / "packages/api/evals").rglob("*.py"))
    files += [
        p
        for p in (_REPO_ROOT / "Qualify").rglob("*.py")
        if not p.name.startswith("test_") and p.name != "conftest.py"
    ]
    return sorted(set(files))


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _gate_aliases(tree: ast.AST) -> set[str]:
    """Local names bound to the gate module itself."""
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "qualify_api.vendors":
            aliases |= {a.asname or a.name for a in node.names if a.name == "scrapecreators"}
        elif isinstance(node, ast.Import):
            aliases |= {a.asname for a in node.names if a.name == _GATE_MODULE and a.asname}
    return aliases


def _string_pieces(node: ast.AST) -> str | None:
    """The literal text of a string built by `+` or an f-string (formatted parts
    dropped), or None when `node` is neither."""
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _string_pieces(node.left), _string_pieces(node.right)
        if left is None and right is None:
            return None
        return (left or "") + (right or "")
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_gate(node: ast.AST, aliases: set[str]) -> bool:
    return (isinstance(node, ast.Name) and node.id in aliases) or ast.unparse(node) == _GATE_MODULE


def offenses(source: str, label: str) -> list[str]:
    """Every way `source` reaches the vendor outside the gate, as `label:line what`."""
    tree = ast.parse(source, filename=label)
    docstrings = _docstring_nodes(tree)
    aliases = _gate_aliases(tree)
    hits: set[str] = set()
    for node in ast.walk(tree):
        if id(node) in docstrings:
            continue
        text = _string_pieces(node)
        if text is not None and _HOST.search(text):
            hits.add(f"{label}:{node.lineno} names the vendor's host")
        elif isinstance(node, ast.ImportFrom) and node.module == _GATE_MODULE:
            for alias in node.names:
                if alias.name in _FORBIDDEN_NAMES or alias.name == "*":
                    hits.add(f"{label}:{node.lineno} imports {alias.name} from the gate")
        elif (
            isinstance(node, ast.Attribute)
            and node.attr in _FORBIDDEN_NAMES
            and _is_gate(node.value, aliases)
        ):
            hits.add(f"{label}:{node.lineno} reaches the gate's {node.attr}")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and _is_gate(node.args[0], aliases)
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in _FORBIDDEN_NAMES
        ):
            hits.add(f"{label}:{node.lineno} reaches the gate's {node.args[1].value} by getattr")
    return sorted(hits)


def test_only_the_gate_calls_scrapecreators() -> None:
    found: list[str] = []
    for path in _scanned_files():
        if path in _ALLOWED:
            continue
        found += offenses(path.read_text(encoding="utf-8"), str(path.relative_to(_REPO_ROOT)))
    assert not found, (
        "ScrapeCreators reached outside the metered gate — call "
        "`qualify_api.vendors.scrapecreators.metered_get` (or a fetch_* built on it):\n"
        + "\n".join(found)
    )


def test_the_gate_is_the_only_exception() -> None:
    assert _ALLOWED == {_GATE}
    scanned = set(_scanned_files())
    for must in (
        "Qualify/creator_discovery.py",
        "Qualify/avatar_proxy.py",
        "Qualify/trending_state.py",
        "packages/api/src/qualify_api/vendors/scrapecreators_trending.py",
        "packages/api/src/qualify_api/creative/brand_prefill.py",
        "packages/api/src/qualify_api/referentes/reels.py",
    ):
        assert _REPO_ROOT / must in scanned, must
    # ADR 44: every `referentes/reel_analysis*` module is scanned like the rest — the scan
    # is the whole source tree, and the allow-list above holds the gate alone.
    for path in (_REPO_ROOT / "packages/api/src/qualify_api/referentes").glob("reel_analysis*"):
        assert path in scanned, path


def test_the_guard_catches_a_direct_call_to_the_vendor() -> None:
    planted = (
        '"""A docstring may say api.scrapecreators.com."""\n'
        "import httpx\n"
        "from qualify_api.vendors import scrapecreators as sc\n"
        "from qualify_api.vendors.scrapecreators import BASE_URL\n"
        "import qualify_api.vendors.scrapecreators\n"
        'httpx.get("https://api.scrapecreators.com/v1/tiktok/profile")\n'
        'httpx.get(f"https://API.ScrapeCreators.com/v1/{1}")\n'
        'httpx.get(f"{sc.BASE_URL}/v1/x")\n'
        "sc._vendor_request(None, '/v1/x', {})\n"
        "qualify_api.vendors.scrapecreators.BASE_URL\n"
        "getattr(sc, 'BASE_URL')\n"
        "httpx.get('https://api.' + 'scrapecreators' + '.com/v1/x')\n"
        "httpx.get(f'https://{h}.scrapecreators' '.com/')\n"
    )
    found = offenses(planted, "packages/api/src/qualify_api/referentes/reel_analysis.py")
    lines = sorted({int(hit.split(" ", 1)[0].rsplit(":", 1)[1]) for hit in found})
    assert lines == [4, 6, 7, 8, 9, 10, 11, 12, 13], found  # never line 1, the docstring


def test_the_guard_lets_the_gate_through() -> None:
    clean = (
        "from qualify_api.vendors import scrapecreators as sc\n"
        "sc.metered_get(client, '/v1/tiktok/profile', {}, feature=sc.FEATURE_PROFILE)\n"
        "sc.is_vendor_host('api.example.com')\n"
    )
    assert offenses(clean, "x.py") == []


def test_only_the_balance_store_opens_the_tenantless_door() -> None:
    importers: list[str] = []
    for path in _scanned_files():
        if path in {_BALANCE, _SESSION, _REEL_REFERENCE, _REEL_COVERS}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.ImportFrom | ast.Import)
                else []
            )
            if "global_session" in names or (
                isinstance(node, ast.Attribute) and node.attr == "global_session"
            ):
                importers.append(f"{path.relative_to(_REPO_ROOT)}:{node.lineno}")
    assert not importers, "global_session is the gate's balance door only:\n" + "\n".join(importers)
