"""The avatar block of a Clip (m-25112920, epic m-25026566, ADR 50 amendment
`[PROPUESTO]` of 2026-11-24): the brand's talking avatar enters the owner's own Clip as
one more stretch of its timeline, instead of being a separate video.

Deivid's decisions (2026-11-24), all enforced here or where named:

- **What it is.** A child draft of the Clip (`content_drafts.parent_draft_id`, ADR 44's
  link of migration 0119) of kind `AVATAR_VIDEO` (a human presenter) or
  `ANIMATED_AVATAR_VIDEO` (an animated character), made by the presenter path that
  already exists (`MediaProducer._omnihuman_video`: Seedream draws the presenter, Seed
  Speech reads the owner's script, OmniHuman 1.5 moves the lips). Its brief carries
  `media.clip_avatar_block=True` (server-owned, in `content_briefs.media`: no migration).
  Its `part_index` is only its SLOT under the Clip (1-`AVATAR_BLOCK_SLOTS`, the range and
  the unique index migration 0119 already enforce); it has no `media.part` — it is not a
  part of a video by parts (`service.check_part_link`).
- **How it enters the Clip.** Its kept video (`t/{tenant}/generated/{block}/r{n}/…`) is a
  `SourceSegment` of kind `video` in the Clip's `local` recipe (`place_block`), from 0 to
  its length, at ×1. The local assembly (`video_pipeline.local.produce_local`) asks
  `generated_sources` which of its stretches are blocks: such a stretch must belong to THIS
  Clip and play at ×1 (at any other speed its voice would be silence — m-25049580 keeps a
  stretch's sound only at ×1), and the composed video is marked `ai_generated=True` with
  each block's provenance. Nothing else in the assembly changes.
- **Length.** At most `AVATAR_BLOCK_MAX_SECONDS` (30 s): refused at creation from the
  script's estimate, before any row or spend, and again by the producer from the real
  voice track, before OmniHuman (the expensive call) is ordered.
- **Model.** OmniHuman 1.5 (`AVATAR_BLOCK_REQ_KEY`): the producer refuses a block before
  any spend if the platform's OmniHuman is another one.
- **Quota.** A block takes nothing when it is made: its charge row is written at weight
  0 (`weight_for` → 0), as `create_draft` writes one for every piece — the queue reads
  the generation's reservation from it. Its seconds are counted from the month's video
  when the CLIP is approved (`clip_block_charges`, charged by `ContentService.approve`)
  on the BLOCK's own row, so approving another version of the Clip never charges it
  again. Its creation is refused when the month cannot pay its seconds plus those of
  every uncharged live block of the brand, in any Clip (`NotEnoughCreations`): no paid
  call without quota.
- **Daily cap.** Deivid, 2026-11-24: at most `AVATAR_DAILY_CAP` (3) blocks a day per
  business, its own day (`check_avatar_daily_cap`, modelled on EF-15's local cap);
  every block created counts, approved or not, except one that failed before anything
  was paid. Checked before any row or paid call, under the business's lock.
- **Switches.** `QUALIFY_CLIP_AVATAR_PRESENTER` and `QUALIFY_CLIP_AVATAR_ANIMATED`, off
  everywhere (`.env.example`, `deploy/.env.prod.example`). The server refuses to create —
  or place — a block whose kind is switched off (`ClipAvatarRefused`, code
  `switched_off`), before anything is read or written. With both off no block can exist,
  so nothing else behaves differently: the assembly only looks blocks up for stretches
  under a draft's own generated folder (a generator file the owner chose, ADR 50 P3,
  finds no block and is made as before), and only marks AI what the lookup says is a
  block.
- **Old pieces.** A stand-alone `avatar_video` / `animated_avatar_video` draft is
  untouched: `clip_avatar_block` is False on every stored brief.

Tenant isolation: every read goes through `tenant_session` (RLS); a block of another
business is never found, and a stretch key is checked by `owned_by` before the assembly
reads it. Idempotent: `create_block` takes the caller's `request_key` (the repository's
unique index returns the first draft); placing a block twice is refused.
"""

from __future__ import annotations

import logging
import math
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from qualify_creative.adapters.byteplus_omnihuman import OMNIHUMAN_15
from qualify_creative.creations import own_script_seconds, weight_for
from qualify_creative.enums import (
    AvatarSource,
    ContentFormat,
    ContentKind,
    VideoEngine,
)
from qualify_creative.schemas import (
    DURATIONS_SECONDS,
    SCRIPT_MAX,
    ContentBrief,
    MediaInputs,
    SourceSegment,
)

logger = logging.getLogger(__name__)

#: The two switches (house convention: `1`/`on`/`true` turn a switch on; anything else,
#: or nothing, leaves it off — a typo never turns it on).
PRESENTER_SWITCH = "QUALIFY_CLIP_AVATAR_PRESENTER"
ANIMATED_SWITCH = "QUALIFY_CLIP_AVATAR_ANIMATED"
_ON_VALUES = ("1", "on", "true")

AvatarBlockKind = Literal["presenter", "animated"]
#: Each block kind, its switch and the draft kind it is made as.
BLOCK_SWITCHES: dict[str, str] = {"presenter": PRESENTER_SWITCH, "animated": ANIMATED_SWITCH}
BLOCK_DRAFT_KINDS: dict[str, ContentKind] = {
    "presenter": ContentKind.AVATAR_VIDEO,
    "animated": ContentKind.ANIMATED_AVATAR_VIDEO,
}

#: Deivid, 2026-11-24: a block lasts at most 30 s (OmniHuman 1.5 itself takes 59 s).
AVATAR_BLOCK_MAX_SECONDS = 30
#: Deivid, 2026-11-24: OmniHuman 1.5 — US$0.12 a second in `pricing_data/v9.json`.
AVATAR_BLOCK_REQ_KEY = OMNIHUMAN_15
#: How many blocks a Clip may ever have: migration 0119's `part_index` range (1-6) and
#: its unique `(tenant_id, parent_draft_id, part_index)` index. A Clip lasts 60 s at most,
#: so two 30 s blocks already fill it.
AVATAR_BLOCK_SLOTS = 6
#: Deivid, 2026-11-24: a business creates at most 3 avatar blocks a day (its own day,
#: as the local cap of EF-15). Every block created counts, approved or not; one that
#: failed before anything was paid does not (`ClipAvatarStore.blocks_made_today`).
AVATAR_DAILY_CAP = 3
#: The stable code of that refusal (screens read it, never the text).
AVATAR_DAILY_CAP_CODE = "avatar_daily_cap_reached"
#: Provenance of this module's rules (the block's recipe stretch and the assembly's
#: block record). A change of rule is a new version.
CLIP_AVATAR_VERSION = 1

# -- what the owner reads (Spanish, `qualify-copy-es`; the screen is m-25112921) ---------

DAILY_CAP_TEXT = "Ya creaste 3 avatares hoy. Mañana puedes crear más."
SWITCHED_OFF_TEXT = "Por ahora no puedes agregar este avatar a tu video."
TOO_LONG_TEXT = "Lo que dice el avatar dura más de 30 segundos. Acórtalo y vuelve a intentarlo."
CLIP_NOT_LOCAL_TEXT = "Solo puedes agregar un avatar a un video armado con tus fotos y videos."
CLIP_NOT_READY_TEXT = "Espera a que tu video esté listo para agregarle un avatar."
NO_SLOT_TEXT = "Tu video ya tiene todos los avatares que puede llevar."
NO_BRAND_AVATAR_TEXT = (
    "Tu marca todavía no tiene su avatar. Créalo en tu identidad de marca o describe uno."
)
BLOCK_NOT_READY_TEXT = "El avatar todavía no está listo. Espera un momento y vuelve a intentarlo."
ALREADY_PLACED_TEXT = "Este avatar ya está en tu video."
#: The assembly's refusals (`video_pipeline.local`): a stretch of a block at another
#: speed, or a block of another video.
SPEED_TEXT = (
    "El avatar solo puede ir a velocidad normal, para que se escuche su voz. Quítale la "
    "cámara rápida y vuelve a crear el video."
)
ELSEWHERE_TEXT = "Uno de los avatares es de otro video. Quítalo y vuelve a crear el video."
#: A block that came out longer than 30 s (the voice read slower than estimated):
#: refused by the producer before OmniHuman is ordered.
BLOCK_TOO_LONG_TEXT = (
    "Lo que dice el avatar quedó de más de 30 segundos. Acórtalo y vuelve a intentarlo."
)
#: The platform's OmniHuman is not 1.5: ours to fix, refused before any spend.
BLOCK_MODEL_TEXT = "Por ahora no podemos crear este avatar. Inténtalo más tarde."


class ClipAvatarRefused(ValueError):
    """A block refused before anything was written or paid: a stable `code` for the
    screen and the owner's `owner_message` (never `str(exc)`, which is English)."""

    def __init__(self, code: str, owner_message: str, raw: str = "") -> None:
        super().__init__(raw or code)
        self.code = code
        self.owner_message = owner_message


class AvatarDailyCapReached(ClipAvatarRefused):
    """Today's avatar blocks of this business are spent: nothing read past the count,
    written, charged or paid. `used` today's blocks, `cap` the cap."""

    def __init__(self, *, used: int, cap: int = AVATAR_DAILY_CAP) -> None:
        super().__init__(
            AVATAR_DAILY_CAP_CODE, DAILY_CAP_TEXT, raw=f"{used} avatar blocks today, cap {cap}"
        )
        self.used = used
        self.cap = cap


def check_avatar_daily_cap(store: Any, *, tenant_id: UUID, asking: int = 1) -> None:
    """Refuse `asking` new blocks when they do not fit in today's cap (the model is
    `local_cap.check_local_daily_cap`). A store that cannot count is not capped."""
    counter = getattr(store, "blocks_made_today", None)
    if counter is None or asking < 1:
        return
    used = int(counter(tenant_id=tenant_id))
    if used + asking > AVATAR_DAILY_CAP:
        raise AvatarDailyCapReached(used=used)


def switch_on(value: str | None) -> bool:
    return (value or "").strip().lower() in _ON_VALUES


def block_enabled(kind: str, env: Mapping[str, str] | None = None) -> bool:
    """Whether blocks of `kind` (`presenter` / `animated`) may be created. Read at call
    time (tests and a restart change it); an unknown kind is off."""
    switch = BLOCK_SWITCHES.get(kind)
    if switch is None:
        return False
    source = os.environ if env is None else env
    return switch_on(source.get(switch))


def any_block_enabled(env: Mapping[str, str] | None = None) -> bool:
    return any(block_enabled(kind, env) for kind in BLOCK_SWITCHES)


def refuse_if_off(kind: str, env: Mapping[str, str] | None = None) -> None:
    if not block_enabled(kind, env):
        raise ClipAvatarRefused(
            "switched_off", SWITCHED_OFF_TEXT, raw=f"clip avatar block {kind!r} is off"
        )


def block_kind_of(brief: ContentBrief) -> str | None:
    """`presenter` / `animated` for a block's brief, None for anything else."""
    if not brief.media.clip_avatar_block:
        return None
    for kind, draft_kind in BLOCK_DRAFT_KINDS.items():
        if brief.kind is draft_kind:
            return kind
    return None


def script_seconds(script: str) -> int:
    """How long the owner's script lasts read aloud — the estimate the quota already uses
    for a presenter (`qualify_creative.creations.own_script_seconds`)."""
    return own_script_seconds(len(script.strip()))


def block_duration(seconds: int) -> int:
    """The block brief's `duration_seconds`: the first length the brief accepts
    (`DURATIONS_SECONDS`) that holds the script's estimate, at most 30 s. Only a label —
    the video lasts what the voice lasts."""
    return next(
        (d for d in DURATIONS_SECONDS if seconds <= d <= AVATAR_BLOCK_MAX_SECONDS),
        AVATAR_BLOCK_MAX_SECONDS,
    )


def block_max_seconds(media: MediaInputs, platform_max: float) -> float:
    """The longest voice track OmniHuman is ordered for: a block's 30 s, else the
    platform's own (`MediaProducer._omnihuman_max_seconds`)."""
    if media.clip_avatar_block:
        return min(float(AVATAR_BLOCK_MAX_SECONDS), platform_max)
    return platform_max


def block_model_problem(media: MediaInputs, req_key: str) -> str | None:
    """Why a block cannot be made on the platform's OmniHuman (Deivid: 1.5), or None."""
    if media.clip_avatar_block and req_key != AVATAR_BLOCK_REQ_KEY:
        return f"a clip avatar block runs on {AVATAR_BLOCK_REQ_KEY}, not {req_key}"
    return None


#: The vendors whose output is AI imagery (each adapter's `name`, as
#: `image_assets.provider` keeps it; compared lower-case, some writers capitalize).
AI_PROVIDERS = frozenset({"seedance", "seedream", "omnihuman", "heygen"})


def asset_is_ai(*, provider: Any, params_ai: Any, draft_requires_disclosure: bool) -> bool:
    """Whether one generator asset is AI imagery, from the most specific record there
    is: the asset's own `params.ai_generated` when it wrote one (a local video, a join, a
    final by parts); else its provider when it is a generation vendor; else its draft's
    `requires_ai_disclosure` (recomputed from the media the draft made — a composition
    of ours over a Seedream scene). Never guessed from the key's path."""
    if isinstance(params_ai, bool):
        return params_ai
    if str(provider or "").strip().lower() in AI_PROVIDERS:
        return True
    return draft_requires_disclosure


def is_generated_file(tenant_id: UUID, key: str) -> bool:
    """Whether a stretch's key can be a file the generator made — the keys whose
    provenance is looked up: one kept for one of this business's drafts
    (`media.generated_object_key` / `generated_key`). An owner's upload, Galería file or
    reel window never is (the owner's own, not AI) — and is never looked up."""
    return key.startswith((f"t/{tenant_id}/generated/", f"generated/{tenant_id}/"))


# -- the owner's request ----------------------------------------------------------------


class AvatarBlockRequest(BaseModel):
    """What the editor sends to add a block (m-25112921 builds the screen): its kind, the
    exact words the avatar says, the voice (`"brand"` or a public Seed Speech id; None =
    the platform's default) and who speaks — described (`avatar_prompt`), the owner's
    image of a character (`animated` only, with the rights confirmed) or the brand's own
    avatar from its identity (`use_brand_avatar`, `animated` only)."""

    model_config = ConfigDict(frozen=True)

    kind: AvatarBlockKind
    script: str = Field(min_length=1, max_length=SCRIPT_MAX)
    voice_id: str | None = None
    avatar_prompt: str = ""
    avatar_image_key: str | None = None
    avatar_rights_confirmed: bool = False
    use_brand_avatar: bool = False
    background_key: str | None = None
    product_keys: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _who_speaks(self) -> AvatarBlockRequest:
        if not self.script.strip():
            raise ValueError("a block needs what the avatar says")
        if self.kind == "presenter":
            # a human presenter is always described (`ContentBrief`'s own rule)
            if self.avatar_image_key or self.use_brand_avatar:
                raise ValueError("a presenter block is described, never an uploaded photo")
            if not self.avatar_prompt.strip():
                raise ValueError("a presenter block needs the presenter's description")
        elif self.avatar_image_key and self.use_brand_avatar:
            raise ValueError("an animated block speaks with one character")
        return self


def block_brief(
    clip: ContentBrief, request: AvatarBlockRequest, *, brand_avatar_key: str | None = None
) -> ContentBrief:
    """The block's brief: the Clip's brand, objective and topic; the avatar kind of the
    request on OmniHuman, 9:16 (the Clip's frame), the owner's script read word for word,
    no subtitles of its own (the Clip carries its texts), `clip_avatar_block=True`.
    `brand_avatar_key` is the brand's avatar image when the request asks for it."""
    kind = BLOCK_DRAFT_KINDS[request.kind]
    if request.kind == "presenter":
        source: AvatarSource | None = AvatarSource.AI
        image_key: str | None = None
        rights = False
    elif request.use_brand_avatar:
        if not brand_avatar_key:
            raise ClipAvatarRefused("no_brand_avatar", NO_BRAND_AVATAR_TEXT)
        # the brand's own avatar, drawn for it by Qualify (`brand_avatar`): its image
        source, image_key, rights = AvatarSource.IMAGE, brand_avatar_key, True
    elif request.avatar_image_key:
        source, image_key = AvatarSource.IMAGE, request.avatar_image_key
        rights = request.avatar_rights_confirmed
    else:
        source, image_key, rights = AvatarSource.AI, None, False
    media = MediaInputs.model_validate(
        {
            "duration_seconds": block_duration(script_seconds(request.script)),
            "voice_id": request.voice_id,
            "avatar_source": source,
            "avatar_prompt": request.avatar_prompt.strip(),
            "avatar_image_key": image_key,
            "avatar_rights_confirmed": rights,
            "own_script": request.script.strip(),
            "subtitles": False,
            "video_engine": VideoEngine.OMNIHUMAN,
            "background_key": request.background_key,
            "product_keys": request.product_keys,
            "clip_avatar_block": True,
        }
    )
    return ContentBrief.model_validate(
        {
            # the Clip's route AND its source photo (a `from_upload` route needs it; the
            # presenter path never reads it)
            **clip.model_dump(exclude={"media", "kind", "format", "video_plan"}),
            "kind": kind,
            "format": ContentFormat.REELS_9_16,
            # the Clip's own route, as a stand-alone avatar video takes the form's: the
            # brand's image policy is checked against it (`prepare_new_generation`); an
            # avatar kind is «hecho con IA» whatever the route says
            "variants_requested": 1,
            "media": media,
        }
    )


# -- what the database tells -------------------------------------------------------------


@dataclass(frozen=True)
class ClipRow:
    """The Clip a block is added to, as stored."""

    id: UUID
    brand_id: UUID
    brief_id: UUID
    status: str
    revision: int
    parent_draft_id: UUID | None
    purged: bool = False


@dataclass(frozen=True)
class BlockRow:
    """One child of a Clip that is an avatar block (removed ones included: their slot
    stays taken)."""

    id: UUID
    slot: int
    status: str
    kind: str
    script_seconds: int
    removed: bool = False


@dataclass(frozen=True)
class BlockVideo:
    """A block's kept video (its active version's)."""

    asset_id: UUID
    object_key: str
    seconds: float


@dataclass(frozen=True)
class GeneratedSource:
    """A stretch's file that the generator made for one of this business's drafts (its
    `image_assets` row), with what the local assembly needs of it: whether it is AI
    imagery (`ai_generated`, `asset_is_ai`) and whether it is an avatar block of a Clip
    (`block`: then `kind` and `clip_id`, the block's Clip). What the Clip's asset records
    of it is `provenance` / `ai_provenance` (rule 6 — the source's own asset and usage
    rows keep its cost and prompt)."""

    object_key: str
    block_id: UUID
    clip_id: UUID | None
    kind: str
    revision: int
    asset_id: UUID
    provider: str
    model_id: str
    model_revision: str | None
    seconds: float
    pipeline_version: str
    #: An avatar block of a Clip (`media.clip_avatar_block`): `block_id` is the block's
    #: draft. False: any other piece of the generator (`block_id` is its draft).
    block: bool = True
    #: AI imagery, read from what made it (`asset_is_ai`).
    ai_generated: bool = True
    #: A block whose seconds a Clip's approval already took (its own charge row, at its
    #: revision, has videos): never charged again, whatever Clip version is approved.
    charged: bool = False

    def ai_provenance(self, segment: int) -> dict[str, Any]:
        """The Clip asset's record of an AI stretch: the label's evidence."""
        return {
            "segment": segment,
            "draft_id": str(self.block_id),
            "asset_id": str(self.asset_id),
            "provider": self.provider,
            "model_id": self.model_id,
            "avatar_block": self.block,
        }

    def provenance(self, segment: int) -> dict[str, Any]:
        return {
            "segment": segment,
            "block_id": str(self.block_id),
            "kind": self.kind,
            "block_revision": self.revision,
            "asset_id": str(self.asset_id),
            "provider": self.provider,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "seconds": round(self.seconds, 3),
            "pipeline_version": self.pipeline_version,
            "clip_avatar_version": CLIP_AVATAR_VERSION,
        }


class ClipAvatarStore(Protocol):
    def clip(self, *, tenant_id: UUID, clip_id: UUID) -> ClipRow | None: ...

    def blocks_of(self, *, tenant_id: UUID, clip_id: UUID) -> tuple[BlockRow, ...]: ...

    def block_video(self, *, tenant_id: UUID, block_id: UUID) -> BlockVideo | None: ...

    def generated_sources(
        self, *, tenant_id: UUID, keys: Sequence[str]
    ) -> dict[str, GeneratedSource]: ...

    def pending_block_seconds(self, *, tenant_id: UUID, brand_id: UUID) -> tuple[int, int]: ...

    def blocks_made_today(self, *, tenant_id: UUID) -> int: ...


def _block_kind(kind: str) -> str:
    return "presenter" if kind == ContentKind.AVATAR_VIDEO.value else "animated"


class PostgresClipAvatarStore:
    """The blocks as Postgres keeps them — every read through `tenant_session` (RLS)."""

    def clip(self, *, tenant_id: UUID, clip_id: UUID) -> ClipRow | None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            row = session.execute(
                text("""
                SELECT id, brand_id, brief_id, status, revision, parent_draft_id,
                       media_purged_at IS NOT NULL AS purged
                FROM content_drafts WHERE id = :d
            """),
                {"d": clip_id},
            ).first()
        if row is None:
            return None
        return ClipRow(
            id=row.id,
            brand_id=row.brand_id,
            brief_id=row.brief_id,
            status=str(row.status),
            revision=int(row.revision),
            parent_draft_id=row.parent_draft_id,
            purged=bool(row.purged),
        )

    def blocks_of(self, *, tenant_id: UUID, clip_id: UUID) -> tuple[BlockRow, ...]:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            rows = session.execute(
                text("""
                SELECT d.id, d.part_index, d.status, b.kind,
                       COALESCE(b.media->>'own_script', '') AS script,
                       d.part_removed_at IS NOT NULL AS removed
                FROM content_drafts d JOIN content_briefs b ON b.id = d.brief_id
                WHERE d.parent_draft_id = :c
                  AND COALESCE((b.media->>'clip_avatar_block')::boolean, false)
                ORDER BY d.part_index
            """),
                {"c": clip_id},
            ).all()
        return tuple(
            BlockRow(
                id=row.id,
                slot=int(row.part_index),
                status=str(row.status),
                kind=_block_kind(str(row.kind)),
                script_seconds=script_seconds(str(row.script)),
                removed=bool(row.removed),
            )
            for row in rows
        )

    def pending_block_seconds(self, *, tenant_id: UUID, brand_id: UUID) -> tuple[int, int]:
        """(blocks, script seconds) of the brand's live blocks whose seconds no
        approval took yet — in every Clip of the brand: what the month already owes. A
        block that failed or was taken out owes nothing."""
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            rows = session.execute(
                text("""
                SELECT COALESCE(b.media->>'own_script', '') AS script
                FROM content_drafts d JOIN content_briefs b ON b.id = d.brief_id
                WHERE d.brand_id = :brand AND d.parent_draft_id IS NOT NULL
                  AND d.part_removed_at IS NULL AND d.status <> 'failed'
                  AND COALESCE((b.media->>'clip_avatar_block')::boolean, false)
                  AND NOT EXISTS (SELECT 1 FROM creation_charges c
                                  WHERE c.draft_id = d.id AND c.videos > 0)
            """),
                {"brand": brand_id},
            ).all()
        return len(rows), sum(script_seconds(str(row.script)) for row in rows)

    def blocks_made_today(self, *, tenant_id: UUID) -> int:
        """The business's blocks created today (its own day, `tenants.timezone`, empty
        → UTC — the day of `local_cap`), approved or not; one that failed BEFORE anything
        was paid (no usage row with a cost) does not count. Under a unit of work it first
        takes this business's transaction lock, so two blocks asked at once are counted
        one after the other."""
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('clip_avatar_cap'), hashtext(:t))"),
                {"t": str(tenant_id)},
            )
            counted = session.scalar(
                text("""
                WITH z AS (
                  SELECT COALESCE(NULLIF(
                    (SELECT timezone FROM tenants WHERE id = :tenant), ''), 'UTC') AS zone
                )
                SELECT count(*) FROM content_drafts d
                JOIN content_briefs b ON b.id = d.brief_id, z
                WHERE COALESCE((b.media->>'clip_avatar_block')::boolean, false)
                  AND d.created_at
                      >= (date_trunc('day', now() AT TIME ZONE z.zone) AT TIME ZONE z.zone)
                  AND NOT (d.status = 'failed' AND NOT EXISTS (
                        SELECT 1 FROM creative_usage_events u
                        WHERE u.draft_id = d.id AND u.cost_usd > 0))
            """),
                {"tenant": tenant_id},
            )
            return int(counted or 0)

    def block_video(self, *, tenant_id: UUID, block_id: UUID) -> BlockVideo | None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            row = session.execute(
                text("""
                SELECT a.id, a.object_key, a.params->>'duration_seconds' AS seconds
                FROM image_assets a JOIN content_drafts d ON d.id = a.draft_id
                WHERE a.draft_id = :b AND a.media_type = 'video' AND a.object_key IS NOT NULL
                  AND a.version_id IS NOT DISTINCT FROM d.active_version_id
                ORDER BY a.position, a.created_at DESC
                LIMIT 1
            """),
                {"b": block_id},
            ).first()
        if row is None or not row.seconds:
            return None
        return BlockVideo(
            asset_id=row.id, object_key=str(row.object_key), seconds=float(row.seconds)
        )

    def generated_sources(
        self, *, tenant_id: UUID, keys: Sequence[str]
    ) -> dict[str, GeneratedSource]:
        """Every key of `keys` the generator made for this business (its asset rows),
        with whether it is AI imagery and whether it is an avatar block. A key with
        several rows (versions) is AI when any of them is."""
        candidates = sorted({key for key in keys if is_generated_file(tenant_id, key)})
        if not candidates:
            return {}
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import bindparam, text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            rows = session.execute(
                text("""
                SELECT a.object_key, a.id AS asset_id, a.provider, a.model_id, a.media_type,
                       a.params->>'model_revision' AS model_revision,
                       a.params->>'duration_seconds' AS seconds,
                       a.params->'ai_generated' AS params_ai,
                       d.id AS block_id, d.parent_draft_id, d.revision, d.pipeline_version,
                       d.requires_ai_disclosure, b.kind,
                       COALESCE((b.media->>'clip_avatar_block')::boolean, false) AS block,
                       EXISTS (SELECT 1 FROM creation_charges c
                               WHERE c.draft_id = d.id AND c.revision = d.revision
                                 AND c.videos > 0) AS charged
                FROM image_assets a
                JOIN content_drafts d ON d.id = a.draft_id
                JOIN content_briefs b ON b.id = d.brief_id
                WHERE a.object_key IN :keys
                ORDER BY a.created_at
            """).bindparams(bindparam("keys", expanding=True)),
                {"keys": candidates},
            ).all()
        found: dict[str, GeneratedSource] = {}
        for row in rows:
            key = str(row.object_key)
            ai = asset_is_ai(
                provider=row.provider,
                params_ai=row.params_ai,
                draft_requires_disclosure=bool(row.requires_ai_disclosure),
            )
            block = bool(row.block) and row.media_type == "video"
            before = found.get(key)
            if before is not None:
                # several rows of one file (versions): AI when any is, a block when any is
                ai = ai or before.ai_generated
                if before.block and not block:
                    found[key] = replace(before, ai_generated=ai)
                    continue
                block = block or before.block
            found[key] = GeneratedSource(
                object_key=key,
                block_id=row.block_id,
                clip_id=row.parent_draft_id,
                kind=_block_kind(str(row.kind)) if block else str(row.kind),
                revision=int(row.revision),
                asset_id=row.asset_id,
                provider=str(row.provider or ""),
                model_id=str(row.model_id or ""),
                model_revision=row.model_revision,
                seconds=float(row.seconds or 0),
                pipeline_version=str(row.pipeline_version or ""),
                block=block,
                ai_generated=ai,
                charged=bool(row.charged),
            )
        return found


def db_generated_sources(tenant_id: UUID, keys: Sequence[str]) -> dict[str, GeneratedSource]:
    """The production resolver the media producer hands the local assembly."""
    return PostgresClipAvatarStore().generated_sources(tenant_id=tenant_id, keys=keys)


# -- the assembly's rule (pure) ------------------------------------------------------------


@dataclass(frozen=True)
class BlockStretch:
    index: int
    segment: SourceSegment
    source: GeneratedSource


def block_stretches(
    segments: Sequence[SourceSegment], sources: Mapping[str, GeneratedSource]
) -> tuple[BlockStretch, ...]:
    """The recipe's stretches that are avatar blocks' videos, in order."""
    return tuple(
        BlockStretch(index=index, segment=segment, source=sources[segment.key])
        for index, segment in enumerate(segments)
        if segment.kind == "video" and segment.key in sources and sources[segment.key].block
    )


def ai_stretches(
    segments: Sequence[SourceSegment], sources: Mapping[str, GeneratedSource]
) -> tuple[BlockStretch, ...]:
    """The recipe's stretches (videos or photos) whose file is AI imagery — Seedance,
    Seedream, OmniHuman…, read from the asset that made it —, in order. Deivid,
    2026-11-24: one is enough for the composed video's «hecho con IA», with the avatar
    switches on or off."""
    return tuple(
        BlockStretch(index=index, segment=segment, source=sources[segment.key])
        for index, segment in enumerate(segments)
        if segment.key in sources and sources[segment.key].ai_generated
    )


def stretch_problem(stretch: BlockStretch, clip_id: UUID) -> tuple[str, str] | None:
    """Why a block's stretch cannot be assembled into `clip_id`: `(code, owner text)`,
    or None. A block belongs to its own Clip, and plays at ×1 so its voice is heard."""
    if stretch.source.clip_id != clip_id:
        return "avatar_block_elsewhere", ELSEWHERE_TEXT
    if stretch.segment.speed != 1.0:
        return "avatar_block_speed", SPEED_TEXT
    return None


def charged_seconds(stretches: Sequence[BlockStretch]) -> int:
    """The month's video seconds approving a Clip with these blocks uses: each block's
    stretch as it plays (×1), rounded up to the whole second."""
    return sum(math.ceil(s.segment.output_seconds - 1e-9) for s in stretches)


def block_segment(video: BlockVideo) -> SourceSegment:
    """The block's video as a stretch of the Clip's recipe: the whole of it, at ×1."""
    return SourceSegment(
        key=video.object_key, start_s=0.0, end_s=round(video.seconds, 3), speed=1.0
    )


# -- the service -------------------------------------------------------------------------


def _default_brand_avatar_key(tenant_id: UUID, brand_id: UUID) -> str | None:
    from qualify_api.creative.brand_avatar import AvatarStatus, load_brand_avatar  # noqa: PLC0415

    avatar = load_brand_avatar(tenant_id, brand_id)
    if avatar is None or avatar.status is not AvatarStatus.READY or not avatar.object_key:
        return None
    return avatar.object_key


class ClipAvatarService:
    """Adds an avatar block to a Clip (`create_block`), puts its video in the Clip's
    recipe (`place_block`) and says what approving the Clip charges for its blocks
    (`block_charge`). Built over the `ContentService` that owns drafts and quota."""

    def __init__(
        self,
        content: Any,
        *,
        store: ClipAvatarStore | None = None,
        env: Mapping[str, str] | None = None,
        brand_avatar_key: Callable[[UUID, UUID], str | None] | None = None,
    ) -> None:
        self._content = content
        self._store = store or PostgresClipAvatarStore()
        self._env = env
        self._brand_avatar_key = brand_avatar_key or _default_brand_avatar_key

    # -- create ---------------------------------------------------------------------

    def create_block(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        clip_id: UUID,
        request: AvatarBlockRequest,
        request_key: UUID | None = None,
    ) -> UUID:
        """The block's draft, born under the Clip and dispatched — its id. Refused with
        nothing written nor paid (`ClipAvatarRefused`, `NotEnoughCreations`,
        `BrandNotReady`, `RouteBlockedByPolicy`, `UnknownDraft`) when its kind is switched
        off, the script lasts over 30 s, the Clip is not an own-video Clip ready to show,
        it has no free slot or the month cannot pay the block's seconds."""
        from qualify_api.creative.service import DuplicateDraftRequest  # noqa: PLC0415

        refuse_if_off(request.kind, self._env)  # before anything is read
        seconds = script_seconds(request.script)
        if seconds > AVATAR_BLOCK_MAX_SECONDS:
            raise ClipAvatarRefused(
                "too_long",
                TOO_LONG_TEXT,
                raw=f"script of ~{seconds}s > {AVATAR_BLOCK_MAX_SECONDS}s",
            )
        repo = self._content.repository
        if request_key is not None:
            existing = repo.draft_id_for_request(tenant_id=tenant_id, request_key=request_key)
            if existing is not None:
                return existing
        clip, clip_brief = self._clip(tenant_id, clip_id)
        if clip.status not in _CLIP_READY:
            raise ClipAvatarRefused("clip_not_ready", CLIP_NOT_READY_TEXT)
        blocks = self._store.blocks_of(tenant_id=tenant_id, clip_id=clip_id)
        self._refuse_without_quota(tenant_id, clip.brand_id, seconds)
        avatar_key = (
            self._brand_avatar_key(tenant_id, clip.brand_id) if request.use_brand_avatar else None
        )
        brief = block_brief(clip_brief, request, brand_avatar_key=avatar_key)
        stamped, voice_version, pipeline_version = self._content.prepare_new_generation(
            tenant_id=tenant_id, brand_id=clip.brand_id, brief=brief
        )
        if not stamped.media.clip_avatar_block:  # the producer's stamp never drops it
            raise RuntimeError("a block's brief lost its mark while being prepared")
        keyed: dict[str, UUID] = {"request_key": request_key} if request_key else {}
        taken = {block.slot for block in blocks}
        slots = [slot for slot in range(1, AVATAR_BLOCK_SLOTS + 1) if slot not in taken]
        if not slots:
            raise ClipAvatarRefused("no_slot", NO_SLOT_TEXT)
        try:
            draft_id = self._made_in_one_go(
                tenant_id,
                lambda: self._insert_and_charge(
                    tenant_id,
                    user_id,
                    clip,
                    stamped,
                    voice_version,
                    pipeline_version,
                    slots,
                    keyed,
                ),
            )
        except DuplicateDraftRequest as duplicate:
            return duplicate.draft_id
        logger.info(
            "clip %s: avatar block %s (%s, ~%ss) created", clip_id, draft_id, request.kind, seconds
        )
        return draft_id

    def _made_in_one_go(self, tenant_id: UUID, make: Callable[[], UUID]) -> UUID:
        """The daily cap's count, the block's rows and its charge row in ONE
        transaction on Postgres (the count's lock serializes the business's blocks, so
        two asked at once never both take the last place, nor the same slot); the
        dispatch only after it commits. Anything refused writes nothing."""
        from qualify_api.creative.service import PostgresContentRepository  # noqa: PLC0415

        dispatcher = self._content.dispatcher
        if isinstance(self._content.repository, PostgresContentRepository):
            from qualify_shared.db.session import (  # noqa: PLC0415
                after_tenant_commit,
                tenant_unit_of_work,
            )

            with tenant_unit_of_work(tenant_id):
                check_avatar_daily_cap(self._store, tenant_id=tenant_id)
                draft_id = make()
                if dispatcher is not None:
                    after_tenant_commit(
                        tenant_id,
                        lambda: dispatcher.dispatch_generation(
                            tenant_id=tenant_id, draft_id=draft_id
                        ),
                    )
            return draft_id
        check_avatar_daily_cap(self._store, tenant_id=tenant_id)
        draft_id = make()
        if dispatcher is not None:
            dispatcher.dispatch_generation(tenant_id=tenant_id, draft_id=draft_id)
        return draft_id

    def _insert_and_charge(
        self,
        tenant_id: UUID,
        user_id: UUID,
        clip: ClipRow,
        brief: ContentBrief,
        voice_version: int,
        pipeline_version: str,
        slots: list[int],
        keyed: dict[str, UUID],
    ) -> UUID:
        """The block's draft and, as `create_draft` writes for every piece, its charge
        row of revision 1 — weight 0 (`weight_for` of a block): nothing is taken from
        the month, but the queue finds the generation's reservation
        (`PipelineExecutor._validate_reservation`) and refuses none of its paid calls."""
        draft_id = self._insert(
            tenant_id, user_id, clip.id, brief, voice_version, pipeline_version, slots, keyed
        )
        creations = self._content.creations
        if creations is not None:
            creations.charge(
                tenant_id=tenant_id,
                brand_id=clip.brand_id,
                draft_id=draft_id,
                revision=1,
                price=weight_for(brief),
            )
        return draft_id

    def _insert(
        self,
        tenant_id: UUID,
        user_id: UUID,
        clip_id: UUID,
        brief: ContentBrief,
        voice_version: int,
        pipeline_version: str,
        slots: list[int],
        keyed: dict[str, UUID],
    ) -> UUID:
        """Into the first free slot; a slot taken meanwhile by a concurrent block (the
        unique index of 0119, outside the business's lock) moves to the next one. Any
        other integrity error (a foreign key, a check) goes up as it is."""
        from sqlalchemy.exc import IntegrityError  # noqa: PLC0415

        last: IntegrityError | None = None
        for slot in slots:
            try:
                return self._content.repository.insert_brief_and_draft(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    brief=brief,
                    voice_profile_version=voice_version,
                    pipeline_version=pipeline_version,
                    parent_draft_id=clip_id,
                    part_index=slot,
                    **keyed,
                )
            except IntegrityError as exc:
                if not _slot_taken(exc):
                    raise
                last = exc
        assert last is not None
        raise ClipAvatarRefused("no_slot", NO_SLOT_TEXT, raw=str(last)) from last

    def _clip(self, tenant_id: UUID, clip_id: UUID) -> tuple[ClipRow, ContentBrief]:
        """The Clip and its brief: a top-level `local` Clip of this business (RLS), its
        files not purged — else refused."""
        from qualify_api.creative.service import UnknownDraft  # noqa: PLC0415
        from qualify_api.creative.video_pipeline.local import is_local_recipe  # noqa: PLC0415

        clip = self._store.clip(tenant_id=tenant_id, clip_id=clip_id)
        if clip is None:
            raise UnknownDraft(str(clip_id))
        brief = self._content.repository.get_brief(tenant_id=tenant_id, brief_id=clip.brief_id)
        if brief is None:
            raise UnknownDraft(str(clip_id))
        if clip.parent_draft_id is not None or not is_local_recipe(brief):
            # a part of a video by parts, a Seedance clip, an avatar block itself
            raise ClipAvatarRefused("clip_not_local", CLIP_NOT_LOCAL_TEXT)
        if clip.purged:
            raise ClipAvatarRefused("clip_not_ready", CLIP_NOT_READY_TEXT, raw="purged")
        return clip, brief

    def _refuse_without_quota(self, tenant_id: UUID, brand_id: UUID, seconds: int) -> None:
        """No paid call without quota: the month must be able to pay, at approval, this
        block and EVERY live block of the brand not charged yet — in any of its Clips —,
        so blocks are never piled up past the balance."""
        creations = self._content.creations
        if creations is None:
            return
        pending, pending_seconds = self._store.pending_block_seconds(
            tenant_id=tenant_id, brand_id=brand_id
        )
        balance = creations.balance(tenant_id=tenant_id, brand_id=brand_id)
        if balance.video_in_seconds:
            needed = seconds + pending_seconds
        else:
            needed = 1 + pending
        short = balance.video_shortfall(needed)
        if short is not None:
            raise short

    # -- place --------------------------------------------------------------------------

    def place_block(
        self, *, tenant_id: UUID, user_id: UUID, clip_id: UUID, block_id: UUID, at: int
    ) -> UUID:
        """Put the block's video in the Clip's recipe at stretch `at` (clamped to the
        recipe) and make the Clip's next version with it — its new brief id. The version
        shown stays until the new one comes out (a failure keeps it). Refused with
        nothing written when the kind is switched off, the block is not this Clip's or
        not made yet, it is already in the recipe, or the recipe would break a rule
        (`RecipeRefused`: over 60 s, too many stretches)."""
        from qualify_api.creative.service import UnknownDraft  # noqa: PLC0415
        from qualify_api.creative.video_pipeline.recipe import (  # noqa: PLC0415
            RecipeRefused,
            recipe_of,
            validate_recipe,
        )

        if not any_block_enabled(self._env):  # both off: refused before any read
            raise ClipAvatarRefused("switched_off", SWITCHED_OFF_TEXT)
        block = next(
            (
                b
                for b in self._store.blocks_of(tenant_id=tenant_id, clip_id=clip_id)
                if b.id == block_id and not b.removed
            ),
            None,
        )
        if block is None:
            raise UnknownDraft(str(block_id))
        refuse_if_off(block.kind, self._env)
        clip, brief = self._clip(tenant_id, clip_id)
        if clip.status not in _CLIP_READY:
            raise ClipAvatarRefused("clip_not_ready", CLIP_NOT_READY_TEXT)
        from qualify_api.creative.fsm import GENERATED  # noqa: PLC0415

        video = self._store.block_video(tenant_id=tenant_id, block_id=block_id)
        if block.status != GENERATED or video is None:
            raise ClipAvatarRefused("block_not_ready", BLOCK_NOT_READY_TEXT)
        segments = list(brief.media.segments)
        if any(segment.key == video.object_key for segment in segments):
            raise ClipAvatarRefused("already_placed", ALREADY_PLACED_TEXT)
        position = max(0, min(at, len(segments)))
        segments.insert(position, block_segment(video))
        fresh = ContentBrief.model_validate(
            {
                **brief.model_dump(),
                "media": {**brief.media.model_dump(), "segments": tuple(segments)},
            }
        )
        problems = validate_recipe(recipe_of(fresh), video_by_parts=False, tenant_id=tenant_id)
        if problems:
            raise RecipeRefused(problems)
        return self._new_version(tenant_id, user_id, clip, fresh)

    def _new_version(
        self, tenant_id: UUID, user_id: UUID, clip: ClipRow, brief: ContentBrief
    ) -> UUID:
        """The Clip's next version from `brief`, as «Pedir otra versión» makes one (the
        local cap, the charge row of 0, the revision, `drafting`, the dispatch after the
        commit) — without scoring it as a rejection of the version the owner sees."""
        from qualify_api.creative.fsm import (  # noqa: PLC0415
            GENERATED,
            DraftTrigger,
            apply_transition,
        )
        from qualify_api.creative.local_cap import check_local_daily_cap  # noqa: PLC0415
        from qualify_api.creative.service import (  # noqa: PLC0415
            BRAND_APPLIED_PIPELINE_VERSION,
            PIPELINE_VERSION,
            PostgresContentRepository,
        )

        content, repo = self._content, self._content.repository
        status = clip.status
        if status == GENERATED:
            status = apply_transition(status, DraftTrigger.REJECT)
        new_status = apply_transition(status, DraftTrigger.REGENERATE)
        version = getattr(
            getattr(content, "_media", None), "new_generation_pipeline_version", PIPELINE_VERSION
        )

        def write() -> UUID:
            check_local_daily_cap(repo, tenant_id=tenant_id)
            creations = content.creations
            if creations is not None:
                creations.charge(
                    tenant_id=tenant_id,
                    brand_id=clip.brand_id,
                    draft_id=clip.id,
                    revision=clip.revision + 1,
                    price=weight_for(brief, redo=True),
                )
            brief_id = repo.replace_brief(
                tenant_id=tenant_id, draft_id=clip.id, user_id=user_id, brief=brief
            )
            if version == BRAND_APPLIED_PIPELINE_VERSION:
                repo.bump_revision(tenant_id=tenant_id, draft_id=clip.id, pipeline_version=version)
            else:
                repo.bump_revision(tenant_id=tenant_id, draft_id=clip.id)
            repo.update_status(
                tenant_id=tenant_id, draft_id=clip.id, new_status=new_status, failure_reason=None
            )
            return brief_id

        dispatch = (
            (lambda: content.dispatcher.dispatch_generation(tenant_id=tenant_id, draft_id=clip.id))
            if content.dispatcher is not None
            else (lambda: None)
        )
        if isinstance(repo, PostgresContentRepository):
            from qualify_shared.db.session import (  # noqa: PLC0415
                after_tenant_commit,
                tenant_unit_of_work,
            )
            from sqlalchemy import text  # noqa: PLC0415

            with tenant_unit_of_work(tenant_id) as session:
                locked = session.execute(
                    text("SELECT status, revision FROM content_drafts WHERE id = :d FOR UPDATE"),
                    {"d": clip.id},
                ).first()
                if locked is None or (str(locked.status), int(locked.revision)) != (
                    clip.status,
                    clip.revision,
                ):
                    # another version started meanwhile: the owner tries again on it
                    raise ClipAvatarRefused("clip_not_ready", CLIP_NOT_READY_TEXT, raw="moved")
                brief_id = write()
                after_tenant_commit(tenant_id, dispatch)
            return brief_id
        brief_id = write()
        dispatch()
        return brief_id

    # -- approval ------------------------------------------------------------------------

    def block_charge(self, *, tenant_id: UUID, clip_id: UUID, brief: ContentBrief) -> int:
        """The month's video seconds approving the Clip still uses for its blocks."""
        charges = clip_block_charges(
            tenant_id=tenant_id,
            clip_id=clip_id,
            brief=brief,
            sources=lambda keys: self._store.generated_sources(tenant_id=tenant_id, keys=keys),
        )
        return sum(charge.seconds for charge in charges)


#: A Clip a block can be added to: shown to the owner, its copy written (a block carries
#: its Clip's text, `ContentService._inherited_copy`) and not approved yet.
_CLIP_READY = frozenset({"generated", "rejected"})


def clip_block_charges(
    *,
    tenant_id: UUID,
    clip_id: UUID,
    brief: ContentBrief,
    sources: Callable[[Sequence[str]], Mapping[str, GeneratedSource]],
) -> tuple[Any, ...]:
    """What approving the Clip `clip_id` charges for the blocks its recipe plays: one
    `VideoCharge` per block of its own whose seconds no approval took yet, on the
    BLOCK's own charge row (its draft and revision) — so approving another version of
    the Clip never charges a block twice (the row's unique key, and `charged`). Empty
    for anything that is not a `local` Clip with blocks of its own (a block of another
    video is refused by the assembly, never charged here). Only keys a block can have
    are looked up (`is_generated_file`)."""
    from qualify_api.creative.creations import VideoCharge  # noqa: PLC0415
    from qualify_api.creative.video_pipeline.local import is_local_recipe  # noqa: PLC0415

    if not is_local_recipe(brief):
        return ()
    segments = brief.media.segments
    keys = [s.key for s in segments if s.kind == "video" and is_generated_file(tenant_id, s.key)]
    if not keys:
        return ()
    charges: dict[UUID, Any] = {}
    for stretch in block_stretches(segments, sources(keys)):
        source = stretch.source
        if source.clip_id != clip_id or source.charged or source.block_id in charges:
            continue
        charges[source.block_id] = VideoCharge(
            draft_id=source.block_id,
            revision=source.revision,
            videos=1,
            seconds=charged_seconds((stretch,)),
        )
    return tuple(charges.values())


def _slot_taken(exc: BaseException) -> bool:
    """A unique violation (SQLSTATE 23505): the slot of 0119's unique index was taken.
    A foreign key, a check or anything else is not."""
    orig = getattr(exc, "orig", None)
    code = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    return code == "23505"


__all__ = [
    "ANIMATED_SWITCH",
    "AVATAR_BLOCK_MAX_SECONDS",
    "AVATAR_BLOCK_REQ_KEY",
    "AVATAR_BLOCK_SLOTS",
    "AvatarBlockRequest",
    "BlockRow",
    "GeneratedSource",
    "BlockStretch",
    "BlockVideo",
    "CLIP_AVATAR_VERSION",
    "ClipAvatarRefused",
    "ClipAvatarService",
    "ClipAvatarStore",
    "ClipRow",
    "PRESENTER_SWITCH",
    "PostgresClipAvatarStore",
    "any_block_enabled",
    "block_brief",
    "block_duration",
    "block_enabled",
    "block_kind_of",
    "block_max_seconds",
    "block_model_problem",
    "block_segment",
    "block_stretches",
    "AI_PROVIDERS",
    "ai_stretches",
    "asset_is_ai",
    "charged_seconds",
    "AVATAR_DAILY_CAP",
    "AVATAR_DAILY_CAP_CODE",
    "AvatarDailyCapReached",
    "check_avatar_daily_cap",
    "clip_block_charges",
    "db_generated_sources",
    "is_generated_file",
    "refuse_if_off",
    "script_seconds",
    "stretch_problem",
]
