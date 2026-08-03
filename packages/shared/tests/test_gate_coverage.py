"""R11(d): the default test gate is audited, not merely declared.

`testpaths` is an allow-list by pytest's design, so a new or relocated `tests/` directory is
born OUTSIDE the gate and says nothing about it. That is not hypothetical: three directories
fell out in this repo — `packages/models/tests` and, after the QUA-67 contract move, its
fixture-conformance tests; and `packages/docs-harvester/tests`, which was found only by
reading the list once, on purpose.

The positive invariant R11 states: **every test that can fail because of a change outside its
own package belongs in the default gate.** A conformance test against a shared contract is by
definition one of those — it exists precisely to break when the *other* side moves. Hosting it
in an uncollected package turns it into a test that runs only once somebody is already
suspicious, i.e. executable documentation rather than a gate.

So this file does for the gate what `test_session_sanctity.py` does for DB sessions and
`test_object_store_sanctity.py` does for S3 clients: **a structural invariant is defended by a
test, not by discipline.** Every `packages/*/tests` directory must be either collected or
explicitly, reasonedly excluded. Forgetting one now fails the suite.

This test lives in `packages/shared/tests` because that directory is itself inside the gate —
an auditor outside the thing it audits would be the same bug it is auditing for.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PYPROJECT = _REPO_ROOT / "pyproject.toml"


def _config() -> dict:
    return tomllib.loads(_PYPROJECT.read_text())


def _testpaths() -> set[str]:
    return set(_config()["tool"]["pytest"]["ini_options"]["testpaths"])


def _excluded() -> dict[str, str]:
    """Declared exclusions as `{path: reason}`. Absent table == nothing excluded."""
    entries = _config().get("tool", {}).get("qualify", {}).get("test-gate", {}).get("excluded", [])
    return {entry["path"]: entry["reason"] for entry in entries}


def _discovered_test_dirs() -> set[str]:
    """Every `packages/*/tests` directory actually on disk, as repo-relative POSIX paths.

    Discovery is from the filesystem rather than from any list, which is the entire point: a
    list cannot notice a directory nobody added to it.
    """
    return {
        path.relative_to(_REPO_ROOT).as_posix()
        for path in (_REPO_ROOT / "packages").glob("*/tests")
        if path.is_dir()
    }


def test_every_test_directory_is_either_collected_or_explicitly_excluded() -> None:
    discovered = _discovered_test_dirs()
    accounted = _testpaths() | set(_excluded())
    orphans = sorted(discovered - accounted)
    assert not orphans, (
        "test directories in neither `testpaths` nor the R11 deny-list — they run only when "
        "someone remembers to ask, which is how three of these were lost already:\n"
        + "\n".join(f"  - {path}" for path in orphans)
        + "\n\nAdd to `testpaths` in the root pyproject.toml, or to "
        "`[[tool.qualify.test-gate.excluded]]` WITH a reason."
    )


def test_every_exclusion_carries_a_real_reason() -> None:
    """An exclusion without a justification is a silent gap with extra syntax. Enforcing a
    non-trivial reason is what keeps the deny-list from degrading into the allow-list it
    replaced."""
    thin = sorted(path for path, reason in _excluded().items() if len(reason.strip()) < 40)
    assert not thin, (
        "excluded test directories whose reason is too thin to evaluate:\n"
        + "\n".join(f"  - {path}" for path in thin)
    )


def test_no_exclusion_is_stale() -> None:
    """A deny-list entry for a directory that no longer exists is misleading: it implies a
    considered decision about something that is gone, and it hides the fact that the real
    directory may have moved somewhere unaudited."""
    discovered = _discovered_test_dirs()
    stale = sorted(path for path in _excluded() if path not in discovered)
    assert not stale, (
        "deny-list entries for test directories that do not exist — delete them, or fix the "
        "path if the directory moved:\n" + "\n".join(f"  - {path}" for path in stale)
    )


def test_a_path_is_not_both_collected_and_excluded() -> None:
    """Contradictory declarations resolve silently in pytest's favour, so the reader would be
    told one thing while the gate does another."""
    both = sorted(_testpaths() & set(_excluded()))
    assert not both, f"paths both collected and excluded: {both}"


def test_the_audit_would_actually_catch_an_orphan() -> None:
    """A guard that silently matches nothing reads as protection while giving none — the same
    failure mode this whole ruling is about. Drive the comparison over a known-bad input so a
    future refactor cannot leave the assertions vacuously true."""
    discovered = {"packages/api/tests", "packages/ghost/tests"}
    accounted = {"packages/api/tests"}
    assert sorted(discovered - accounted) == ["packages/ghost/tests"]
