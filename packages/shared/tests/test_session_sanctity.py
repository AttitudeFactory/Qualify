"""Static guard (C-01): no code outside the sanctioned DB module may construct a
Session or an Engine. The isolation guarantee holds only if every tenant-scoped query
goes through `tenant_session` (which fixes `app.tenant_id`); a stray `Session(engine)`
or `create_engine(...)` in a repository would bypass that. This is a pure AST test — no
database, no import side effects — so it runs everywhere, including CI without infra.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]

# The only files allowed to build Sessions/Engines: the sanctioned doors —
# `qualify_app` (request path), `qualify_admin` (provisioning, BYPASSRLS),
# `qualify_credential` (decrypt-only, RLS-subject, the sole holder of the ciphertext grant),
# and the two Meta-webhook roles of `webhook.py` (QUA-147: INSERT-only receiver, and the
# intake processor).
_SANCTIONED = {
    _REPO_ROOT / "packages/shared/src/qualify_shared/db/session.py",
    _REPO_ROOT / "packages/shared/src/qualify_shared/db/admin.py",
    _REPO_ROOT / "packages/shared/src/qualify_shared/db/credential.py",
    _REPO_ROOT / "packages/shared/src/qualify_shared/db/webhook.py",
}

_FORBIDDEN = {
    "Session",
    "sessionmaker",
    "create_engine",
    "create_async_engine",
    "async_sessionmaker",
}

_SRC_ROOTS = (
    _REPO_ROOT / "packages/api/src",
    _REPO_ROOT / "packages/shared/src",
    _REPO_ROOT / "packages/scraper/src",
)


def _called_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _offending_calls(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _called_name(node)
            if name in _FORBIDDEN:
                hits.append(f"{name} at {path}:{node.lineno}")
    return hits


def test_no_session_or_engine_outside_sanctioned_module() -> None:
    offenders: list[str] = []
    for root in _SRC_ROOTS:
        for path in root.rglob("*.py"):
            if path in _SANCTIONED:
                continue
            offenders.extend(_offending_calls(path))
    assert not offenders, (
        "Session/Engine constructed outside qualify_shared.db — route through "
        "tenant_session/admin_session instead:\n" + "\n".join(offenders)
    )
