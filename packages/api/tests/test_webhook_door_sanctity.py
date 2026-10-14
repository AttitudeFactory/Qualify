"""Static guard (QUA-147): which database door each half of the webhook intake may use.

- The public request path — `http/mentions_routes.py` and `webhooks/receiver.py` — may
  use only `webhook_session` (INSERT-only). Never `admin_session`, `tenant_session`,
  `credential_session` or the worker door.
- The `webhooks` package never imports `admin_session` at all: the processor's one
  cross-tenant read goes through the narrow `qualify_webhook_worker` door.
- `mentions/resolve.py` uses the worker door, not `admin_session` (it did before
  QUA-147).
- `webhook_session` itself is imported nowhere but the receiver.

Pure AST — no import side effects, no database.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src" / "qualify_api"

_DOORS = {
    "admin_session",
    "tenant_session",
    "credential_session",
    "webhook_session",
    "webhook_worker_session",
}


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.name.rsplit(".", 1)[-1] for alias in node.names)
    return names


def test_the_request_path_uses_only_the_insert_only_door() -> None:
    for relative in ("http/mentions_routes.py", "webhooks/receiver.py"):
        doors = _imported_names(_SRC / relative) & _DOORS
        assert doors <= {"webhook_session"}, f"{relative} imports {sorted(doors)}"


def test_the_webhooks_package_never_imports_admin_session() -> None:
    offenders = [
        str(path.relative_to(_SRC))
        for path in (_SRC / "webhooks").rglob("*.py")
        if "admin_session" in _imported_names(path)
    ]
    assert offenders == []


def test_the_resolver_uses_the_worker_door() -> None:
    doors = _imported_names(_SRC / "mentions" / "resolve.py") & _DOORS
    assert doors == {"webhook_worker_session"}


def test_the_insert_only_door_is_used_only_by_the_receiver() -> None:
    users = sorted(
        str(path.relative_to(_SRC)).replace("\\", "/")
        for path in _SRC.rglob("*.py")
        if "webhook_session" in _imported_names(path)
    )
    assert users == ["webhooks/receiver.py"]
