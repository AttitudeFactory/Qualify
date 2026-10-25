"""The owner's review of the Brand Kit proposed from their account (m-24852199, PB-5 of
the epic m-24852192, docs/epica-prellenado-brand-kit-alta.md §2.5 and §3 PB-5).

`brand_prefill` (PB-3) writes a PROPOSAL under `brand_kit_details.connect["prefill"]` and
leaves alone what generation reads: the top-level `connect` keys and the `profile`
document (`brand_context.build_context`) and `brand_kits.palette_rgb`. This module is
the other half — what the owner's three buttons do with it:

- **«Aprobar»** (`approve_prefill`): the proposal becomes the Brand Kit's own answers —
  its `connect` keys over the top-level `connect`, its `profile` as the `profile`
  document, its colours merged into `brand_kits.palette_rgb` — and the proposal is
  marked `approved`, its provenance kept. The profile picture that becomes the logo is
  the R2 copy the run kept (`profile.pic_key`, m-24852537), checked to sit under this
  brand's own prefix (`approved_profile`); the network's CDN link, which expires in
  days, is never promoted.
- **«Cambiar»** (`change_prefill`): marked `changed` and handed back for the wizard to
  open its steps with it; nothing is promoted here (the wizard saves the owner's own
  answers as they walk, as for any draft).
- **«Empezar de cero»** (`discard_prefill`): marked `discarded`; nothing is promoted.

Each one reads the details row under `FOR UPDATE` and acts only on a proposal still
`proposed` on an unfinished kit, so a double tap or a second tab is a no-op, never a
second promotion. If the owner already saved answers of their own (`owner_started`,
re-checked under the lock), nothing is promoted over them: the proposal is marked
`superseded` and the button answers done=False. A decided proposal is never put back
to `proposed` by a re-run (`brand_prefill._write_status`, `DECIDED_STATES`). Nothing
is ever deleted: status, proposal, usage and provenance stay in the document, with who
decided and when.

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

from collections.abc import Callable, Iterable, Mapping
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

from qualify_api.creative import kept_pictures, logo_palette
from qualify_api.creative.brand_kit_store import PREFILL_KEY
from qualify_api.creative.brand_service import _apply_kit, kit_from_row
from qualify_api.creative.models import BrandKit as BrandKitRow
from qualify_api.creative.models import BrandKitAsset as AssetRow
from qualify_api.creative.models import BrandKitDetails as DetailsRow
from qualify_api.privacy import mask_phones_in

#: The proposal's review states (`brand_prefill.STATE_PROPOSED` is the first one).
STATE_PROPOSED = "proposed"
STATE_APPROVED = "approved"
STATE_CHANGED = "changed"
STATE_DISCARDED = "discarded"
#: The owner had already started their own Brand Kit when the proposal was decided (or
#: landed): it is never promoted over their answers (review of PB-5, 2026-10-24).
STATE_SUPERSEDED = "superseded"
#: Decided: a re-run of the prefill never puts these back to `proposed`
#: (`brand_prefill._write_status`).
DECIDED_STATES = frozenset({STATE_APPROVED, STATE_CHANGED, STATE_DISCARDED, STATE_SUPERSEDED})

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
#: The `connect` answers only the owner gives (the wizard's own; `country_code` is left
#: out: the five steps prefill it from the signup's country, `BrandMinimalState.enter`).
_OWNER_CONNECT_KEYS = (
    "network",
    "username",
    "sector",
    "rubro_text",
    "city",
    "hashtags",
    "account_kind",
    "has_maps",
)
#: Progress flags only an owner's choice sets («No tengo redes», «Usar mi foto de perfil»).
_OWNER_PROGRESS_FLAGS = ("started_without_socials", "logo_from_profile")
#: The logo brief's answers (the avatar's reserved key is not the owner's).
_OWNER_BRIEF_KEYS = ("style", "feeling", "references")
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
    a finished kit, no document) and nothing was written — or the owner had already
    started, and the proposal was only marked `superseded`. Either way the screen
    reloads from the database."""

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


def is_decided(document: Any) -> bool:
    """A proposal document the owner (or their own answers) already decided."""
    return isinstance(document, Mapping) and document.get("state") in DECIDED_STATES


def owner_started(
    connect: Mapping[str, Any] | None,
    profile: Mapping[str, Any] | None,
    logo_brief: Mapping[str, Any] | None,
    *,
    kit_answers: Iterable[str] = (),
    has_files: bool = False,
) -> bool:
    """Has the owner saved anything of their own Brand Kit? A typed answer of the
    connect flow, a read account, a logo brief, a file of their brandboard, or a kit
    answer (`kit_answers`: positioning, audience, palette, examples). An empty draft —
    the wizard saves one as soon as Tus redes is shown — is not a start."""
    connect = connect or {}
    if has_files:
        return True
    if any(connect.get(key) for key in _OWNER_CONNECT_KEYS):
        return True
    progress = _progress(connect) or {}
    if any(progress.get(flag) for flag in _OWNER_PROGRESS_FLAGS):
        return True
    if str((profile or {}).get("username") or "").strip():
        return True
    if any(str((logo_brief or {}).get(key) or "").strip() for key in _OWNER_BRIEF_KEYS):
        return True
    return any(str(answer or "").strip() for answer in kit_answers)


def _waiting_proposal(connect: Mapping[str, Any] | None, *, has_kit: bool) -> dict[str, Any] | None:
    """The proposal still `proposed` on an unfinished kit (started or not)."""
    document = _prefill(connect)
    if document is None or kit_finished(has_kit, _progress(connect)):
        return None
    if document.get("status") != _STATUS_OK or document.get("state") != STATE_PROPOSED:
        return None
    return _proposal(document)


def review_of(
    connect: Mapping[str, Any] | None, *, has_kit: bool, started: bool = False
) -> PrefillReview:
    """The notice for the stored `connect` document (see the module docstring).
    `started` (`owner_started`): the owner already saved answers of their own — a
    proposal is then never offered over them."""
    document = _prefill(connect)
    if document is None or kit_finished(has_kit, _progress(connect)):
        return PrefillReview()
    username = str(document.get("username") or "").lstrip("@")
    proposal = _waiting_proposal(connect, has_kit=has_kit)
    if proposal is not None and started:
        return PrefillReview()
    if proposal is not None:
        username = str(proposal["connect"].get("username") or username).lstrip("@")
        return PrefillReview(Notice.PROPOSAL, username, proposal)
    if document.get("state"):  # a proposal already decided
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
            out[key] = mask_phones_in(proposal["connect"][key])
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


def approved_profile(tenant_id: UUID, brand_id: UUID, profile: Mapping[str, Any]) -> dict[str, Any]:
    """The proposal's `profile` as it is promoted (m-24852537): its picture is the R2
    copy (`pic_key`) when it is a kept picture of THIS brand, and the CDN link (`pic`)
    is cleared then — it expires in days. A key that is not this brand's is dropped,
    never trusted. A proposal written before the copy existed (no `pic_key`) is promoted
    as it was. Its texts are masked again (m-24854323): a proposal written before the
    masking must not carry a full phone number into what generation reads."""
    out = mask_phones_in(dict(profile))
    key = out.get("pic_key")
    if not key:
        out.pop("pic_key", None)
        out.pop("pic_content_type", None)
        return out
    if kept_pictures.is_kept_key(tenant_id, brand_id, key):
        out["pic"] = ""
        return out
    out.pop("pic_key", None)
    out.pop("pic_content_type", None)
    return out


def picture_key(proposal: Mapping[str, Any] | None) -> tuple[UUID, str, str] | None:
    """`(tenant id, R2 key, content type)` of the proposal's kept profile picture, or
    None — what the review card shows (through a `/r2media` view of that tenant). The
    tenant is read from the key itself (`kept_pictures.owner_of`) and the key re-checked
    as that brand's kept picture; the proposal came from the caller's own tenant-scoped
    read, and the view door re-checks the prefix once more."""
    profile = (proposal or {}).get("profile")
    if not isinstance(profile, Mapping):
        return None
    key = profile.get("pic_key")
    owner = kept_pictures.owner_of(key)
    if owner is None or not kept_pictures.is_kept_key(owner[0], owner[1], key):
        return None
    return owner[0], str(key), str(profile.get("pic_content_type") or "image/jpeg")


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


def _has_files(session: Session, brand_id: UUID) -> bool:
    found = session.scalar(select(AssetRow.brand_id).where(AssetRow.brand_id == brand_id).limit(1))
    return found is not None


def _kit_answers(kit: BrandKitRow | None) -> list[str]:
    if kit is None:
        return []
    return [
        kit.positioning or "",
        kit.audience or "",
        ",".join(kit.palette_rgb or ()),
        "\n".join(str(e) for e in kit.do_examples or ()),
    ]


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
        proposal = _waiting_proposal(connect, has_kit=kit is not None)
        if proposal is None:
            return PrefillDecision(False)
        now = datetime.now(UTC)
        started = owner_started(
            connect,
            row.profile,
            row.logo_brief,
            kit_answers=_kit_answers(kit),
            has_files=_has_files(session, brand_id),
        )
        if started:
            # re-checked under the lock: the owner's own answers win, the proposal is
            # kept (with its provenance) as superseded, and nothing is promoted
            state = STATE_SUPERSEDED
            proposal = {}
        if state == STATE_APPROVED:
            row.connect = approved_connect(connect, proposal, user_id, now)
            row.profile = approved_profile(tenant_id, brand_id, proposal["profile"])
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
        return PrefillDecision(not started, proposal)


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
    "STATE_SUPERSEDED",
    "DECIDED_STATES",
    "STATE_PROPOSED",
    "Notice",
    "PrefillDecision",
    "PrefillReview",
    "approve_prefill",
    "approved_connect",
    "approved_profile",
    "change_prefill",
    "discard_prefill",
    "is_decided",
    "owner_started",
    "kit_finished",
    "merged_palette",
    "palette_colours",
    "picture_key",
    "review_of",
]
