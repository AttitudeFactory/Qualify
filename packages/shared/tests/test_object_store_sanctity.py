"""Static guard (QUA-19 / ADR 28c): no code outside the sanctioned objects module may
construct an S3/boto3 client.

The sibling of `test_session_sanctity.py`, and for the same reason. Tenant isolation on the
object plane holds only if every read and write goes through `ObjectGate`, which enforces the
`t/{tenant_id}/` prefix. A stray `boto3.client("s3", ...)` in a publisher would reach any key
in the bucket, and no amount of care in the gate would matter. Pure AST — no imports, no
network, no boto3 required.

Note the guard is deliberately stricter than today's code needs: `boto3` is not yet a declared
dependency, so an offending call could not even run. The point is that the day it IS declared,
the rule is already in force rather than being remembered.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]

# The sole module allowed to build an S3 client — the analogue of the three DB session doors.
_SANCTIONED = {
    _REPO_ROOT / "packages/shared/src/qualify_shared/objects/s3.py",
}

# `client`/`resource` are boto3's two constructors. They are common verbs, so the check below
# only fires when the call also names an S3-ish service, keeping false positives off.
_BOTO_CONSTRUCTORS = {"client", "resource"}
_S3_SERVICE_NAMES = {"s3"}

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


def _first_string_arg(node: ast.Call) -> str | None:
    for arg in node.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
    for keyword in node.keywords:
        if keyword.arg in {"service_name"} and isinstance(keyword.value, ast.Constant):
            value = keyword.value.value
            if isinstance(value, str):
                return value
    return None


def _offending_calls(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _called_name(node) not in _BOTO_CONSTRUCTORS:
            continue
        service = _first_string_arg(node)
        if service is not None and service.lower() in _S3_SERVICE_NAMES:
            hits.append(f"boto3 S3 client at {path}:{node.lineno}")
    return hits


def _boto_imports(path: Path) -> list[str]:
    """Importing boto3 at all, outside the sanctioned module, is the earlier smell — an
    import is how the second client eventually gets built."""
    tree = ast.parse(path.read_text(), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in {"boto3", "botocore"}:
                    hits.append(f"import {alias.name} at {path}:{node.lineno}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in {"boto3", "botocore"}:
                hits.append(f"from {node.module} import ... at {path}:{node.lineno}")
    return hits


def _unsanctioned_files() -> list[Path]:
    return [path for root in _SRC_ROOTS for path in root.rglob("*.py") if path not in _SANCTIONED]


def test_no_s3_client_outside_sanctioned_module() -> None:
    offenders = [hit for path in _unsanctioned_files() for hit in _offending_calls(path)]
    assert not offenders, (
        "S3 client constructed outside qualify_shared.objects.s3 — route through "
        "ObjectGate instead, so the tenant prefix is enforced:\n" + "\n".join(offenders)
    )


def test_no_boto_import_outside_sanctioned_module() -> None:
    offenders = [hit for path in _unsanctioned_files() for hit in _boto_imports(path)]
    assert not offenders, (
        "boto3/botocore imported outside qualify_shared.objects.s3:\n" + "\n".join(offenders)
    )


def test_the_guard_would_actually_catch_an_offender(tmp_path: Path) -> None:
    """A static guard that silently matches nothing is worse than none — it reads as
    protection. This drives the detector over a known-bad file so a future refactor of the
    AST walk cannot leave the assertions vacuously true."""
    offender = tmp_path / "bad.py"
    offender.write_text('import boto3\nc = boto3.client("s3", endpoint_url="x")\n')
    assert _offending_calls(offender)
    assert _boto_imports(offender)


def test_the_guard_ignores_unrelated_client_calls(tmp_path: Path) -> None:
    """`client(...)` is a common verb; the guard must not fire on, say, an HTTP client."""
    innocent = tmp_path / "ok.py"
    innocent.write_text('c = client("redis")\nd = some.client()\n')
    assert not _offending_calls(innocent)
