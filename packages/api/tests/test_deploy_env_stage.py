"""Exercise env-stage through fake SSH against local synthetic files, never a server."""

from __future__ import annotations

import json
import os
import shlex
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
KEY = "QUALIFY_DB_CREATIVE_WORKER_PASSWORD"
VALUE = "synthetic-only-$literal;never-execute=$(no-op)"


@pytest.fixture
def stage(tmp_path):
    binaries = tmp_path / "bin"
    binaries.mkdir()
    remote = tmp_path / "remote"
    remote.mkdir()
    destination = remote / ".env.prod"
    destination.write_text(f"UNCHANGED=keep\n{KEY}=synthetic-before\n")
    destination.chmod(0o644)  # Stage must enforce 0600 rather than preserve this mode.
    source = tmp_path / "local.env"
    source.write_text(
        f'{KEY}="{VALUE}"\nQUALIFY_CREATIVE_DISPATCHER=queue\nUNSELECTED=local-only\n'
    )
    calls = tmp_path / "ssh-calls.jsonl"
    ssh = binaries / "ssh"
    ssh.write_text(
        f"#!{sys.executable}\n"
        "import json,os,sys\n"
        "with open(os.environ['FAKE_SSH_CALLS'],'a') as out:\n"
        " out.write(json.dumps(sys.argv[1:])+'\\n')\n"
        "assert sys.argv[1:4]==['-o','BatchMode=yes','synthetic-target']\n"
        "assert 'docker compose' not in sys.argv[-1], 'stage must never restart'\n"
        "os.execv('/bin/bash',['bash','-c',sys.argv[-1]])\n"
    )
    ssh.chmod(0o755)
    # macOS lacks GNU chown --reference. Preserve the real script and adapt only that
    # platform tool, asserting that the fixture's owner already equals the target's.
    chown = binaries / "chown"
    chown.write_text(
        f"#!{sys.executable}\n"
        "import json,os,sys\n"
        "with open(os.environ['FAKE_SSH_CALLS']+'.ownership','a') as out:\n"
        " out.write(json.dumps(sys.argv[1:])+'\\n')\n"
        "reference=os.stat(sys.argv[1].split('=',1)[1]); target=os.stat(sys.argv[2])\n"
        "assert (reference.st_uid,reference.st_gid)==(target.st_uid,target.st_gid)\n"
    )
    chown.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{binaries}:{os.environ['PATH']}",
        "QUALIFY_ENV_SOURCE": str(source),
        "QUALIFY_REMOTE_ROOT": str(remote),
        "FAKE_SSH_CALLS": str(calls),
    }

    def run(*keys, action="env-stage"):
        return subprocess.run(
            ["bash", str(ROOT / "deploy/deploy.sh"), action, "synthetic-target", *keys],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    return run, source, destination, calls


def test_stage_password_and_config_are_stdin_only_atomic_backup_and_no_restart(stage):
    run, _, destination, calls = stage
    before = destination.read_text()
    original_owner = destination.stat().st_uid, destination.stat().st_gid
    result = run(KEY, "QUALIFY_CREATIVE_DISPATCHER")
    assert result.returncode == 0, result.stderr
    assert destination.read_text() == (
        f"UNCHANGED=keep\n{KEY}={VALUE}\nQUALIFY_CREATIVE_DISPATCHER=queue\n"
    )
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    backups = list(destination.parent.glob(".env.prod.bak-*"))
    assert len(backups) == 1 and backups[0].read_text() == before
    assert stat.S_IMODE(backups[0].stat().st_mode) == 0o600
    assert (backups[0].stat().st_uid, backups[0].stat().st_gid) == original_owner
    ownership_calls = [
        json.loads(line) for line in Path(str(calls) + ".ownership").read_text().splitlines()
    ]
    assert [f"--reference={destination}", str(backups[0])] in ownership_calls
    assert "no services restarted" in result.stdout
    assert VALUE not in result.stdout + result.stderr + calls.read_text()
    assert len(calls.read_text().splitlines()) == 1
    # Applying again immediately still retains both versions, even within one second.
    assert run(KEY).returncode == 0
    assert len(list(destination.parent.glob(".env.prod.bak-*"))) == 2


def test_dry_run_compares_without_file_changes_backups_or_restart(stage):
    run, _, destination, calls = stage
    before = destination.read_bytes(), destination.stat().st_mode
    result = run("--dry-run", KEY)
    assert result.returncode == 0, result.stderr
    assert "Dry run: .env.prod untouched" in result.stdout
    assert (destination.read_bytes(), destination.stat().st_mode) == before
    assert list(destination.parent.glob(".env.prod.bak-*")) == []
    assert VALUE not in result.stdout + result.stderr + calls.read_text()


@pytest.mark.parametrize("action", ["env-push", "env-stage"])
@pytest.mark.parametrize(
    "key",
    ["QUALIFY_DEV_FERNET_KEY", "QUALIFY_PUBLIC_URL", "COMPOSE_PROJECT_NAME", "QUALIFY_IMAGE_APP"],
)
def test_both_modes_keep_dangerous_key_refusals_before_ssh(stage, action, key):
    run, _, _, calls = stage
    result = run(key, action=action)
    assert result.returncode != 0 and f"refusing {key}" in result.stderr
    assert not calls.exists()


def test_env_push_still_refuses_role_password_and_points_to_staging(stage):
    run, _, _, calls = stage
    result = run(KEY, action="env-push")
    assert result.returncode != 0 and "just env-stage" in result.stderr
    assert not calls.exists()


@pytest.mark.parametrize("key", ["MISSING", "BAD;touch", "lowercase", "--unknown"])
def test_invalid_or_missing_keys_never_reach_ssh(stage, key):
    run, _, _, calls = stage
    assert run(key).returncode != 0
    assert not calls.exists()


def test_just_stage_recipe_forwards_named_keys_only():
    result = subprocess.run(
        ["just", "--dry-run", "env-stage", "synthetic-target", "--dry-run", KEY],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert shlex.split(result.stderr.strip()) == [
        "deploy/deploy.sh",
        "env-stage",
        "synthetic-target",
        "--dry-run",
        KEY,
    ]
