"""Explicit, retryable deletion of prefill review pictures (m-24854328).

The kept root is shared with the proposed profile photo. Approved logos remain pinned;
only thumbnails and unapproved profile pictures enter the durable cleanup manifest.
The daily retention chore also expires proposals after 30 days, under the same row lock
as approval, so it cannot race a logo promotion.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.creative import kept_pictures
from qualify_api.creative.models import BrandKit, BrandKitAsset, BrandKitDetails

logger = logging.getLogger(__name__)
RETENTION = timedelta(days=30)


def manifest(
    tenant_id: UUID, brand_id: UUID, proposal: Mapping[str, Any], *, keep: str = ""
) -> list[str]:
    observed = proposal.get("observed") or {}
    profile = proposal.get("profile") or {}
    candidates = [profile.get("pic_key")]
    candidates.extend(
        item.get("thumb_r2_key")
        for item in observed.get("recent_media", [])
        if isinstance(item, Mapping)
    )
    return list(
        dict.fromkeys(
            key
            for key in candidates
            if kept_pictures.is_kept_key(tenant_id, brand_id, key) and key != keep
        )
    )


def cleanup_brand(
    tenant_id: UUID,
    brand_id: UUID,
    *,
    gate: Any = None,
    session_factory: Callable[..., Any] = tenant_session,
    now: datetime | None = None,
    execute: bool = True,
) -> int:
    """Retry a stored manifest or expire a pending proposal. Failures retain the manifest."""
    with session_factory(tenant_id) as session:
        row = session.get(BrandKitDetails, brand_id, with_for_update=True)
        if row is None:
            return 0
        connect = dict(row.connect or {})
        document = dict(connect.get("prefill") or {})
        proposal = document.get("proposal") or {}
        pending = list(document.get("cleanup_keys") or [])
        ledger = dict(connect.get("prefill_media") or {})
        moment = now or datetime.now(UTC)
        for key, registered_at in ledger.items():
            try:
                if datetime.fromisoformat(registered_at) <= moment - RETENTION:
                    pending.append(key)
            except (TypeError, ValueError):
                continue
        try:
            created = datetime.fromisoformat(document.get("created_at", ""))
            expired = created <= (now or datetime.now(UTC)) - RETENTION
        except (ValueError, TypeError):
            expired = False
        if expired:
            from qualify_api.tenancy.models import BrandKitDraft

            claimed = session.scalar(
                select(BrandKitDraft.claimed_at).where(BrandKitDraft.tenant_id == tenant_id)
            )
            expired = claimed is None
        if expired:
            # Preserve the currently promoted picture, even after a later decision.
            keep = (row.profile or {}).get("pic_key", "")
            pending.extend(manifest(tenant_id, brand_id, proposal, keep=keep))
        if not expired and document.get("state") in {"proposed", "changed"}:
            protected = set(manifest(tenant_id, brand_id, proposal))
            explicit = set(document.get("cleanup_keys") or [])
            pending = [key for key in pending if key not in protected or key in explicit]
        keep = (row.profile or {}).get("pic_key", "")
        logo_key = session.scalar(
            select(BrandKit.logo_asset_key).where(BrandKit.brand_id == brand_id)
        )
        pending = [key for key in dict.fromkeys(pending) if key != keep and key != logo_key]
        pending = [
            key
            for key in pending
            if session.scalar(
                select(BrandKitAsset.id).where(
                    BrandKitAsset.brand_id == brand_id, BrandKitAsset.object_key == key
                )
            )
            is None
        ]
        if not pending or not execute:
            return len(pending)
        # Revalidate all keys against this brand, including a persisted manifest.
        if any(not kept_pictures.is_kept_key(tenant_id, brand_id, key) for key in pending):
            raise ValueError("invalid prefill cleanup manifest")
        if gate is None:
            gate = kept_pictures._default_gate()  # noqa: SLF001 — same sanctioned object door
        document["cleanup_keys"] = pending
        row.connect = {**connect, "prefill": document}
        session.flush()
        try:
            gate.delete_brand_prefill_objects(tenant_id, brand_id, pending)
        except Exception as exc:  # noqa: BLE001 — retry next daily pass
            logger.warning("prefill media cleanup deferred: %s", type(exc).__name__)
            return 0
        document = {
            **document,
            "cleanup_keys": [],
            "media_cleaned_at": datetime.now(UTC).isoformat(),
        }
        cleaned_proposal = dict(proposal)
        observed = dict(cleaned_proposal.get("observed") or {})
        observed["recent_media"] = [
            {k: v for k, v in item.items() if k not in {"thumb_r2_key", "thumb_content_type"}}
            if item.get("thumb_r2_key") in pending
            else dict(item)
            for item in observed.get("recent_media", [])
            if isinstance(item, Mapping)
        ]
        cleaned_proposal["observed"] = observed
        profile = dict(cleaned_proposal.get("profile") or {})
        if profile.get("pic_key") in pending:
            profile.pop("pic_key", None)
            profile.pop("pic_content_type", None)
        cleaned_proposal["profile"] = profile
        document["proposal"] = cleaned_proposal
        if expired and document.get("state") == "proposed":
            document["media_expired"] = True
        row.connect = {
            **connect,
            "prefill": document,
            "prefill_media": {
                key: date
                for key, date in ledger.items()
                if key not in pending or datetime.fromisoformat(date) > moment - RETENTION
            },
        }
        session.flush()
        return len(pending)


def run_cleanup(
    tenant_ids: list[UUID] | None, *, execute: bool, now: datetime | None = None
) -> int:
    """Daily worker wiring: production discovery reads ids only, then tenant-scoped work."""
    if tenant_ids is None:
        from qualify_shared.db.admin import admin_session

        with admin_session() as session:
            tenant_ids = list(session.scalars(select(BrandKitDetails.tenant_id).distinct()).all())
    total = 0
    for tenant_id in tenant_ids:
        with tenant_session(tenant_id) as session:
            brands = list(session.scalars(select(BrandKitDetails.brand_id)).all())
        for brand_id in brands:
            try:
                total += cleanup_brand(tenant_id, brand_id, execute=execute, now=now)
            except Exception as exc:  # noqa: BLE001 — one brand never stops retention
                logger.warning("prefill media cleanup failed: %s", type(exc).__name__)
    return total
