"""Static guard (QUA-226, ADR 21c): no module outside `conversations/outbox.py` may write
`conversation_outbox`.

The sibling of `test_object_store_sanctity.py` / `test_session_sanctity.py`, for the same
reason. "No private reply leaves without a human" holds because the ONE way into the queue
is `enqueue(..., approval=HumanApproval)` and the column it fills is NOT NULL. A second
writer — a raw `INSERT INTO conversation_outbox` in a handler, a `session.add(
ConversationOutboxItem(...))` in a service — would be a path around that argument. Pure
AST over the api sources: no imports, no database.

Two things are forbidden outside the sanctioned module:
- any string constant mentioning `conversation_outbox` together with INSERT/UPDATE/DELETE
  (raw SQL);
- any call that constructs `ConversationOutboxItem` or passes it to an insert
  (`ConversationOutboxItem(...)`, `pg_insert(ConversationOutboxItem)`, `insert(...)`).

`models.py` may NAME the class (it defines it); nothing else may build one.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_API_SRC = _REPO_ROOT / "packages/api/src"

_SANCTIONED_WRITER = _API_SRC / "qualify_api/conversations/outbox.py"
_DEFINING_MODULE = _API_SRC / "qualify_api/conversations/models.py"

_RAW_WRITE = re.compile(r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+conversation_outbox\b", re.I)
_MODEL = "ConversationOutboxItem"


def _raw_sql_writes(path: Path, tree: ast.AST) -> list[str]:
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _RAW_WRITE.search(node.value):
                hits.append(f"raw write to conversation_outbox at {path}:{node.lineno}")
    return hits


def _model_constructions(path: Path, tree: ast.AST) -> list[str]:
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name == _MODEL:
            hits.append(f"{_MODEL}(...) built at {path}:{node.lineno}")
            continue
        for arg in node.args:
            if isinstance(arg, ast.Name) and arg.id == _MODEL:
                hits.append(f"{_MODEL} passed to {name}() at {path}:{node.lineno}")
    return hits


def test_only_the_outbox_module_writes_conversation_outbox() -> None:
    offenders: list[str] = []
    for path in sorted(_API_SRC.rglob("*.py")):
        if path == _SANCTIONED_WRITER:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders.extend(_raw_sql_writes(path, tree))
        if path != _DEFINING_MODULE:
            offenders.extend(_model_constructions(path, tree))
    assert offenders == [], "\n".join(offenders)


def test_the_sanctioned_writer_requires_an_approval() -> None:
    """The guard above is only worth something if the one writer really demands the
    approval: every `enqueue` defined in `outbox.py` has a parameter named `approval`
    with NO default."""
    tree = ast.parse(_SANCTIONED_WRITER.read_text(encoding="utf-8"))
    enqueues = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == "enqueue"
    ]
    assert enqueues, "outbox.py defines no `enqueue`"
    for fn in enqueues:
        kwonly = dict(zip(fn.args.kwonlyargs, fn.args.kw_defaults, strict=True))
        by_name = {arg.arg: default for arg, default in kwonly.items()}
        assert "approval" in by_name, f"enqueue at line {fn.lineno} has no `approval`"
        assert by_name["approval"] is None, f"enqueue at line {fn.lineno} defaults `approval`"
