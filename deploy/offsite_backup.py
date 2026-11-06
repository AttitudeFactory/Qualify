"""Off-site copy of the nightly backups to R2, encrypted with age (m-24824122).

Runs INSIDE the `api` container of the Qualify stack (`docker exec`), driven by
`deploy/backup-offsite.sh`, which `deploy/backup-db.sh` calls after the local pg_dump. The
container already has what this needs and the host does not: Python, the R2 credentials of
`.env.prod`, the `uploads` volume mounted at `/data/uploaded_files`, and `age` (installed in
the app image). Nothing here can reach another compose project (Pedidos): it only sees the
container it runs in.

    offsite_backup.py check                     recipient + store reachable, before streaming
    offsite_backup.py put <day> <name>          stdin -> age -> backups/<day>/<name>.age
    offsite_backup.py finish <day> <name>...    every named object exists -> MANIFEST.json,
                                                then the retention prune
    offsite_backup.py alert <text>              one line to the team channel; never fails
    offsite_backup.py list                      the complete snapshots (those with a manifest)
    offsite_backup.py get <key>                 one object to stdout (still encrypted)

Layout: `backups/<YYYYMMDD>/{qualify.dump,globals.sql,uploads.tar}.age` + `MANIFEST.json`,
outside the tenants' `t/{tenant}/` space. A snapshot without `MANIFEST.json` is incomplete
and never restored from; the manifest is written last, after every object was checked.

Retention (prune after each complete snapshot): every snapshot of the last
`QUALIFY_BACKUP_KEEP_DAILY` days (14) plus the newest snapshot of each ISO week of the last
`QUALIFY_BACKUP_KEEP_WEEKLY` x 7 days (8 weeks). Incomplete snapshots older than two days go too.
The newest complete snapshot is never deleted, and only keys of exactly this layout are ever
touched.

Environment (read in the container, i.e. `.env.prod`):

    QUALIFY_BACKUP_AGE_RECIPIENT   age public key(s), comma-separated. REQUIRED: without it
                                   nothing is uploaded (fail closed). The private key never
                                   reaches the server.
    QUALIFY_R2_*                   the app's bucket and token (default target)
    QUALIFY_BACKUP_R2_BUCKET       optional: another bucket, with
    QUALIFY_BACKUP_R2_ACCESS_KEY_ID / QUALIFY_BACKUP_R2_SECRET_ACCESS_KEY  its own token
    QUALIFY_BACKUP_PRUNE           `off` = never delete (a write-only token; lifecycle rules
                                   in R2 do the retention instead). Default on.
    QUALIFY_BACKUP_LOCAL_DIR       a directory instead of R2 (restore drills and tests only)
    QUALIFY_BACKUP_AGE_BIN         the age executable (default `age`)
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Protocol

PREFIX = "backups/"
MANIFEST = "MANIFEST.json"
#: The only keys this tool ever deletes: `backups/<8 digits>/<plain file name>`.
_KEY = re.compile(r"^backups/(\d{8})/([A-Za-z0-9._-]+)$")
_NAME = re.compile(r"^[a-z][a-z0-9_-]*(\.[a-z0-9]+)+$")
_DAY = re.compile(r"^\d{8}$")
_INCOMPLETE_GRACE_DAYS = 2
_CHUNK = 1024 * 1024


class BackupError(Exception):
    """A refusal or failure that must make the nightly run exit non-zero."""


@dataclass(frozen=True)
class Listed:
    key: str
    size: int


class Store(Protocol):
    def put(self, key: str, fileobj: IO[bytes], content_type: str) -> None: ...
    def size(self, key: str) -> int: ...
    def sha256(self, key: str) -> str: ...
    def open(self, key: str) -> IO[bytes]: ...
    def list_prefix(self, prefix: str) -> Iterator[Any]: ...
    def delete_keys(self, keys: Sequence[str]) -> None: ...


class DirStore:
    """The same operations over a local directory (restore drills and tests)."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, key: str) -> Path:
        return self._root / key

    def put(self, key: str, fileobj: IO[bytes], content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as out:
            shutil.copyfileobj(fileobj, out, _CHUNK)

    def size(self, key: str) -> int:
        return self._path(key).stat().st_size

    def sha256(self, key: str) -> str:
        digest = hashlib.sha256()
        with self._path(key).open("rb") as src:
            while chunk := src.read(_CHUNK):
                digest.update(chunk)
        return digest.hexdigest()

    def open(self, key: str) -> IO[bytes]:
        return self._path(key).open("rb")

    def list_prefix(self, prefix: str) -> Iterator[Listed]:
        base = self._root / prefix
        if not base.exists():
            return
        for path in sorted(base.rglob("*")):
            if path.is_file():
                key = path.relative_to(self._root).as_posix()
                yield Listed(key=key, size=path.stat().st_size)

    def delete_keys(self, keys: Sequence[str]) -> None:
        for key in keys:
            self._path(key).unlink(missing_ok=True)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def build_store() -> Store:
    local = _env("QUALIFY_BACKUP_LOCAL_DIR")
    if local:
        return DirStore(Path(local))
    # The sanctioned S3 door (packages/shared/.../objects/s3.py), not a second boto3 client.
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    settings = R2Settings.from_env()
    bucket = _env("QUALIFY_BACKUP_R2_BUCKET")
    key_id = _env("QUALIFY_BACKUP_R2_ACCESS_KEY_ID")
    secret = _env("QUALIFY_BACKUP_R2_SECRET_ACCESS_KEY")
    if bool(key_id) != bool(secret):
        raise BackupError("set both QUALIFY_BACKUP_R2_ACCESS_KEY_ID and _SECRET_ACCESS_KEY")
    if bucket or key_id:
        settings = R2Settings(
            endpoint_url=settings.endpoint_url,
            access_key_id=key_id or settings.access_key_id,
            secret_access_key=secret or settings.secret_access_key,
            bucket=bucket or settings.bucket,
        )
    return R2ObjectStore(settings)


def recipients() -> list[str]:
    raw = _env("QUALIFY_BACKUP_AGE_RECIPIENT")
    keys = [part.strip() for part in raw.split(",") if part.strip()]
    if not keys:
        raise BackupError(
            "QUALIFY_BACKUP_AGE_RECIPIENT is not set: nothing is uploaded unencrypted "
            "(docs/respaldos-fuera-del-servidor.md, «Llave de cifrado»)"
        )
    if any(not key.startswith("age1") for key in keys):
        raise BackupError("QUALIFY_BACKUP_AGE_RECIPIENT must hold age public keys (age1...)")
    return keys


def _check_day(day: str) -> str:
    if not _DAY.match(day):
        raise BackupError(f"day must be YYYYMMDD, got {day!r}")
    try:
        dt.datetime.strptime(day, "%Y%m%d")
    except ValueError:
        raise BackupError(f"day must be a real date, got {day!r}") from None
    return day


def _check_name(name: str) -> str:
    if not _NAME.match(name):
        raise BackupError(f"invalid object name {name!r}")
    return name


def object_key(day: str, name: str) -> str:
    return f"{PREFIX}{_check_day(day)}/{_check_name(name)}.age"


def _age_bin() -> str:
    return _env("QUALIFY_BACKUP_AGE_BIN", "age")


def cmd_check(store: Store) -> dict[str, Any]:
    keys = recipients()
    if shutil.which(_age_bin()) is None:
        raise BackupError(f"age executable {_age_bin()!r} not found in this image")
    # One listing proves the endpoint, the token and the bucket before anything is streamed.
    next(iter(store.list_prefix(PREFIX)), None)
    return {"recipients": len(keys), "store": "ok"}


def cmd_put(store: Store, day: str, name: str, source: IO[bytes]) -> dict[str, Any]:
    """Encrypt `source` with age into a spool file, then one PUT. The spool gives the exact
    length a single PUT needs, and a failed encryption never reaches the bucket."""
    key = object_key(day, name)
    command = [_age_bin()]
    for recipient in recipients():
        command += ["-r", recipient]
    digest = hashlib.sha256()
    size = 0
    with tempfile.TemporaryFile(prefix="offsite-") as spool:
        proc = subprocess.Popen(command, stdin=source, stdout=subprocess.PIPE)
        assert proc.stdout is not None
        while chunk := proc.stdout.read(_CHUNK):
            spool.write(chunk)
            digest.update(chunk)
            size += len(chunk)
        if proc.wait() != 0:
            raise BackupError(f"age failed with exit code {proc.returncode} for {name}")
        if size == 0:
            raise BackupError(f"age produced no output for {name}")
        spool.seek(0)
        store.put(key, spool, "application/octet-stream")
    return {"key": key, "bytes": size, "sha256": digest.hexdigest()}


def _day_of(key: str) -> str | None:
    match = _KEY.match(key)
    return match.group(1) if match else None


def _is_manifest(key: str) -> bool:
    return key.endswith("/" + MANIFEST)


def snapshots(store: Store) -> dict[str, list[Any]]:
    """Objects of this layout, by day. Any other key under the prefix is ignored."""
    days: dict[str, list[Any]] = {}
    for item in store.list_prefix(PREFIX):
        day = _day_of(item.key)
        if day is not None:
            days.setdefault(day, []).append(item)
    return days


def complete_days(days: dict[str, list[Any]]) -> list[str]:
    return sorted(d for d, items in days.items() if any(_is_manifest(i.key) for i in items))


def _as_date(day: str) -> dt.date:
    return dt.datetime.strptime(day, "%Y%m%d").date()


def days_to_keep(
    complete: Iterable[str], incomplete: Iterable[str], today: dt.date, daily: int, weekly: int
) -> set[str]:
    good = sorted(complete)
    keep: set[str] = set()
    if good:
        keep.add(good[-1])  # never the last good copy, whatever the clock says
    for day in good:
        if (today - _as_date(day)).days < daily:
            keep.add(day)
    newest_per_week: dict[tuple[int, int], str] = {}
    for day in good:
        iso = _as_date(day).isocalendar()
        week = (iso[0], iso[1])
        newest_per_week[week] = max(day, newest_per_week.get(week, day))
    for day in newest_per_week.values():
        if (today - _as_date(day)).days < weekly * 7:
            keep.add(day)
    for day in incomplete:
        if (today - _as_date(day)).days < _INCOMPLETE_GRACE_DAYS:
            keep.add(day)
    return keep


def prune(store: Store, today: dt.date) -> list[str]:
    if _env("QUALIFY_BACKUP_PRUNE", "on").lower() in {"off", "0", "false", "no"}:
        return []
    try:
        daily = int(_env("QUALIFY_BACKUP_KEEP_DAILY", "14"))
        weekly = int(_env("QUALIFY_BACKUP_KEEP_WEEKLY", "8"))
    except ValueError:
        raise BackupError("QUALIFY_BACKUP_KEEP_DAILY/_KEEP_WEEKLY must be integers") from None
    if daily < 1 or weekly < 0:
        raise BackupError("QUALIFY_BACKUP_KEEP_DAILY must be >= 1 and _KEEP_WEEKLY >= 0")
    days = snapshots(store)
    complete = complete_days(days)
    incomplete = [d for d in days if d not in complete]
    keep = days_to_keep(complete, incomplete, today, daily, weekly)
    doomed = sorted(item.key for day, items in days.items() if day not in keep for item in items)
    for start in range(0, len(doomed), 1000):
        store.delete_keys(doomed[start : start + 1000])
    return sorted({day for day in days if day not in keep})


def cmd_finish(store: Store, day: str, names: Sequence[str], today: dt.date) -> dict[str, Any]:
    if not names:
        raise BackupError("finish needs the names of the objects of this snapshot")
    objects = []
    for name in names:
        key = object_key(day, name)
        try:
            size = store.size(key)
        except Exception as exc:  # noqa: BLE001 - the store's not-found and network errors alike
            raise BackupError(f"{key} is missing ({type(exc).__name__})") from None
        if size == 0:
            raise BackupError(f"{key} is empty")
        objects.append({"name": f"{name}.age", "bytes": size, "sha256": store.sha256(key)})
    manifest = {
        "day": day,
        "written_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "encryption": "age",
        "recipients": len(recipients()),
        "objects": objects,
    }
    with tempfile.TemporaryFile() as spool:
        spool.write(json.dumps(manifest, indent=2).encode())
        spool.seek(0)
        store.put(f"{PREFIX}{day}/{MANIFEST}", spool, "application/json")
    pruned = prune(store, today)
    total = sum(int(o["bytes"]) for o in objects)
    return {"day": day, "bytes": total, "objects": len(objects), "pruned_days": pruned}


def cmd_list(store: Store) -> list[dict[str, Any]]:
    days = snapshots(store)
    return [
        {"day": day, "bytes": sum(i.size for i in days[day]), "files": len(days[day])}
        for day in complete_days(days)
    ]


def cmd_get(store: Store, key: str, out: IO[bytes]) -> None:
    if not _KEY.match(key):
        raise BackupError(f"only keys of the form {PREFIX}<YYYYMMDD>/<file> can be read")
    src = store.open(key)
    try:
        shutil.copyfileobj(src, out, _CHUNK)
    finally:
        src.close()


def cmd_alert(text: str) -> bool:
    """Best effort: the run is already failing; a dead channel must not hide the reason."""
    url = _env("QUALIFY_SUPPORT_WEBHOOK_URL")
    if not url:
        print("offsite-backup: no team channel (QUALIFY_SUPPORT_WEBHOOK_URL)", file=sys.stderr)
        return False
    try:
        from qualify_api.support.webhook import TextWebhook  # noqa: PLC0415

        return TextWebhook(url, secret=_env("QUALIFY_SUPPORT_WEBHOOK_SECRET")).send(text)
    except Exception as exc:  # noqa: BLE001 - never raise from the alert path
        print(f"offsite-backup: alert not sent ({type(exc).__name__})", file=sys.stderr)
        return False


def main(argv: Sequence[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    command, args = argv[0], list(argv[1:])
    if command == "alert":
        cmd_alert(" ".join(args))
        return 0
    try:
        store = build_store()
        today = dt.datetime.now(dt.UTC).date()
        if command == "check" and not args:
            result: Any = cmd_check(store)
        elif command == "put" and len(args) == 2:
            result = cmd_put(store, args[0], args[1], sys.stdin.buffer)
        elif command == "finish" and len(args) >= 2:
            result = cmd_finish(store, args[0], args[1:], today)
        elif command == "list" and not args:
            result = cmd_list(store)
        elif command == "get" and len(args) == 1:
            cmd_get(store, args[0], sys.stdout.buffer)
            return 0
        else:
            print(__doc__, file=sys.stderr)
            return 2
    except BackupError as exc:
        print(f"offsite-backup: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - only the type: messages may carry endpoints
        print(f"offsite-backup: {command} failed ({type(exc).__name__})", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
