"""The owner's review of the Brand Kit proposed from their account (m-24852199, PB-5 of
the epic m-24852192, docs/epica-prellenado-brand-kit-alta.md §2.5 and §3 PB-5).

`brand_prefill` (PB-3) writes a PROPOSAL under `brand_kit_details.connect["prefill"]` and
leaves alone what generation reads: the top-level `connect` keys and the `profile`
document (`brand_context.build_context`) and `brand_kits.palette_rgb`. This module is
the other half — what the owner's three buttons do with it:

- **«Aprobar»** (`approve_prefill`): the proposal becomes the Brand Kit's own answers —
  its `connect` keys over the top-level `connect`, its `profile` as the `profile`
  document, its colours merged into `brand_kits.palette_rgb` — and the proposal is
  marked `approved`, its provenance kept.
- **«Cambiar»** (`change_prefill`): marked `changed` and handed back for the wizard to
  open its steps with it; nothing is promoted here (the wizard saves the owner's own
  answers as they walk, as for any draft).
- **«Empezar de cero»** (`discard_prefill`): marked `discarded`; nothing is promoted.

Each one reads the details row under `FOR UPDATE` and acts only on a proposal still
`proposed` on an unfinished kit, so a double tap or a second tab is a no-op, never a
second promotion. Nothing is ever deleted: status, proposal, usage and provenance stay
in the document, with who decided and when.

**What "pending" means** (`review_of`), decided for PB-5:

- `PROPOSAL` — the run ended `ok`, the proposal is there, it is still `proposed`, and
  the kit is not finished. Only this shows the proposal and the three buttons.
- `PRIVATE` — the run read the account and it is private (`private_account`).
- `UNREADABLE` — every other failed run: `not_found`, `read_failed`, `cap_reached`
  and `account_taken`. The owner cannot act on the difference (our credit cap, a typo
  in the Alta, a vendor outage), and naming `account_taken` would tell them that
  another business holds that account — so they all get «No pudimos leer…».
- `NONE` — no proposal document, a finished kit, or a proposal already decided.

The failure notices are information only: they change nothing stored, and the wizard
opens empty as for any new brand.

All database access goes through `qualify_shared.db.session.tenant_session(tenant_id)`,
so RLS scopes every read and write to the caller's tenant.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from qualify_creative.schemas import BrandKit, ToneAxes
from qualify_shared.db.session import tenant_session
from sqlalchemy import select
from sqlalchemy.orm import Session

from qualify_api.creative import logo_palette
from qualify_api.creative.brand_kit_store import PREFILL_KEY
from qualify_api.creative.brand_service import _apply_kit, kit_from_row
from qualify_api.creative.models import BrandKit as BrandKitRow
from qualify_api.creative.models import BrandKitDetails as DetailsRow

#: The proposal's review states (`brand_prefill.STATE_PROPOSED` is the first one).
STATE_PROPOSED = "proposed"
STATE_APPROVED = "approved"
STATE_CHANGED = "changed"
STATE_DISCARDED = "discarded"

#: The run outcomes (`brand_prefill.PrefillOutcome` values) and the notice each shows.
_STATUS_OK = "ok"
_STATUS_PRIVATE = "private_account"
_STATUS_UNREADABLE = frozenset({"not_found", "read_failed", "cap_reached", "account_taken"})

#: The `connect` keys a proposal carries — the connect flow's own answers
#: (`Qualify/brand_finish._connect_document`); nothing else of `connect` is touched.
PROMOTED_CONNECT_KEYS = (
    "network",
    "username",
    "sector",
    "rubro_text",
    "country_code",
    "city",
    "hashtags",
)
#: The five-step flow's key in `connect.progress` (`Qualify/brand_minimal_vm.MINIMAL_FLOW`):
#: an approved proposal resumes there, on the first step that still misses data.
RESUME_FLOW = "minimo"
#: The wizard's position inside `connect` (`Qualify/brand_finish.PROGRESS_KEY`).
PROGRESS_KEY = "progress"
#: A kit row created by an approval carries only the colours; the tone starts at the
#: middle of every axis, as the wizard's own first save (`creative_state.TONE_DEFAULT`).
_TONE_DEFAULT = 50


class Notice(StrEnum):
    NONE = ""
    PROPOSAL = "proposal"
    PRIVATE = "private"
    UNREADABLE = "unreadable"


@dataclass(frozen=True)
class PrefillReview:
    """What the Brand Kit screen shows about the proposal."""

    notice: Notice = Notice.NONE
    #: The account the run read, without the «@» (for «…@{usuario}…»).
    username: str = ""
    #: `{"connect": …, "profile": …, "palette": …|None}` — only with `PROPOSAL`.
    proposal: dict[str, Any] = field(default_factory=dict)

    @property
    def pending(self) -> bool:
        return self.notice is Notice.PROPOSAL


@dataclass(frozen=True)
class PrefillDecision:
    """What a button did. `done` False: there was no pending proposal (already decided,
    a finished kit, no document) and nothing was written."""

    done: bool
    #: The proposal as it was decided, for the screen to show it in the wizard.
    proposal: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------------------
# Pure rules
# --------------------------------------------------------------------------------------


def kit_finished(has_kit: bool, progress: Mapping[str, Any] | None) -> bool:
    """`Qualify/brand_finish.kit_status`'s rule: a kit row and no unfinished progress."""
    return has_kit and (progress or {}).get("completed") is not False


def _prefill(connect: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    raw = (connect or {}).get(PREFILL_KEY)
    return raw if isinstance(raw, Mapping) else None


def _proposal(document: Mapping[str, Any]) -> dict[str, Any] | None:
    raw = document.get("proposal")
    if not isinstance(raw, Mapping):
        return None
    connect = raw.get("connect")
    profile = raw.get("profile")
    if not isinstance(connect, Mapping) or not isinstance(profile, Mapping):
        return None
    palette = raw.get("palette")
    return {
        "connect": dict(connect),
        "profile": dict(profile),
        "palette": dict(palette) if isinstance(palette, Mapping) else None,
    }


def _progress(connect: Mapping[str, Any] | None) -> dict[str, Any] | None:
    raw = (connect or {}).get(PROGRESS_KEY)
    return dict(raw) if isinstance(raw, Mapping) else None


def _pending_proposal(connect: Mapping[str, Any] | None, *, has_kit: bool) -> dict[str, Any] | None:
    document = _prefill(connect)
    if document is None or kit_finished(has_kit, _progress(connect)):
        return None
    if document.get("status") != _STATUS_OK or document.get("state") != STATE_PROPOSED:
        return None
    return _proposal(document)


def review_of(connect: Mapping[str, Any] | None, *, has_kit: bool) -> PrefillReview:
    """The notice for the stored `connect` document (see the module docstring)."""
    document = _prefill(connect)
    if document is None or kit_finished(has_kit, _progress(connect)):
        return PrefillReview()
    username = str(document.get("username") or "").lstrip("@")
    proposal = _pending_proposal(connect, has_kit=has_kit)
    if proposal is not None:
        username = str(proposal["connect"].get("username") or username).lstrip("@")
        return PrefillReview(Notice.PROPOSAL, username, proposal)
    if document.get("state"):  # a proposal already approved, changed or discarded
        return PrefillReview()
    status = document.get("status")
    if status == _STATUS_PRIVATE:
        return PrefillReview(Notice.PRIVATE, username)
    if status in _STATUS_UNREADABLE:
        return PrefillReview(Notice.UNREADABLE, username)
    return PrefillReview()


def palette_colours(proposal: Mapping[str, Any]) -> list[str]:
    """The colours the proposal's profile picture gave ([] without a real picture)."""
    palette = proposal.get("palette")
    if not isinstance(palette, Mapping):
        return []
    colours = palette.get("logo_colors")
    if isinstance(colours, list) and colours:
        return [str(c) for c in colours if str(c).strip()]
    text = str(palette.get("palette") or "")
    return [c.strip() for c in text.split(",") if c.strip()]


def decided(
    document: Mapping[str, Any], state: str, user_id: UUID | None, now: datetime
) -> dict[str, Any]:
    """The proposal document with its decision; everything else in it as it was."""
    return {
        **document,
        "state": state,
        "reviewed_at": now.isoformat(),
        "reviewed_by": str(user_id) if user_id else None,
    }


def approved_connect(
    connect: Mapping[str, Any], proposal: Mapping[str, Any], user_id: UUID | None, now: datetime
) -> dict[str, Any]:
    """`connect` after «Aprobar»: the proposal's answers over the top-level keys, the
    proposal marked approved, and the five-step flow's progress (unfinished — the owner
    still has the steps the proposal cannot answer: what makes them different, who
    buys, how they talk)."""
    out = dict(connect)
    for key in PROMOTED_CONNECT_KEYS:
        if key in proposal["connect"]:
            out[key] = proposal["connect"][key]
    progress = _progress(connect) or {}
    progress.setdefault("flow", RESUME_FLOW)
    progress["completed"] = False
    if palette_colours(proposal):
        # the picture's colours are the palette: the picture is the logo, as
        # «Usar mi foto de perfil» does in the wizard
        progress["logo_from_profile"] = True
        progress["profile_pic_is_real"] = True
    out[PROGRESS_KEY] = progress
    out[PREFILL_KEY] = decided(connect[PREFILL_KEY], STATE_APPROVED, user_id, now)
    return out


def merged_palette(stored: list[str] | tuple[str, ...] | None, colours: list[str]) -> list[str]:
    """The kit's palette with the proposal's colours added after the ones already there
    (`logo_palette.merge_into_palette`: no duplicates, nothing hand-picked removed)."""
    merged = logo_palette.merge_into_palette(",".join(stored or ()), [], colours)
    return [c for c in merged.split(",") if c]


# --------------------------------------------------------------------------------------
# The three buttons
# --------------------------------------------------------------------------------------

SessionFactory = Callable[[UUID], AbstractContextManager[Session]]


def _kit_row(session: Session, brand_id: UUID) -> BrandKitRow | None:
    return session.scalar(select(BrandKitRow).where(BrandKitRow.brand_id == brand_id))


def _set_palette(
    session: Session, tenant_id: UUID, brand_id: UUID, kit: BrandKitRow | None, colours: list[str]
) -> None:
    """`brand_kits.palette_rgb` ← the proposal's colours, in the same transaction as the
    documents. A brand with no kit row yet gets one, as the wizard's first save makes:
    the colours, empty answers and the middle tone (the progress written alongside keeps
    it unfinished, so it never counts as a finished kit)."""
    if kit is None:
        model = BrandKit(
            brand_id=brand_id,
            positioning="",
            audience="",
            tone_axes=ToneAxes(
                formal_casual=_TONE_DEFAULT,
                sober_enthusiastic=_TONE_DEFAULT,
                technical_plain=_TONE_DEFAULT,
                brief_elaborate=_TONE_DEFAULT,
            ),
            palette_rgb=tuple(colours),
        )
        kit = BrandKitRow(tenant_id=tenant_id, brand_id=brand_id, language=model.language)
        session.add(kit)
    else:
        model = kit_from_row(kit).model_copy(
            update={"palette_rgb": tuple(merged_palette(kit.palette_rgb, colours))}
        )
    _apply_kit(kit, model)
    kit.updated_at = datetime.now(UTC)


def _decide(
    tenant_id: UUID,
    brand_id: UUID,
    user_id: UUID | None,
    state: str,
    session_factory: SessionFactory,
) -> PrefillDecision:
    with session_factory(tenant_id) as session:
        row = session.get(DetailsRow, brand_id, with_for_update=True)
        if row is None:
            return PrefillDecision(False)
        connect = dict(row.connect or {})
        kit = _kit_row(session, brand_id)
        proposal = _pending_proposal(connect, has_kit=kit is not None)
        if proposal is None:
            return PrefillDecision(False)
        now = datetime.now(UTC)
        if state == STATE_APPROVED:
            row.connect = approved_connect(connect, proposal, user_id, now)
            row.profile = dict(proposal["profile"])
            colours = palette_colours(proposal)
            if colours:
                _set_palette(session, tenant_id, brand_id, kit, colours)
        else:
            row.connect = {
                **connect,
                PREFILL_KEY: decided(connect[PREFILL_KEY], state, user_id, now),
            }
        row.updated_by = user_id
        row.updated_at = now
        session.flush()
        return PrefillDecision(True, proposal)


def approve_prefill(
    tenant_id: UUID,
    brand_id: UUID,
    user_id: UUID | None,
    *,
    session_factory: SessionFactory = tenant_session,
) -> PrefillDecision:
    """«Aprobar»: promote the pending proposal into what generation reads (one
    transaction) and mark it approved. Blocking: run it in a thread from an event loop."""
    return _decide(tenant_id, brand_id, user_id, STATE_APPROVED, session_factory)


def change_prefill(
    tenant_id: UUID,
    brand_id: UUID,
    user_id: UUID | None,
    *,
    session_factory: SessionFactory = tenant_session,
) -> PrefillDecision:
    """«Cambiar»: mark the pending proposal `changed` and return it for the wizard.
    Nothing is promoted."""
    return _decide(tenant_id, brand_id, user_id, STATE_CHANGED, session_factory)


def discard_prefill(
    tenant_id: UUID,
    brand_id: UUID,
    user_id: UUID | None,
    *,
    session_factory: SessionFactory = tenant_session,
) -> PrefillDecision:
    """«Empezar de cero»: mark the pending proposal `discarded`. Nothing is promoted;
    the proposal and its provenance stay in the document."""
    return _decide(tenant_id, brand_id, user_id, STATE_DISCARDED, session_factory)


__all__ = [
    "PROMOTED_CONNECT_KEYS",
    "RESUME_FLOW",
    "STATE_APPROVED",
    "STATE_CHANGED",
    "STATE_DISCARDED",
    "STATE_PROPOSED",
    "Notice",
    "PrefillDecision",
    "PrefillReview",
    "approve_prefill",
    "approved_connect",
    "change_prefill",
    "discard_prefill",
    "kit_finished",
    "merged_palette",
    "palette_colours",
    "review_of",
]
