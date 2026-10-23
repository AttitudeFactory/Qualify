"""Static guard (m-24789645, criterion 1): no public comment reply leaves without a human
approval.

A public reply reaches Instagram through exactly one call, `CommentReplyClient.post_reply`.
This file proves, by AST over every non-test source of the API and the Reflex app, that:

1. `.post_reply(...)` is called from exactly two functions —
   - `replies/service.py :: ReplyService.send`, the assisted comment reply, whose very
     first statement is `require_approval(approval, ...)`; and
   - `followups/notice.py :: PublicNoticePoster._process`, Fase C's «Te enviamos la
     información por DM», which only takes forward `notice_status = 'pending'` rows, a
     state written exclusively by `FollowupService.approve_and_queue` with a
     `HumanApproval` (its own module docstring and tests).
   A third caller would be a path around the approval.
2. Every definition of the public send entry points (`ReplyService.send`,
   `replies.composition.send_draft`, `Qualify/replies_provider.send_draft`) has a
   keyword-only `approval` parameter with NO default.
3. Every call to `send_draft(...)` anywhere passes `approval=`.

The behavioural half (each entry point raises `ApprovalRequired` without one) lives in
`test_replies_service.py` and `test_replies_routes.py`. Pure AST: no imports, no database.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_API_SRC = _REPO_ROOT / "packages/api/src/qualify_api"
_UI_SRC = _REPO_ROOT / "Qualify"

_SERVICE = _API_SRC / "replies/service.py"
_ALLOWED_POST_REPLY_CALLERS = {
    (_SERVICE, "send"),
    (_API_SRC / "followups/notice.py", "_process"),
}
_SEND_ENTRY_POINTS = {
    (_SERVICE, "send"),
    (_API_SRC / "replies/composition.py", "send_draft"),
    (_UI_SRC / "replies_provider.py", "send_draft"),
}


def _sources() -> list[Path]:
    paths = sorted(_API_SRC.rglob("*.py")) + sorted(_UI_SRC.rglob("*.py"))
    return [
        p
        for p in paths
        if not p.name.startswith("test_")
        and p.name != "conftest.py"
        and "__pycache__" not in p.parts
        and ".web" not in p.parts
    ]


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _enclosing_functions(tree: ast.AST) -> dict[int, str]:
    """`id(call node) -> name of the innermost function that contains it`."""
    owner: dict[int, str] = {}

    def visit(node: ast.AST, current: str | None) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            current = node.name
        if isinstance(node, ast.Call) and current is not None:
            owner[id(node)] = current
        for child in ast.iter_child_nodes(node):
            visit(child, current)

    visit(tree, None)
    return owner


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_post_reply_is_called_only_from_the_approved_paths() -> None:
    offenders: list[str] = []
    seen: set[tuple[Path, str]] = set()
    for path in _sources():
        tree = _parse(path)
        owners = _enclosing_functions(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node) == "post_reply":
                caller = owners.get(id(node), "<module>")
                if (path, caller) in _ALLOWED_POST_REPLY_CALLERS:
                    seen.add((path, caller))
                else:
                    offenders.append(f"post_reply called from {caller}() at {path}:{node.lineno}")
    assert offenders == [], "\n".join(offenders)
    # The guard is only meaningful if it still sees the real callers (a rename would
    # otherwise make it pass vacuously).
    assert seen == _ALLOWED_POST_REPLY_CALLERS


def _function(path: Path, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    matches = [
        node
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name
    ]
    assert len(matches) == 1, f"expected one {name}() in {path}, found {len(matches)}"
    return matches[0]


def test_every_send_entry_point_requires_an_approval_without_default() -> None:
    for path, name in sorted(_SEND_ENTRY_POINTS):
        fn = _function(path, name)
        kwonly = {
            arg.arg: default
            for arg, default in zip(fn.args.kwonlyargs, fn.args.kw_defaults, strict=True)
        }
        assert "approval" in kwonly, f"{name}() in {path} has no keyword-only `approval`"
        assert kwonly["approval"] is None, f"{name}() in {path} defaults `approval`"


def test_reply_service_send_checks_the_approval_before_anything_else() -> None:
    fn = _function(_SERVICE, "send")
    body = list(fn.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]  # the docstring
    first = body[0]
    assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Call), (
        "ReplyService.send must start with require_approval(...)"
    )
    call = first.value
    assert _call_name(call) == "require_approval"
    assert isinstance(call.args[0], ast.Name) and call.args[0].id == "approval"
    keywords = {k.arg: k.value for k in call.keywords}
    assert isinstance(keywords.get("draft_id"), ast.Name)
    assert keywords["draft_id"].id == "draft_id"


def test_every_send_draft_call_passes_an_approval() -> None:
    offenders: list[str] = []
    calls = 0
    for path in _sources():
        for node in ast.walk(_parse(path)):
            if isinstance(node, ast.Call) and _call_name(node) in ("send_draft", "_send_draft"):
                calls += 1
                if "approval" not in {k.arg for k in node.keywords}:
                    offenders.append(f"send_draft(...) without approval= at {path}:{node.lineno}")
    assert offenders == [], "\n".join(offenders)
    assert calls >= 3  # the HTTP route, the Reflex state, the Reflex provider
