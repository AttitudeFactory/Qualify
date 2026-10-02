"""Saving the whole Brand Kit (§ request 2026-10-01: "que se guarde todo lo que falta al
terminar el brandkit").

Finishing a wizard, or "Guardar cambios" in the editor, used to save only the kit form
(`creative_provider.save_kit`) and leave the rest in the session. Now one save keeps:

- the kit form, which also adopts the voice (`VoiceProfileService.adopt_from_kit`);
- the brandboard — each logo version, every element added with the "+" and a standalone
  logo — uploaded to R2 under the tenant's prefix and recorded with its label and
  context (`brand_kit_store.BrandKitStore.replace_assets`), the main one becoming
  `brand_kits.logo_asset_key` so it reaches the flyers;
- the wizards' answers: the logo brief, the connect flow's (network, user, account kind,
  Google Maps, rubro, location, hashtags) and the account as read with its metrics.

The save is awaited before the wizard moves on: a failure stays on screen
(`CreativeState.kit_error`) instead of being lost behind a redirect.

`load_saved` is the way back: the stored brandboard (with a short-lived view URL per R2
file) and the documents, merged into the session by the states that show them."""

from __future__ import annotations

import asyncio
import io
import logging
import mimetypes
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import reflex as rx
from qualify_api.creative.brand_kit_store import (
    EXTRA,
    LOGO,
    LOGO_VERSION,
    BrandAsset,
    BrandKitDetails,
    BrandKitStore,
    brand_asset_prefix,
)
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .connections_provider import acting_user_id
from .creative_provider import brand_readiness, default_brand_id, save_kit
from .creative_vm import KitFormVM
from .r2_media import is_r2_key, issue_view_path
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_SAVED = "Brand Kit guardado: tu marca, tus archivos y tus respuestas."
_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_KIT_FAILED = "No se pudo guardar el Brand Kit. Inténtalo de nuevo."
_FILES_FAILED = (
    "Guardamos tu marca, pero no los archivos del brandboard (logo y elementos). "
    "Inténtalo de nuevo en un momento."
)
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass
class StagedFile:
    kind: str
    slot: str
    key: str  # a local upload key (`uploads/<tenant>/…`) or an R2 key (`t/<tenant>/…`)
    name: str
    label: str = ""
    context: str = ""
    position: int = 0


@dataclass
class KitSnapshot:
    """Everything a save needs, copied out of the states under their lock."""

    form: KitFormVM
    files: list[StagedFile] = field(default_factory=list)
    #: None = this screen did not touch that document; it keeps what is stored.
    logo_brief: dict[str, Any] | None = None
    connect: dict[str, Any] | None = None
    profile: dict[str, Any] | None = None


class FilesNotSaved(RuntimeError):
    """The kit was saved; the brandboard's files could not be (R2 or their record)."""


# ---------------------------------------------------------------------------------------
# Off the event loop


def _r2_gate() -> Any:
    from qualify_shared.objects.config import R2Settings
    from qualify_shared.objects.gate import ObjectGate
    from qualify_shared.objects.s3 import R2ObjectStore

    return ObjectGate(R2ObjectStore(R2Settings.from_env()))


def _upload(gate: Any, tenant_id: UUID, prefix: str, file: StagedFile, upload_dir: Path) -> str:
    """A staged local file into R2; returns its key there. An R2 key is already there."""
    if is_r2_key(file.key):
        return file.key
    data = (upload_dir / file.key).read_bytes()
    name = _SAFE_NAME.sub("_", file.name or Path(file.key).name)[-80:] or "archivo"
    folder = file.kind if not file.slot else f"{file.kind}/{file.slot}"
    object_key = f"{prefix}{folder}/{uuid4().hex}_{name}"
    content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    gate.put_media(tenant_id, object_key, io.BytesIO(data), content_type)
    return object_key


def persist_brand_kit(
    tenant_id: UUID,
    brand_id: UUID,
    user_id: UUID,
    snapshot: KitSnapshot,
    *,
    upload_dir: Path,
    store: BrandKitStore | None = None,
    gate: Any = None,
) -> None:
    """The kit form first (it is what generation needs), then the brandboard's files,
    then the documents. Raises `FilesNotSaved` when only the files failed."""
    save_kit(tenant_id, brand_id, user_id, snapshot.form)
    store = store or BrandKitStore()
    try:
        prefix = brand_asset_prefix(tenant_id, brand_id)
        gate = gate if gate is not None else (_r2_gate() if _needs_upload(snapshot) else None)
        assets = [
            BrandAsset(
                kind=f.kind,
                slot=f.slot,
                object_key=_upload(gate, tenant_id, prefix, f, upload_dir),
                filename=f.name,
                content_type=mimetypes.guess_type(f.name)[0] or "",
                label=f.label.strip(),
                context=f.context.strip(),
                position=f.position,
            )
            for f in snapshot.files
        ]
        store.replace_assets(tenant_id=tenant_id, brand_id=brand_id, assets=assets)
    except Exception as exc:
        logger.warning("brand kit files not saved: %s", type(exc).__name__)
        raise FilesNotSaved(str(exc)) from exc
    documents = {
        name: document
        for name, document in (
            ("logo_brief", snapshot.logo_brief),
            ("connect", snapshot.connect),
            ("profile", snapshot.profile),
        )
        if document is not None
    }
    if documents:
        store.save_details(
            tenant_id=tenant_id, brand_id=brand_id, user_id=user_id, documents=documents
        )


def _needs_upload(snapshot: KitSnapshot) -> bool:
    return any(not is_r2_key(f.key) for f in snapshot.files)


@dataclass
class SavedBrandKit:
    files: list[StagedFile]
    #: R2 key → `/r2media/<token>` (an hour) for showing it; "" when one cannot be issued.
    views: dict[str, str]
    details: BrandKitDetails


def load_saved(
    tenant_id: UUID, brand_id: UUID, *, store: BrandKitStore | None = None
) -> SavedBrandKit:
    store = store or BrandKitStore()
    assets = store.list_assets(tenant_id=tenant_id, brand_id=brand_id)
    views: dict[str, str] = {}
    for asset in assets:
        try:
            views[asset.object_key] = issue_view_path(
                tenant_id, asset.object_key, "image", asset.content_type or None
            )
        except Exception as exc:  # Redis down: the file still loads, without a preview
            logger.warning("brand asset view not issued: %s", type(exc).__name__)
            views[asset.object_key] = ""
    files = [
        StagedFile(
            kind=a.kind,
            slot=a.slot,
            key=a.object_key,
            name=a.filename,
            label=a.label,
            context=a.context,
            position=a.position,
        )
        for a in assets
    ]
    return SavedBrandKit(
        files=files,
        views=views,
        details=store.load_details(tenant_id=tenant_id, brand_id=brand_id),
    )


# ---------------------------------------------------------------------------------------
# From the states


async def session_ids(state: Any) -> tuple[UUID, UUID, UUID] | None:
    """(tenant, brand, acting user) for the session; `state` is a background handler's
    state, NOT under its lock."""
    async with state:
        auth = await state.get_state(AuthState)
        session_tenant_id = auth.session_tenant_id
    tenant_id = tenant_uuid(session_tenant_id) if session_tenant_id else None
    if tenant_id is None:
        return None
    try:
        brand_id = await asyncio.to_thread(default_brand_id, tenant_id)
        user_id = await asyncio.to_thread(acting_user_id, tenant_id)
    except SQLAlchemyError:
        return None
    if brand_id is None or user_id is None:
        return None
    return tenant_id, brand_id, user_id


def _connect_document(connect: Any) -> dict[str, Any] | None:
    answers = {
        "network": connect.network,
        "username": connect.username,
        "account_kind": connect.account_kind,
        "has_maps": connect.has_maps,
        "sector": connect.sector,
        "rubro_text": connect.rubro_text,
        "country_code": connect.country_code,
        "city": connect.city,
        "hashtags": [dict(item) for item in connect.rubro_hashtags],
    }
    return answers if any(answers.values()) else None


def _profile_document(connect: Any) -> dict[str, Any] | None:
    if not connect.profile_username:
        return None
    return {
        "username": connect.profile_username,
        "fullname": connect.profile_fullname,
        "bio": connect.profile_bio,
        "category": connect.profile_category,
        "followers": connect.profile_followers,
        "followers_count": connect.profile_followers_count,
        "pic": connect.profile_pic,
        "metrics": [
            {"label": label, "hint": hint, "suffix": suffix, "decimals": decimals, "target": target}
            for label, hint, suffix, decimals, target in zip(
                connect.metric_labels,
                connect.metric_hints,
                connect.metric_suffixes,
                connect.metric_decimals,
                connect.metric_targets,
                strict=False,
            )
        ],
    }


async def snapshot_states(state: Any) -> KitSnapshot:
    """Copy the kit out of `CreativeState`, `BrandWizardState` and `BrandConnectState`
    (under `state`'s lock — the caller holds it)."""
    from .creative_state import CreativeState
    from .creative_wizard_pages import LOGO_VERSIONS, BrandConnectState, BrandWizardState

    creative = await state.get_state(CreativeState)
    wizard = await state.get_state(BrandWizardState)
    connect = await state.get_state(BrandConnectState)
    files: list[StagedFile] = []
    if wizard.logo_key:
        files.append(StagedFile(LOGO, "", wizard.logo_key, wizard.logo_name))
    for position, (version, _name, _blurb) in enumerate(LOGO_VERSIONS):
        key = wizard.logo_versions.get(version, "")
        if key:
            files.append(
                StagedFile(
                    LOGO_VERSION,
                    version,
                    key,
                    Path(key).name.split("_", 1)[-1],
                    context=wizard.logo_version_context.get(version, ""),
                    position=position,
                )
            )
    for position, extra in enumerate(wizard.brand_extras):
        files.append(
            StagedFile(
                EXTRA,
                extra["id"],
                extra["key"],
                extra.get("name", ""),
                label=extra.get("label", ""),
                context=extra.get("context", ""),
                position=position,
            )
        )
    brief = {
        "style": wizard.logo_brief_1,
        "feeling": wizard.logo_brief_2,
        "references": wizard.logo_brief_3,
    }
    snapshot = KitSnapshot(
        form=creative._kit_form(),
        files=files,
        logo_brief=brief if any(v.strip() for v in brief.values()) else None,
        connect=_connect_document(connect),
        profile=_profile_document(connect),
    )
    if wizard.replacing_kit:
        # TEMPORAL (docs/brand-kit-resumen-temporal.md): a replacement kit rewrites every
        # document, so nothing of the old kit's answers survives under the new one
        snapshot.logo_brief = snapshot.logo_brief or {}
        snapshot.connect = snapshot.connect or {}
        snapshot.profile = snapshot.profile or {}
    return snapshot


async def save_brand_kit(state: Any) -> bool:
    """Save everything from a background handler's `state`; True on success. The outcome
    lands in `CreativeState.kit_notice` / `kit_error`, and `kit_saving` drives the
    buttons' spinner."""
    from .creative_state import CreativeState

    async with state:
        creative = await state.get_state(CreativeState)
        if creative.kit_saving:
            return False
        creative.kit_saving = True
        creative.kit_error = ""
        creative.kit_notice = ""
    ids = await session_ids(state)
    error = ""
    verdict = None
    if ids is None:
        error = _NO_SESSION
    else:
        async with state:
            snapshot = await snapshot_states(state)
        try:
            await asyncio.to_thread(
                persist_brand_kit, *ids, snapshot, upload_dir=rx.get_upload_dir()
            )
        except FilesNotSaved:
            error = _FILES_FAILED
        except Exception as exc:  # the kit itself (validation, database)
            logger.warning("brand kit save failed: %s", type(exc).__name__)
            error = _KIT_FAILED
        try:
            verdict = await asyncio.to_thread(brand_readiness, ids[0], ids[1])
        except SQLAlchemyError:
            verdict = None
    async with state:
        creative = await state.get_state(CreativeState)
        creative.kit_saving = False
        if verdict is not None:
            creative.readiness = verdict
        if error:
            creative.kit_error = error
            return False
        creative.kit_notice = _SAVED
        from .creative_wizard_pages import BrandWizardState

        wizard = await state.get_state(BrandWizardState)
        wizard.replacing_kit = False  # TEMPORAL: the new kit is now the saved one
    return True
