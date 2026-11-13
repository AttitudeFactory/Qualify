"""Backend access of «Revisar y rehacer una parte» (m-24921083, UI-8). Blocking: the
states run every call with `asyncio.to_thread`.

- `set_liked`: «Me gusta así» / «✓ Lista» on a part (`part_review.set_part_liked`: the
  mark lives on the part's active version, no charge, the parent does not move).
- `read_review`: what the chosen part's panel shows — its versions
  (`part_review.part_versions`), the fields it was made with
  (`part_review.part_edit_fields`: mode, description, effective photos), each version's
  own vista previa signed for the part's tile, and what another version uses of the
  month (the brand's balance, a plain read).
- `inspiration`: the reel the video is inspired by and its account, for its page.
- `use_version`: «Usar esta versión» (`part_review.use_part_version`): the version
  already made comes back and the whole video is joined again; no vista previa used.

Every read and write goes through the backend's own doors, which open `tenant_session`
themselves (RLS). A refusal of the part (`part_review.PartNotReviewable`) reaches the
caller as `NotReviewable`, carrying the backend's text for the owner
(`NOT_REVIEWABLE_TEXTS`); any other exception keeps its type.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from qualify_api.creative import part_review

from .part_review_vm import (
    PartReview,
    PhotoRead,
    VersionRead,
    account_text,
    inspiration_href,
)
from .r2_media import is_r2_key, issue_view_path

logger = logging.getLogger(__name__)


class NotReviewable(ValueError):
    """The part cannot be marked, or that version cannot be used, as it is now (it is
    being made, it moved on, it expired, the version is gone). Nothing was written.
    `text`: the owner's words for it ("" when the backend gave none we know)."""

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.text = text


def _review_module() -> Any:
    """`qualify_api.creative.part_review` (a seam: the tests hand a stand-in)."""
    return part_review


def _refused(module: Any, exc: BaseException) -> NotReviewable | None:
    """`exc` as `NotReviewable` when it is the backend's refusal of the part, with its
    text only when it is one of the backend's own owner texts."""
    refusal = getattr(module, "PartNotReviewable", None)
    if not (isinstance(refusal, type) and isinstance(exc, refusal)):
        return None
    texts = getattr(module, "NOT_REVIEWABLE_TEXTS", {}) or {}
    said = exc.args[0] if exc.args and isinstance(exc.args[0], str) else ""
    return NotReviewable(said if said in texts.values() else "")


def _view(tenant_id: UUID, key: str | None, media_type: str) -> str:
    """A short-lived `/r2media` path for an R2 key of this business ("" otherwise, or
    when no token can be minted: a picture is not worth failing the panel)."""
    if not key or not is_r2_key(key):
        return ""
    try:
        return issue_view_path(tenant_id, key, media_type)
    except Exception as exc:  # noqa: BLE001 — a missing picture must not break the panel
        logger.warning("part review token not issued: %s", type(exc).__name__)
        return ""


def set_liked(tenant_id: UUID, parent_id: UUID, part_index: int, liked: bool) -> bool:
    """«Me gusta así» (`liked` True) or its undoing. Whether the mark changed."""
    module = _review_module()
    try:
        return bool(
            module.set_part_liked(
                tenant_id=tenant_id, parent_id=parent_id, part_index=part_index, liked=liked
            )
        )
    except Exception as exc:
        refused = _refused(module, exc)
        if refused is not None:
            raise refused from exc
        raise


def use_version(
    tenant_id: UUID, parent_id: UUID, part_index: int, version_id: UUID, user_id: UUID
) -> None:
    """«Usar esta versión»: that version is the part's again and the video is joined
    once more. Nothing charged."""
    module = _review_module()
    try:
        module.use_part_version(
            tenant_id=tenant_id,
            parent_id=parent_id,
            part_index=part_index,
            version_id=version_id,
            user_id=user_id,
        )
    except Exception as exc:
        refused = _refused(module, exc)
        if refused is not None:
            raise refused from exc
        raise


def inspiration(tenant_id: UUID, parent_id: UUID) -> tuple[str, str]:
    """The reel the video by parts is inspired by, for its page's «Video de
    inspiración» card (Deivid, 2026-11-13): `(page, account)` — the analysed post's
    public page (`post_url`, https only: the address step 2's «Basado en @… ↗» opens)
    of the FIRST part that comes from a reel, and its account («@thegoldenbalance»:
    `public_reels.handle`, else the one the page names). ("", "") when no part comes
    from a reel or its analysis is gone. Database reads only — never ScrapeCreators;
    the page lives on after the stored copy is purged at 30 days."""
    from qualify_api.creative.part_progress import read_part_progress  # noqa: PLC0415
    from qualify_api.referentes import reel_analysis  # noqa: PLC0415

    progress = read_part_progress(tenant_id=tenant_id, parent_id=parent_id)
    rows = () if progress is None else progress.parts
    analysis_id = next(
        (row.analysis_id for row in rows if getattr(row, "analysis_id", None) is not None),
        None,
    )
    if analysis_id is None:
        return "", ""
    analysis = reel_analysis.get_analysis(tenant_id, analysis_id)
    page = inspiration_href(getattr(analysis, "post_url", "") if analysis else "")
    if not page:
        return "", ""
    try:
        handle = _review_module().reel_account(
            tenant_id=tenant_id,
            network=str(getattr(analysis, "network", "") or ""),
            post_id=str(getattr(analysis, "post_id", "") or ""),
        )
    except Exception as exc:  # noqa: BLE001 — the card still opens the reel
        logger.warning("inspiration account unreadable: %s", type(exc).__name__)
        handle = ""
    return page, account_text(handle, page)


def _quote(
    tenant_id: UUID, brand_id: UUID | None
) -> tuple[int, int, int, str, int, int, int] | None:
    """What another version of the part uses of the month: 1 vista previa against the
    brand's balance (`ContentService.creations_balance`) — the quote's shape of
    `creative_provider.regeneration_creations`. A plain read: never the draft's
    `FOR UPDATE` (`regeneration_price` takes it, and a join holding the part's row made
    the panel wait for ever — live test 2026-11-13). None without a brand, a quota, or
    when unreadable: the service still refuses what it cannot pay."""
    if brand_id is None:
        return None
    from qualify_api.creative.composition import production_content_service  # noqa: PLC0415

    from .creative_vm import renewal_day_label  # noqa: PLC0415

    try:
        balance = production_content_service().creations_balance(
            tenant_id=tenant_id, brand_id=brand_id
        )
    except Exception as exc:  # noqa: BLE001 — a courtesy line, never the charge
        logger.warning("part review quote unreadable: %s", type(exc).__name__)
        return None
    if balance is None:
        return None
    return (
        0,
        balance.left,
        balance.quota,
        renewal_day_label(balance.renews_on),
        1 if balance.preview_quota > 0 else 0,
        balance.previews_left,
        balance.preview_quota,
    )


def read_review(
    tenant_id: UUID, parent_id: UUID, part_index: int, draft_id: UUID | None = None
) -> PartReview:
    """The chosen part's panel, read once: its fields, its versions (each with its own
    vista previa signed, for the part's tile) and what another version uses.
    `draft_id`: the part's own draft (kept for the caller; the quote reads the brand)."""
    del draft_id
    module = _review_module()
    fields = module.part_edit_fields(
        tenant_id=tenant_id, parent_id=parent_id, part_index=part_index
    )
    versions = module.part_versions(tenant_id=tenant_id, parent_id=parent_id, part_index=part_index)
    analysis_id = getattr(fields, "analysis_id", None)
    shots = tuple(getattr(fields, "shot_indexes", ()) or ())
    photo_keys = tuple(getattr(fields, "photo_keys", ()) or ())
    every_key = list(dict.fromkeys([*photo_keys, *(k for v in versions for k in v.photo_keys)]))
    return PartReview(
        mode=str(getattr(fields, "mode", "") or ""),
        description=str(getattr(fields, "description", "") or ""),
        photo_keys=photo_keys,
        versions=tuple(
            VersionRead(
                version_id=str(v.version_id),
                ordinal=int(v.ordinal),
                total=int(v.total),
                current=bool(v.current),
                description=str(v.description or ""),
                photo_keys=tuple(v.photo_keys or ()),
                seconds=float(v.seconds or 0),
                liked=bool(v.liked),
                expired=bool(v.expired),
                video_url="" if v.expired else _view(tenant_id, v.video_key, "video"),
                poster_url="" if v.expired else _view(tenant_id, v.poster_key, "image"),
            )
            for v in versions
        ),
        photos=tuple(PhotoRead(key=k, url=_view(tenant_id, k, "image")) for k in every_key),
        from_reel=analysis_id is not None and bool(shots),
        all_photo_keys=tuple(getattr(fields, "all_photo_keys", ()) or ()),
        quote=_quote(tenant_id, getattr(fields, "brand_id", None)),
    )


__all__ = ["NotReviewable", "inspiration", "read_review", "set_liked", "use_version"]
