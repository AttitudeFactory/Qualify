"""Execute the real deploy workflow shell with offline SSH, without contacting a server."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
SHA = "a" * 40
SECRET = "synthetic-private-key-never-log"


def _bash() -> str:
    if os.name == "nt":
        # Windows' system bash may launch an unconfigured WSL instance. These tests
        # need the Git Bash installation used by the repository's shell recipes.
        candidate = (
            Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git" / "bin" / "bash.exe"
        )
        if candidate.is_file():
            return str(candidate)
        pytest.fail("Git Bash is required to execute the deploy transport harness on Windows")
    executable = shutil.which("bash")
    if executable is None:
        pytest.fail("Bash is required to execute the deploy transport harness")
    return executable


@pytest.fixture
def transport(tmp_path: Path) -> Callable[..., tuple[subprocess.CompletedProcess[str], list[str]]]:
    workflow = yaml.safe_load((ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["deploy"]["steps"]
    step = next(item for item in steps if item.get("name", "").startswith("Deploy ${{"))
    arguments = tmp_path / "arguments"
    calls = tmp_path / "calls"
    http_calls = tmp_path / "http-calls"
    stdin = tmp_path / "stdin"
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "deploy_key").write_text(SECRET, encoding="utf-8")

    def run(
        status: int, action: str = "deploy"
    ) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        # A shell function substitutes only SSH. The workflow's actual shell, option
        # parsing, redirection, error handling and exit code run unchanged under -e.
        script = r"""
export HOME="$FAKE_HOME"
ssh() {
  printf 'call\n' >>"$FAKE_CALLS"
  printf '%s\0' "$@" >"$FAKE_ARGUMENTS"
  cat >"$FAKE_STDIN"
  if [ "$FAKE_STATUS" -eq 1 ]; then
    echo 'server-deploy: migration failed' >&2
  elif [ "$FAKE_STATUS" -eq 255 ]; then
    echo 'client_loop: send disconnect: Broken pipe' >&2
  fi
  return "$FAKE_STATUS"
}
curl() {
  printf 'unexpected HTTP fallback\n' >>"$FAKE_HTTP_CALLS"
  printf '200'
}
"""
        result = subprocess.run(
            [_bash(), "--noprofile", "--norc", "-e", "-o", "pipefail"],
            input=script + step["run"],
            env={
                **os.environ,
                "HOME": home.as_posix(),
                "FAKE_HOME": home.as_posix(),
                "FAKE_ARGUMENTS": arguments.as_posix(),
                "FAKE_CALLS": calls.as_posix(),
                "FAKE_HTTP_CALLS": http_calls.as_posix(),
                "FAKE_STDIN": stdin.as_posix(),
                "FAKE_STATUS": str(status),
                "TARGET": "synthetic-target",
                "SHA": SHA,
                "ACTION": action,
                "KEY": SECRET,
            },
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        assert calls.read_text() == "call\n", "a deployment must never be replayed automatically"
        assert not http_calls.exists(), "HTTP health cannot reconcile an unknown remote release"
        assert stdin.read_bytes() == b"", "the restricted command receives no stdin payload"
        argv = arguments.read_bytes().decode().strip("\0").split("\0")
        assert SECRET not in " ".join(argv) + result.stdout + result.stderr
        return result, argv

    return run


@pytest.mark.parametrize("action", ["deploy", "rollback"])
def test_success_preserves_restricted_protocol_and_transport_security(
    transport: Callable[..., Any], action: str
) -> None:
    result, argv = transport(0, action)
    assert result.returncode == 0, result.stderr
    assert "::error::" not in result.stdout
    assert argv[-3:] == ["synthetic-target", action, SHA]
    assert argv[0] == "-i"
    assert argv[1].endswith("/.ssh/deploy_key")
    assert argv[2:-3:2] == ["-o"] * 8
    assert set(argv[3:-3:2]) == {
        "IdentitiesOnly=yes",
        "BatchMode=yes",
        "StrictHostKeyChecking=yes",
        "ConnectTimeout=15",
        "ConnectionAttempts=1",
        "ServerAliveInterval=15",
        "ServerAliveCountMax=6",
        "TCPKeepAlive=yes",
    }


def test_remote_failure_remains_a_failure_without_transport_success_fallback(
    transport: Callable[..., Any],
) -> None:
    result, _ = transport(1)
    assert result.returncode == 1
    assert "server-deploy: migration failed" in result.stderr
    assert "outcome is unknown" not in result.stdout


def test_transport_failure_preserves_255_and_requires_reconciliation_before_retry(
    transport: Callable[..., Any],
) -> None:
    result, _ = transport(255)
    assert result.returncode == 255
    assert "Broken pipe" in result.stderr
    assert "::error::" in result.stdout
    assert "outcome is unknown" in result.stdout
    assert "may still be running" in result.stdout
    assert "Before retrying" in result.stdout
    assert "trusted deploy-status" in result.stdout
    assert "running release, container images and health" in result.stdout
