"""The ONE-TIME copy of the `uploads` volume to R2 (CM-9, m-24957283).

Run by hand, never on deploy (`docs/mudanza-subidas-r2.md`):

    python -m qualify_api.creative.local_media_move --all-tenants              # dry run
    python -m qualify_api.creative.local_media_move --all-tenants --apply      # copy
    python -m qualify_api.creative.local_media_move --all-tenants --delete-local

**Dry run (the default)** writes nothing anywhere: per business it says how many files
and bytes it would copy, how many are already copied, and the **inventory** — every
column and JSON field of the business's tables that holds an old local key
(`uploads/{tenant}/…`, `generated/{tenant}/…`), with how many rows, how many distinct
keys, and how many of those keys have no file on the volume.

**`--apply`** copies, file by file, through one row of `local_media_moves` each:

1. the local file is hashed (SHA-256, streamed) and its row written `pending`;
2. it is PUT to its R2 key (`owner_uploads.moved_key_for`) ONCE, streamed from disk —
   unless that key already holds an object: same size and digest = an earlier run's
   copy (resumed); anything else = `conflict` (never overwritten — the bucket lock on
   `t/` would refuse it anyway — never mapped, listed);
3. the R2 object is read back (size + SHA-256) and, in ONE transaction, the row becomes
   `verified` — from then on it maps — and the key columns of `REWRITE_COLUMNS` that hold
   exactly that old key are rewritten to the R2 key. JSON fields are NOT rewritten: the
   map resolves their old keys (`R2ReadingMediaStore`, the WhatsApp reader, the upload
   route).

Cutting it and running it again redoes nothing done and skips nothing left: each step
reads the row first.

**`--delete-local`** (a separate run, after the founder's go-ahead) deletes a local file
only when its row is `verified`, the file on disk still has the row's size and digest,
and the R2 object still has them too. The row becomes `local_deleted`. Nothing else is
ever deleted, here or in R2.

A file whose business cannot be determined (not under `uploads/<tenant uuid>/` or
`generated/<tenant uuid>/`, or a tenant that does not exist) is neither copied nor
deleted: it is listed. Waiting rooms (`gallery-staging`, `catalog_staging`) and symbolic
links are skipped. Every database access is a `tenant_session` (RLS); the only
cross-tenant read is the list of tenant ids (`admin_session`).
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sys
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from qualify_api.creative.owner_uploads import (
    LOCAL_ROOTS,
    PIPELINE_VERSION,
    content_type_for,
    is_staging,
    local_key_tenant,
    moved_key_for,
    put_once,
)

logger = logging.getLogger(__name__)

#: Whole-value key columns rewritten to the R2 key when a file is verified — each one
#: holds one media key per row (or, for an array, one per element). Every other place a
#: local key lives (JSON documents, prose) keeps it and resolves through the map.
REWRITE_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "product_media": (("object_key", "text"),),
    "content_briefs": (("source_media_key", "text"),),
    "content_drafts": (("preview_key", "text"),),
    "brand_kits": (
        ("logo_asset_key", "text"),
        ("template_asset_key", "text"),
        ("reference_image_keys", "array"),
    ),
    "brand_kit_assets": (("object_key", "text"),),
    "brand_voice_clones": (("sample_object_key", "text"), ("preview_object_key", "text")),
    "image_assets": (("object_key", "text"), ("mask_object_key", "text")),
    "canva_design_links": (("source_object_key", "text"), ("exported_object_key", "text")),
}
#: Never swept nor rewritten: the map itself, and the Galería's waiting-room paths.
_NOT_SWEPT = {("local_media_moves", "local_key"), ("gallery_jobs", "staged_path")}
_CHUNK = 1024 * 1024
_SWEPT_TYPES = ("text", "character varying", "jsonb", "json", "ARRAY")


# -- the volume ----------------------------------------------------------------------


@dataclass(frozen=True)
class LocalFile:
    local_key: str
    path: Path
    size: int


@dataclass
class Walk:
    files: dict[UUID, list[LocalFile]] = field(default_factory=dict)
    #: keys whose business cannot be determined (never copied, never deleted)
    unowned: list[str] = field(default_factory=list)
    skipped_links: list[str] = field(default_factory=list)
    staging: int = 0


def walk_volume(
    root: Path, *, tenant: UUID | None = None, roots: Iterable[str] = LOCAL_ROOTS
) -> Walk:
    """Every regular file under `<root>/<uploads|generated>/`, grouped by the tenant its
    key names (only `tenant`'s when given). Symbolic links are never followed."""
    walk = Walk()
    base = root.resolve()
    for top in roots:
        top_dir = base / top
        if not top_dir.is_dir():
            continue
        start = top_dir / str(tenant) if tenant is not None else top_dir
        if not start.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(start, followlinks=False):
            current = Path(dirpath)
            for name in list(dirnames):
                if (current / name).is_symlink():
                    walk.skipped_links.append((current / name).relative_to(base).as_posix())
                    dirnames.remove(name)
            for name in filenames:
                path = current / name
                key = path.relative_to(base).as_posix()
                if path.is_symlink():
                    walk.skipped_links.append(key)
                    continue
                if not path.is_file():
                    continue
                if is_staging(key):
                    walk.staging += 1
                    continue
                owner = local_key_tenant(key)
                if owner is None:
                    walk.unowned.append(key)
                    continue
                walk.files.setdefault(owner, []).append(LocalFile(key, path, path.stat().st_size))
    for files in walk.files.values():
        files.sort(key=lambda f: f.local_key)
    return walk


def file_digest(path: Path) -> tuple[int, str]:
    """`(bytes, sha256)` of a file, read 1 MiB at a time."""
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


# -- the database --------------------------------------------------------------------


def known_tenants() -> set[UUID]:
    """Every tenant id — the one cross-tenant read (`admin_session`)."""
    from qualify_shared.db import admin_session  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415

    with admin_session() as session:
        return {UUID(str(row)) for row in session.scalars(text("SELECT id FROM tenants"))}


@dataclass(frozen=True)
class MoveRow:
    local_key: str
    r2_key: str
    bytes: int
    sha256: str
    status: str


def _rows(tenant_id: UUID) -> dict[str, MoveRow]:
    from qualify_shared.db import tenant_session  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415

    with tenant_session(tenant_id) as session:
        found = session.execute(
            text(
                "SELECT local_key, r2_key, bytes, sha256, status FROM local_media_moves"
                " WHERE tenant_id = :t"
            ),
            {"t": str(tenant_id)},
        )
        return {r.local_key: MoveRow(*r) for r in found}


def _upsert_pending(tenant_id: UUID, f: LocalFile, r2_key: str, size: int, sha: str) -> None:
    from qualify_shared.db import tenant_session  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415

    with tenant_session(tenant_id) as session:
        session.execute(
            text(
                """
                INSERT INTO local_media_moves
                    (tenant_id, local_key, r2_key, bytes, sha256, content_type, status,
                     pipeline_version)
                VALUES (:t, :local, :r2, :bytes, :sha, :ct, 'pending', :version)
                ON CONFLICT (tenant_id, local_key) DO UPDATE
                    SET bytes = EXCLUDED.bytes, sha256 = EXCLUDED.sha256,
                        status = 'pending', error = NULL, updated_at = now()
                    WHERE local_media_moves.status IN ('pending', 'copied')
                """
            ),
            {
                "t": str(tenant_id),
                "local": f.local_key,
                "r2": r2_key,
                "bytes": size,
                "sha": sha,
                "ct": content_type_for(f.local_key),
                "version": PIPELINE_VERSION,
            },
        )


def _set_status(tenant_id: UUID, local_key: str, status: str, *, error: str | None = None) -> None:
    from qualify_shared.db import tenant_session  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415

    stamp = {"copied": ", copied_at = now()"}.get(status, "")
    with tenant_session(tenant_id) as session:
        session.execute(
            text(
                f"UPDATE local_media_moves SET status = :s, error = :e, updated_at = now()"
                f"{stamp} WHERE tenant_id = :t AND local_key = :k"
            ),
            {"s": status, "e": error, "t": str(tenant_id), "k": local_key},
        )


def _existing_rewrites(session: Any) -> dict[str, tuple[tuple[str, str], ...]]:
    """`REWRITE_COLUMNS` restricted to the columns this database has."""
    from sqlalchemy import text  # noqa: PLC0415

    present = {
        (r.table_name, r.column_name)
        for r in session.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns"
                " WHERE table_schema = 'public'"
            )
        )
    }
    return {
        table: tuple(c for c in columns if (table, c[0]) in present)
        for table, columns in REWRITE_COLUMNS.items()
        if any((table, c[0]) in present for c in columns)
    }


def mark_verified(tenant_id: UUID, local_key: str, r2_key: str) -> dict[str, int]:
    """ONE transaction: the row maps from now on, and the whole-value key columns that
    hold exactly `local_key` point at `r2_key`. Returns the rewritten rows per column."""
    from qualify_shared.db import tenant_session  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415

    rewrites: dict[str, int] = {}
    params = {"t": str(tenant_id), "old": local_key, "new": r2_key}
    with tenant_session(tenant_id) as session:
        for table, columns in _existing_rewrites(session).items():
            for column, kind in columns:
                if kind == "array":
                    sql = (
                        f"UPDATE {table} SET {column} = array_replace({column}, :old, :new)"
                        f" WHERE tenant_id = :t AND :old = ANY({column})"
                    )
                else:
                    sql = (
                        f"UPDATE {table} SET {column} = :new"
                        f" WHERE tenant_id = :t AND {column} = :old"
                    )
                count = session.execute(text(sql), params).rowcount or 0
                if count:
                    rewrites[f"{table}.{column}"] = count
        session.execute(
            text(
                """
                UPDATE local_media_moves
                   SET status = 'verified', verified_at = now(), updated_at = now(),
                       rewrites = CAST(:rewrites AS jsonb), error = NULL
                 WHERE tenant_id = :t AND local_key = :old AND status = 'copied'
                """
            ),
            {**params, "rewrites": _json(rewrites)},
        )
    return rewrites


def _json(value: dict[str, int]) -> str:
    import json  # noqa: PLC0415

    return json.dumps(value, sort_keys=True)


def _mark_deleted(tenant_id: UUID, local_key: str) -> None:
    from qualify_shared.db import tenant_session  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415

    with tenant_session(tenant_id) as session:
        session.execute(
            text(
                "UPDATE local_media_moves SET status = 'local_deleted',"
                " local_deleted_at = now(), updated_at = now()"
                " WHERE tenant_id = :t AND local_key = :k AND status = 'verified'"
            ),
            {"t": str(tenant_id), "k": local_key},
        )


# -- the inventory -------------------------------------------------------------------


@dataclass
class ColumnUse:
    table: str
    column: str
    data_type: str
    rows: int = 0
    keys: set[str] = field(default_factory=set)
    embedded: int = 0  # rows where a local key sits inside prose, not as a whole value
    rewritten: bool = False
    #: distinct keys with no file on the volume and no verified copy in R2
    missing: int = 0


def _leaves(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _leaves(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _leaves(item)


def inventory(tenant_id: UUID) -> list[ColumnUse]:
    """Every text, JSON and array column of a table with `tenant_id` that holds one of
    this tenant's old local keys — counted under `tenant_session`. A column this role
    cannot read is skipped (its own savepoint)."""
    from qualify_shared.db import tenant_session  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415

    prefixes = tuple(f"{root}/{tenant_id}/" for root in LOCAL_ROOTS)
    found: list[ColumnUse] = []
    with tenant_session(tenant_id) as session:
        columns = session.execute(
            text(
                """
                SELECT c.table_name, c.column_name, c.data_type
                  FROM information_schema.columns c
                  JOIN information_schema.tables t
                    ON t.table_schema = c.table_schema AND t.table_name = c.table_name
                 WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'
                   AND c.data_type = ANY(:types)
                   AND EXISTS (SELECT 1 FROM information_schema.columns k
                                WHERE k.table_schema = 'public'
                                  AND k.table_name = c.table_name
                                  AND k.column_name = 'tenant_id')
                 ORDER BY c.table_name, c.column_name
                """
            ),
            {"types": list(_SWEPT_TYPES)},
        ).all()
        rewritten = {(t, c) for t, cols in REWRITE_COLUMNS.items() for c, _ in cols}
        for table, column, data_type in columns:
            if (table, column) in _NOT_SWEPT:
                continue
            like = " OR ".join(f'"{column}"::text LIKE :p{i}' for i in range(len(prefixes)))
            params = {f"p{i}": f"%{p}%" for i, p in enumerate(prefixes)}
            try:
                with session.begin_nested():
                    values = session.scalars(
                        text(f'SELECT "{column}" FROM "{table}" WHERE {like}'), params
                    ).all()
            except Exception as exc:  # no grant for this role: listed as unread
                logger.info("inventory: %s.%s not readable: %s", table, column, type(exc).__name__)
                continue
            if not values:
                continue
            use = ColumnUse(table, column, data_type, rewritten=(table, column) in rewritten)
            for value in values:
                use.rows += 1
                whole = [leaf for leaf in _leaves(value) if leaf.startswith(prefixes)]
                if whole:
                    use.keys.update(whole)
                else:
                    use.embedded += 1
            found.append(use)
    return found


# -- the copy ------------------------------------------------------------------------


@dataclass
class TenantReport:
    tenant_id: UUID
    files: int = 0
    bytes: int = 0
    by_root: dict[str, list[int]] = field(default_factory=dict)  # root -> [files, bytes]
    to_copy: int = 0
    to_copy_bytes: int = 0
    already: int = 0
    copied: int = 0
    deleted: int = 0
    deletable: int = 0
    conflicts: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    inventory: list[ColumnUse] = field(default_factory=list)


def _held(gate: Any, tenant_id: UUID, key: str) -> int | None:
    from qualify_shared.objects.gate import ObjectNotFound  # noqa: PLC0415

    try:
        return int(gate.object_size(tenant_id, key))
    except ObjectNotFound:
        return None


def _r2_matches(gate: Any, tenant_id: UUID, key: str, size: int, sha: str) -> bool:
    return _held(gate, tenant_id, key) == size and gate.sha256(tenant_id, key) == sha


def copy_file(
    gate: Any, tenant_id: UUID, f: LocalFile, row: MoveRow | None, report: TenantReport
) -> None:
    """Steps 1–3 for one file (see the module docstring); never raises for one file."""
    r2_key = moved_key_for(f.local_key)
    if r2_key is None:  # cannot happen for a walked file; refused all the same
        report.failures.append(f.local_key)
        return
    try:
        size, sha = file_digest(f.path)
        if row is None or row.status in ("pending", "copied"):
            _upsert_pending(tenant_id, f, r2_key, size, sha)
        held = _held(gate, tenant_id, r2_key)
        if held is None:
            with f.path.open("rb") as handle:
                put_once(tenant_id, r2_key, handle, content_type_for(f.local_key), gate=gate)
        elif held != size or gate.sha256(tenant_id, r2_key) != sha:
            _set_status(tenant_id, f.local_key, "conflict", error="R2 key holds another file")
            report.conflicts.append(f.local_key)
            return
        _set_status(tenant_id, f.local_key, "copied")
        if not _r2_matches(gate, tenant_id, r2_key, size, sha):
            _set_status(tenant_id, f.local_key, "conflict", error="R2 copy does not verify")
            report.conflicts.append(f.local_key)
            return
        mark_verified(tenant_id, f.local_key, r2_key)
        report.copied += 1
    except Exception as exc:
        logger.warning("copy failed for one file: %s: %s", type(exc).__name__, exc)
        report.failures.append(f.local_key)


def delete_local(
    gate: Any, tenant_id: UUID, row: MoveRow, root: Path, report: TenantReport
) -> None:
    """Delete one verified local file after checking both copies again: the R2 object
    and the file on disk must both still have the row's size and SHA-256."""
    try:
        if not _r2_matches(gate, tenant_id, row.r2_key, row.bytes, row.sha256):
            report.failures.append(row.local_key)
            return
        path = root / row.local_key
        if path.is_symlink():
            report.failures.append(row.local_key)  # never followed, never deleted
            return
        if path.is_file():
            if file_digest(path) != (row.bytes, row.sha256):
                report.failures.append(row.local_key)  # the file changed since its copy
                return
            path.unlink()
        _mark_deleted(tenant_id, row.local_key)
        report.deleted += 1
    except Exception as exc:
        logger.warning("delete failed for one file: %s: %s", type(exc).__name__, exc)
        report.failures.append(row.local_key)


def run(
    *,
    root: Path,
    tenants: Iterable[UUID] | None,
    mode: str,
    gate_factory: Callable[[], Any],
    roots: Iterable[str] = LOCAL_ROOTS,
    with_inventory: bool = True,
    known: Callable[[], set[UUID]] = known_tenants,
) -> tuple[list[TenantReport], Walk]:
    """One pass: `mode` is `dry-run`, `apply` or `delete-local`. `tenants=None` = every
    tenant found on the volume."""
    roots = tuple(roots)
    wanted = list(tenants) if tenants is not None else None
    if wanted is not None and len(wanted) == 1:
        walk = walk_volume(root, tenant=wanted[0], roots=roots)
    else:
        walk = walk_volume(root, roots=roots)
    existing = known()
    for tenant in list(walk.files):
        if tenant not in existing:  # a folder of no business: listed, never touched
            walk.unowned.extend(f.local_key for f in walk.files.pop(tenant))
    targets = wanted if wanted is not None else sorted(walk.files, key=str)
    gate = gate_factory() if mode != "dry-run" else None
    reports: list[TenantReport] = []
    for tenant in targets:
        files = walk.files.get(tenant, [])
        report = TenantReport(tenant)
        rows = _rows(tenant) if tenant in existing else {}
        for f in files:
            report.files += 1
            report.bytes += f.size
            per_root = report.by_root.setdefault(f.local_key.split("/", 1)[0], [0, 0])
            per_root[0] += 1
            per_root[1] += f.size
            row = rows.get(f.local_key)
            if row is not None and row.status in ("verified", "local_deleted"):
                report.already += 1
                if row.status == "verified":
                    report.deletable += 1
                continue
            if row is not None and row.status == "conflict":
                report.conflicts.append(f.local_key)
                continue
            report.to_copy += 1
            report.to_copy_bytes += f.size
            if mode == "apply":
                copy_file(gate, tenant, f, row, report)
        if mode == "delete-local":
            for row in rows.values():
                if row.status == "verified" and row.local_key.split("/", 1)[0] in roots:
                    delete_local(gate, tenant, row, root, report)
        if with_inventory and tenant in existing:
            report.inventory = inventory(tenant)
            known_keys = {f.local_key for f in files} | {
                k for k, row in _rows(tenant).items() if row.status in ("verified", "local_deleted")
            }
            for use in report.inventory:
                use.missing = sum(1 for key in use.keys if key not in known_keys)
        reports.append(report)
    return reports, walk


# -- the command ---------------------------------------------------------------------


def _mb(n: int) -> str:
    return f"{n / (1024 * 1024):.1f} MB"


def render(reports: list[TenantReport], walk: Walk, mode: str) -> str:
    lines = [
        f"local media move ({PIPELINE_VERSION}) — {mode} — {datetime.now(UTC):%Y-%m-%d %H:%M} UTC"
    ]
    for r in reports:
        lines.append(f"\ntenant {r.tenant_id}: {r.files} files, {_mb(r.bytes)} on the volume")
        for root_name, (n, b) in sorted(r.by_root.items()):
            lines.append(f"  {root_name}/: {n} files, {_mb(b)}")
        lines.append(f"  already in R2 (mapped): {r.already}; deletable locally: {r.deletable}")
        verb = "would copy" if mode == "dry-run" else "to copy"
        lines.append(f"  {verb}: {r.to_copy} files, {_mb(r.to_copy_bytes)}")
        if mode == "apply":
            lines.append(f"  copied and verified now: {r.copied}")
        if mode == "delete-local":
            lines.append(f"  local files deleted now: {r.deleted}")
        for key in r.conflicts:
            lines.append(f"  CONFLICT (not copied, not mapped): {key}")
        for key in r.failures:
            lines.append(f"  FAILED (retry later): {key}")
        if r.inventory:
            lines.append("  inventory (column [type]: rows, distinct keys, keys with no file):")
            for use in r.inventory:
                note = "rewritten" if use.rewritten else "resolved by the map"
                extra = f", {use.embedded} inside text" if use.embedded else ""
                lines.append(
                    f"    {use.table}.{use.column} [{use.data_type}]: {use.rows} rows,"
                    f" {len(use.keys)} keys, {use.missing} with no file{extra} — {note}"
                )
    lines.append(f"\nwaiting-room files skipped: {walk.staging}")
    for key in walk.skipped_links:
        lines.append(f"SYMLINK skipped: {key}")
    for key in sorted(walk.unowned):
        lines.append(f"UNOWNED (business unknown — not copied, not deleted): {key}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="local_media_move",
        description="CM-9: copy the uploads volume to R2 once. Dry run unless --apply.",
    )
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument("--tenant", type=UUID, action="append", help="one business (repeatable)")
    who.add_argument("--all-tenants", action="store_true", help="every business on the volume")
    what = parser.add_mutually_exclusive_group()
    what.add_argument("--apply", action="store_true", help="copy, verify and map")
    what.add_argument(
        "--delete-local",
        action="store_true",
        help="delete local files already verified in R2 (a separate run)",
    )
    parser.add_argument("--root", choices=LOCAL_ROOTS, action="append", help="limit to one root")
    parser.add_argument("--no-inventory", action="store_true", help="skip the column sweep")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    from qualify_api.creative.composition import media_root  # noqa: PLC0415
    from qualify_api.creative.owner_uploads import default_gate  # noqa: PLC0415

    mode = "apply" if args.apply else ("delete-local" if args.delete_local else "dry-run")
    reports, walk = run(
        root=media_root(),
        tenants=None if args.all_tenants else args.tenant,
        mode=mode,
        gate_factory=default_gate,
        roots=args.root or LOCAL_ROOTS,
        with_inventory=not args.no_inventory,
    )
    print(render(reports, walk, mode))
    failed = any(r.failures for r in reports)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
