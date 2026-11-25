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
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from qualify_creative.adapters.byteplus_omnihuman import OMNIHUMAN_15
from qualify_creative.creations import CHARS_PER_SECOND, own_script_seconds, weight_for
from qualify_creative.enums import (
    AvatarSource,
    ContentFormat,
    ContentKind,
    VideoEngine,
)
from qualify_creative.schemas import (
    CUT_EFFECT_ID,
    DURATIONS_SECONDS,
    LOCAL_TOTAL_MAX_S,
    LOCAL_TOTAL_MIN_S,
    SCRIPT_MAX,
    SEGMENTS_MAX,
    ClipAvatarSlot,
    ContentBrief,
    MediaInputs,
    SourceSegment,
)

from qualify_api.creative.heavy_video import LocalVideoWait

logger = logging.getLogger(__name__)

#: The two switches (house convention: `1`/`on`/`true` turn a switch on; anything else,
#: or nothing, leaves it off — a typo never turns it on).
#: NEVER turned on before PR 2 of m-25119867: until then a Clip whose avatar block of its
#: first «Crear» fails waits forever (no «Intentar de nuevo», «Quitar avatar» nor the 72 h
#: limit yet). Said next to them in `.env.example` and `deploy/.env.prod.example` too.
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

DAILY_CAP_TEXT = (
    f"Ya creaste {AVATAR_DAILY_CAP} avatares hoy. Mañana puedes crear más. "
    "Tu video queda guardado como está."
)
SWITCHED_OFF_TEXT = "Este tipo de avatar todavía no está disponible. Tu video queda como está."
#: How many short sentences fit in a block: 30 s × `CHARS_PER_SECOND` (15) = 450
#: characters read aloud; a short sentence is about 60 characters (10-12 words), so
#: 450 // 60 = 7.
SHORT_SENTENCE_CHARS = 60
SENTENCES_PER_BLOCK = int(AVATAR_BLOCK_MAX_SECONDS * CHARS_PER_SECOND) // SHORT_SENTENCE_CHARS
TOO_LONG_TEXT = (
    "Lo que dice el avatar dura más de 30 segundos. Déjalo en unas "
    f"{SENTENCES_PER_BLOCK} frases cortas y vuelve a intentarlo."
)
CLIP_NOT_LOCAL_TEXT = "Solo puedes agregar un avatar a un video armado con tus fotos y videos."
CLIP_NOT_READY_TEXT = "Espera a que tu video esté listo para agregarle un avatar."
NO_SLOT_TEXT = "Tu video ya tiene el máximo de avatares. Si quieres otro, quita uno."
NO_BRAND_AVATAR_TEXT = (
    "Tu marca todavía no tiene su avatar. Créalo en Tu marca, o describe aquí cómo "
    "quieres que se vea."
)
BLOCK_NOT_READY_TEXT = "El avatar todavía no está listo. Espera un momento y vuelve a intentarlo."
ALREADY_PLACED_TEXT = "Este avatar ya está en tu video."
#: The assembly's refusals (`video_pipeline.local`): a stretch of a block at another
#: speed, or a block of another video.
SPEED_TEXT = (
    "El avatar tiene que ir en velocidad Normal para que se escuche su voz. Ponle "
    "Velocidad: Normal a esa parte y vuelve a crear el video."
)
ELSEWHERE_TEXT = "Uno de los avatares no pertenece a este video. Quítalo y agrégalo de nuevo."
#: A block that came out longer than 30 s (the voice read slower than estimated):
#: refused by the producer before OmniHuman is ordered. The presenter and the voice were
#: already paid, so the block still counts for today's cap (Deivid's rule).
BLOCK_TOO_LONG_TEXT = (
    "Al leerlo en voz alta, lo que dice el avatar pasó de 30 segundos. Acórtalo un poco y "
    f"vuelve a intentarlo. Este intento cuenta para tus {AVATAR_DAILY_CAP} avatares de hoy."
)
#: The platform's OmniHuman is not 1.5: ours to fix, refused before any spend.
BLOCK_MODEL_TEXT = (
    "Por ahora no podemos crear este avatar. Inténtalo más tarde. No se gastó nada de tu plan."
)

# -- option B (m-25119867): the avatar chosen at the Clip's first «Crear» -----------------
# The contract is `docs/contrato-avatar-primer-crear.md` §1; the screen is m-25112921.

#: At most this many blocks in one «Crear» (the daily cap: more could never be made).
BLOCKS_PER_CREATE = AVATAR_DAILY_CAP
#: The daily cap's words at the first «Crear», ADR 50 §9 exactly: there is no video yet.
FIRST_CREATE_DAILY_CAP_TEXT = (
    f"Ya creaste {AVATAR_DAILY_CAP} avatares hoy. Mañana puedes crear más."
)
FIRST_CREATE_SWITCHED_OFF_TEXT = (
    "Este tipo de avatar todavía no está disponible. Quítalo para crear tu video."
)
TOO_MANY_BLOCKS_TEXT = (
    f"Un video puede tener hasta {BLOCKS_PER_CREATE} avatares. Quita los que sobren."
)
#: The owner's stretches and the avatars together pass `SEGMENTS_MAX` (8).
TOO_MANY_SEGMENTS_TEXT = (
    f"Tu video puede tener hasta {SEGMENTS_MAX} entre fotos, videos y avatares. "
    "Quita alguno y vuelve a crear tu video."
)
NEEDS_OWN_MEDIA_TEXT = "Agrega al menos 3 segundos de tus fotos o videos para acompañar al avatar."
FILE_NOT_OWNED_TEXT = "No pudimos usar una de las imágenes del avatar. Súbela de nuevo."
#: `clip_wait`'s words (`ClipWait.owner_text`).
WAITING_ONE_TEXT = (
    "Estamos creando tu avatar. Puede tardar varios minutos. Puedes salir: tu video te "
    "espera en Por aprobar."
)
WAITING_MANY_TEXT = (
    "Estamos creando tus avatares. Puede tardar varios minutos. Puedes salir: tu video te "
    "espera en Por aprobar."
)
#: PR 1 of m-25119867 has no «Intentar de nuevo» / «Quitar avatar» yet: the words never
#: promise a button the screen cannot show (the PR 2 wording is in the contract §1.2).
BLOCK_FAILED_STATE_TEXT = (
    "Uno de tus avatares no se pudo crear. Tu video espera. Pronto podrás intentarlo de "
    "nuevo o quitarlo."
)
ASSEMBLING_WITH_BLOCKS_TEXT = "Tus avatares están listos. Estamos armando tu video."
ASSEMBLING_TEXT = "Estamos armando tu video."
READY_TEXT = "Tu video está listo. Revísalo y apruébalo."
#: Ready and already approved (or scheduled, or published): nothing left to ask.
READY_DONE_TEXT = "Tu video está listo."
#: A block's own words when it failed without a detail of its own (no buttons yet, PR 1).
BLOCK_TIMEOUT_TEXT = (
    "Tu avatar tardó demasiado y no se pudo crear. Pronto podrás intentarlo de nuevo o quitarlo."
)
BLOCK_FAILED_TEXT = "Tu avatar no se pudo crear. Pronto podrás intentarlo de nuevo o quitarlo."
#: A block that, at its real length, makes the Clip pass 60 s (`clip_too_long`). The
#: owner cannot edit the Clip's stretches while it waits (`drafting` has no EDIT edge),
#: so the words only ask about the avatar.
CLIP_TOO_LONG_TEXT = (
    "Con tu avatar, el video pasa de 60 segundos. Acorta lo que dice el avatar o quítalo."
)


def daily_left_text(left: int, asking: int) -> str:
    """The cap's words when fewer blocks are left today (`left`, at least 1) than the
    «Crear» asks for (`asking`): how many there are room for, and how many to take out."""
    extra = max(1, asking - left)
    return (
        f"Hoy solo puedes crear {_avatars(left)} más. Quita {_avatars(extra)} para crear tu video."
    )


def _avatars(count: int) -> str:
    return "1 avatar" if count == 1 else f"{count} avatares"


class ClipAvatarRefused(ValueError):
    """A block refused before anything was written or paid: a stable `code` for the
    screen and the owner's `owner_message` (never `str(exc)`, which is English).
    `block`: at the first «Crear», the refused block's place in the list (from 0)."""

    def __init__(
        self, code: str, owner_message: str, raw: str = "", *, block: int | None = None
    ) -> None:
        super().__init__(raw or code)
        self.code = code
        self.owner_message = owner_message
        self.block = block


class AvatarDailyCapReached(ClipAvatarRefused):
    """Today's avatar blocks of this business are spent: nothing read past the count,
    written, charged or paid. `used` today's blocks, `cap` the cap, `asking` how many
    the refused request wanted."""

    def __init__(
        self,
        *,
        used: int,
        cap: int = AVATAR_DAILY_CAP,
        asking: int = 1,
        owner_message: str = DAILY_CAP_TEXT,
    ) -> None:
        super().__init__(
            AVATAR_DAILY_CAP_CODE,
            owner_message,
            raw=f"{used} avatar blocks today, cap {cap}, asking {asking}",
        )
        self.used = used
        self.cap = cap
        self.asking = asking


def check_avatar_daily_cap(
    store: Any, *, tenant_id: UUID, asking: int = 1, first_create: bool = False
) -> None:
    """Refuse `asking` new blocks when they do not fit in today's cap (the model is
    `local_cap.check_local_daily_cap`). A store that cannot count is not capped.
    `first_create` (m-25119867): the words of the Clip's first «Crear», where there is
    no video yet — §9's own sentence when nothing is left, else how many are."""
    counter = getattr(store, "blocks_made_today", None)
    if counter is None or asking < 1:
        return
    used = int(counter(tenant_id=tenant_id))
    if used + asking <= AVATAR_DAILY_CAP:
        return
    left = max(0, AVATAR_DAILY_CAP - used)
    if not first_create:
        raise AvatarDailyCapReached(used=used, asking=asking)
    words = FIRST_CREATE_DAILY_CAP_TEXT if left == 0 else daily_left_text(left, asking)
    raise AvatarDailyCapReached(used=used, asking=asking, owner_message=words)


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
    #: m-25119867: what the owner reads when the Clip failed (`failure_detail`).
    failure_detail: str | None = None


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
    #: m-25119867: why it failed (`failure_reason`) and the owner's words for it.
    failure_reason: str | None = None
    failure_detail: str | None = None


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
    #: False: no asset row says what made this file (`ai_stretches`' fail-safe): its
    #: `provider` says why it counts as AI (`unknown_generated`, `brand_avatar`).
    recorded: bool = True
    #: A block whose seconds a Clip's approval already took (its own charge row, at its
    #: revision, has videos): never charged again, whatever Clip version is approved.
    charged: bool = False

    def ai_provenance(self, segment: int) -> dict[str, Any]:
        """The Clip asset's record of an AI stretch: the label's evidence."""
        if not self.recorded:
            return {"segment": segment, "provenance": self.provider, "object_key": self.object_key}
        return {
            "segment": segment,
            "provenance": "asset",
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
                       media_purged_at IS NOT NULL AS purged, failure_detail
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
            failure_detail=row.failure_detail,
        )

    def blocks_of(self, *, tenant_id: UUID, clip_id: UUID) -> tuple[BlockRow, ...]:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            rows = session.execute(
                text("""
                SELECT d.id, d.part_index, d.status, b.kind,
                       COALESCE(b.media->>'own_script', '') AS script,
                       d.part_removed_at IS NOT NULL AS removed,
                       d.failure_reason, d.failure_detail
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
                failure_reason=row.failure_reason,
                failure_detail=row.failure_detail,
            )
            for row in rows
        )

    def pending_block_seconds(self, *, tenant_id: UUID, brand_id: UUID) -> tuple[int, int]:
        """(blocks, script seconds) of the brand's live blocks whose seconds no
        approval took yet, whose Clip is not approved yet — in every Clip of the brand,
        whatever month it was made in (a block made on the 31st and approved on the 1st
        still owes). A block of a Clip already approved (charged then, or never placed:
        never charged) owes nothing, nor does one that failed or was taken out; an old
        one leaves with its Clip's approval or its retention.

        m-25119867 (P6, Deivid 2026-11-25): nor does a block whose Clip FAILED — a failed
        Clip is never approved, so its blocks would hold the month until the retention.
        Read from the Clip's status, so it holds from the moment it fails."""
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            rows = session.execute(
                text("""
                SELECT COALESCE(b.media->>'own_script', '') AS script
                FROM content_drafts d
                JOIN content_briefs b ON b.id = d.brief_id
                JOIN content_drafts p ON p.tenant_id = d.tenant_id AND p.id = d.parent_draft_id
                WHERE d.brand_id = :brand
                  AND d.part_removed_at IS NULL AND d.status <> 'failed'
                  AND COALESCE((b.media->>'clip_avatar_block')::boolean, false)
                  AND p.status NOT IN ('approved', 'staged', 'published', 'failed')
                  AND p.media_purged_at IS NULL AND d.media_purged_at IS NULL
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
    segments: Sequence[SourceSegment],
    sources: Mapping[str, GeneratedSource],
    *,
    tenant_id: UUID | None = None,
) -> tuple[BlockStretch, ...]:
    """The recipe's stretches (videos or photos) whose file is AI imagery, in order.
    Deivid, 2026-11-24: one is enough for the composed video's «hecho con IA», with the
    avatar switches on or off. The label FAILS SAFE (review of 66850d75):

    - a file of the generator with an asset row: what the asset says (`asset_is_ai`);
    - a file of the generator with NO row (a Seedance 480p preview whose row the final
      replaced, a poster, a Seedream presenter, a checkpoint): AI, recorded as
      `unknown_generated` — failing the Clip would be worse for the owner;
    - the brand's avatar (`t/{t}/brand/{b}/avatar/…`, drawn by Seedream): AI.

    Anything else `owned_by` accepts is the owner's own: uploads, the Galería (photos and
    videos the business uploaded — the Galería holds no generated piece), the brand's
    logos and files, the normalized copies of the owner's videos, reel windows."""
    found: list[BlockStretch] = []
    for index, segment in enumerate(segments):
        source = sources.get(segment.key)
        if source is None and tenant_id is not None:
            if is_generated_file(tenant_id, segment.key):
                source = _unrecorded(segment.key, UNKNOWN_GENERATED)
            elif is_brand_avatar_file(tenant_id, segment.key):
                source = _unrecorded(segment.key, BRAND_AVATAR)
        if source is not None and source.ai_generated:
            found.append(BlockStretch(index=index, segment=segment, source=source))
    return tuple(found)


#: `ai_sources` provenance of an AI stretch with no asset row to read.
UNKNOWN_GENERATED = "unknown_generated"
BRAND_AVATAR = "brand_avatar"


def is_brand_avatar_file(tenant_id: UUID, key: str) -> bool:
    """The brand's «avatar animado» (`brand_avatar.avatar_object_key`:
    `t/{tenant}/brand/{brand}/avatar/{uuid}.jpg`), which Seedream draws — AI imagery.
    The brand's other files (logos, brandboard, kept pictures) are the owner's."""
    parts = key.split("/")
    return (
        len(parts) >= 6
        and parts[0] == "t"
        and parts[1] == str(tenant_id)
        and parts[2] == "brand"
        and parts[4] == "avatar"
    )


def _unrecorded(key: str, provider: str) -> GeneratedSource:
    """An AI file with no asset row to read: its provenance says why it counts."""
    nothing = UUID(int=0)
    return GeneratedSource(
        object_key=key,
        block_id=nothing,
        clip_id=None,
        kind=provider,
        revision=0,
        asset_id=nothing,
        provider=provider,
        model_id="",
        model_revision=None,
        seconds=0.0,
        pipeline_version="",
        block=False,
        ai_generated=True,
        recorded=False,
    )


def stretch_problem(stretch: BlockStretch, clip_id: UUID) -> tuple[str, str] | None:
    """Why a block's stretch cannot be assembled into `clip_id`: `(code, owner text)`,
    or None. A block belongs to its own Clip, and plays at ×1 so its voice is heard."""
    if stretch.source.clip_id != clip_id:
        return "avatar_block_elsewhere", ELSEWHERE_TEXT
    if stretch.segment.speed != 1.0:
        return "avatar_block_speed", SPEED_TEXT
    return None


#: m-25119867 (Deivid, 2026-11-25): a join next to an avatar block is only «Corte» —
#: a blend would mix up to 0.8 s of the voice's end with the next stretch. The code the
#: screen reads, and the owner's words.
AVATAR_JOIN_CODE = "avatar_join_cut_only"
AVATAR_JOIN_TEXT = (
    "Al lado de un avatar, la unión tiene que ser «Corte», para que su voz se escuche "
    "completa. Cambia la unión de esa foto o video a «Corte» y vuelve a crear tu video."
)


def avatar_join_problems(
    segments: Sequence[SourceSegment | None], blocks: Iterable[int]
) -> tuple[int, ...]:
    """The indexes of the stretches whose join touches an avatar block and is not a cut
    (ADR 50 §10's `SourceSegment.transition_in`): the block's own (its join with the
    stretch before it) and the one of the stretch right after it. `blocks` are the
    blocks' indexes in `segments`; None is a block not made yet (its join is always a
    cut). Holds with `QUALIFY_CLIP_BLOCK_TRANSITIONS` off or on — it is the condition to
    turn it on — on every path that checks it: the first «Crear», `place_block` and the
    local assembly. Pure."""
    found: list[int] = []
    for index in sorted(set(blocks)):
        for at in (index, index + 1):
            if not 0 <= at < len(segments) or at in found:
                continue
            segment = segments[at]
            join = segment.transition_in if segment is not None else None
            # `corte` is read as None by the type already; kept explicit for clarity
            if join is not None and join.effect_id != CUT_EFFECT_ID:
                found.append(at)
    return tuple(sorted(found))


def refuse_avatar_joins(segments: Sequence[SourceSegment | None], blocks: Iterable[int]) -> None:
    """`ClipAvatarRefused` (`avatar_join_cut_only`) when a join next to a block blends."""
    bad = avatar_join_problems(segments, blocks)
    if bad:
        raise ClipAvatarRefused(
            AVATAR_JOIN_CODE, AVATAR_JOIN_TEXT, raw=f"blending joins at stretches {list(bad)}"
        )


def charged_seconds(stretches: Sequence[BlockStretch]) -> int:
    """The month's video seconds approving a Clip with these blocks uses: each block's
    stretch as it plays (×1), rounded up to the whole second."""
    return sum(math.ceil(s.segment.output_seconds - 1e-9) for s in stretches)


def block_segment(video: BlockVideo) -> SourceSegment:
    """The block's video as a stretch of the Clip's recipe: the whole of it, at ×1."""
    return SourceSegment(
        key=video.object_key, start_s=0.0, end_s=round(video.seconds, 3), speed=1.0
    )


# -- option B: the blocks a Clip waits for (m-25119867) ---------------------------------


class ClipAvatarPlacement(BaseModel):
    """One avatar block asked for at a Clip's first «Crear»: what it says and who says
    it (`block`), and BEFORE which of the owner's stretches it goes (`at`, 0 = first,
    `len(segments)` = at the end; equal `at` keep the list's order)."""

    model_config = ConfigDict(frozen=True)

    block: AvatarBlockRequest
    at: int = Field(ge=0, le=SEGMENTS_MAX)


@dataclass(frozen=True)
class ClipWithBlocks:
    """What `create_clip_with_blocks` gives back: the Clip and its blocks, by slot."""

    clip_id: UUID
    block_ids: tuple[UUID, ...]


def avatar_kind_enabled(kind: str, env: Mapping[str, str] | None = None) -> bool:
    """Whether the screen offers blocks of `kind` (`presenter` / `animated`) — the same
    switch the server refuses with (`refuse_if_off`). Free: no read, no network."""
    return block_enabled(kind, env)


def plan_seconds(blocks: Sequence[AvatarBlockRequest | ClipAvatarPlacement]) -> int:
    """The video seconds the blocks of a «Crear» will owe when the Clip is approved, from
    their scripts read aloud (`script_seconds`) — what the screen shows before «Crear»
    and EXACTLY what the quota check of `create_clip_with_blocks` adds. Pure."""
    return sum(
        script_seconds((b.block if isinstance(b, ClipAvatarPlacement) else b).script)
        for b in blocks
    )


@dataclass(frozen=True)
class AvatarQuota:
    """The month's video and what avatar blocks already hold of it, for the screen to say
    before «Crear». `pending_seconds` (or `pending_blocks` when the plan counts videos,
    not seconds) are the brand's blocks made and not charged yet, in any of its Clips
    (ADR 50 §9). `free` is what a new «Crear» may still ask for: seconds (or videos)
    left in the month minus what is pending; None when the month sets no limit."""

    pending_blocks: int
    pending_seconds: int
    video_in_seconds: bool
    left: int | None
    free: int | None


@dataclass(frozen=True)
class PlannedBlock:
    """One entry of a Clip's plan as it stands now: its block's row (None if there is
    none), what the screen calls its state and, when failed, why (`code`)."""

    entry: ClipAvatarSlot
    row: BlockRow | None
    state: Literal["creating", "ready", "failed", "removed"]
    code: str | None = None


def plan_states(
    plan: Sequence[ClipAvatarSlot],
    blocks: Sequence[BlockRow],
    env: Mapping[str, str] | None = None,
) -> tuple[PlannedBlock, ...]:
    """Each plan entry's state, derived from its block's row (nothing stored): removed
    by the owner, refused by the server (`clip_too_long`), its kind switched off since
    (never placed), still being made, failed, or made. Pure."""
    by_slot = {row.slot: row for row in blocks}
    found: list[PlannedBlock] = []
    for entry in sorted(plan, key=lambda e: e.slot):
        row = by_slot.get(entry.slot)
        if row is None:
            found.append(PlannedBlock(entry, None, "failed", "block_missing"))
        elif row.removed:
            found.append(PlannedBlock(entry, row, "removed"))
        elif entry.refused:
            found.append(PlannedBlock(entry, row, "failed", entry.refused))
        elif row.status == "failed":
            found.append(PlannedBlock(entry, row, "failed", row.failure_reason or "failed"))
        elif not block_enabled(row.kind, env):
            found.append(PlannedBlock(entry, row, "failed", "switched_off"))
        elif row.status == "drafting":
            found.append(PlannedBlock(entry, row, "creating"))
        else:
            found.append(PlannedBlock(entry, row, "ready"))
    return tuple(found)


def _row_state(row: BlockRow) -> PlannedBlock:
    """A block with no plan entry (option A, or a Clip already made from its plan) as
    its row stands: removed, being made, failed (its reason) or made."""
    entry = ClipAvatarSlot(slot=row.slot, at=0, seconds_estimate=max(1, row.script_seconds))
    if row.removed:
        return PlannedBlock(entry, row, "removed")
    if row.status == "drafting":
        return PlannedBlock(entry, row, "creating")
    if row.status == "failed":
        return PlannedBlock(entry, row, "failed", row.failure_reason or "failed")
    return PlannedBlock(entry, row, "ready")


#: The placeholder stretch of a block not made yet, only to check the recipe the owner
#: sees (`virtual_brief`): never stored, never read.
_PLAN_NAMESPACE = UUID("0b6a3f2e-25e1-4c9b-8f67-251198670001")


def _placeholder(tenant_id: UUID, entry: ClipAvatarSlot) -> SourceSegment:
    from uuid import uuid5  # noqa: PLC0415

    folder = uuid5(_PLAN_NAMESPACE, f"{tenant_id}:{entry.slot}")
    return SourceSegment(
        key=f"t/{tenant_id}/generated/{folder}/avatar-plan.mp4",
        start_s=0.0,
        end_s=float(entry.seconds_estimate),
        speed=1.0,
    )


def _ordered(
    segments: Sequence[SourceSegment], plan: Sequence[ClipAvatarSlot]
) -> list[tuple[SourceSegment | None, ClipAvatarSlot | None]]:
    """The Clip's timeline: each block before the owner's stretch at its `at` (equal
    `at` in slot order), the owner's stretches in their order."""
    order: list[tuple[SourceSegment | None, ClipAvatarSlot | None]] = []
    by_at = sorted(plan, key=lambda e: (e.at, e.slot))
    for index in range(len(segments) + 1):
        order.extend((None, entry) for entry in by_at if min(entry.at, len(segments)) == index)
        if index < len(segments):
            order.append((segments[index], None))
    return order


def virtual_brief(
    brief: ContentBrief, plan: Sequence[ClipAvatarSlot], tenant_id: UUID
) -> ContentBrief:
    """The recipe as the owner sees it before «Crear»: each block a stretch at its
    estimated length, in its place. Only to check it (`refuse_unbuilt_recipe`)."""
    segments = tuple(
        segment if segment is not None else _placeholder(tenant_id, entry)  # type: ignore[arg-type]
        for segment, entry in _ordered(brief.media.segments, plan)
    )
    return brief.model_copy(
        update={
            "media": brief.media.model_copy(update={"segments": segments, "clip_avatar_plan": ()})
        }
    )


@dataclass(frozen=True)
class PlanFit:
    """`fit_plan`'s answer: the brief the Clip is made from, or the slot of the block that
    makes it pass `LOCAL_TOTAL_MAX_S` (`too_long`) — then `brief` is None."""

    brief: ContentBrief | None
    too_long: int | None = None
    moved: int = 0
    dropped: int = 0


def _mapper(points: Sequence[tuple[float, float]]) -> Callable[[float], float]:
    """A piecewise-linear map from the estimated timeline to the real one, through the
    item boundaries `(estimated, real)`: a time inside a block keeps its place in it, a
    time over the owner's stretch moves with what came before."""

    def at(t: float) -> float:
        for (e0, r0), (e1, r1) in zip(points, points[1:], strict=False):
            if t <= e1:
                if e1 <= e0:
                    return r0
                return r0 + (max(t, e0) - e0) * (r1 - r0) / (e1 - e0)
        last_e, last_r = points[-1]
        return last_r + (t - last_e)

    return at


def fit_plan(
    brief: ContentBrief, made: Mapping[int, BlockVideo], *, keep: Sequence[ClipAvatarSlot]
) -> PlanFit:
    """The Clip's recipe with its blocks made (`made`: slot → its kept video; `keep`: the
    plan entries still in it): each block a stretch of its whole video at ×1, in its
    place; every text and effect timed on the estimated timeline moved to the real one
    (a time inside a block keeps its place in it), cut at the new end, and dropped when it
    would start at or after it. Over `LOCAL_TOTAL_MAX_S`: the slot of the first block
    that passes it, nothing else. Pure."""
    media = brief.media
    order = _ordered(media.segments, keep)
    points: list[tuple[float, float]] = [(0.0, 0.0)]
    segments: list[SourceSegment] = []
    for segment, entry in order:
        e, r = points[-1]
        if segment is not None:
            length = segment.output_seconds
            segments.append(segment)
            points.append((e + length, r + length))
            continue
        assert entry is not None
        stretch = block_segment(made[entry.slot])
        segments.append(stretch)
        points.append((e + entry.seconds_estimate, r + stretch.output_seconds))
        if r + stretch.output_seconds > LOCAL_TOTAL_MAX_S + 1e-6:
            return PlanFit(brief=None, too_long=entry.slot)
    total = points[-1][1]
    move = _mapper(points)
    moved = dropped = 0
    texts = []
    for layer in media.text_layers:
        start = round(move(layer.start_s), 3)
        end = None if layer.end_s is None else round(min(move(layer.end_s), total), 3)
        if start >= total or (end is not None and end <= start):
            dropped += 1
            continue
        moved += int((start, end) != (layer.start_s, layer.end_s))
        texts.append(layer.model_copy(update={"start_s": start, "end_s": end}))
    effects = []
    for effect in media.effects:
        if effect.start_s is None or effect.end_s is None:
            effects.append(effect)
            continue
        start = round(move(effect.start_s), 3)
        end = round(min(move(effect.end_s), total), 3)
        if start >= total or end <= start:
            dropped += 1
            continue
        moved += int((start, end) != (effect.start_s, effect.end_s))
        effects.append(effect.model_copy(update={"start_s": start, "end_s": end}))
    fresh = ContentBrief.model_validate(
        {
            **brief.model_dump(),
            "media": {
                **media.model_dump(),
                "segments": tuple(s.model_dump() for s in segments),
                "text_layers": tuple(t.model_dump() for t in texts),
                "effects": tuple(f.model_dump() for f in effects),
                "clip_avatar_plan": (),
            },
        }
    )
    return PlanFit(brief=fresh, moved=moved, dropped=dropped)


class ClipBlocksWait(LocalVideoWait):
    """A Clip waits for its avatar blocks (m-25119867): its run is released NOT done and
    tried again no sooner than `retry_after_s` — nothing read past the blocks, written
    or paid. Its sign of life is stamped first, so it is never reaped while it waits
    (its job also stays queued)."""

    retry_after_s = 30.0


@dataclass(frozen=True)
class PlanWait:
    """The Clip goes on waiting: `reason` is `creating` or `block_failed`."""

    reason: str
    brief: ContentBrief | None = None


@dataclass(frozen=True)
class PlanReady:
    """Every block made: the brief the Clip is made from."""

    brief: ContentBrief
    moved: int = 0
    dropped: int = 0


@dataclass(frozen=True)
class PlanRefused:
    """A made block the Clip cannot take as it came out: the Clip's brief with that plan
    entry refused (`code`), and it waits for the owner."""

    brief: ContentBrief
    slot: int
    code: str

    @property
    def reason(self) -> str:
        return self.code


def _refused(brief: ContentBrief, slot: int, code: str) -> ContentBrief:
    plan = tuple(
        entry.model_copy(update={"refused": code}) if entry.slot == slot else entry
        for entry in brief.media.clip_avatar_plan
    )
    return brief.model_copy(
        update={"media": brief.media.model_copy(update={"clip_avatar_plan": plan})}
    )


def plan_gate(
    *,
    tenant_id: UUID,
    clip_id: UUID,
    brief: ContentBrief,
    store: ClipAvatarStore,
    env: Mapping[str, str] | None = None,
) -> PlanWait | PlanReady | PlanRefused:
    """What a Clip with a plan does on this pass: wait (a block still being made, or one
    failed — the owner retries or removes it), take a made block it cannot use as
    refused, or be made from the blocks' videos. Reads the blocks once (and each made
    block's video); writes nothing."""
    states = plan_states(
        brief.media.clip_avatar_plan, store.blocks_of(tenant_id=tenant_id, clip_id=clip_id), env
    )
    live = [s for s in states if s.state != "removed"]
    if any(s.state == "creating" for s in live):
        return PlanWait("creating")
    if any(s.state == "failed" for s in live):
        return PlanWait("block_failed")
    made: dict[int, BlockVideo] = {}
    for planned in live:
        assert planned.row is not None
        video = store.block_video(tenant_id=tenant_id, block_id=planned.row.id)
        if video is None:
            return PlanRefused(
                _refused(brief, planned.entry.slot, "block_not_ready"),
                planned.entry.slot,
                "block_not_ready",
            )
        made[planned.entry.slot] = video
    fit = fit_plan(brief, made, keep=[s.entry for s in live])
    if fit.brief is None:
        assert fit.too_long is not None
        return PlanRefused(
            _refused(brief, fit.too_long, "clip_too_long"), fit.too_long, "clip_too_long"
        )
    return PlanReady(fit.brief, moved=fit.moved, dropped=fit.dropped)


@dataclass(frozen=True)
class BlockWait:
    """One avatar of a Clip as the screen shows it while the Clip waits
    (`docs/contrato-avatar-primer-crear.md` §1.2)."""

    block_id: UUID | None
    slot: int
    at: int
    kind: str
    state: Literal["creating", "ready", "failed", "removed"]
    seconds_estimate: int
    seconds: float | None = None
    failure_code: str | None = None
    owner_text: str | None = None
    #: PR 1 of m-25119867 offers none yet: «Intentar de nuevo» and «Quitar avatar» come
    #: with `retry_block` / `remove_block`.
    actions: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClipWait:
    """A Clip with avatar blocks as the screen reads it (§1.2)."""

    clip_id: UUID
    clip_status: str
    state: Literal["waiting_blocks", "block_failed", "assembling", "ready", "failed"]
    owner_text: str
    blocks: tuple[BlockWait, ...]
    wait_until: Any = None


def block_failure_text(code: str | None, detail: str | None) -> str:
    """A failed block's words: its own detail when it has one, else by its code."""
    if detail:
        return detail
    if code == "clip_too_long":
        return CLIP_TOO_LONG_TEXT
    if code == "switched_off":
        return FIRST_CREATE_SWITCHED_OFF_TEXT
    if code == "timeout":
        return BLOCK_TIMEOUT_TEXT
    return BLOCK_FAILED_TEXT


_READY_STATUSES = frozenset({"generated", "rejected", "approved", "staged", "published"})


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
                # under the business's lock: the same request already made (a double
                # click, a retry of the screen) is that block; two blocks asked at once
                # never both fit
                lambda: self._made_already(tenant_id, request_key),
                lambda: self._refuse_without_quota(tenant_id, clip.brand_id, seconds),
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

    def _made_already(self, tenant_id: UUID, request_key: UUID | None) -> None:
        """The block this request key already made — read again under the business's
        lock, after the first lookup: a concurrent ask with the same key that won the
        lock has committed by now (`DuplicateDraftRequest`: its draft is the answer)."""
        from qualify_api.creative.service import DuplicateDraftRequest  # noqa: PLC0415

        if request_key is None:
            return
        existing = self._content.repository.draft_id_for_request(
            tenant_id=tenant_id, request_key=request_key
        )
        if existing is not None:
            raise DuplicateDraftRequest(existing)

    def _made_in_one_go(
        self,
        tenant_id: UUID,
        made_already: Callable[[], None],
        check: Callable[[], None],
        make: Callable[[], UUID],
    ) -> UUID:
        """The daily cap's count, the block's rows and its charge row in ONE
        transaction on Postgres (the count's lock serializes the business's blocks, so
        two asked at once never both take the last place, nor the same slot, nor make
        the same request twice); the dispatch only after it commits. Anything refused
        writes nothing."""
        from qualify_api.creative.service import PostgresContentRepository  # noqa: PLC0415

        dispatcher = self._content.dispatcher
        if isinstance(self._content.repository, PostgresContentRepository):
            from qualify_shared.db.session import (  # noqa: PLC0415
                after_tenant_commit,
                tenant_unit_of_work,
            )

            with tenant_unit_of_work(tenant_id):
                # the lock first: the same request key, then the cap
                self._lock(tenant_id)
                made_already()
                check_avatar_daily_cap(self._store, tenant_id=tenant_id)
                check()
                draft_id = make()
                if dispatcher is not None:
                    after_tenant_commit(
                        tenant_id,
                        lambda: dispatcher.dispatch_generation(
                            tenant_id=tenant_id, draft_id=draft_id
                        ),
                    )
            return draft_id
        made_already()
        check_avatar_daily_cap(self._store, tenant_id=tenant_id)
        check()
        draft_id = make()
        if dispatcher is not None:
            dispatcher.dispatch_generation(tenant_id=tenant_id, draft_id=draft_id)
        return draft_id

    def _lock(self, tenant_id: UUID) -> None:
        """The business's transaction lock (the daily cap's, `blocks_made_today` takes
        it too: re-entrant within the transaction)."""
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('clip_avatar_cap'), hashtext(:t))"),
                {"t": str(tenant_id)},
            )

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

        from qualify_api.creative.service import (  # noqa: PLC0415
            DuplicateDraftRequest,
            PostgresContentRepository,
        )

        repo = self._content.repository
        # on Postgres the bare insert (no lookup of its own after a failure): the
        # savepoint rolls back first, THEN the key is read, on a usable session
        insert = (
            repo._insert_brief_and_draft  # noqa: SLF001
            if isinstance(repo, PostgresContentRepository)
            else repo.insert_brief_and_draft
        )
        last: IntegrityError | None = None
        for slot in slots:
            try:
                # a savepoint per attempt: a unique violation (23505) never aborts the
                # transaction of the cap, the charge and the dispatch around it
                with self._savepoint(tenant_id):
                    return insert(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        brief=brief,
                        voice_profile_version=voice_version,
                        pipeline_version=pipeline_version,
                        parent_draft_id=clip_id,
                        part_index=slot,
                        request_key=keyed.get("request_key"),
                    )
            except IntegrityError as exc:
                if not _slot_taken(exc):
                    raise
                request_key = keyed.get("request_key")
                if request_key is not None:
                    # the request key's own index, not the slot's: its draft is the answer
                    existing = repo.draft_id_for_request(
                        tenant_id=tenant_id, request_key=request_key
                    )
                    if existing is not None:
                        raise DuplicateDraftRequest(existing) from exc
                last = exc
        assert last is not None
        raise ClipAvatarRefused("no_slot", NO_SLOT_TEXT, raw=str(last)) from last

    @contextmanager
    def _savepoint(self, tenant_id: UUID) -> Iterator[None]:
        """`begin_nested` on the unit of work's session (Postgres); nothing elsewhere."""
        from qualify_api.creative.service import PostgresContentRepository  # noqa: PLC0415

        if not isinstance(self._content.repository, PostgresContentRepository):
            yield
            return
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415

        with tenant_session(tenant_id) as session, session.begin_nested():
            yield

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

    def _refuse_without_quota(
        self, tenant_id: UUID, brand_id: UUID, seconds: int, blocks: int = 1
    ) -> None:
        """No paid call without quota: the month must be able to pay, at approval, these
        `blocks` (`seconds` in all) and EVERY live block of the brand not charged yet — in
        any of its Clips —, so blocks are never piled up past the balance."""
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
            needed = blocks + pending
        short = balance.video_shortfall(needed)
        if short is not None:
            raise short

    # -- option B: the avatar at the Clip's first «Crear» (m-25119867) -------------------

    def create_clip_with_blocks(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        user_id: UUID,
        brief: ContentBrief,
        blocks: Sequence[ClipAvatarPlacement],
        request_key: UUID | None = None,
    ) -> ClipWithBlocks:
        """A `local` Clip and its avatar blocks, born together: the Clip in `drafting`
        with its plan (`media.clip_avatar_plan`), each block under it in slots 1..N, all
        dispatched after ONE commit — the blocks are made, the Clip waits for them
        (`ClipBlocksWait`) and is assembled once. Every rule of ADR 50 §9 and of the
        recipe is checked BEFORE anything is written and before any paid call (paid calls
        only start in the worker, after the commit): the switches, 30 s per block, the
        number of blocks, an own-video Clip with 3 s of the owner's own, the recipe with
        the blocks at their estimated length, the brand, today's cap, the month's video
        for every uncharged block, the Clip's own price. `request_key`: the same «Crear»
        again returns what it made and dispatches nothing."""
        from qualify_api.creative.service import DuplicateDraftRequest  # noqa: PLC0415
        from qualify_api.creative.video_pipeline.local import is_local_recipe  # noqa: PLC0415

        placements = tuple(blocks)
        # 1. what needs no read
        if not placements:
            raise ValueError("a Clip with avatars has at least one")
        if len(placements) > BLOCKS_PER_CREATE:
            raise ClipAvatarRefused(
                "too_many_blocks", TOO_MANY_BLOCKS_TEXT, raw=f"{len(placements)} blocks"
            )
        for index, placement in enumerate(placements):
            if not block_enabled(placement.block.kind, self._env):
                raise ClipAvatarRefused(
                    "switched_off",
                    FIRST_CREATE_SWITCHED_OFF_TEXT,
                    raw=f"clip avatar block {placement.block.kind!r} is off",
                    block=index,
                )
        for index, placement in enumerate(placements):
            seconds = script_seconds(placement.block.script)
            if seconds > AVATAR_BLOCK_MAX_SECONDS:
                raise ClipAvatarRefused(
                    "too_long",
                    TOO_LONG_TEXT,
                    raw=f"script of ~{seconds}s > {AVATAR_BLOCK_MAX_SECONDS}s",
                    block=index,
                )
        if brief.brand_id != brand_id:
            raise ValueError("brief.brand_id does not match brand_id")
        media = brief.media
        if media.clip_avatar_plan or media.clip_avatar_block:
            raise ValueError("a Clip's avatar plan is the server's to write")
        if media.part is not None or not is_local_recipe(brief):
            raise ClipAvatarRefused("clip_not_local", CLIP_NOT_LOCAL_TEXT)
        own = sum(segment.output_seconds for segment in media.segments)
        if own < LOCAL_TOTAL_MIN_S:
            # P5 (Deivid 2026-11-25): never a Clip of avatars alone
            raise ClipAvatarRefused(
                "avatar_needs_own_media", NEEDS_OWN_MEDIA_TEXT, raw=f"own stretches {own:.1f}s"
            )
        if any(placement.at > len(media.segments) for placement in placements):
            raise ValueError("an avatar goes before one of the owner's stretches, or at the end")
        if len(media.segments) + len(placements) > SEGMENTS_MAX:
            # checked here, by its code: the recipe with the blocks is built by
            # `model_copy` (no validation) and would otherwise fail as a bare
            # ValidationError when its parts are read
            raise ClipAvatarRefused(
                "too_many_segments",
                TOO_MANY_SEGMENTS_TEXT,
                raw=f"{len(media.segments)} stretches + {len(placements)} avatars",
            )
        plan = tuple(
            ClipAvatarSlot(
                slot=slot,
                at=placement.at,
                seconds_estimate=max(1, script_seconds(placement.block.script)),
            )
            for slot, placement in enumerate(placements, 1)
        )
        planned = brief.model_copy(
            update={"media": media.model_copy(update={"clip_avatar_plan": plan})}
        )
        # a join next to an avatar is only «Corte» (Deivid, 2026-11-25)
        timeline = _ordered(media.segments, plan)
        refuse_avatar_joins(
            [segment for segment, _ in timeline],
            [index for index, (_, entry) in enumerate(timeline) if entry is not None],
        )
        # 2. reads, nothing written: the same request again, the brand, the recipe as the
        # owner sees it (blocks at their estimated length), the queue, today's local cap,
        # the Clip's price — then each block's brief and its files
        repo = self._content.repository
        if request_key is not None:
            existing = repo.draft_id_for_request(tenant_id=tenant_id, request_key=request_key)
            if existing is not None:
                return self._made(tenant_id, existing)
        inputs = self._content.new_draft_inputs(
            tenant_id=tenant_id,
            brand_id=brand_id,
            brief=planned,
            recipe_brief=virtual_brief(brief, plan, tenant_id),
        )
        clip_brief = inputs.brief
        if not clip_brief.media.clip_avatar_plan:  # the producer's stamp never drops it
            raise RuntimeError("a Clip's avatar plan was lost while being prepared")
        avatar_key = (
            self._brand_avatar_key(tenant_id, brand_id)
            if any(p.block.use_brand_avatar for p in placements)
            else None
        )
        prepared: list[tuple[ContentBrief, int, str]] = []
        for index, placement in enumerate(placements):
            try:
                block = block_brief(clip_brief, placement.block, brand_avatar_key=avatar_key)
            except ClipAvatarRefused as refused:
                raise ClipAvatarRefused(
                    refused.code, refused.owner_message, block=index
                ) from refused
            self._refuse_foreign_files(tenant_id, block, index)
            prepared.append(
                self._content.prepare_new_generation(
                    tenant_id=tenant_id, brand_id=brand_id, brief=block
                )
            )
        if any(not stamped.media.clip_avatar_block for stamped, _, _ in prepared):
            raise RuntimeError("a block's brief lost its mark while being prepared")
        seconds = plan_seconds(placements)

        # 3. one transaction under the business's lock
        def write() -> list[UUID]:
            if request_key is not None:
                existing = repo.draft_id_for_request(tenant_id=tenant_id, request_key=request_key)
                if existing is not None:
                    raise DuplicateDraftRequest(existing)
            check_avatar_daily_cap(
                self._store, tenant_id=tenant_id, asking=len(placements), first_create=True
            )
            self._refuse_without_quota(tenant_id, brand_id, seconds, blocks=len(placements))
            insert = self._bare_insert()
            clip_id = insert(
                tenant_id=tenant_id,
                user_id=user_id,
                brief=clip_brief,
                voice_profile_version=inputs.voice_version,
                pipeline_version=inputs.pipeline_version,
                request_key=request_key,
            )
            creations = self._content.creations
            if creations is not None and inputs.price is not None:
                creations.charge(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    draft_id=clip_id,
                    revision=1,
                    price=inputs.price,
                )
            made: list[UUID] = []
            for entry, (stamped, voice_version, pipeline_version) in zip(
                plan, prepared, strict=True
            ):
                block_id = insert(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    brief=stamped,
                    voice_profile_version=voice_version,
                    pipeline_version=pipeline_version,
                    request_key=None,
                    parent_draft_id=clip_id,
                    part_index=entry.slot,
                )
                if creations is not None:
                    creations.charge(
                        tenant_id=tenant_id,
                        brand_id=brand_id,
                        draft_id=block_id,
                        revision=1,
                        price=weight_for(stamped),
                    )
                made.append(block_id)
            # the blocks first, then the Clip (it waits for them)
            return [*made, clip_id]

        try:
            ids = self._write_and_dispatch(tenant_id, write)
        except DuplicateDraftRequest as duplicate:
            return self._made(tenant_id, duplicate.draft_id)
        clip_id, block_ids = ids[-1], tuple(ids[:-1])
        logger.info(
            "clip %s: created with %d avatar block(s) (~%ss) it waits for",
            clip_id,
            len(block_ids),
            seconds,
        )
        return ClipWithBlocks(clip_id=clip_id, block_ids=block_ids)

    def _made(self, tenant_id: UUID, clip_id: UUID) -> ClipWithBlocks:
        """What an earlier «Crear» with the same key made: the Clip and its blocks."""
        rows = self._store.blocks_of(tenant_id=tenant_id, clip_id=clip_id)
        return ClipWithBlocks(clip_id=clip_id, block_ids=tuple(row.id for row in rows))

    def _bare_insert(self) -> Callable[..., UUID]:
        """The repository's insert: on Postgres the bare one (inside the unit of work a
        failed insert never runs a lookup on an aborted transaction)."""
        from qualify_api.creative.service import PostgresContentRepository  # noqa: PLC0415

        repo = self._content.repository
        if isinstance(repo, PostgresContentRepository):
            return repo._insert_brief_and_draft  # noqa: SLF001
        return repo.insert_brief_and_draft

    def _write_and_dispatch(self, tenant_id: UUID, write: Callable[[], list[UUID]]) -> list[UUID]:
        """`write` in ONE transaction under the business's lock on Postgres (anything
        refused writes nothing), then each draft dispatched in order after the commit."""
        from qualify_api.creative.service import PostgresContentRepository  # noqa: PLC0415

        dispatcher = self._content.dispatcher
        if isinstance(self._content.repository, PostgresContentRepository):
            from qualify_shared.db.session import (  # noqa: PLC0415
                after_tenant_commit,
                tenant_unit_of_work,
            )

            with tenant_unit_of_work(tenant_id):
                self._lock(tenant_id)
                ids = write()
                if dispatcher is not None:
                    for draft_id in ids:
                        after_tenant_commit(
                            tenant_id,
                            lambda d=draft_id: dispatcher.dispatch_generation(
                                tenant_id=tenant_id, draft_id=d
                            ),
                        )
            return ids
        ids = write()
        if dispatcher is not None:
            for draft_id in ids:
                dispatcher.dispatch_generation(tenant_id=tenant_id, draft_id=draft_id)
        return ids

    def _refuse_foreign_files(self, tenant_id: UUID, block: ContentBrief, index: int) -> None:
        """A block's files (the character's image, the background, the products) must be
        this business's (`media.owned_by`) — checked before anything is written; the
        producer checks them again before it reads any."""
        from qualify_api.creative.media import owned_by  # noqa: PLC0415

        media = block.media
        keys = [media.avatar_image_key, media.background_key, *media.product_keys]
        if any(key and not owned_by(tenant_id, key) for key in keys):
            raise ClipAvatarRefused(
                "avatar_file_not_owned", FILE_NOT_OWNED_TEXT, raw="a file of another", block=index
            )

    def clip_wait(self, *, tenant_id: UUID, clip_id: UUID) -> ClipWait | None:
        """A Clip with avatar blocks as the screen shows it (§1.2), derived from the rows
        each time (nothing stored): its state, its words and each block's. None for no
        Clip of this business (RLS) or one with no avatar block at all. Free."""
        clip = self._store.clip(tenant_id=tenant_id, clip_id=clip_id)
        if clip is None:
            return None
        brief = self._content.repository.get_brief(tenant_id=tenant_id, brief_id=clip.brief_id)
        if brief is None:
            return None
        rows = self._store.blocks_of(tenant_id=tenant_id, clip_id=clip_id)
        plan = brief.media.clip_avatar_plan
        if not plan and not rows:
            return None
        if plan:
            planned = plan_states(plan, rows, self._env)
        else:
            # already made from its blocks (or option A's): each block as its row says —
            # being made, failed (with its own words) or made; never guessed
            planned = tuple(_row_state(row) for row in rows)
        blocks = tuple(self._block_wait(tenant_id, planned_block) for planned_block in planned)
        live = [b for b in blocks if b.state != "removed"]
        state: Literal["waiting_blocks", "block_failed", "assembling", "ready", "failed"]
        if clip.status == "failed":
            state, words = "failed", clip.failure_detail or BLOCK_FAILED_TEXT
        elif clip.status in _READY_STATUSES:
            # «Revísalo y apruébalo» only while it waits for the owner's approval
            state, words = "ready", READY_TEXT if clip.status == "generated" else READY_DONE_TEXT
        elif any(b.state == "failed" for b in live) and plan:
            state, words = "block_failed", BLOCK_FAILED_STATE_TEXT
        elif any(b.state == "creating" for b in live) and plan:
            state = "waiting_blocks"
            words = WAITING_MANY_TEXT if len(live) > 1 else WAITING_ONE_TEXT
        else:
            state = "assembling"
            words = ASSEMBLING_WITH_BLOCKS_TEXT if live else ASSEMBLING_TEXT
        return ClipWait(
            clip_id=clip_id,
            clip_status=clip.status,
            state=state,
            owner_text=words,
            blocks=blocks,
        )

    def _block_wait(self, tenant_id: UUID, planned: PlannedBlock) -> BlockWait:
        row = planned.row
        seconds = None
        if row is not None and planned.state == "ready":
            video = self._store.block_video(tenant_id=tenant_id, block_id=row.id)
            seconds = video.seconds if video is not None else None
        failed = planned.state == "failed"
        return BlockWait(
            block_id=row.id if row is not None else None,
            slot=planned.entry.slot,
            at=planned.entry.at,
            kind=row.kind if row is not None else "presenter",
            state=planned.state,
            seconds_estimate=planned.entry.seconds_estimate,
            seconds=seconds,
            failure_code=planned.code if failed else None,
            owner_text=(
                block_failure_text(
                    planned.code,
                    # a refusal of ours speaks for itself, never the block's own detail
                    row.failure_detail if row is not None and not planned.entry.refused else None,
                )
                if failed
                else None
            ),
        )

    def avatar_daily_left(self, *, tenant_id: UUID) -> tuple[int, int]:
        """(used, cap): today's avatar blocks of this business and the cap the server
        refuses with — for the screen to say how many are left before «Crear». Free."""
        counter = getattr(self._store, "blocks_made_today", None)
        used = int(counter(tenant_id=tenant_id)) if counter is not None else 0
        return used, AVATAR_DAILY_CAP

    def avatar_quota(self, *, tenant_id: UUID, brand_id: UUID) -> AvatarQuota | None:
        """What the month's video still allows for avatars, with what the brand's
        uncharged blocks already hold (ADR 50 §9) — None without a monthly quota. The
        check of `create_clip_with_blocks` refuses when `plan_seconds` (or the number of
        blocks) passes `free`. Free."""
        creations = self._content.creations
        if creations is None:
            return None
        pending, pending_seconds = self._store.pending_block_seconds(
            tenant_id=tenant_id, brand_id=brand_id
        )
        balance = creations.balance(tenant_id=tenant_id, brand_id=brand_id)
        if balance.unlimited or balance.video_quota <= 0:
            return AvatarQuota(pending, pending_seconds, balance.video_in_seconds, None, None)
        left = int(balance.videos_left)
        held = pending_seconds if balance.video_in_seconds else pending
        return AvatarQuota(
            pending, pending_seconds, balance.video_in_seconds, left, max(0, left - held)
        )

    def brand_avatar_ready(self, *, tenant_id: UUID, brand_id: UUID) -> bool:
        """Whether the brand has its own avatar ready (`use_brand_avatar`). Free."""
        return bool(self._brand_avatar_key(tenant_id, brand_id))

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
        # m-25119867: a join next to an avatar is only «Corte» — the stretch the block now
        # goes before keeps no blend into the voice
        refuse_avatar_joins(segments, [position])
        fresh = ContentBrief.model_validate(
            {
                **brief.model_dump(),
                "media": {
                    **brief.media.model_dump(),
                    "segments": tuple(segments),
                    # provenance: a brief the server derives points to the owner's one
                    "derived_from_brief_id": brief.media.derived_from_brief_id or clip.brief_id,
                },
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
    "BLOCKS_PER_CREATE",
    "AvatarQuota",
    "BlockWait",
    "ClipAvatarPlacement",
    "ClipBlocksWait",
    "ClipWait",
    "ClipWithBlocks",
    "PlanReady",
    "PlanRefused",
    "PlanWait",
    "PlannedBlock",
    "avatar_kind_enabled",
    "block_failure_text",
    "fit_plan",
    "plan_gate",
    "plan_seconds",
    "plan_states",
    "virtual_brief",
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
    "BRAND_AVATAR",
    "UNKNOWN_GENERATED",
    "ai_stretches",
    "is_brand_avatar_file",
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
