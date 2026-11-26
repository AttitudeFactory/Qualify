"""The business's characters (m-25129385, epic m-25026566): described by the owner, drawn
by AI, chosen and kept to be reused in the Clip's character scenes (m-25128784).

Deivid's decisions (2026-11-26), all enforced here:

- **Drawing.** The owner describes a character and picks a style (`STYLES`; an open
  vocabulary — the table has no closed CHECK). One description opens a ROUND of
  `OPTIONS_PER_ROUND` (3) options, each ONE Seedream 5.0 pro image at 1080x1920 (the 1K
  price tier) run by `creative-worker` (`business_character_ai`). The prompt
  (`build_character_prompt`, version `PROMPT_VERSION`) is built once, here, from the
  description, the style and the Brand Kit palette, and stored with each option.
- **Choosing.** The owner keeps ONE option under a name (`saved`); the round's other
  options are `discarded` and their images deleted from R2. A saved character can be
  renamed and deleted (the row stays as `deleted`: it is the provenance of a paid call; its
  image IS deleted from R2).
- **Caps per business.** At most `MAX_SAVED` (5) saved characters; at most `DAILY_ROUNDS`
  (2) rounds a day, the business's own day (`tenants.timezone`); a round whose options all
  failed without paying anything does not count; one open round at a time (choose or
  discard before asking again); a round left unchosen for `ROUND_TTL` (7 days) is
  discarded by the next visit. All checked under the business's transaction lock.
- **Quota.** Drawing does NOT charge the creaciones quota (Deivid, P2). Every paid image
  books its USD cost in `creative_usage_events` and the brand's monthly spend, and the
  price guard refuses an option over the brand's hard monthly dollar cap.
- **Deleting a character in use.** Refused (`in_use`) while a video that is not approved
  yet uses it (Deivid, P4). The scene's brief (m-25128784) names its characters under
  `content_briefs.media.character_scenes[*].character_id` (`SCENE_MEDIA_KEY`).
- **Switch.** `QUALIFY_CLIP_CHARACTER_SCENE` (one switch for the scene, the characters and
  «Sugerir con IA»), off everywhere. Off — or without the ModelArk key — every public
  method raises `CharacterRefused("switched_off")` before reading or writing anything.
- **Reuse.** `character_reference` gives the scene the saved character's image key (read
  through `ObjectGate.open_business_character`, byte for byte as Seedream returned it),
  its provenance and `drawn_at` (AVESC-001 read a «Seedream output under 30 days» rule
  for Seedance's faces; m-25128784 measures it — a character can be drawn again from its
  description).

Tenant isolation: every read and write through `tenant_session` (RLS); every method also
checks the brand. Idempotent: a round is keyed by the screen's `request_key`.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Protocol
from uuid import UUID, uuid4

logger = logging.getLogger("qualify_api.creative.business_characters")

# --- switch -------------------------------------------------------------------------------

#: ONE switch for the character scene, the characters and «Sugerir con IA» (Deivid,
#: 2026-11-26, ADR 50 §12). Off by default. A rename is this one line.
CHARACTER_SCENE_SWITCH_ENV: Final = "QUALIFY_CLIP_CHARACTER_SCENE"
#: The key Seedream resolves through (`composition.PROVIDER_KEY_ENVS["seedream"]`).
ARK_KEY_ENV: Final = "QUALIFY_BYTEPLUS_ARK_API_KEY"
_ON_VALUES: Final = frozenset({"1", "true", "yes", "on"})

# --- the rules (Deivid, 2026-11-26) -------------------------------------------------------

OPTIONS_PER_ROUND: Final = 3
MAX_SAVED: Final = 5
DAILY_ROUNDS: Final = 2
ROUND_TTL: Final = timedelta(days=7)
DESCRIPTION_MIN: Final = 10
DESCRIPTION_MAX: Final = 300
NAME_MAX: Final = 40
REQUEST_KEY_MAX: Final = 200

#: Where the scene's brief (m-25128784) lists its characters: `media.character_scenes`,
#: each item with a `character_id`. The `in_use` check reads exactly this path.
SCENE_MEDIA_KEY: Final = "character_scenes"
#: Draft statuses of a video «not approved yet»: being made, made, and also failed or
#: rejected — both can be tried again, and that retry needs the character's image.
UNAPPROVED_DRAFT_STATUSES: Final = ("drafting", "generated", "failed", "rejected")

# --- the drawing (provenance) -------------------------------------------------------------

#: Seedream 5.0 pro (`pricing.SEEDREAM_PRO_MODEL`); the founder confirmed 2026-11-12 that
#: it does not cede data. Pinned here, not read from the deployment's Seedream setting.
MODEL_ID: Final = "dola-seedream-5-0-pro-260628"
#: 1080x1920 = 2.07 MP: the 1K price tier (<= 2.36 MP), vertical like the Clip.
IMAGE_SIZE: Final = "1080x1920"
PRICING_VERSION: Final = "v10"
PROMPT_VERSION: Final = "business-character-v1"
PIPELINE_VERSION: Final = "business-character-1"
SOURCE_DRAWN: Final = "drawn"
#: Where a character comes from. Today only drawn; a later version takes one the owner
#: already made (Deivid, 2026-11-26) — the column leaves room, nothing else is built.
SOURCES: Final = frozenset({SOURCE_DRAWN})

#: The styles the owner picks from, and what each asks Seedream for. An open vocabulary:
#: adding one is a line here (and a prompt version bump).
STYLES: Final[dict[str, str]] = {
    "animado": (
        "Stylized 3D animated cartoon character, original design, big expressive eyes, "
        "friendly smile, clean animated film look"
    ),
    "realista": (
        "Photorealistic photo of an original, fictional person (not a celebrity, not a real "
        "person), warm friendly smile, sharp focus"
    ),
}

#: The fixed frame AVESC-001 measured (`avatar-escena-v1`): a full figure Seedance can put
#: inside a scene and make pick a product up.
_FRAME: Final = (
    "Full body from the knees up, standing and facing the camera, arms relaxed, hands empty "
    "and visible. Plain light background, soft even studio light, vertical 9:16. No text, "
    "no logos, no watermark."
)
_HEX = re.compile(r"^#?([0-9A-Fa-f]{6})$")
_MAX_PALETTE: Final = 4
_KEY_CHARS = re.compile(r"^[A-Za-z0-9:_\-.]+$")

# --- statuses -----------------------------------------------------------------------------

STATUS_PENDING: Final = "pending"
STATUS_READY: Final = "ready"
STATUS_FAILED: Final = "failed"
STATUS_SAVED: Final = "saved"
STATUS_DISCARDED: Final = "discarded"
STATUS_DELETED: Final = "deleted"

ROUND_DRAWING: Final = "drawing"
ROUND_READY: Final = "ready"
ROUND_FAILED: Final = "failed"
ROUND_CLOSED: Final = "closed"

# --- the owner's words --------------------------------------------------------------------

SWITCHED_OFF: Final = "switched_off"
LIMIT_REACHED: Final = "limit_reached"
DAILY_CAP: Final = "daily_cap"
ROUND_OPEN: Final = "round_open"
STYLE_UNKNOWN: Final = "style_unknown"
DESCRIPTION_SHORT: Final = "description_short"
DESCRIPTION_LONG: Final = "description_long"
NAME_INVALID: Final = "name_invalid"
NAME_TAKEN: Final = "name_taken"
NOT_FOUND: Final = "not_found"
NOT_READY: Final = "not_ready"
IN_USE: Final = "in_use"

REFUSAL_TEXT: Final[dict[str, str]] = {
    SWITCHED_OFF: (
        "Los personajes todavía no están listos en tu cuenta. "
        "Mientras tanto, puedes crear tus videos sin ellos."
    ),
    LIMIT_REACHED: f"Ya tienes {MAX_SAVED} personajes guardados. Borra uno para crear otro.",
    # the day is the business's own (`tenants.timezone`): it resets at its midnight
    DAILY_CAP: (
        f"Hoy ya pediste dibujos {DAILY_ROUNDS} veces, que es lo máximo por día. "
        "Mañana puedes pedir otra vez."
    ),
    ROUND_OPEN: (
        f"Ya te dibujamos {OPTIONS_PER_ROUND} opciones. "
        "Elige una, o descártalas para pedir otras nuevas."
    ),
    STYLE_UNKNOWN: "Elige cómo quieres a tu personaje: dibujo animado o realista.",
    DESCRIPTION_SHORT: "Cuéntanos un poco más cómo es tu personaje.",
    DESCRIPTION_LONG: (f"Tu descripción es muy larga. Déjala en {DESCRIPTION_MAX} letras o menos."),
    NAME_INVALID: f"Ponle a tu personaje un nombre de hasta {NAME_MAX} letras.",
    NAME_TAKEN: "Ya tienes un personaje con ese nombre. Elige otro.",
    NOT_FOUND: "No encontramos ese personaje. Puede que ya lo hayas borrado.",
    NOT_READY: "Ese dibujo todavía se está haciendo. Espera un momento y elígelo de nuevo.",
    IN_USE: (
        "Este personaje está en un video que todavía no apruebas. "
        "Quítalo de ese video para poder borrarlo."
    ),
}

#: Why an option did not come out (`fail_reason`) and what the owner reads.
REASON_VENDOR_FAILED: Final = "vendor_failed"
REASON_MODERATED: Final = "moderated"
REASON_BUDGET_CAP: Final = "budget_cap"
REASON_UNCERTAIN: Final = "uncertain"
REASON_LOST_RESULT: Final = "lost_result"
REASON_SWITCHED_OFF: Final = "switched_off"
#: One option that did not come out (the round's other options may still be chosen).
_OPTION_FAILED: Final = "Este dibujo no salió. Elige uno de los otros, o pide dibujos nuevos."
FAILURE_TEXT: Final[dict[str, str]] = {
    REASON_VENDOR_FAILED: _OPTION_FAILED,
    REASON_UNCERTAIN: _OPTION_FAILED,
    REASON_LOST_RESULT: _OPTION_FAILED,
    REASON_SWITCHED_OFF: _OPTION_FAILED,
    REASON_MODERATED: (
        "No pudimos dibujar ese personaje. Cambia un poco la descripción y vuelve a intentarlo."
    ),
    REASON_BUDGET_CAP: "Ahora no pudimos dibujarlo. Inténtalo más tarde.",
}
#: The whole round failed (`DrawingRound.failure_text`); a round that paid something counts
#: for the day (`rounds_today`), and then the owner is told.
ROUND_FAILED_TEXT: Final = "Ningún dibujo salió. Puedes volver a pedirlos."
ROUND_FAILED_COUNTED_TEXT: Final = (
    f"Esta vez cuenta como uno de tus {DAILY_ROUNDS} pedidos del día."
)


def failure_text(reason: str | None) -> str:
    return FAILURE_TEXT.get(reason or "", _OPTION_FAILED)


class CharacterRefused(ValueError):
    """A refusal the owner reads: `code` is stable (screens branch on it), `text` is the
    sentence to show."""

    def __init__(self, code: str, text: str | None = None, *, draft_id: UUID | None = None) -> None:
        self.code = code
        self.text = text or REFUSAL_TEXT.get(code, REFUSAL_TEXT[NOT_FOUND])
        #: `in_use`: the video that holds the character (the screen's «Ver ese video»)
        self.draft_id = draft_id
        super().__init__(self.text)


class CharacterChanged(Exception):
    """The stored row is no longer in the expected status (a concurrent change)."""


# --- switch -------------------------------------------------------------------------------


def characters_unavailable_reason(env: Mapping[str, str] | None = None) -> str | None:
    """None when the characters may be used; else `switched_off` (the switch is off or
    the ModelArk key is missing). Read at call time."""
    source = os.environ if env is None else env
    if (source.get(CHARACTER_SCENE_SWITCH_ENV) or "").strip().lower() not in _ON_VALUES:
        return SWITCHED_OFF
    if not (source.get(ARK_KEY_ENV) or "").strip():
        return SWITCHED_OFF
    return None


def refuse_if_unavailable(env: Mapping[str, str] | None = None) -> None:
    reason = characters_unavailable_reason(env)
    if reason is not None:
        raise CharacterRefused(reason)


# --- the prompt ---------------------------------------------------------------------------


def _clean(text: str) -> str:
    """One line, no quotes that could close the owner's text inside the prompt."""
    return " ".join(text.replace('"', "'").split())


def palette_hexes(palette: Iterable[str]) -> list[str]:
    out: list[str] = []
    for raw in palette:
        match = _HEX.match(str(raw).strip())
        if match:
            value = f"#{match.group(1).lower()}"
            if value not in out:
                out.append(value)
        if len(out) >= _MAX_PALETTE:
            break
    return out


def build_character_prompt(description: str, style: str, palette: Iterable[str] = ()) -> str:
    """The Seedream prompt of one option (`PROMPT_VERSION`): the style, the owner's own
    description (Spanish is fine), the brand's colors for the clothes, the fixed frame."""
    if style not in STYLES:
        raise CharacterRefused(STYLE_UNKNOWN)
    parts = [f"{STYLES[style]}.", f'The character: "{_clean(description)}".']
    colors = palette_hexes(palette)
    if colors:
        parts.append(f"Clothes in the brand colors {', '.join(colors)}.")
    parts.append(_FRAME)
    return " ".join(parts)


def option_quote_usd(pricing: Any) -> Decimal:
    """One option's quote from the versioned table: one 1080x1920 Seedream 5.0 pro image,
    no reference image (US$0.045 in `v10`)."""
    from qualify_creative.pricing import seedream_image_cost  # noqa: PLC0415

    return seedream_image_cost(pricing, model_id=MODEL_ID, size=IMAGE_SIZE, references=0)


def round_quote_usd(pricing: Any, options: int = OPTIONS_PER_ROUND) -> Decimal:
    return option_quote_usd(pricing) * options


def pricing_table() -> Any:
    from qualify_creative.pricing import JsonPricingTable  # noqa: PLC0415

    return JsonPricingTable(PRICING_VERSION)


# --- the rows -----------------------------------------------------------------------------


@dataclass(frozen=True)
class BusinessCharacter:
    """One option of a round; a `saved` one is a character of the business."""

    id: UUID
    tenant_id: UUID
    brand_id: UUID
    round_id: UUID
    option_index: int
    request_key: str
    style: str
    description: str
    prompt: str
    source: str = SOURCE_DRAWN
    name: str | None = None
    status: str = STATUS_PENDING
    fail_reason: str | None = None
    object_key: str | None = None
    content_type: str | None = None
    width: int | None = None
    height: int | None = None
    byte_size: int | None = None
    sha256: str | None = None
    model_id: str = MODEL_ID
    model_revision: str | None = None
    prompt_version: str = PROMPT_VERSION
    pipeline_version: str = PIPELINE_VERSION
    pricing_table_version: str = PRICING_VERSION
    quoted_usd: Decimal = Decimal("0")
    cost_usd: Decimal = Decimal("0")
    vendor_request_id: str | None = None
    vendor_request_started_at: datetime | None = None
    created_by: UUID | None = None
    created_at: datetime | None = None
    drawn_at: datetime | None = None
    finished_at: datetime | None = None
    saved_at: datetime | None = None
    deleted_at: datetime | None = None

    @property
    def failure_text(self) -> str:
        return failure_text(self.fail_reason) if self.status == STATUS_FAILED else ""


@dataclass(frozen=True)
class DrawingRound:
    round_id: UUID
    status: str
    description: str
    style: str
    options: tuple[BusinessCharacter, ...]
    created_at: datetime | None = None

    @property
    def counts_for_the_day(self) -> bool:
        """Whether this round takes one of the day's rounds: every round does, except one
        whose options all failed without paying anything."""
        return not all(o.status == STATUS_FAILED and o.cost_usd == 0 for o in self.options)

    @property
    def failure_text(self) -> str:
        """What the owner reads when NO option came out (empty otherwise). The options that
        did come out of a half-failed round stay eligible (`status` is then `ready`)."""
        if self.status != ROUND_FAILED:
            return ""
        if self.counts_for_the_day:
            return f"{ROUND_FAILED_TEXT} {ROUND_FAILED_COUNTED_TEXT}"
        return ROUND_FAILED_TEXT


@dataclass(frozen=True)
class CharactersView:
    saved: tuple[BusinessCharacter, ...]
    open_round: DrawingRound | None
    rounds_left_today: int
    slots_left: int


@dataclass(frozen=True)
class CharacterReference:
    """What the character scene (m-25128784) needs: the image key (read it with
    `ObjectGate.open_business_character(tenant, brand, key)`, never re-encode it) and the
    provenance of the drawing."""

    character_id: UUID
    brand_id: UUID
    name: str
    style: str
    description: str
    source: str
    object_key: str
    content_type: str
    model_id: str
    model_revision: str | None
    prompt_version: str
    drawn_at: datetime | None


@dataclass(frozen=True)
class RoundState:
    """What the repository counts for `begin_round`, under the business's lock."""

    existing: tuple[BusinessCharacter, ...]  # the round of this request_key, if any
    open_rounds: tuple[UUID, ...]  # rounds with an option pending or ready, within the TTL
    saved: int
    rounds_today: int


@dataclass(frozen=True)
class ChoiceState:
    """What the repository reads for `choose`, under the business's lock."""

    option: BusinessCharacter | None
    round_options: tuple[BusinessCharacter, ...]
    saved_names: tuple[str, ...]


def round_status(options: Sequence[BusinessCharacter]) -> str:
    statuses = {o.status for o in options}
    if STATUS_PENDING in statuses:
        return ROUND_DRAWING
    if STATUS_READY in statuses:
        return ROUND_READY
    if statuses and statuses <= {STATUS_FAILED}:
        return ROUND_FAILED
    return ROUND_CLOSED


def _round_of(options: Sequence[BusinessCharacter]) -> DrawingRound:
    ordered = tuple(sorted(options, key=lambda o: o.option_index))
    first = ordered[0]
    return DrawingRound(
        round_id=first.round_id,
        status=round_status(ordered),
        description=first.description,
        style=first.style,
        options=ordered,
        created_at=first.created_at,
    )


# --- seams --------------------------------------------------------------------------------


class CharacterRepository(Protocol):
    """Tenant-scoped (Postgres: `tenant_session`, RLS)."""

    def begin_round(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        request_key: str,
        now: datetime,
        build: Callable[[RoundState], list[BusinessCharacter]],
    ) -> tuple[list[BusinessCharacter], bool]:
        """Under the business's lock: count (`RoundState`), let `build` refuse or return the
        options, insert them and their jobs in ONE transaction. Returns (options, created);
        an existing round of the same `request_key` comes back with created=False."""
        ...

    def rounds_today(self, *, tenant_id: UUID, brand_id: UUID) -> int:
        """Rounds started today (the business's day), except all-failed unpaid ones."""
        ...

    def get(self, *, tenant_id: UUID, character_id: UUID) -> BusinessCharacter | None: ...

    def list_brand(self, *, tenant_id: UUID, brand_id: UUID) -> list[BusinessCharacter]:
        """Every row of the business but the deleted ones."""
        ...

    def save(self, character: BusinessCharacter, *, expected_status: str) -> BusinessCharacter: ...

    def choose(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        option_id: UUID,
        name: str,
        now: datetime,
        check: Callable[[ChoiceState], None],
    ) -> tuple[BusinessCharacter, list[BusinessCharacter]]:
        """Under the business's lock: `check` refuses or passes; the option becomes `saved`
        (only if it is still `ready`, else `CharacterRefused`) and its round's other
        ready/pending options `discarded` (`discard`'s conditional write). Returns (saved,
        discarded)."""
        ...

    def discard(
        self, *, tenant_id: UUID, character_ids: Sequence[UUID], at: datetime
    ) -> list[BusinessCharacter]:
        """`discarded` for those still `pending` or `ready` — a conditional write that never
        touches the cost columns the worker may be writing; returns the rows it changed."""
        ...

    def start_request(self, *, tenant_id: UUID, character_id: UUID, at: datetime) -> bool: ...

    def clear_request(self, *, tenant_id: UUID, character_id: UUID) -> None: ...


class CharacterUsage(Protocol):
    def unapproved_video(
        self, *, tenant_id: UUID, brand_id: UUID, character_id: UUID
    ) -> UUID | None:
        """The draft of a video not approved yet that uses this character
        (`SCENE_MEDIA_KEY`), or None."""
        ...


class CharacterObjects(Protocol):
    def delete_business_characters(
        self, tenant_id: UUID, brand_id: UUID, object_keys: list[str]
    ) -> None: ...


# --- the service --------------------------------------------------------------------------


class BusinessCharacterService:
    def __init__(
        self,
        *,
        repo: CharacterRepository,
        usage: CharacterUsage,
        objects: CharacterObjects,
        palette: Callable[[UUID, UUID], Sequence[str]] = lambda _t, _b: (),
        pricing: Any = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        env: Mapping[str, str] | None = None,
        options_per_round: int = OPTIONS_PER_ROUND,
        max_saved: int = MAX_SAVED,
        daily_rounds: int = DAILY_ROUNDS,
    ) -> None:
        self._repo = repo
        self._usage = usage
        self._objects = objects
        self._palette = palette
        self._pricing = pricing
        self._clock = clock
        self._env = env
        self.options_per_round = options_per_round
        self.max_saved = max_saved
        self.daily_rounds = daily_rounds

    # -- reads -------------------------------------------------------------------------

    def list_characters(self, tenant_id: UUID, brand_id: UUID) -> CharactersView:
        refuse_if_unavailable(self._env)
        rows = self._expire_stale(tenant_id, brand_id, self._brand_rows(tenant_id, brand_id))
        saved = tuple(
            sorted(
                (r for r in rows if r.status == STATUS_SAVED),
                key=lambda r: r.saved_at or r.created_at or datetime.min.replace(tzinfo=UTC),
            )
        )
        open_round = self._open_round(rows)
        return CharactersView(
            saved=saved,
            open_round=open_round,
            rounds_left_today=max(
                0,
                self.daily_rounds
                - int(self._repo.rounds_today(tenant_id=tenant_id, brand_id=brand_id)),
            ),
            slots_left=max(0, self.max_saved - len(saved)),
        )

    def drawing_round(self, tenant_id: UUID, brand_id: UUID, round_id: UUID) -> DrawingRound:
        refuse_if_unavailable(self._env)
        options = [r for r in self._brand_rows(tenant_id, brand_id) if r.round_id == round_id]
        if not options:
            raise CharacterRefused(NOT_FOUND)
        return _round_of(options)

    def character_reference(
        self, tenant_id: UUID, brand_id: UUID, character_id: UUID
    ) -> CharacterReference:
        refuse_if_unavailable(self._env)
        found = self._own(tenant_id, brand_id, character_id)
        if found.status != STATUS_SAVED or not found.object_key:
            raise CharacterRefused(NOT_FOUND)
        return CharacterReference(
            character_id=found.id,
            brand_id=found.brand_id,
            name=found.name or "",
            style=found.style,
            description=found.description,
            source=found.source,
            object_key=found.object_key,
            content_type=found.content_type or "image/jpeg",
            model_id=found.model_id,
            model_revision=found.model_revision,
            prompt_version=found.prompt_version,
            drawn_at=found.drawn_at,
        )

    # -- drawing -----------------------------------------------------------------------

    def request_drawings(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        user_id: UUID | None,
        *,
        description: str,
        style: str,
        request_key: str,
    ) -> DrawingRound:
        """Open a round of `options_per_round` options (each queued for `creative-worker`).
        Idempotent by `request_key`: a resent request returns the same round."""
        refuse_if_unavailable(self._env)
        text = check_description(description)
        if style not in STYLES:
            raise CharacterRefused(STYLE_UNKNOWN)
        key = (request_key or "").strip()
        if not key or len(key) > REQUEST_KEY_MAX or not _KEY_CHARS.match(key):
            raise ValueError("request_key must be a short opaque token")
        self._expire_stale(tenant_id, brand_id, self._brand_rows(tenant_id, brand_id))
        prompt = build_character_prompt(text, style, self._palette(tenant_id, brand_id))
        pricing = self._pricing if self._pricing is not None else pricing_table()
        quote = option_quote_usd(pricing)
        now = self._clock()

        def build(state: RoundState) -> list[BusinessCharacter]:
            if state.open_rounds:
                raise CharacterRefused(ROUND_OPEN)
            if state.saved >= self.max_saved:
                raise CharacterRefused(LIMIT_REACHED)
            if state.rounds_today >= self.daily_rounds:
                raise CharacterRefused(DAILY_CAP)
            round_id = uuid4()
            return [
                BusinessCharacter(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    round_id=round_id,
                    option_index=index,
                    request_key=key,
                    style=style,
                    description=text,
                    prompt=prompt,
                    quoted_usd=quote,
                    pricing_table_version=getattr(pricing, "version", PRICING_VERSION),
                    created_by=user_id,
                    created_at=now,
                )
                for index in range(1, self.options_per_round + 1)
            ]

        options, created = self._repo.begin_round(
            tenant_id=tenant_id, brand_id=brand_id, request_key=key, now=now, build=build
        )
        if created:
            logger.info(
                "business_characters.round_opened tenant=%s brand=%s round=%s options=%d "
                "quote=%s prompt=%s",
                tenant_id,
                brand_id,
                options[0].round_id,
                len(options),
                quote * len(options),
                PROMPT_VERSION,
            )
        return _round_of(options)

    # -- choosing ----------------------------------------------------------------------

    def choose_option(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        round_id: UUID,
        option_id: UUID,
        *,
        name: str,
    ) -> BusinessCharacter:
        refuse_if_unavailable(self._env)
        clean = check_name(name)

        def check(state: ChoiceState) -> None:
            option = state.option
            if (
                option is None
                or option.brand_id != brand_id
                or option.round_id != round_id
                or option.status in (STATUS_DISCARDED, STATUS_DELETED)
            ):
                raise CharacterRefused(NOT_FOUND)
            if option.status == STATUS_SAVED:
                return  # chosen already: idempotent
            if option.status != STATUS_READY:
                raise CharacterRefused(NOT_READY)
            if len(state.saved_names) >= self.max_saved:
                raise CharacterRefused(LIMIT_REACHED)
            if clean.casefold() in {n.strip().casefold() for n in state.saved_names}:
                raise CharacterRefused(NAME_TAKEN)

        saved, discarded = self._repo.choose(
            tenant_id=tenant_id,
            brand_id=brand_id,
            option_id=option_id,
            name=clean,
            now=self._clock(),
            check=check,
        )
        self._delete_files(tenant_id, brand_id, discarded)
        return saved

    def discard_round(self, tenant_id: UUID, brand_id: UUID, round_id: UUID) -> None:
        refuse_if_unavailable(self._env)
        options = [r for r in self._brand_rows(tenant_id, brand_id) if r.round_id == round_id]
        if not options:
            raise CharacterRefused(NOT_FOUND)
        self._discard(tenant_id, brand_id, options)

    def rename_character(
        self, tenant_id: UUID, brand_id: UUID, character_id: UUID, *, name: str
    ) -> BusinessCharacter:
        refuse_if_unavailable(self._env)
        clean = check_name(name)
        found = self._own(tenant_id, brand_id, character_id)
        if found.status != STATUS_SAVED:
            raise CharacterRefused(NOT_FOUND)
        if (found.name or "") == clean:
            return found
        taken = {
            (r.name or "").strip().casefold()
            for r in self._brand_rows(tenant_id, brand_id)
            if r.status == STATUS_SAVED and r.id != found.id
        }
        if clean.casefold() in taken:
            raise CharacterRefused(NAME_TAKEN)
        try:
            return self._repo.save(replace(found, name=clean), expected_status=STATUS_SAVED)
        except CharacterChanged as exc:
            raise CharacterRefused(NOT_FOUND) from exc

    def delete_character(self, tenant_id: UUID, brand_id: UUID, character_id: UUID) -> None:
        refuse_if_unavailable(self._env)
        found = self._own(tenant_id, brand_id, character_id)
        if found.status == STATUS_DELETED:
            return  # idempotent
        if found.status != STATUS_SAVED:
            raise CharacterRefused(NOT_FOUND)
        video = self._usage.unapproved_video(
            tenant_id=tenant_id, brand_id=brand_id, character_id=character_id
        )
        if video is not None:
            # `draft_id` lets the screen offer «Ver ese video»
            raise CharacterRefused(IN_USE, draft_id=video)
        try:
            deleted = self._repo.save(
                replace(found, status=STATUS_DELETED, deleted_at=self._clock()),
                expected_status=STATUS_SAVED,
            )
        except CharacterChanged as exc:
            raise CharacterRefused(NOT_FOUND) from exc
        self._delete_files(tenant_id, brand_id, [deleted])

    # -- the worker's marks (business_character_ai) -------------------------------------

    def mark_ready(
        self,
        *,
        tenant_id: UUID,
        character_id: UUID,
        object_key: str,
        content_type: str,
        width: int | None,
        height: int | None,
        byte_size: int,
        sha256: str,
        model_revision: str | None,
        drawn_at: datetime,
    ) -> BusinessCharacter:
        found = self._repo.get(tenant_id=tenant_id, character_id=character_id)
        if found is None or found.status != STATUS_PENDING:
            raise CharacterChanged()
        return self._repo.save(
            replace(
                found,
                status=STATUS_READY,
                object_key=object_key,
                content_type=content_type,
                width=width,
                height=height,
                byte_size=byte_size,
                sha256=sha256,
                model_revision=model_revision,
                drawn_at=drawn_at,
                fail_reason=None,
                finished_at=self._clock(),
            ),
            expected_status=STATUS_PENDING,
        )

    def note_paid(
        self, *, tenant_id: UUID, character_id: UUID, cost_usd: Decimal, vendor_request_id: str
    ) -> None:
        found = self._repo.get(tenant_id=tenant_id, character_id=character_id)
        if found is None:
            return
        try:
            self._repo.save(
                replace(found, cost_usd=cost_usd, vendor_request_id=vendor_request_id),
                expected_status=found.status,
            )
        except CharacterChanged:
            logger.warning("business_characters.cost_not_noted character=%s", character_id)

    def mark_failed(
        self, *, tenant_id: UUID, character_id: UUID, reason: str
    ) -> BusinessCharacter | None:
        found = self._repo.get(tenant_id=tenant_id, character_id=character_id)
        if found is None or found.status != STATUS_PENDING:
            return None
        try:
            return self._repo.save(
                replace(
                    found,
                    status=STATUS_FAILED,
                    fail_reason=(reason or REASON_VENDOR_FAILED)[:200],
                    finished_at=self._clock(),
                ),
                expected_status=STATUS_PENDING,
            )
        except CharacterChanged:
            return None

    # -- helpers -----------------------------------------------------------------------

    def _brand_rows(self, tenant_id: UUID, brand_id: UUID) -> list[BusinessCharacter]:
        return [
            r
            for r in self._repo.list_brand(tenant_id=tenant_id, brand_id=brand_id)
            if r.brand_id == brand_id
        ]

    def _own(self, tenant_id: UUID, brand_id: UUID, character_id: UUID) -> BusinessCharacter:
        found = self._repo.get(tenant_id=tenant_id, character_id=character_id)
        if found is None or found.brand_id != brand_id:
            raise CharacterRefused(NOT_FOUND)
        return found

    def _open_round(self, rows: Sequence[BusinessCharacter]) -> DrawingRound | None:
        now = self._clock()
        rounds: dict[UUID, list[BusinessCharacter]] = {}
        for row in rows:
            rounds.setdefault(row.round_id, []).append(row)
        live = [
            options
            for options in rounds.values()
            if any(o.status in (STATUS_PENDING, STATUS_READY) for o in options)
            and not _stale(options, now)
        ]
        if not live:
            return None
        live.sort(key=lambda o: o[0].created_at or now, reverse=True)
        return _round_of(live[0])

    def _expire_stale(
        self, tenant_id: UUID, brand_id: UUID, rows: list[BusinessCharacter]
    ) -> list[BusinessCharacter]:
        """Discard the ready options of rounds left unchosen past `ROUND_TTL` (their images
        are deleted); best effort — a failure leaves them for the next visit."""
        now = self._clock()
        stale = [r for r in rows if r.status == STATUS_READY and _stale([r], now)]
        if not stale:
            return rows
        try:
            gone = {c.id for c in self._discard(tenant_id, brand_id, stale)}
        except Exception:  # noqa: BLE001 — never block the screen on housekeeping
            logger.exception("business_characters.expire_failed brand=%s", brand_id)
            return rows
        return [replace(r, status=STATUS_DISCARDED) if r.id in gone else r for r in rows]

    def _discard(
        self, tenant_id: UUID, brand_id: UUID, options: Sequence[BusinessCharacter]
    ) -> list[BusinessCharacter]:
        ids = [o.id for o in options if o.status in (STATUS_READY, STATUS_PENDING)]
        if not ids:
            return []
        done = self._repo.discard(tenant_id=tenant_id, character_ids=ids, at=self._clock())
        # a `pending` option has no file yet: its late image is removed by the worker
        # (`business_character_ai._ready`) when it finds the option discarded
        self._delete_files(tenant_id, brand_id, done)
        return done

    def _delete_files(
        self, tenant_id: UUID, brand_id: UUID, rows: Sequence[BusinessCharacter]
    ) -> None:
        from qualify_shared.objects.keys import business_character_key  # noqa: PLC0415

        # a discarded option without `object_key` may still have its image: a claim that
        # wrote it and died before `mark_ready` — delete the fixed key too (a no-op if
        # there is nothing; review of m-25129385)
        keys = [
            r.object_key
            or (
                business_character_key(r.tenant_id, r.brand_id, r.id)
                if r.status == STATUS_DISCARDED
                else None
            )
            for r in rows
        ]
        keys = [k for k in keys if k]
        if not keys:
            return
        try:
            self._objects.delete_business_characters(tenant_id, brand_id, keys)
        except Exception as exc:  # noqa: BLE001 — the rows are already settled
            logger.warning(
                "business_characters.delete_files_failed brand=%s files=%d error=%s",
                brand_id,
                len(keys),
                type(exc).__name__,
            )


def _stale(options: Sequence[BusinessCharacter], now: datetime) -> bool:
    created = min((o.created_at for o in options if o.created_at), default=None)
    return created is not None and now - created > ROUND_TTL


def check_description(description: str) -> str:
    text = " ".join((description or "").split())
    if len(text) < DESCRIPTION_MIN:
        raise CharacterRefused(DESCRIPTION_SHORT)
    if len(text) > DESCRIPTION_MAX:
        raise CharacterRefused(DESCRIPTION_LONG)
    return text


def check_name(name: str) -> str:
    text = " ".join((name or "").split())
    if not 1 <= len(text) <= NAME_MAX:
        raise CharacterRefused(NAME_INVALID)
    return text


# ======================================================================================
# In memory (tests)
# ======================================================================================


@dataclass
class MemoryCharacterRepository:
    rows: dict[UUID, BusinessCharacter] = field(default_factory=dict)
    jobs: list[UUID] = field(default_factory=list)
    #: the clock `rounds_today` counts the day with (UTC here; the tenant's zone in Postgres)
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def begin_round(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        request_key: str,
        now: datetime,
        build: Callable[[RoundState], list[BusinessCharacter]],
    ) -> tuple[list[BusinessCharacter], bool]:
        mine = [
            r for r in self.rows.values() if r.tenant_id == tenant_id and r.brand_id == brand_id
        ]
        existing = tuple(r for r in mine if r.request_key == request_key)
        if existing:
            return sorted(existing, key=lambda r: r.option_index), False
        rounds: dict[UUID, list[BusinessCharacter]] = {}
        for row in mine:
            rounds.setdefault(row.round_id, []).append(row)
        state = RoundState(
            existing=(),
            open_rounds=tuple(
                rid
                for rid, opts in rounds.items()
                if any(o.status in (STATUS_PENDING, STATUS_READY) for o in opts)
                and not _stale(opts, now)
            ),
            saved=sum(1 for r in mine if r.status == STATUS_SAVED),
            rounds_today=self.rounds_today(tenant_id=tenant_id, brand_id=brand_id),
        )
        options = build(state)
        for option in options:
            self.rows[option.id] = option
            self.jobs.append(option.id)
        return options, True

    def rounds_today(self, *, tenant_id: UUID, brand_id: UUID) -> int:
        """Rounds started since UTC midnight (the Postgres twin uses the tenant's zone),
        except a round whose options all failed without paying anything."""
        start = self.clock().replace(hour=0, minute=0, second=0, microsecond=0)
        rounds: dict[UUID, list[BusinessCharacter]] = {}
        for row in self.rows.values():
            if row.tenant_id == tenant_id and row.brand_id == brand_id:
                rounds.setdefault(row.round_id, []).append(row)
        return sum(
            1
            for opts in rounds.values()
            if (opts[0].created_at or start) >= start
            and not all(o.status == STATUS_FAILED and o.cost_usd == 0 for o in opts)
        )

    def get(self, *, tenant_id: UUID, character_id: UUID) -> BusinessCharacter | None:
        found = self.rows.get(character_id)
        return found if found is not None and found.tenant_id == tenant_id else None

    def list_brand(self, *, tenant_id: UUID, brand_id: UUID) -> list[BusinessCharacter]:
        return [
            r
            for r in self.rows.values()
            if r.tenant_id == tenant_id and r.brand_id == brand_id and r.status != STATUS_DELETED
        ]

    def save(self, character: BusinessCharacter, *, expected_status: str) -> BusinessCharacter:
        stored = self.rows.get(character.id)
        if stored is None or stored.status != expected_status:
            raise CharacterChanged()
        if character.status == STATUS_SAVED:
            for other in self.rows.values():
                if (
                    other.id != character.id
                    and other.brand_id == character.brand_id
                    and other.status == STATUS_SAVED
                    and (other.name or "").strip().casefold()
                    == (character.name or "").strip().casefold()
                ):
                    raise CharacterRefused(NAME_TAKEN)
        self.rows[character.id] = character
        return character

    def choose(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        option_id: UUID,
        name: str,
        now: datetime,
        check: Callable[[ChoiceState], None],
    ) -> tuple[BusinessCharacter, list[BusinessCharacter]]:
        option = self.get(tenant_id=tenant_id, character_id=option_id)
        mine = self.list_brand(tenant_id=tenant_id, brand_id=brand_id)
        state = ChoiceState(
            option=option,
            round_options=tuple(
                r for r in mine if option is not None and r.round_id == option.round_id
            ),
            saved_names=tuple(r.name or "" for r in mine if r.status == STATUS_SAVED),
        )
        check(state)
        assert option is not None
        if option.status == STATUS_SAVED:
            return option, []
        current = self.rows.get(option.id)
        if current is None or current.status != STATUS_READY:
            raise CharacterRefused(NOT_FOUND)
        saved = self.save(
            replace(current, status=STATUS_SAVED, name=name, saved_at=now, finished_at=now),
            expected_status=STATUS_READY,
        )
        discarded = self.discard(
            tenant_id=tenant_id,
            character_ids=[o.id for o in state.round_options if o.id != option.id],
            at=now,
        )
        return saved, discarded

    def discard(
        self, *, tenant_id: UUID, character_ids: Sequence[UUID], at: datetime
    ) -> list[BusinessCharacter]:
        done: list[BusinessCharacter] = []
        for character_id in character_ids:
            current = self.get(tenant_id=tenant_id, character_id=character_id)
            if current is None or current.status not in (STATUS_PENDING, STATUS_READY):
                continue
            self.rows[character_id] = replace(current, status=STATUS_DISCARDED, finished_at=at)
            done.append(self.rows[character_id])
        return done

    def start_request(self, *, tenant_id: UUID, character_id: UUID, at: datetime) -> bool:
        found = self.get(tenant_id=tenant_id, character_id=character_id)
        if found is None or found.status != STATUS_PENDING:
            return False
        if found.vendor_request_started_at is not None:
            return False
        self.rows[character_id] = replace(found, vendor_request_started_at=at)
        return True

    def clear_request(self, *, tenant_id: UUID, character_id: UUID) -> None:
        found = self.get(tenant_id=tenant_id, character_id=character_id)
        if found is not None and found.status == STATUS_PENDING:
            self.rows[character_id] = replace(found, vendor_request_started_at=None)


@dataclass
class MemoryCharacterUsage:
    #: character → the draft (video not approved yet) that uses it
    in_use: dict[UUID, UUID] = field(default_factory=dict)

    def unapproved_video(
        self, *, tenant_id: UUID, brand_id: UUID, character_id: UUID
    ) -> UUID | None:
        return self.in_use.get(character_id)


# ======================================================================================
# Postgres
# ======================================================================================

_TABLE: Final = "business_characters"
_COLUMNS: Final = (
    "id, tenant_id, brand_id, round_id, option_index, request_key, source, style, "
    "description, prompt, name, status, fail_reason, object_key, content_type, width, height, "
    "byte_size, sha256, model_id, model_revision, prompt_version, pipeline_version, "
    "pricing_table_version, quoted_usd, cost_usd, vendor_request_id, "
    "vendor_request_started_at, created_by, created_at, drawn_at, finished_at, saved_at, "
    "deleted_at"
)
#: Rounds started today, the business's own day (`tenants.timezone`, empty → UTC), except
#: a round whose options all failed and paid nothing.
_ROUNDS_TODAY_SQL: Final = f"""
    WITH z AS (
      SELECT COALESCE(NULLIF(
        (SELECT timezone FROM tenants WHERE id = :tenant), ''), 'UTC') AS zone
    )
    SELECT count(*) FROM (
      SELECT c.round_id
      FROM {_TABLE} c, z
      WHERE c.brand_id = :brand
        AND c.created_at >= (date_trunc('day', now() AT TIME ZONE z.zone) AT TIME ZONE z.zone)
      GROUP BY c.round_id
      HAVING NOT bool_and(c.status = 'failed' AND c.cost_usd = 0)
    ) r
"""


def _from_row(row: Any) -> BusinessCharacter:
    return BusinessCharacter(
        id=row.id,
        tenant_id=row.tenant_id,
        brand_id=row.brand_id,
        round_id=row.round_id,
        option_index=int(row.option_index),
        request_key=row.request_key,
        source=row.source,
        style=row.style,
        description=row.description,
        prompt=row.prompt,
        name=row.name,
        status=row.status,
        fail_reason=row.fail_reason,
        object_key=row.object_key,
        content_type=row.content_type,
        width=row.width,
        height=row.height,
        byte_size=row.byte_size,
        sha256=row.sha256,
        model_id=row.model_id,
        model_revision=row.model_revision,
        prompt_version=row.prompt_version,
        pipeline_version=row.pipeline_version,
        pricing_table_version=row.pricing_table_version,
        quoted_usd=Decimal(row.quoted_usd),
        cost_usd=Decimal(row.cost_usd),
        vendor_request_id=row.vendor_request_id,
        vendor_request_started_at=row.vendor_request_started_at,
        created_by=row.created_by,
        created_at=row.created_at,
        drawn_at=row.drawn_at,
        finished_at=row.finished_at,
        saved_at=row.saved_at,
        deleted_at=row.deleted_at,
    )


def _lock(session: Any, brand_id: UUID) -> None:
    from sqlalchemy import text  # noqa: PLC0415

    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('business_characters'), hashtext(:b))"),
        {"b": str(brand_id)},
    )


class PostgresCharacterRepository:
    """`tenant_session(tenant_id)` per call (`qualify_app`, RLS)."""

    def begin_round(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        request_key: str,
        now: datetime,
        build: Callable[[RoundState], list[BusinessCharacter]],
    ) -> tuple[list[BusinessCharacter], bool]:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        from qualify_api.creative import job_queue as q  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            _lock(session, brand_id)
            existing = [
                _from_row(r)
                for r in session.execute(
                    text(
                        f"SELECT {_COLUMNS} FROM {_TABLE} WHERE brand_id = :b "
                        "AND request_key = :k ORDER BY option_index"
                    ),
                    {"b": brand_id, "k": request_key},
                ).all()
            ]
            if existing:
                return existing, False
            open_rounds = tuple(
                session.execute(
                    text(
                        f"SELECT round_id FROM {_TABLE} WHERE brand_id = :b "
                        "GROUP BY round_id "
                        "HAVING bool_or(status IN ('pending', 'ready')) "
                        "AND min(created_at) >= CAST(:since AS timestamptz)"
                    ),
                    {"b": brand_id, "since": now - ROUND_TTL},
                ).scalars()
            )
            saved = int(
                session.execute(
                    text(f"SELECT count(*) FROM {_TABLE} WHERE brand_id = :b AND status = 'saved'"),
                    {"b": brand_id},
                ).scalar_one()
            )
            today = int(
                session.execute(
                    text(_ROUNDS_TODAY_SQL), {"tenant": tenant_id, "brand": brand_id}
                ).scalar_one()
            )
            options = build(
                RoundState(existing=(), open_rounds=open_rounds, saved=saved, rounds_today=today)
            )
            stored: list[BusinessCharacter] = []
            for option in options:
                row = session.execute(
                    text(
                        f"""
                        INSERT INTO {_TABLE} (
                            id, tenant_id, brand_id, round_id, option_index, request_key,
                            source, style, description, prompt, status, model_id,
                            prompt_version, pipeline_version, pricing_table_version,
                            quoted_usd, created_by, created_at
                        ) VALUES (
                            :id, :tenant_id, :brand_id, :round_id, :option_index,
                            :request_key, :source, :style, :description, :prompt, 'pending',
                            :model_id, :prompt_version, :pipeline_version,
                            :pricing_table_version, :quoted_usd, :created_by,
                            COALESCE(CAST(:created_at AS timestamptz), now())
                        )
                        RETURNING {_COLUMNS}
                        """
                    ),
                    {
                        "id": option.id,
                        "tenant_id": option.tenant_id,
                        "brand_id": option.brand_id,
                        "round_id": option.round_id,
                        "option_index": option.option_index,
                        "request_key": option.request_key,
                        "source": option.source,
                        "style": option.style,
                        "description": option.description,
                        "prompt": option.prompt,
                        "model_id": option.model_id,
                        "prompt_version": option.prompt_version,
                        "pipeline_version": option.pipeline_version,
                        "pricing_table_version": option.pricing_table_version,
                        "quoted_usd": option.quoted_usd,
                        "created_by": option.created_by,
                        "created_at": option.created_at,
                    },
                ).one()
                q.enqueue_business_character_job(
                    session,
                    tenant_id=option.tenant_id,
                    character_id=option.id,
                    pricing_version=option.pricing_table_version,
                    pipeline_version=option.pipeline_version,
                )
                stored.append(_from_row(row))
            return stored, True

    def rounds_today(self, *, tenant_id: UUID, brand_id: UUID) -> int:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            return int(
                session.execute(
                    text(_ROUNDS_TODAY_SQL), {"tenant": tenant_id, "brand": brand_id}
                ).scalar_one()
            )

    def get(self, *, tenant_id: UUID, character_id: UUID) -> BusinessCharacter | None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            row = session.execute(
                text(f"SELECT {_COLUMNS} FROM {_TABLE} WHERE id = :id"), {"id": character_id}
            ).one_or_none()
            return _from_row(row) if row is not None else None

    def list_brand(self, *, tenant_id: UUID, brand_id: UUID) -> list[BusinessCharacter]:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            rows = session.execute(
                text(
                    f"SELECT {_COLUMNS} FROM {_TABLE} WHERE brand_id = :b "
                    "AND status <> 'deleted' ORDER BY created_at DESC, option_index LIMIT 500"
                ),
                {"b": brand_id},
            ).all()
            return [_from_row(r) for r in rows]

    def save(self, character: BusinessCharacter, *, expected_status: str) -> BusinessCharacter:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415

        with tenant_session(character.tenant_id) as session:
            return self._save(session, character, expected_status=expected_status)

    def _save(
        self, session: Any, character: BusinessCharacter, *, expected_status: str
    ) -> BusinessCharacter:
        from sqlalchemy import text  # noqa: PLC0415
        from sqlalchemy.exc import IntegrityError  # noqa: PLC0415

        current = session.execute(
            text(f"SELECT status FROM {_TABLE} WHERE id = :id FOR UPDATE"),
            {"id": character.id},
        ).scalar_one_or_none()
        if current is None or current != expected_status:
            raise CharacterChanged()
        try:
            with session.begin_nested():
                row = session.execute(
                    text(
                        f"""
                        UPDATE {_TABLE} SET
                            name = :name, status = :status, fail_reason = :fail_reason,
                            object_key = :object_key, content_type = :content_type,
                            width = :width, height = :height, byte_size = :byte_size,
                            sha256 = :sha256, model_revision = :model_revision,
                            cost_usd = :cost_usd, vendor_request_id = :vendor_request_id,
                            drawn_at = :drawn_at, finished_at = :finished_at,
                            saved_at = :saved_at, deleted_at = :deleted_at
                        WHERE id = :id
                        RETURNING {_COLUMNS}
                        """
                    ),
                    {
                        "id": character.id,
                        "name": character.name,
                        "status": character.status,
                        "fail_reason": character.fail_reason,
                        "object_key": character.object_key,
                        "content_type": character.content_type,
                        "width": character.width,
                        "height": character.height,
                        "byte_size": character.byte_size,
                        "sha256": character.sha256,
                        "model_revision": character.model_revision,
                        "cost_usd": character.cost_usd,
                        "vendor_request_id": character.vendor_request_id,
                        "drawn_at": character.drawn_at,
                        "finished_at": character.finished_at,
                        "saved_at": character.saved_at,
                        "deleted_at": character.deleted_at,
                    },
                ).one()
        except IntegrityError as exc:
            if "uq_business_characters_saved_name" in str(exc.orig):
                raise CharacterRefused(NAME_TAKEN) from exc
            raise
        return _from_row(row)

    def choose(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        option_id: UUID,
        name: str,
        now: datetime,
        check: Callable[[ChoiceState], None],
    ) -> tuple[BusinessCharacter, list[BusinessCharacter]]:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            _lock(session, brand_id)
            found = session.execute(
                text(f"SELECT {_COLUMNS} FROM {_TABLE} WHERE id = :id"), {"id": option_id}
            ).one_or_none()
            option = _from_row(found) if found is not None else None
            round_options: tuple[BusinessCharacter, ...] = ()
            if option is not None:
                round_options = tuple(
                    _from_row(r)
                    for r in session.execute(
                        text(f"SELECT {_COLUMNS} FROM {_TABLE} WHERE round_id = :r"),
                        {"r": option.round_id},
                    ).all()
                )
            names = tuple(
                session.execute(
                    text(f"SELECT name FROM {_TABLE} WHERE brand_id = :b AND status = 'saved'"),
                    {"b": brand_id},
                ).scalars()
            )
            check(ChoiceState(option=option, round_options=round_options, saved_names=names))
            assert option is not None
            if option.status == STATUS_SAVED:
                return option, []
            from sqlalchemy.exc import IntegrityError  # noqa: PLC0415

            try:
                with session.begin_nested():
                    row = session.execute(
                        text(
                            f"UPDATE {_TABLE} SET status = 'saved', name = :name, "
                            "saved_at = :now, finished_at = :now "
                            f"WHERE id = :id AND status = 'ready' RETURNING {_COLUMNS}"
                        ),
                        {"id": option.id, "name": name, "now": now},
                    ).one_or_none()
            except IntegrityError as exc:
                if "uq_business_characters_saved_name" in str(exc.orig):
                    raise CharacterRefused(NAME_TAKEN) from exc
                raise
            if row is None:  # changed meanwhile (discarded by another device)
                raise CharacterRefused(NOT_FOUND)
            discarded = self._discard(
                session, [o.id for o in round_options if o.id != option.id], now
            )
            return _from_row(row), discarded

    def discard(
        self, *, tenant_id: UUID, character_ids: Sequence[UUID], at: datetime
    ) -> list[BusinessCharacter]:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            return self._discard(session, character_ids, at)

    @staticmethod
    def _discard(session: Any, character_ids: Sequence[UUID], at: datetime) -> list[Any]:
        from sqlalchemy import text  # noqa: PLC0415

        if not character_ids:
            return []
        rows = session.execute(
            text(
                f"UPDATE {_TABLE} SET status = 'discarded', finished_at = :at "
                "WHERE id = ANY(:ids) AND status IN ('pending', 'ready') "
                f"RETURNING {_COLUMNS}"
            ),
            {"ids": list(character_ids), "at": at},
        ).all()
        return [_from_row(r) for r in rows]

    def start_request(self, *, tenant_id: UUID, character_id: UUID, at: datetime) -> bool:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            started = session.execute(
                text(
                    f"UPDATE {_TABLE} SET vendor_request_started_at = :at "
                    "WHERE id = :id AND status = 'pending' "
                    "AND vendor_request_started_at IS NULL RETURNING id"
                ),
                {"id": character_id, "at": at},
            ).scalar_one_or_none()
            return started is not None

    def clear_request(self, *, tenant_id: UUID, character_id: UUID) -> None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            session.execute(
                text(
                    f"UPDATE {_TABLE} SET vendor_request_started_at = NULL "
                    "WHERE id = :id AND status = 'pending'"
                ),
                {"id": character_id},
            )


class PostgresCharacterUsage:
    """A character is in use while a draft not approved yet names it in its brief's
    `media.character_scenes[*].character_id` (the scene's contract, m-25128784)."""

    def unapproved_video(
        self, *, tenant_id: UUID, brand_id: UUID, character_id: UUID
    ) -> UUID | None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            return session.execute(
                text(
                    f"""
                    SELECT d.id FROM content_drafts d
                    JOIN content_briefs b ON b.id = d.brief_id
                    WHERE d.brand_id = :brand
                      AND d.status IN {UNAPPROVED_DRAFT_STATUSES!r}
                      AND jsonb_path_exists(
                        b.media,
                        '$.{SCENE_MEDIA_KEY}[*] ? (@.character_id == $id)',
                        jsonb_build_object('id', CAST(:character AS text))
                      )
                    ORDER BY d.created_at DESC LIMIT 1
                    """
                ),
                {"brand": brand_id, "character": str(character_id)},
            ).scalar_one_or_none()

    def in_unapproved_video(self, *, tenant_id: UUID, brand_id: UUID, character_id: UUID) -> bool:
        return (
            self.unapproved_video(tenant_id=tenant_id, brand_id=brand_id, character_id=character_id)
            is not None
        )


def brand_palette(tenant_id: UUID, brand_id: UUID) -> Sequence[str]:
    """The Brand Kit palette (hex), empty without a kit."""
    from qualify_api.creative.brand_service import BrandKitService  # noqa: PLC0415

    kit = BrandKitService().get_kit(tenant_id=tenant_id, brand_id=brand_id)
    return tuple(kit.palette_rgb) if kit is not None else ()


def production_business_character_service() -> BusinessCharacterService:
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.gate import ObjectGate  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    class _LazyObjects:
        """R2 is opened only when a file is really deleted (never while the switch is off)."""

        def delete_business_characters(
            self, tenant_id: UUID, brand_id: UUID, object_keys: list[str]
        ) -> None:
            ObjectGate(R2ObjectStore(R2Settings.from_env())).delete_business_characters(
                tenant_id, brand_id, object_keys
            )

    return BusinessCharacterService(
        repo=PostgresCharacterRepository(),
        usage=PostgresCharacterUsage(),
        objects=_LazyObjects(),
        palette=brand_palette,
    )


__all__ = [
    "CHARACTER_SCENE_SWITCH_ENV",
    "DAILY_ROUNDS",
    "MAX_SAVED",
    "OPTIONS_PER_ROUND",
    "BusinessCharacter",
    "BusinessCharacterService",
    "CharacterRefused",
    "CharacterReference",
    "CharactersView",
    "DrawingRound",
    "characters_unavailable_reason",
]
