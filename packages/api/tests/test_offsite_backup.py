"""m-24824122: the off-site backup (deploy/offsite_backup.py + deploy/backup-offsite.sh).

Offline: a directory stands in for R2 (`QUALIFY_BACKUP_LOCAL_DIR`), a fake `age` marks what
it "encrypted", and a fake `docker` on PATH plays the api container. Nothing reaches a server.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "deploy/offsite_backup.py"
SCRIPT = ROOT / "deploy/backup-offsite.sh"
RECIPIENT = "age1qualifytestrecipientnotarealkey"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("offsite_backup", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["offsite_backup"] = module
    spec.loader.exec_module(module)
    return module


ob = _load()


def _fake_age(tmp_path: Path, *, exit_code: int = 0) -> Path:
    path = tmp_path / "fake-age"
    path.write_text(f"#!/bin/sh\nprintf 'FAKEAGE\\n'\ncat\nexit {exit_code}\n")
    path.chmod(0o755)
    return path


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    store = tmp_path / "store"
    monkeypatch.setenv("QUALIFY_BACKUP_LOCAL_DIR", str(store))
    monkeypatch.setenv("QUALIFY_BACKUP_AGE_RECIPIENT", RECIPIENT)
    monkeypatch.setenv("QUALIFY_BACKUP_AGE_BIN", str(_fake_age(tmp_path)))
    for name in ("QUALIFY_BACKUP_PRUNE", "QUALIFY_BACKUP_KEEP_DAILY", "QUALIFY_BACKUP_KEEP_WEEKLY"):
        monkeypatch.delenv(name, raising=False)
    return store


def _source(tmp_path: Path, data: bytes) -> io.BufferedReader:
    """A real file: the tool hands its descriptor to age, exactly like the script's stdin."""
    path = tmp_path / f"source-{len(list(tmp_path.iterdir()))}"
    path.write_bytes(data)
    return path.open("rb")


def _snapshot(store: Path, day: str, *, complete: bool = True) -> None:
    folder = store / "backups" / day
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "qualify.dump.age").write_bytes(b"x")
    if complete:
        (folder / "MANIFEST.json").write_text("{}")


def _days(store: Path) -> list[str]:
    base = store / "backups"
    return sorted(p.name for p in base.iterdir() if p.is_dir() and any(p.iterdir()))


# -- encryption and upload --------------------------------------------------------------


def test_put_stores_the_age_output_under_the_day(env: Path, tmp_path: Path) -> None:
    source = _source(tmp_path, b"pgdump")
    result = ob.cmd_put(ob.build_store(), "20261105", "qualify.dump", source)
    stored = env / "backups/20261105/qualify.dump.age"
    assert stored.read_bytes() == b"FAKEAGE\npgdump"
    assert result["key"] == "backups/20261105/qualify.dump.age"
    assert result["bytes"] == len(b"FAKEAGE\npgdump")


def test_put_refuses_without_a_recipient(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUALIFY_BACKUP_AGE_RECIPIENT")
    with pytest.raises(ob.BackupError, match="not set"):
        ob.cmd_put(ob.build_store(), "20261105", "qualify.dump", io.BytesIO(b"pgdump"))
    assert not (env / "backups").exists()


def test_put_refuses_a_recipient_that_is_not_an_age_public_key(
    env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QUALIFY_BACKUP_AGE_RECIPIENT", "AGE-SECRET-KEY-1ABC")
    with pytest.raises(ob.BackupError, match="public keys"):
        ob.recipients()


def test_a_failed_encryption_never_reaches_the_store(
    env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = tmp_path / "broken"
    broken.mkdir()
    monkeypatch.setenv("QUALIFY_BACKUP_AGE_BIN", str(_fake_age(broken, exit_code=3)))
    with pytest.raises(ob.BackupError, match="age failed"):
        ob.cmd_put(ob.build_store(), "20261105", "qualify.dump", _source(tmp_path, b"pgdump"))
    assert not (env / "backups/20261105/qualify.dump.age").exists()


@pytest.mark.parametrize(
    "day,name",
    [
        ("2026-11-05", "a.dump"),
        ("20261399", "a.dump"),
        ("20261105", "../t/x.dump"),
        ("20261105", "MANIFEST"),
    ],
)
def test_keys_cannot_escape_the_layout(day: str, name: str) -> None:
    with pytest.raises(ob.BackupError):
        ob.object_key(day, name)


# -- manifest -----------------------------------------------------------------------------


def test_finish_writes_the_manifest_only_when_every_object_is_there(
    env: Path, tmp_path: Path
) -> None:
    store = ob.build_store()
    ob.cmd_put(store, "20261105", "qualify.dump", _source(tmp_path, b"pgdump"))
    with pytest.raises(ob.BackupError, match="missing"):
        ob.cmd_finish(store, "20261105", ["qualify.dump", "uploads.tar"], dt.date(2026, 11, 5))
    assert not (env / "backups/20261105/MANIFEST.json").exists()

    ob.cmd_put(store, "20261105", "uploads.tar", _source(tmp_path, b"tar"))
    result = ob.cmd_finish(store, "20261105", ["qualify.dump", "uploads.tar"], dt.date(2026, 11, 5))
    manifest = json.loads((env / "backups/20261105/MANIFEST.json").read_text())
    assert [o["name"] for o in manifest["objects"]] == ["qualify.dump.age", "uploads.tar.age"]
    assert manifest["encryption"] == "age"
    assert result["objects"] == 2
    assert ob.cmd_list(store)[0]["day"] == "20261105"


# -- retention ----------------------------------------------------------------------------


def _day(date: dt.date) -> str:
    return date.strftime("%Y%m%d")


def test_retention_keeps_14_daily_and_the_newest_of_8_weeks() -> None:
    today = dt.date(2026, 11, 5)
    every_day = [_day(today - dt.timedelta(days=n)) for n in range(120)]
    keep = ob.days_to_keep(every_day, [], today, daily=14, weekly=8)
    daily = {_day(today - dt.timedelta(days=n)) for n in range(14)}
    assert daily <= keep
    older = sorted(keep - daily)
    # Beyond the daily window: the newest snapshot of each ISO week of the last 8 weeks
    # (a Sunday, when every day has one), never older.
    assert older
    assert all((today - ob._as_date(d)).days < 8 * 7 for d in older)
    assert all(ob._as_date(d).isoweekday() == 7 for d in older)
    assert len(keep) <= 14 + 8


def test_retention_never_drops_the_last_good_copy() -> None:
    keep = ob.days_to_keep(["20250101"], [], dt.date(2026, 11, 5), daily=14, weekly=0)
    assert keep == {"20250101"}


def test_prune_removes_old_and_stale_incomplete_days_only(env: Path) -> None:
    today = dt.date(2026, 11, 5)
    for n in (0, 1, 13, 14, 40, 200):
        _snapshot(env, _day(today - dt.timedelta(days=n)))
    _snapshot(env, _day(today - dt.timedelta(days=3)), complete=False)  # stale, incomplete
    (env / "backups/notes.txt").write_text("not ours")  # outside the layout
    (env / "backups/20261104/extra dir").mkdir()

    pruned = ob.prune(ob.build_store(), today)

    assert _day(today - dt.timedelta(days=3)) in pruned
    assert _day(today - dt.timedelta(days=200)) in pruned
    remaining = _days(env)
    for n in (0, 1, 13):
        assert _day(today - dt.timedelta(days=n)) in remaining
    assert (env / "backups/notes.txt").exists()


def test_prune_off_deletes_nothing(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUALIFY_BACKUP_PRUNE", "off")
    _snapshot(env, "20200101")
    _snapshot(env, "20261105")
    assert ob.prune(ob.build_store(), dt.date(2026, 11, 5)) == []
    assert _days(env) == ["20200101", "20261105"]


def test_get_reads_only_backup_keys(env: Path) -> None:
    with pytest.raises(ob.BackupError):
        ob.cmd_get(ob.build_store(), "t/00000000-0000-0000-0000-000000000000/x", io.BytesIO())


# -- the host script, with a fake docker ------------------------------------------------


def _fake_docker(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        f"""#!/usr/bin/env bash
set -u
echo "$*" >>"$FAKE_DOCKER_LOG"
case "$1" in
  ps) printf '%s' "${{FAKE_API_ID-api123}}"; [[ -n "${{FAKE_API_ID-api123}}" ]] && echo ;;
  exec)
    shift; [[ "$1" == -i ]] && shift; shift
    if [[ "$1" == tar ]]; then
      [[ -n "${{FAKE_TAR_FAIL:-}}" ]] && exit 2
      shift; args=()
      for a in "$@"; do [[ "$a" == /data/uploaded_files ]] && a=$FAKE_UPLOADS; args+=("$a"); done
      exec tar "${{args[@]}}"
    elif [[ "$1" == python ]]; then
      shift; shift; exec {sys.executable} {TOOL} "$@"
    fi
    exit 99 ;;
  *) exit 98 ;;
esac
"""
    )
    docker.chmod(0o755)
    return bin_dir


def _run(tmp_path: Path, env_store: Path, **extra: str) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    assert bash is not None
    backups = tmp_path / "backups"
    backups.mkdir(exist_ok=True)
    dump = backups / "qualify-20261105T031500Z.dump"
    globals_ = backups / "globals-20261105T031500Z.sql"
    dump.write_bytes(b"PGDMP-fake")
    globals_.write_text("CREATE ROLE x;")
    uploads = tmp_path / "uploads"
    (uploads / "uploads/tenant/catalog").mkdir(parents=True, exist_ok=True)
    (uploads / "uploads/tenant/catalog/a.jpg").write_bytes(b"jpeg")
    environ = {
        **os.environ,
        "PATH": f"{_fake_docker(tmp_path)}:{os.environ['PATH']}",
        "FAKE_DOCKER_LOG": str(tmp_path / "docker.log"),
        "FAKE_UPLOADS": str(uploads),
        "QUALIFY_BACKUP_DIR": str(backups),
        "QUALIFY_BACKUP_LOCAL_DIR": str(env_store),
        "QUALIFY_BACKUP_AGE_RECIPIENT": RECIPIENT,
        "QUALIFY_BACKUP_AGE_BIN": str(_fake_age(tmp_path)),
        **extra,
    }
    environ.pop("QUALIFY_SUPPORT_WEBHOOK_URL", None)
    return subprocess.run(
        [bash, str(SCRIPT), str(dump), str(globals_)],
        env=environ,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_script_uploads_three_objects_and_a_manifest(tmp_path: Path, env: Path) -> None:
    result = _run(tmp_path, env)
    assert result.returncode == 0, result.stderr
    day = dt.datetime.now(dt.UTC).strftime("%Y%m%d")
    names = sorted(p.name for p in (env / "backups" / day).iterdir())
    assert names == ["MANIFEST.json", "globals.sql.age", "qualify.dump.age", "uploads.tar.age"]
    assert (env / f"backups/{day}/qualify.dump.age").read_bytes() == b"FAKEAGE\nPGDMP-fake"
    assert (tmp_path / "backups/offsite.ok").exists()
    log = (tmp_path / "docker.log").read_text()
    # Only this project's api container, found by label; never a volume or another project.
    assert "label=com.docker.compose.project=qualify-prod" in log
    assert "volume" not in log and "run " not in log


@pytest.mark.parametrize(
    "extra,stage",
    [
        ({"QUALIFY_BACKUP_AGE_RECIPIENT": ""}, "check"),
        ({"FAKE_TAR_FAIL": "1"}, "put uploads.tar"),
        ({"FAKE_API_ID": ""}, "locate api"),
    ],
)
def test_script_fails_loudly_and_writes_no_manifest(
    tmp_path: Path, env: Path, extra: dict[str, str], stage: str
) -> None:
    result = _run(tmp_path, env, **extra)
    assert result.returncode != 0
    assert f"FAILED at '{stage}'" in result.stderr
    assert "local dump" in result.stderr
    assert not (tmp_path / "backups/offsite.ok").exists()
    assert not list(env.rglob("MANIFEST.json"))
