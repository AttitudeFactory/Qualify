"""Load a client's own logo files and colours into the Brand Kit an «Alta de cliente»
prepared (m-24973635; founder's approval 2026-11-06 for «Araguaney Bar», Meegle item
24973550). A one-off admin command for the `qualify-prod` session — never a request path.

    python -m qualify_api.meegle.alta_brand_files --meegle-item 24973550 \\
        --file logo_version:logotipo=/in/3-logotipo-amarillo-morado.png \\
        --file logo_version:isotipo=/in/1-isotipo-amarillo-morado.png \\
        --file "extra:Logotipo en turquesa=/in/4-logotipo-amarillo-turquesa.png" \\
        --colors "#FFD920,#74238C,#1AC5A3" --dry-run

**Which tenant.** The draft is found by `brand_kit_drafts (origin = 'alta',
meegle_work_item_id)` — the row `auth.drafts.start_alta_brand_kit_draft` wrote — never by
an editable Meegle field. Its brand is the tenant's first one (as `claim_draft` picks it).
It works before the signup (the draft) and after it (the same tenant, adopted: the
client's live Brand Kit). `--expect-tenant` cross-checks the resolved tenant.

**What it writes** (only through `tenant_session` and the creative store's own doors):

- each file to R2 under the brand's prefix, at a key derived from its bytes
  (`t/<tenant>/brand/<brand>/<kind>/<slot>/<sha256[:16]>_<name>`), so a re-run PUTs the
  same object or none (a key already recorded is not uploaded again);
- `brand_kit_assets`: the given (kind, slot) rows; every other file already there stays
  (the store's `replace_assets` is given the whole merged set). An `extra`'s slot is
  derived from its label, so the same label replaces, never duplicates;
- `brand_kits.palette_rgb`: the given colours first, then any other colour already there
  (nothing hand-picked is dropped); a brand with no kit row gets one with empty answers
  and the middle tone — as the prefill approval creates it;
- `brand_kit_details.connect.progress`: `completed = False` (flow `minimo`) when it had to
  create the kit row, so the kit never counts as finished (`kit_finished`);
- `brand_kit_details.connect.alta_brand_files`: the provenance — founder-provided files
  (manual input), item id, each file's sha256 and original name, the colours, when, and
  this command's version. It is also printed, to paste on the Meegle item.

**The proposal guard.** `creative.brand_prefill_review.owner_started` counts any
brandboard file or palette as the owner's own answers: once this runs, a pending Alta
prefill proposal (PB-5: rubro, city, hashtags, picture…) is never offered, and approving
it only marks it `superseded`. So the command refuses while the prefill job of the item is
unsettled or its proposal is still waiting, unless `--supersede-proposal` says the founder
accepts losing it. `--colors-into-proposal` is the other way: it only corrects the pending
proposal's colours (`edit_prefill_field`, the review card's own correction), so the owner's
«Aprobar» brings them — with `--no-profile-logo` the proposal also stops taking the
Instagram picture as the logo; the files then go in after that approval (a re-run then
passes the guard: the proposal is `approved`).

`--dry-run` reads and prints the plan; it writes nothing to Postgres or R2.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from qualify_api.creative.brand_kit_store import (
    EXTRA,
    LOGO,
    LOGO_VERSION,
    BrandAsset,
    brand_asset_prefix,
    main_logo_key,
)

COMMAND_VERSION = "alta_brand_files/1"
PROVENANCE_KEY = "alta_brand_files"
PROGRESS_KEY = "progress"
PREFILL_KEY = "prefill"
RESUME_FLOW = "minimo"
#: The logo versions Tu brandboard lays out, in its order (`Qualify/creative_wizard_pages.
#: LOGO_VERSIONS`): one file per version.
LOGO_VERSION_SLOTS = ("logotipo", "isotipo", "imagotipo", "isologo")
#: Extras sit after the versions on the brandboard.
EXTRA_POSITION_BASE = 10
CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}
MAX_FILE_BYTES = 10 * 1024 * 1024
_HEX = re.compile(r"#[0-9a-fA-F]{6}")
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
#: Prefill job statuses that mean the run (and its proposal write) has not settled.
_JOB_DONE = "done"


class RefusedError(Exception):
    """The command will not write; `message` says why and what to pass instead."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# --------------------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FileSpec:
    kind: str
    slot: str
    label: str
    path: Path


def extra_slot(label: str) -> str:
    """An extra's slot, stable per label (the wizard uses 8 hex characters too)."""
    return hashlib.sha1(label.strip().casefold().encode()).hexdigest()[:8]  # noqa: S324


def parse_file_arg(value: str) -> FileSpec:
    """`KIND:NAME=PATH`: `logo_version:<logotipo|isotipo|imagotipo|isologo>=…`,
    `extra:<label shown to the client>=…` or `logo:=…` (a standalone main logo)."""
    head, sep, path = value.partition("=")
    kind, colon, name = head.partition(":")
    if not sep or not colon or not path.strip():
        raise ValueError(f"expected KIND:NAME=PATH, got {value!r}")
    kind, name = kind.strip(), name.strip()
    if kind == LOGO_VERSION:
        if name not in LOGO_VERSION_SLOTS:
            raise ValueError(f"logo_version must be one of {', '.join(LOGO_VERSION_SLOTS)}")
        return FileSpec(LOGO_VERSION, name, "", Path(path.strip()))
    if kind == EXTRA:
        if not name or len(name) > 80:
            raise ValueError("an extra needs a label of 1-80 characters")
        return FileSpec(EXTRA, extra_slot(name), name, Path(path.strip()))
    if kind == LOGO:
        if name:
            raise ValueError("logo takes no name: logo:=PATH")
        return FileSpec(LOGO, "", "", Path(path.strip()))
    raise ValueError(f"unknown kind {kind!r} (logo_version, extra, logo)")


def parse_colors(value: str) -> list[str]:
    colours: list[str] = []
    for raw in value.split(","):
        colour = raw.strip()
        if not colour:
            continue
        if not _HEX.fullmatch(colour):
            raise ValueError(f"not a #rrggbb colour: {colour!r}")
        if colour.lower() not in {c.lower() for c in colours}:
            colours.append(colour.upper())
    if not 1 <= len(colours) <= 6:
        raise ValueError("expected one to six colours")
    return colours


@dataclass(frozen=True)
class LoadedFile:
    spec: FileSpec
    data: bytes
    sha256: str
    content_type: str

    @property
    def filename(self) -> str:
        return self.spec.path.name


def load_file(spec: FileSpec) -> LoadedFile:
    suffix = spec.path.suffix.lower()
    if suffix not in CONTENT_TYPES:
        raise ValueError(f"{spec.path.name}: only {', '.join(sorted(CONTENT_TYPES))}")
    data = spec.path.read_bytes()
    if not data or len(data) > MAX_FILE_BYTES:
        raise ValueError(f"{spec.path.name}: empty or over {MAX_FILE_BYTES} bytes")
    return LoadedFile(spec, data, hashlib.sha256(data).hexdigest(), CONTENT_TYPES[suffix])


def object_key(tenant_id: UUID, brand_id: UUID, loaded: LoadedFile) -> str:
    spec = loaded.spec
    folder = spec.kind if not spec.slot else f"{spec.kind}/{spec.slot}"
    name = _SAFE_NAME.sub("_", loaded.filename)[-80:]
    return f"{brand_asset_prefix(tenant_id, brand_id)}{folder}/{loaded.sha256[:16]}_{name}"


def position_of(spec: FileSpec, index: int) -> int:
    if spec.kind == LOGO_VERSION:
        return LOGO_VERSION_SLOTS.index(spec.slot)
    if spec.kind == EXTRA:
        return EXTRA_POSITION_BASE + index
    return 0


# --------------------------------------------------------------------------------------
# What is there
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DraftTarget:
    tenant_id: UUID
    brand_id: UUID
    user_id: UUID | None
    claimed: bool


@dataclass(frozen=True)
class PrefillJobRow:
    status: str
    outcome: str | None
    proposal_written: bool


@dataclass(frozen=True)
class TargetState:
    jobs: tuple[PrefillJobRow, ...] = ()
    connect: Mapping[str, Any] = field(default_factory=dict)
    has_kit: bool = False
    palette: tuple[str, ...] = ()
    assets: tuple[BrandAsset, ...] = ()

    @property
    def prefill(self) -> Mapping[str, Any] | None:
        raw = self.connect.get(PREFILL_KEY)
        return raw if isinstance(raw, Mapping) else None

    @property
    def progress(self) -> dict[str, Any] | None:
        raw = self.connect.get(PROGRESS_KEY)
        return dict(raw) if isinstance(raw, Mapping) else None

    @property
    def kit_finished(self) -> bool:
        return self.has_kit and (self.progress or {}).get("completed") is not False

    @property
    def proposal_waiting(self) -> bool:
        document = self.prefill
        return (
            document is not None
            and not self.kit_finished
            and document.get("status") == "ok"
            and document.get("state") == "proposed"
        )

    @property
    def prefill_unsettled(self) -> bool:
        return any(job.status != _JOB_DONE for job in self.jobs)


def guard(state: TargetState, *, supersede_proposal: bool) -> list[str]:
    """Why writing files/colours now would hide the Alta's prefill proposal ([] = safe)."""
    reasons: list[str] = []
    if state.prefill_unsettled:
        reasons.append(
            "the Alta prefill job has not finished: its proposal would land hidden "
            "(owner_started) — wait for it, or pass --supersede-proposal"
        )
    if state.proposal_waiting:
        reasons.append(
            "a prefill proposal is waiting for the owner's review: loading files or "
            "colours hides it and «Aprobar» would only mark it superseded — run after "
            "the owner approves it, use --colors-into-proposal, or pass --supersede-proposal"
        )
    return [] if supersede_proposal else reasons


# --------------------------------------------------------------------------------------
# The plan
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PlannedFile:
    kind: str
    slot: str
    label: str
    filename: str
    sha256: str
    content_type: str
    size: int
    object_key: str
    upload: bool  # False: that key is already recorded (same bytes)


@dataclass(frozen=True)
class Plan:
    tenant_id: str
    brand_id: str
    claimed: bool
    files: tuple[PlannedFile, ...]
    assets_after: tuple[BrandAsset, ...]
    main_logo: str | None
    palette_before: tuple[str, ...]
    palette_after: tuple[str, ...]
    create_kit: bool
    progress_after: dict[str, Any] | None  # None: left as it is
    provenance: dict[str, Any]
    warnings: tuple[str, ...]

    def as_document(self) -> dict[str, Any]:
        out = asdict(self)
        out["assets_after"] = [asdict(a) for a in self.assets_after]
        out["files"] = [asdict(f) for f in self.files]
        return out


def merged_palette(stored: Sequence[str], colours: Sequence[str]) -> tuple[str, ...]:
    """The given colours first, then every other stored colour (case-insensitive)."""
    wanted = {c.lower() for c in colours}
    return (*colours, *(c for c in stored if c.lower() not in wanted))


def build_plan(
    target: DraftTarget,
    state: TargetState,
    files: Sequence[LoadedFile],
    colours: Sequence[str],
    *,
    meegle_work_item_id: int,
    now: datetime,
    warnings: Sequence[str] = (),
) -> Plan:
    slots = [(f.spec.kind, f.spec.slot) for f in files]
    if len(set(slots)) != len(slots):
        raise ValueError("two files for the same kind and slot")
    recorded = {a.object_key for a in state.assets}
    planned: list[PlannedFile] = []
    ours: list[BrandAsset] = []
    for index, loaded in enumerate(files):
        key = object_key(target.tenant_id, target.brand_id, loaded)
        planned.append(
            PlannedFile(
                kind=loaded.spec.kind,
                slot=loaded.spec.slot,
                label=loaded.spec.label,
                filename=loaded.filename,
                sha256=loaded.sha256,
                content_type=loaded.content_type,
                size=len(loaded.data),
                object_key=key,
                upload=key not in recorded,
            )
        )
        ours.append(
            BrandAsset(
                kind=loaded.spec.kind,
                slot=loaded.spec.slot,
                object_key=key,
                filename=loaded.filename,
                content_type=loaded.content_type,
                label=loaded.spec.label,
                position=position_of(loaded.spec, index),
            )
        )
    kept = [a for a in state.assets if (a.kind, a.slot) not in set(slots)]
    assets_after = tuple(sorted([*kept, *ours], key=lambda a: (a.kind, a.position, a.slot)))
    palette_after = merged_palette(state.palette, colours) if colours else state.palette
    create_kit = not state.has_kit and bool(colours or files)
    progress_after: dict[str, Any] | None = None
    if create_kit:
        progress_after = state.progress or {}
        progress_after.setdefault("flow", RESUME_FLOW)
        progress_after["completed"] = False
    provenance = {
        "source": "founder_provided_files",
        "input": "manual",
        "meegle_work_item_id": meegle_work_item_id,
        "files": [
            {
                "kind": p.kind,
                "slot": p.slot,
                "label": p.label,
                "filename": p.filename,
                "sha256": p.sha256,
                "object_key": p.object_key,
            }
            for p in planned
        ],
        "colors": list(colours),
        "pipeline": __name__,
        "pipeline_version": COMMAND_VERSION,
        "loaded_at": now.isoformat(),
    }
    return Plan(
        tenant_id=str(target.tenant_id),
        brand_id=str(target.brand_id),
        claimed=target.claimed,
        files=tuple(planned),
        assets_after=assets_after,
        main_logo=main_logo_key(assets_after),
        palette_before=tuple(state.palette),
        palette_after=tuple(palette_after),
        create_kit=create_kit,
        progress_after=progress_after,
        provenance=provenance,
        warnings=tuple(warnings),
    )


# --------------------------------------------------------------------------------------
# Ports
# --------------------------------------------------------------------------------------


class Backend(Protocol):
    def resolve(self, meegle_work_item_id: int) -> DraftTarget | None: ...

    def read_state(self, target: DraftTarget, meegle_work_item_id: int) -> TargetState: ...

    def write_connect_key(self, target: DraftTarget, key: str, value: Any) -> None: ...

    def write_palette(self, target: DraftTarget, palette: Sequence[str]) -> None: ...

    def put_object(self, tenant_id: UUID, key: str, data: bytes, content_type: str) -> None: ...

    def replace_assets(self, target: DraftTarget, assets: Sequence[BrandAsset]) -> str | None: ...

    def correct_proposal_colors(self, target: DraftTarget, colours: Sequence[str]) -> bool: ...

    def drop_proposal_profile_logo(self, target: DraftTarget) -> bool: ...


class DatabaseBackend:
    """The production wiring: `admin_session` for the one cross-tenant lookup (the draft
    row), `tenant_session` + the creative store for everything else, R2 via ObjectGate."""

    def __init__(self) -> None:
        self._gate: Any = None

    def resolve(self, meegle_work_item_id: int) -> DraftTarget | None:
        from qualify_shared.db.admin import admin_session
        from sqlalchemy import select

        from qualify_api.auth.drafts import ORIGIN_ALTA
        from qualify_api.tenancy.models import Brand, BrandKitDraft, User

        with admin_session() as session:
            draft = session.scalar(
                select(BrandKitDraft).where(
                    BrandKitDraft.origin == ORIGIN_ALTA,
                    BrandKitDraft.meegle_work_item_id == meegle_work_item_id,
                )
            )
            if draft is None:
                return None
            brand_id = session.scalar(
                select(Brand.id)
                .where(Brand.tenant_id == draft.tenant_id)
                .order_by(Brand.created_at)
                .limit(1)
            )
            if brand_id is None:
                return None
            user_id = session.scalar(
                select(User.id).where(User.tenant_id == draft.tenant_id).order_by(User.created_at)
            )
            return DraftTarget(draft.tenant_id, brand_id, user_id, draft.claimed_at is not None)

    def read_state(self, target: DraftTarget, meegle_work_item_id: int) -> TargetState:
        from qualify_shared.db.session import tenant_session
        from sqlalchemy import select, text

        from qualify_api.creative.brand_kit_store import BrandKitStore
        from qualify_api.creative.models import BrandKit as KitRow
        from qualify_api.creative.models import BrandKitDetails as DetailsRow

        with tenant_session(target.tenant_id) as session:
            jobs = tuple(
                PrefillJobRow(row.status, row.outcome, bool(row.proposal_written))
                for row in session.execute(
                    text(
                        "SELECT status, outcome, proposal_written FROM alta_prefill_jobs "
                        "WHERE meegle_work_item_id = :item"
                    ),
                    {"item": meegle_work_item_id},
                )
            )
            details = session.get(DetailsRow, target.brand_id)
            kit = session.scalar(select(KitRow).where(KitRow.brand_id == target.brand_id))
            connect = dict(details.connect or {}) if details is not None else {}
            palette = tuple(kit.palette_rgb or ()) if kit is not None else ()
        assets = BrandKitStore().list_assets(tenant_id=target.tenant_id, brand_id=target.brand_id)
        return TargetState(jobs, connect, kit is not None, palette, tuple(assets))

    def write_connect_key(self, target: DraftTarget, key: str, value: Any) -> None:
        from qualify_api.creative.brand_kit_store import BrandKitStore

        BrandKitStore().set_document_key(
            tenant_id=target.tenant_id,
            brand_id=target.brand_id,
            document="connect",
            key=key,
            value=value,
        )

    def write_palette(self, target: DraftTarget, palette: Sequence[str]) -> None:
        """An existing kit row gets only its `palette_rgb` column (never a pydantic round
        trip that could fail on, or rewrite, the owner's other answers); a brand without
        one gets the row the prefill approval would create: empty answers, middle tone."""
        from qualify_creative.schemas import BrandKit, ToneAxes
        from qualify_shared.db.session import tenant_session
        from sqlalchemy import select

        from qualify_api.creative.brand_service import BrandKitService
        from qualify_api.creative.models import BrandKit as KitRow

        with tenant_session(target.tenant_id) as session:
            row = session.scalar(
                select(KitRow).where(KitRow.brand_id == target.brand_id).with_for_update()
            )
            if row is not None:
                row.palette_rgb = list(palette)
                row.updated_at = datetime.now(UTC)
                session.flush()
                return
        middle = 50  # the wizard's first save and the prefill approval: the middle tone
        kit = BrandKit(
            brand_id=target.brand_id,
            positioning="",
            audience="",
            tone_axes=ToneAxes(
                formal_casual=middle,
                sober_enthusiastic=middle,
                technical_plain=middle,
                brief_elaborate=middle,
            ),
            palette_rgb=tuple(palette),
        )
        BrandKitService().upsert_kit(
            tenant_id=target.tenant_id,
            brand_id=target.brand_id,
            kit=kit,
            user_id=target.user_id or target.tenant_id,
        )

    def put_object(self, tenant_id: UUID, key: str, data: bytes, content_type: str) -> None:
        import io

        if self._gate is None:
            from qualify_shared.objects.config import R2Settings
            from qualify_shared.objects.gate import ObjectGate
            from qualify_shared.objects.s3 import R2ObjectStore

            self._gate = ObjectGate(R2ObjectStore(R2Settings.from_env()))
        self._gate.put_media(tenant_id, key, io.BytesIO(data), content_type)

    def replace_assets(self, target: DraftTarget, assets: Sequence[BrandAsset]) -> str | None:
        from qualify_api.creative.brand_kit_store import BrandKitStore

        return BrandKitStore().replace_assets(
            tenant_id=target.tenant_id, brand_id=target.brand_id, assets=assets
        )

    def correct_proposal_colors(self, target: DraftTarget, colours: Sequence[str]) -> bool:
        from qualify_api.creative.brand_prefill_review import edit_prefill_field

        decision = edit_prefill_field(target.tenant_id, target.brand_id, "colors", list(colours))
        return decision.done

    def drop_proposal_profile_logo(self, target: DraftTarget) -> bool:
        from qualify_api.creative.brand_prefill_review import edit_prefill_field

        return edit_prefill_field(target.tenant_id, target.brand_id, "logo", False).done


# --------------------------------------------------------------------------------------
# Running it
# --------------------------------------------------------------------------------------


def apply_plan(
    backend: Backend, target: DraftTarget, plan: Plan, files: Sequence[LoadedFile]
) -> None:
    """Order matters for a crash in between: progress before the kit row (never a
    "finished" empty kit), the kit row before the assets (so `replace_assets` points
    `logo_asset_key` at the main logo), R2 before the rows that name the keys."""
    if plan.progress_after is not None:
        backend.write_connect_key(target, PROGRESS_KEY, plan.progress_after)
    backend.write_connect_key(target, PROVENANCE_KEY, plan.provenance)
    if plan.palette_after != plan.palette_before or plan.create_kit:
        backend.write_palette(target, plan.palette_after)
    by_key = {object_key(target.tenant_id, target.brand_id, f): f for f in files}
    for planned in plan.files:
        if planned.upload:
            loaded = by_key[planned.object_key]
            backend.put_object(
                target.tenant_id, planned.object_key, loaded.data, planned.content_type
            )
    if plan.files:
        backend.replace_assets(target, plan.assets_after)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m qualify_api.meegle.alta_brand_files",
        description="Load an Alta client's logo files and colours into its Brand Kit draft.",
    )
    parser.add_argument("--meegle-item", required=True, type=int, help="Alta work item id")
    parser.add_argument(
        "--file",
        action="append",
        default=[],
        type=parse_file_arg,
        metavar="KIND:NAME=PATH",
        help="logo_version:logotipo=PATH, extra:<label>=PATH or logo:=PATH (repeatable)",
    )
    parser.add_argument("--colors", type=parse_colors, default=[], help="#RRGGBB,#RRGGBB,…")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    parser.add_argument(
        "--expect-tenant",
        type=UUID,
        help="refuse unless the Alta's draft resolves to this tenant (a cross-check)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--supersede-proposal",
        action="store_true",
        help="load even though the Alta prefill proposal will then never be offered",
    )
    mode.add_argument(
        "--colors-into-proposal",
        action="store_true",
        help="only correct the waiting proposal's colours (no files)",
    )
    parser.add_argument(
        "--no-profile-logo",
        action="store_true",
        help="with --colors-into-proposal: the proposal stops using the profile picture as "
        "the logo (the client's own files go in after the approval)",
    )
    return parser


def run(argv: Sequence[str] | None, backend: Backend, *, now: datetime | None = None) -> dict:
    """Parse, read, plan, guard and (unless --dry-run) write. Returns the printed report.
    Raises `RefusedError` when it will not write."""
    args = build_parser().parse_args(argv)
    if not args.file and not args.colors:
        raise RefusedError("nothing to load: pass --file and/or --colors")
    target = backend.resolve(args.meegle_item)
    if target is None:
        raise RefusedError(f"no Alta Brand Kit draft for Meegle item {args.meegle_item}")
    if args.expect_tenant is not None and args.expect_tenant != target.tenant_id:
        raise RefusedError(
            f"Meegle item {args.meegle_item} resolves to tenant {target.tenant_id}, "
            f"not {args.expect_tenant}"
        )
    state = backend.read_state(target, args.meegle_item)
    base = {
        "meegle_work_item_id": args.meegle_item,
        "tenant_id": str(target.tenant_id),
        "brand_id": str(target.brand_id),
        "claimed": target.claimed,
        "prefill_jobs": [asdict(j) for j in state.jobs],
        "prefill_state": (state.prefill or {}).get("state"),
        "prefill_status": (state.prefill or {}).get("status"),
        "dry_run": args.dry_run,
    }
    if args.colors_into_proposal:
        if args.file:
            raise RefusedError("--colors-into-proposal takes only --colors")
        if not args.colors or not state.proposal_waiting:
            raise RefusedError("no waiting prefill proposal to correct (or no --colors)")
        done = False if args.dry_run else backend.correct_proposal_colors(target, args.colors)
        logo_done = False
        if args.no_profile_logo and not args.dry_run:
            logo_done = backend.drop_proposal_profile_logo(target)
        return {
            **base,
            "mode": "colors_into_proposal",
            "colors": args.colors,
            "no_profile_logo": args.no_profile_logo,
            "written": done,
            "profile_logo_dropped": logo_done,
        }
    if args.no_profile_logo:
        raise RefusedError("--no-profile-logo goes with --colors-into-proposal")
    refusals = guard(state, supersede_proposal=args.supersede_proposal)
    files = [load_file(spec) for spec in args.file]
    warnings: list[str] = []
    if args.supersede_proposal and (state.prefill_unsettled or state.proposal_waiting):
        warnings.append("the Alta prefill proposal will not be offered to the owner")
    plan = build_plan(
        target,
        state,
        files,
        args.colors,
        meegle_work_item_id=args.meegle_item,
        now=now or datetime.now(UTC),
        warnings=warnings,
    )
    report = {**base, "mode": "kit", "refused": refusals, "plan": plan.as_document()}
    if refusals and not args.dry_run:
        raise RefusedError("; ".join(refusals))
    if not args.dry_run:
        apply_plan(backend, target, plan, files)
        report["written"] = True
    return report


def main(argv: Sequence[str] | None = None) -> int:
    try:
        report = run(argv, DatabaseBackend())
    except RefusedError as exc:
        print(f"refused: {exc.message}", file=sys.stderr)
        return 2
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return 3 if report.get("refused") else 0  # a dry run that a real run would refuse


if __name__ == "__main__":
    raise SystemExit(main())
