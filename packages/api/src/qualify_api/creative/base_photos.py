"""The stored base photographs of a piece (m-25017279, ADR 49 §2 item 1, migration 0165).

A base is the raw Seedream photograph a still was composed over. It is described in its
own table, `piece_base_photos` — one row per version and position, `stored` (its R2 key,
SHA-256, type, size) or `missing` (paid for, but not kept) — never in `image_assets`, so no
reader of a piece's outputs (cover, media list, carousel children, Planificador, export)
can see one: there is nothing for them to filter. `piece_layers.base_asset_id` points here
(ADR 49 §2.1).

**Bookkeeping never costs the owner their piece.** `record_base_photos` writes the rows
inside a SAVEPOINT: if anything in it fails (a constraint, a bad size, the database), the
savepoint is rolled back alone, the bases are written again as `missing` (in a savepoint of
their own), and if even that fails nothing but the alert is left — the paid generation and
its outputs are committed either way.

**A missing base is never silent:** its row says so (a re-compose will offer only «Crear
otra» for that slide) and the team gets ONE alert per piece, sent in the background after
the piece's media is written, through the channel of the plan and vendor alerts
(`plans.notify`, Lark). A slow or failing webhook never delays or fails the piece.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import replace
from uuid import UUID

from sqlalchemy.orm import Session

from qualify_api.creative import models as orm
from qualify_api.creative.media import MediaWrite

logger = logging.getLogger(__name__)

STORED = "stored"
MISSING = "missing"
#: The pipeline that writes base rows (provenance; ADR 49 §2.3, stage `base`).
BASE_PIPELINE_VERSION = "image-pipeline-base-v1"
#: The metric tag of the operational log line (`extra={"metric": …}`).
MISSING_METRIC = "creative.base_photo.missing"


def _team_notifier() -> object:
    from qualify_api.plans.notify import production_team_notifier  # noqa: PLC0415

    return production_team_notifier()


def _in_background(send: Callable[[], None]) -> None:
    threading.Thread(target=send, name="base-photo-alert", daemon=True).start()


#: Swappable in tests (`RecordingTeamNotifier`); production reads the team webhook.
notifier_factory: Callable[[], object] = _team_notifier
#: How the alert is sent: in a daemon thread, so the generation never waits on Lark.
alert_dispatch: Callable[[Callable[[], None]], None] = _in_background


def alert_text(tenant_id: UUID, draft_id: UUID, names: Sequence[str]) -> str:
    return (
        f"Foto base no guardada: negocio {tenant_id}, pieza {draft_id}, archivo(s) "
        f"{', '.join(names)}. El almacenamiento (R2) la rechazó. El cliente recibió su pieza "
        "igual, pero no podremos rehacer su texto más adelante. Revisar R2 (m-25017279)."
    )


def alert_missing_bases(tenant_id: UUID, draft_id: UUID, names: Sequence[str]) -> None:
    """ONE operational alert for a piece whose bases were not kept. Never raises and never
    blocks: the send runs through `alert_dispatch`. Ids and file names only."""
    if not names:
        return
    logger.error(
        "base photos not kept: tenant=%s draft=%s files=%s",
        tenant_id,
        draft_id,
        ",".join(names),
        extra={"metric": MISSING_METRIC, "count": len(names)},
    )
    text = alert_text(tenant_id, draft_id, names)

    def send() -> None:
        try:
            notify = getattr(notifier_factory(), "notify", None)
            if callable(notify):
                notify(text)
        except Exception:  # noqa: BLE001 - an alert never breaks anything
            logger.warning("base photo alert not sent for draft %s", draft_id, exc_info=True)

    try:
        alert_dispatch(send)
    except Exception:  # noqa: BLE001
        logger.warning("base photo alert not dispatched for draft %s", draft_id, exc_info=True)


def _rows(
    *,
    tenant_id: UUID,
    brand_id: UUID,
    draft_id: UUID,
    version_id: UUID,
    media: Sequence[MediaWrite],
) -> list[orm.PieceBasePhoto]:
    return [
        orm.PieceBasePhoto(
            tenant_id=tenant_id,
            brand_id=brand_id,
            draft_id=draft_id,
            version_id=version_id,
            position=item.position,
            state=STORED if item.base.key is not None else MISSING,
            object_key=item.base.key,
            # what was paid for, also when it was not kept
            sha256=item.base.sha256,
            content_type=item.base.content_type,
            width=item.base.width,
            height=item.base.height,
            rendered_prompt=item.base.rendered_prompt,
            model_id=item.base.model_id,
            provider=item.base.provider,
            prompt_compiler_version=item.base.prompt_compiler_version,
            pipeline_version=BASE_PIPELINE_VERSION,
            missing_reason=item.base.missing_reason if item.base.key is None else None,
        )
        for item in media
        if item.base is not None
    ]


def add_base_photos(
    session: Session,
    *,
    tenant_id: UUID,
    brand_id: UUID,
    draft_id: UUID,
    version_id: UUID,
    media: Sequence[MediaWrite],
) -> int:
    """One `piece_base_photos` row per still that carries a base, at the still's position
    (`uq_piece_base_photos_position`: one per version and position). Raises on any
    database refusal — `record_base_photos` is the caller that never does."""
    rows = _rows(
        tenant_id=tenant_id,
        brand_id=brand_id,
        draft_id=draft_id,
        version_id=version_id,
        media=media,
    )
    session.add_all(rows)
    if rows:
        session.flush()
    return len(rows)


def _as_missing(media: Sequence[MediaWrite], reason: str) -> list[MediaWrite]:
    return [
        replace(
            item,
            base=replace(item.base, key=None, width=None, height=None, missing_reason=reason[:200]),
        )
        for item in media
        if item.base is not None
    ]


def record_base_photos(
    session: Session,
    *,
    tenant_id: UUID,
    brand_id: UUID,
    draft_id: UUID,
    version_id: UUID,
    media: Sequence[MediaWrite],
) -> list[str]:
    """Write the bases of a generation's stills without ever failing it; return the names
    of the bases that end up missing (for the one alert of the piece)."""
    if not any(item.base is not None for item in media):
        return []
    common = {
        "tenant_id": tenant_id,
        "brand_id": brand_id,
        "draft_id": draft_id,
        "version_id": version_id,
    }
    try:
        with session.begin_nested():
            add_base_photos(session, media=media, **common)
        return _missing_names(media)
    except Exception as exc:  # noqa: BLE001 - bookkeeping never fails the paid piece
        logger.warning("base rows of draft %s refused: %s", draft_id, exc)
        reason = f"base row refused: {type(exc).__name__}"
    missing = _as_missing(media, reason)
    try:
        with session.begin_nested():
            add_base_photos(session, media=missing, **common)
    except Exception as exc:  # noqa: BLE001
        logger.warning("missing base rows of draft %s refused too: %s", draft_id, exc)
    return _missing_names(missing)


def _missing_names(media: Sequence[MediaWrite]) -> list[str]:
    return [
        f"slide-{item.position + 1}"
        for item in media
        if item.base is not None and item.base.key is None
    ]
