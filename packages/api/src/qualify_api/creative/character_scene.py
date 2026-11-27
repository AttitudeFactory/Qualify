"""The character's scene in a Clip (m-25128784, epic m-25026566, ADR 50 §12 — signed by
Deivid on 2026-11-26): the brand's saved character acts and speaks INSIDE a scene with
the business's product and place, and that scene replaces a window of the owner's own
Clip.

What this module holds (the first of the ticket's PRs — the recipe, its checks and the
480p draft; the Clip's wait and assembly, the 1080p final and its charge come next):

- **The switch.** `QUALIFY_CLIP_CHARACTER_SCENE`, off in every environment. Off, the
  server refuses the scene before anything is read (`switched_off`). It also covers the
  saved characters (m-25129385) and «Sugerir con IA» (m-25129386), §12.5.
- **The character.** A port, `CharacterReferenceSource`, that m-25129385 implements: the
  saved drawing BYTE FOR BYTE (never cropped nor recompressed — Seedance only accepts a
  Seedream 5.0 output of our account, unedited and under 30 days old, §12.3), its
  content type, when it was drawn and its provenance. A drawing past 30 days is refused
  before any spend with `character_needs_redraw` («Tu personaje necesita un dibujo
  nuevo», R7), and so is one the vendor takes for a real face.
- **The recipe checks** (`scene_problems`), all before anything is written or paid:
  5 to 10 whole seconds, at most 3 per video, never two at once (the schema's own),
  none past the end of the video, at least 3 s of the owner's own video left in view,
  the line within `15 × (duration − 2.5)` characters (the schema's), «Textos sí, efectos
  no» over the scene's window, and its EXIT only with «Corte» (§12.6: the scene may come
  in with any transition; a blend at its exit would eat the last word).
- **The creation** (`CharacterSceneService.create_clip_with_scenes`): the Clip and one
  child draft per scene (`ContentKind.CHARACTER_SCENE`, `parent_draft_id`, its
  `part_index` its slot) born in ONE transaction under the business's lock, after the
  daily cap (3 a day per business, scenes and avatar blocks together — §9's cap), the
  month's vistas previas (1 per scene, D7) and the month's video seconds for every
  scene of the brand not charged yet. Each scene's charge row is written with its price
  (`character_scene_price`: 1 vista previa, its requested seconds for the approval) —
  the run's refund gives the vista previa back when the vendor delivers nothing (P2).
- **The draft** (`produce_scene`, called by the media producer): one Seedance 2.5
  omni-reference task at 480p (`draft: true`), with the character, the product photo
  and the place as references (in that order) and the line as dialogue. The task goes
  through the router (the price guard against the versioned table, the vendor task
  record) and leaves its usage with its cost; the kept video records its provenance
  (provider, model, prompt version `personaje-escena-v1`, the character's own, the
  inputs and the request digest).

Tenant isolation: every read goes through `tenant_session` (RLS) or the content
repository; every file of a scene is checked with `owned_by` before anything is written,
and again by the producer before it reads any.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID, uuid5

from qualify_creative.creations import character_scene_price
from qualify_creative.enums import ContentFormat, ContentKind, FailureReason
from qualify_creative.schemas import (
    CHARACTER_SCENE_MAX_S,
    CHARACTER_SCENE_MIN_S,
    CHARACTER_SCENES_MAX,
    LOCAL_TOTAL_MIN_S,
    CharacterSceneItem,
    ContentBrief,
    MediaInputs,
    character_line_max_chars,
)

from qualify_api.creative.clip_avatar import (
    AVATAR_DAILY_CAP,
    AVATAR_FORBIDDEN_EFFECTS,
    ClipAvatarRefused,
    switch_on,
)

if TYPE_CHECKING:
    from qualify_creative.schemas import BrandKit

logger = logging.getLogger(__name__)

#: ADR 50 §12.5 (P3): ONE switch for the scene, the saved characters and «Sugerir con
#: IA». House convention: `1`/`on`/`true` turn it on; anything else leaves it off.
SCENE_SWITCH = "QUALIFY_CLIP_CHARACTER_SCENE"
#: The prompt of the scene (§12.7), derived from AVESC-001's `avatar-escena-v1`
#: (`qualify_api.evals.avatar_scene_bench.scene_prompt`). A change is a new version,
#: measured first (`qualify-measure`, R5).
SCENE_PROMPT_VERSION = "personaje-escena-v1"
#: The model the scene is made on (§12.7): Seedance 2.5, the only family with a draft
#: mode AND omni references.
SCENE_MODEL = "dreamina-seedance-2-5-260628"
SCENE_RATIO = "9:16"
#: The vendor accepts a Seedream drawing as a character for 30 days (§12.3, R7).
CHARACTER_MAX_AGE = timedelta(days=30)
#: §9's daily cap, shared by scenes and avatar blocks (each a paid «avatar» of the day).
SCENE_DAILY_CAP = AVATAR_DAILY_CAP
#: Provenance of this module's rules. A change of rule is a new version.
CHARACTER_SCENE_VERSION = 1
#: Namespace of a scene's request digest as a UUID (`scene_request_key`).
_SCENE_NAMESPACE = UUID("6c1f0d52-2512-4c9b-8f67-251287840012")

# -- codes the screen reads (never the text) ---------------------------------------------

SWITCHED_OFF = "switched_off"
SCENE_DAILY_CAP_CODE = "character_scene_daily_cap"
PAST_END = "character_scene_past_end"
NEEDS_OWN_MEDIA = "character_scene_needs_own_media"
SCENE_EFFECT = "character_scene_effect"
EXIT_CUT_ONLY = "character_scene_exit_cut_only"
CHARACTER_MISSING = "character_missing"
NEEDS_REDRAW = FailureReason.CHARACTER_NEEDS_REDRAW.value
FILE_NOT_OWNED = "character_scene_file_not_owned"
NOT_LOCAL = "clip_not_local"
UNAVAILABLE = "character_scene_unavailable"

# -- what the owner reads (Spanish, `qualify-copy-es`; the screen is m-25112921) ---------

SWITCHED_OFF_TEXT = (
    "Las escenas con tu personaje todavía no están disponibles. Quita la escena para crear "
    "tu video."
)
#: The cap counts scenes AND avatar blocks together (§9's cap): «creaciones».
DAILY_CAP_TEXT = (
    f"Hoy ya usaste tus {SCENE_DAILY_CAP} creaciones con tu personaje. Mañana puedes crear "
    "más. Quita la escena para crear tu video ahora."
)
DURATION_TEXT = (
    f"Cada escena dura de {CHARACTER_SCENE_MIN_S} a {CHARACTER_SCENE_MAX_S} segundos. "
    "Cambia cuánto dura y vuelve a crear tu video."
)
TOO_MANY_TEXT = (
    f"Un video puede tener hasta {CHARACTER_SCENES_MAX} escenas con tu personaje. Quita las "
    "que sobren."
)
OVERLAP_TEXT = "Dos escenas no pueden aparecer al mismo tiempo. Mueve una para que no se crucen."
NEEDS_OWN_MEDIA_TEXT = (
    f"Tu video necesita al menos {LOCAL_TOTAL_MIN_S:g} segundos con tus propias fotos o "
    "videos, sin escena de tu personaje. Acorta una escena o agrega más fotos o videos."
)
#: R7 / P5: the words the ADR fixes, plus what to do now.
NEEDS_REDRAW_TEXT = (
    "Tu personaje necesita un dibujo nuevo. Ve a tus personajes, elige uno de los dibujos "
    "nuevos que te preparamos y vuelve a crear tu video."
)
#: The one-touch fix the screen offers on `character_scene_exit_cut_only` («Cambiar a
#: Corte»: the join after the scene becomes a cut).
CUT_ACTION = "cut_after_scene"
TRANSITION_UNAVAILABLE = "character_scene_transition_unavailable"


def past_end_text(number: int) -> str:
    return (
        f"La escena {number} termina después del final de tu video. Muévela antes o hazla "
        "más corta."
    )


def effect_text(number: int) -> str:
    return (
        "Los efectos de humo, brasas y vapor no pueden aparecer durante la escena "
        f"{number}. Muévelos a otra parte de tu video o quítalos."
    )


def exit_cut_text(number: int) -> str:
    return (
        f"Después de la escena {number}, tu video tiene que cortar directo a lo que sigue, "
        "para que se escuche completo lo que dice tu personaje. Toca «Cambiar a Corte»."
    )


def transition_unavailable_text(number: int) -> str:
    return (
        f"Por ahora la escena {number} solo puede aparecer con «Corte». Cámbiala a "
        "«Corte» y vuelve a crear tu video."
    )


CHARACTER_MISSING_TEXT = "No encontramos tu personaje. Elígelo de nuevo y vuelve a crear tu video."
FILE_NOT_OWNED_TEXT = "No pudimos usar una de las fotos de la escena. Súbela de nuevo."
NOT_LOCAL_TEXT = (
    "Solo puedes agregar escenas con tu personaje a un video armado con tus fotos y videos."
)
#: Ours to fix (no character source wired, a model without omni references): refused
#: before any spend.
UNAVAILABLE_TEXT = (
    "Por ahora no podemos crear esta escena. Inténtalo más tarde. No se gastó nada de tu plan."
)
#: The Clip waits for its scenes (this PR builds no assembly with them yet).
WAITING_TEXT = (
    "Estamos creando las escenas con tu personaje. Puede tardar varios minutos. Puedes "
    "salir: tu video te espera en Por aprobar."
)


def line_too_long_text(duration: int) -> str:
    """The line does not fit in its scene: how many characters it takes."""
    return (
        f"Lo que dice tu personaje es muy largo para una escena de {duration} segundos. "
        f"Escríbelo en {character_line_max_chars(duration)} letras o menos, o haz la "
        "escena más larga."
    )


def daily_left_text(left: int, asking: int) -> str:
    """Fewer creations left today (`left`, at least 1) than this «Crear» asks for."""
    extra = max(1, asking - left)
    return (
        f"Hoy {'te queda' if left == 1 else 'te quedan'} {_creations(left)} con tu personaje. "
        f"Quita {_scenes(extra)} para crear tu video."
    )


def _scenes(count: int) -> str:
    return "1 escena" if count == 1 else f"{count} escenas"


def _creations(count: int) -> str:
    return "1 creación" if count == 1 else f"{count} creaciones"


#: The schema's own refusals (`PydanticCustomError` types of `CharacterSceneItem` and
#: `MediaInputs.character_scenes`) in the owner's words — the editor shows these when
#: the brief it sends does not validate.
def schema_problem_text(error_type: str, context: Mapping[str, Any] | None = None) -> str | None:
    context = context or {}
    if error_type == "character_scene_duration":
        return DURATION_TEXT
    if error_type == "character_line_too_long":
        return line_too_long_text(int(context.get("duration", CHARACTER_SCENE_MIN_S)))
    if error_type == "too_many_character_scenes":
        return TOO_MANY_TEXT
    if error_type == "character_scenes_overlap":
        return OVERLAP_TEXT
    if error_type == "character_scene_not_local":
        return NOT_LOCAL_TEXT
    if error_type == "character_line_empty":
        return "Escribe lo que dice tu personaje."
    return None


def scene_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Whether scenes may be created. Read at call time (tests and a restart change it)."""
    source = os.environ if env is None else env
    return switch_on(source.get(SCENE_SWITCH))


def refuse_if_off(env: Mapping[str, str] | None = None) -> None:
    if not scene_enabled(env):
        raise ClipAvatarRefused(SWITCHED_OFF, SWITCHED_OFF_TEXT, raw=f"{SCENE_SWITCH} is off")


# -- the saved character (the port m-25129385 implements) ---------------------------------


@dataclass(frozen=True)
class CharacterReference:
    """One saved character of the business as the scene sends it: the drawing's bytes
    exactly as Seedream gave them (never cropped nor recompressed), their content type,
    when it was drawn (the vendor accepts it for `CHARACTER_MAX_AGE`) and its provenance
    (provider, model id, prompt version, its asset — recorded in the scene's)."""

    character_id: UUID
    image: bytes
    content_type: str
    #: None (a drawing whose date is unknown) fails safe: it needs a new drawing (R7).
    drawn_at: datetime | None
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def too_old(self, now: datetime) -> bool:
        if self.drawn_at is None:
            return True
        drawn = self.drawn_at if self.drawn_at.tzinfo else self.drawn_at.replace(tzinfo=UTC)
        return now - drawn >= CHARACTER_MAX_AGE

    def data_url(self) -> str:
        """The drawing as the vendor's `data:` URL, byte for byte."""
        encoded = base64.b64encode(self.image).decode("ascii")
        return f"data:{self.content_type};base64,{encoded}"


class CharacterReferenceSource(Protocol):
    """One saved character of THIS business and brand (RLS) with its drawing's bytes,
    or None when it does not exist or is not saved (deleted, another business's, the
    switch off). Wired over m-25129385's `BusinessCharacterService.character_reference(
    tenant_id, brand_id, character_id)` (which returns the object key and raises
    `CharacterRefused`) plus `ObjectGate.open_business_character(tenant, brand, key)` for
    the bytes — see `business_character_source`."""

    def scene_character(
        self, *, tenant_id: UUID, brand_id: UUID, character_id: UUID
    ) -> CharacterReference | None: ...


def business_character_source(
    service: Any, open_object: Callable[[UUID, UUID, str], Any]
) -> CharacterReferenceSource:
    """The adapter over m-25129385 (duck-typed: its module is not on `main` yet).
    `service.character_reference(tenant_id, brand_id, character_id)` gives the saved
    character's key and provenance (`CharacterRefused` → None); `open_object(tenant,
    brand, key)` (`ObjectGate.open_business_character`) gives its bytes, never
    re-encoded — a file-like object or bytes."""

    class _Source:
        def scene_character(
            self, *, tenant_id: UUID, brand_id: UUID, character_id: UUID
        ) -> CharacterReference | None:
            try:
                found = service.character_reference(tenant_id, brand_id, character_id)
            except ValueError:  # `CharacterRefused` is a ValueError
                return None
            handle = open_object(tenant_id, brand_id, found.object_key)
            if hasattr(handle, "__enter__"):
                with handle as opened:
                    image = opened.read() if hasattr(opened, "read") else bytes(opened)
            else:
                image = handle.read() if hasattr(handle, "read") else bytes(handle)
            return CharacterReference(
                character_id=found.character_id,
                image=image,
                content_type=found.content_type,
                drawn_at=found.drawn_at,
                provenance={
                    "source": found.source,
                    "style": found.style,
                    "object_key": found.object_key,
                    "model_id": found.model_id,
                    "model_revision": found.model_revision,
                    "prompt_version": found.prompt_version,
                },
            )

    return _Source()


def check_character(reference: CharacterReference | None, now: datetime) -> None:
    """A scene's character before anything is written or paid: it exists, and its
    drawing is still one the vendor accepts (R7)."""
    if reference is None:
        raise ClipAvatarRefused(CHARACTER_MISSING, CHARACTER_MISSING_TEXT)
    if reference.too_old(now):
        raise ClipAvatarRefused(
            NEEDS_REDRAW,
            NEEDS_REDRAW_TEXT,
            raw=f"character {reference.character_id} drawn at {reference.drawn_at}",
        )


# -- the request digest (§12.2: what did not change is not paid again) --------------------


def scene_inputs(item: CharacterSceneItem) -> dict[str, Any]:
    """What makes a scene THE scene: character, product, place, line and length (not
    where it goes in the Clip, nor how it comes in)."""
    return {
        "character_id": str(item.character_id),
        "product_id": str(item.product.product_id),
        "product_photo_key": item.product.photo_key,
        "background_key": item.background.key,
        "background_source": item.background.source,
        "line": item.line,
        "duration": item.duration,
        "prompt_version": SCENE_PROMPT_VERSION,
    }


def scene_digest(item: CharacterSceneItem) -> str:
    """The scene's request digest: equal inputs, equal digest."""
    raw = json.dumps(scene_inputs(item), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def scene_request_key(tenant_id: UUID, item: CharacterSceneItem) -> UUID:
    """The digest as a request key of this business."""
    return uuid5(_SCENE_NAMESPACE, f"{tenant_id}:{scene_digest(item)}")


# -- the recipe checks (pure) ---------------------------------------------------------------


@dataclass(frozen=True)
class Join:
    """One blending join of the owner's stretches on the Clip's output timeline: the
    stretch it brings in (`index`) and the window the blend plays in."""

    index: int
    start: float
    end: float


def stretch_joins(lengths: Sequence[float], overlaps: Sequence[float]) -> tuple[Join, ...]:
    """Where each blending join plays: stretch `i` starts `overlaps[i]` seconds before
    the one before it ends (the block join's overlap, `recipe.block_overlaps`), and the
    blend is that overlap. Cuts (0) are left out. Pure."""
    joins: list[Join] = []
    position = 0.0
    for index, length in enumerate(lengths):
        overlap = overlaps[index] if index < len(overlaps) and index > 0 else 0.0
        start = position - overlap
        if overlap > 0:
            joins.append(Join(index=index, start=start, end=position))
        position = start + float(length)
    return tuple(joins)


@dataclass(frozen=True)
class SceneProblem:
    code: str
    text: str
    scene: int | None = None
    #: What the screen may offer to fix it in one touch (`CUT_ACTION`), or None.
    action: str | None = None


class CharacterSceneRefused(ClipAvatarRefused):
    """A scene refused before anything was written or paid: `ClipAvatarRefused` (its
    `code`, `owner_message` and `block` — the scene's place, from 0) plus the one-touch
    fix the screen may offer (`action`)."""

    def __init__(
        self,
        code: str,
        owner_message: str,
        raw: str = "",
        *,
        block: int | None = None,
        action: str | None = None,
    ) -> None:
        super().__init__(code, owner_message, raw, block=block)
        self.action = action


_EPSILON = 1e-6


def scene_problems(
    scenes: Sequence[CharacterSceneItem],
    *,
    clip_seconds: float,
    effects: Sequence[Any] = (),
    joins: Sequence[Join] = (),
) -> tuple[SceneProblem, ...]:
    """Every rule of §12.2 the schema cannot check alone, on the Clip's OUTPUT timeline
    (`clip_seconds`: its stretches at their speed minus the overlaps of its blends):
    no scene past the end; at least `LOCAL_TOTAL_MIN_S` of the owner's own video in view
    (P5 of §11); no smoke, embers or steam crossing a scene (§11 point 8); and no blend
    at a scene's exit (§12.6) — a join whose blend window reaches past the scene's end
    while starting at or before it. A blend that comes in at the scene's start, or lies
    wholly under it, is fine. Pure."""
    found: list[SceneProblem] = []
    for number, scene in enumerate(scenes):
        if scene.transition_in is not None:
            # until the assembly (PR 2 of m-25128784) draws a scene's way in, only a cut
            found.append(
                SceneProblem(
                    TRANSITION_UNAVAILABLE, transition_unavailable_text(number + 1), number
                )
            )
    for number, scene in enumerate(scenes):
        if scene.end > clip_seconds + _EPSILON:
            found.append(SceneProblem(PAST_END, past_end_text(number + 1), number))
    covered = sum(scene.duration for scene in scenes)
    if clip_seconds - covered < LOCAL_TOTAL_MIN_S - _EPSILON:
        found.append(SceneProblem(NEEDS_OWN_MEDIA, NEEDS_OWN_MEDIA_TEXT))
    for effect in effects:
        if effect.effect_id not in AVATAR_FORBIDDEN_EFFECTS:
            continue
        whole = effect.start_s is None or effect.end_s is None
        crossed = next(
            (
                number
                for number, scene in enumerate(scenes)
                if whole or (effect.start_s < scene.end and effect.end_s > scene.start)
            ),
            None,
        )
        if crossed is not None:
            found.append(SceneProblem(SCENE_EFFECT, effect_text(crossed + 1), crossed))
            break
    for number, scene in enumerate(scenes):
        exit_at = scene.end
        # Deliberately strict (review of cbbfbe77): ANY blend whose window starts at or
        # before the scene's end and runs past it is refused, even where the overlay may
        # end up hiding part of it — until PR 2's assembly decides exactly what plays at
        # a scene's exit, the voice's last word is never put at risk.
        if any(j.start <= exit_at + _EPSILON and j.end > exit_at + _EPSILON for j in joins):
            found.append(SceneProblem(EXIT_CUT_ONLY, exit_cut_text(number + 1), number, CUT_ACTION))
    return tuple(found)


def refuse_scene_problems(problems: Sequence[SceneProblem]) -> None:
    if problems:
        first = problems[0]
        raise CharacterSceneRefused(
            first.code,
            first.text,
            raw="; ".join(p.code for p in problems),
            block=first.scene,
            action=first.action,
        )


# -- the scene's brief, its prompt and its task ---------------------------------------------


def scene_brief(clip: ContentBrief, item: CharacterSceneItem) -> ContentBrief:
    """A scene's child brief: the Clip's brand, objective and topic; 9:16; exactly this
    scene in `character_scenes`. No recipe, no text of its own (the Clip carries it)."""
    media = MediaInputs.model_validate(
        {
            # the nearest bucket the brief allows — a label, never read for the scene's
            # real length: `character_scenes[0].duration` and the task's params carry it
            "duration_seconds": item.duration if item.duration in (5, 10) else 10,
            "character_scenes": (item.model_dump(mode="json"),),
        }
    )
    return ContentBrief.model_validate(
        {
            **clip.model_dump(exclude={"media", "kind", "format", "video_plan"}),
            "kind": ContentKind.CHARACTER_SCENE,
            "format": ContentFormat.REELS_9_16,
            "variants_requested": 1,
            "media": media,
        }
    )


def brand_line(kit: BrandKit | None) -> str:
    """Brand fidelity (rule 7): the palette and typefaces go into every prompt."""
    if kit is None:
        return ""
    palette = ", ".join(str(color) for color in kit.palette_rgb)
    fonts = " and ".join(font for font in (kit.font_heading, kit.font_body) if font)
    parts = []
    if palette:
        parts.append(f"Brand colors for any accents: {palette}")
    if fonts:
        parts.append(f"brand typefaces {fonts} (no on-screen text is wanted)")
    return ("; ".join(parts) + ".") if parts else ""


def scene_prompt(
    *, product_name: str, brand_name: str, background_source: str, kit: BrandKit | None
) -> str:
    """`personaje-escena-v1`: AVESC-001's `avatar-escena-v1` with the business's own
    product, place and brand. The line is NOT here: it goes as the task's dialogue (what
    Seedance 2.x speaks with lip-sync, in double quotes). Asks the product at its real
    size in the hand (R4)."""
    place = (
        "the owner's real place, exactly as in Image 3"
        if background_source == "photo"
        else "the place of Image 3"
    )
    product = f'"{product_name}" from {brand_name}' if brand_name else f'"{product_name}"'
    return " ".join(
        part
        for part in (
            "A vertical 9:16 video, one continuous shot, natural light and realistic motion.",
            "Image 1 is the character: keep the same face, hair, body, clothes and style "
            "through the whole video.",
            f"Image 2 is the client's real product, {product}: keep its exact shape, layers "
            "and colors, at its real size in the character's hand, never another product.",
            f"Image 3 is the place: the scene happens in {place}.",
            "Action: the character picks up the product, shows it to the camera and enjoys "
            "it, then speaks to the camera.",
            "The character speaks in neutral Latin American Spanish, lips in sync with the "
            "words, a friendly natural voice, no background music.",
            "No captions, no subtitles, no logos, no watermark.",
            brand_line(kit),
        )
        if part
    )


def scene_params(
    *,
    prompt: str,
    line: str,
    seconds: int,
    character_url: str,
    product_url: str,
    background_url: str,
    model: str = SCENE_MODEL,
) -> dict[str, Any]:
    """`request.params` for the Seedance adapter: ONE omni-reference task with the three
    images in order (character, product, place), sound on, the line as dialogue, as a
    480p draft whose task id becomes the 1080p final at approval (§12.4)."""
    from qualify_creative.adapters.byteplus_ark import DRAFT_RESOLUTION  # noqa: PLC0415

    return {
        "model": model,
        "prompt": prompt,
        "dialogue": line,
        "reference_images": [character_url, product_url, background_url],
        "omni_reference_task_type": "reference",
        "ratio": SCENE_RATIO,
        "duration_seconds": int(seconds),
        "generate_audio": True,
        "draft": True,
        "resolution": DRAFT_RESOLUTION,
    }


def scene_quote_usd(pricing: Any, seconds: int, *, model: str = SCENE_MODEL) -> Decimal:
    """What a scene's 480p draft costs by the versioned table (the token formula at the
    output size, no reference video) — the guard's own estimate, for the screen and the
    provenance."""
    from qualify_creative.adapters.byteplus_ark import (  # noqa: PLC0415
        DRAFT_RESOLUTION,
        estimate_video_tokens,
        video_cost_usd,
    )

    tokens = estimate_video_tokens(model, DRAFT_RESOLUTION, SCENE_RATIO, int(seconds))
    return video_cost_usd(pricing, model, DRAFT_RESOLUTION, tokens)


def model_problem(model: str) -> str | None:
    """Why a scene cannot be made on `model`, or None: it needs a draft mode AND omni
    references (Seedance 2.5)."""
    from qualify_creative.adapters.byteplus_ark import seedance_family  # noqa: PLC0415

    try:
        family = seedance_family(model)
    except ValueError:
        return f"unknown Seedance model {model!r}"
    if not (family.draft and family.omni_task_types):
        return f"{model} has no draft mode with omni references: a scene runs on Seedance 2.5"
    return None


def is_redraw_refusal(raw: str | None) -> bool:
    """The vendor took the character for a real person (R7): it needs a new drawing."""
    return "PrivacyInformation" in (raw or "")


def produce_scene(
    producer: Any,
    *,
    tenant_id: UUID,
    draft_id: UUID,
    brief: ContentBrief,
    kit: BrandKit | None,
    budget: Any,
    usage: list[Any],
    save: Callable[[str, bytes, str], str],
    now: datetime | None = None,
) -> list[Any]:
    """The scene's 480p draft (the media producer's `_character_scene`). Everything that
    can refuse without a vendor call does first — the source wired, the model, the
    character found and not too old, the files read; then ONE Seedance task through the
    router (price guard, vendor task record, usage with its cost). A refusal of the
    character as a real face becomes `character_needs_redraw`. Raises the producer's own
    `_MediaFailed` / `_MediaPending`."""
    from qualify_creative.adapters.byteplus_ark import output_dimensions  # noqa: PLC0415
    from qualify_creative.enums import GenerationTask  # noqa: PLC0415
    from qualify_creative.photo.normalize import to_reference_jpeg  # noqa: PLC0415
    from qualify_creative.providers import GenerationRequest, RenderedPrompt  # noqa: PLC0415

    from qualify_api.creative import media as m  # noqa: PLC0415

    item = brief.media.character_scenes[0]
    references: CharacterReferenceSource | None = getattr(producer, "_character_references", None)
    if references is None:
        raise m._MediaFailed(  # noqa: SLF001
            FailureReason.INVALID_PARAMETERS.value,
            UNAVAILABLE_TEXT,
            raw="no character reference source wired",
        )
    model = SCENE_MODEL
    problem = model_problem(model)
    if problem is not None:
        raise m._MediaFailed(  # noqa: SLF001
            FailureReason.INVALID_PARAMETERS.value, UNAVAILABLE_TEXT, raw=problem
        )
    character = references.scene_character(
        tenant_id=tenant_id, brand_id=brief.brand_id, character_id=item.character_id
    )
    try:
        check_character(character, now or datetime.now(UTC))
    except ClipAvatarRefused as refused:
        reason = (
            FailureReason.CHARACTER_NEEDS_REDRAW.value
            if refused.code == NEEDS_REDRAW
            else FailureReason.INVALID_PARAMETERS.value
        )
        raise m._MediaFailed(reason, refused.owner_message, raw=str(refused)) from refused  # noqa: SLF001
    assert character is not None
    product = producer._read(item.product.photo_key)  # noqa: SLF001
    place = producer._read(item.background.key)  # noqa: SLF001
    if product is None or place is None:
        raise m._MediaFailed(  # noqa: SLF001
            FailureReason.INVALID_PARAMETERS.value, FILE_NOT_OWNED_TEXT, raw="a scene file is gone"
        )
    product_name, brand_name = _names(producer, tenant_id, brief, item)
    prompt = scene_prompt(
        product_name=product_name,
        brand_name=brand_name,
        background_source=item.background.source,
        kit=kit,
    )
    params = scene_params(
        prompt=prompt,
        line=item.line,
        seconds=item.duration,
        character_url=character.data_url(),
        product_url=m._jpeg_url(to_reference_jpeg(product)),  # noqa: SLF001
        background_url=m._jpeg_url(to_reference_jpeg(place)),  # noqa: SLF001
        model=model,
    )
    request = GenerationRequest(
        task=GenerationTask.SCENE_VIDEO,
        rendered_prompt=RenderedPrompt("", "", ""),
        params=params,
    )
    try:
        result = producer._run(  # noqa: SLF001
            tenant_id=tenant_id,
            brand_id=brief.brand_id,
            link=m.SEEDANCE,
            request=request,
            budget=budget,
            usage=usage,
        )
    except m._MediaFailed as exc:  # noqa: SLF001
        if is_redraw_refusal(exc.raw):
            raise m._MediaFailed(  # noqa: SLF001
                FailureReason.CHARACTER_NEEDS_REDRAW.value, NEEDS_REDRAW_TEXT, raw=exc.raw
            ) from exc
        raise
    payload = dict(result.payload) if isinstance(result.payload, dict) else {}
    resolution = str(payload.get("resolution") or params["resolution"])
    cost = producer._seedance_usage(result, resolution, usage)  # noqa: SLF001
    video = producer._download(str(result.media_url))  # noqa: SLF001
    width, height = output_dimensions(result.model_id, resolution, SCENE_RATIO)
    key = save("scene.mp4", video, m.MP4)
    provenance = scene_provenance(
        item,
        character=character,
        provider=result.provider,
        model_id=result.model_id,
        task_id=payload.get("task_id"),
        seconds=payload.get("duration_seconds"),
        cost_usd=cost,
    )
    return [
        m.MediaWrite(
            position=0,
            media_type="video",
            media_url=key,
            object_key=key,
            width=width,
            height=height,
            aspect_ratio=SCENE_RATIO,
            model_id=result.model_id,
            provider=result.provider,
            content_type=m.MP4,
            ai_generated=True,
            params=m._with_draft(  # noqa: SLF001
                {
                    "task_id": payload.get("task_id"),
                    "generation_prompt": prompt,
                    "prompt_version": SCENE_PROMPT_VERSION,
                    "duration_seconds": payload.get("duration_seconds"),
                    "resolution": resolution,
                    "tokens": int(result.usage.output_tokens),
                    "spoken": bool(payload.get("generate_audio")),
                    "model_revision": result.model_revision,
                    "ai_generated": True,
                    "character_scene": provenance,
                },
                payload,
                model_id=result.model_id,
                ratio=SCENE_RATIO,
                seconds=item.duration,
                cost_usd=cost,
                finish=m.FINISH_VIDEO,
            ),
        )
    ]


def _names(
    producer: Any, tenant_id: UUID, brief: ContentBrief, item: CharacterSceneItem
) -> tuple[str, str]:
    """The product's and the brand's names for the prompt (best effort: a catalog that
    cannot say leaves «the product»)."""
    product_name = "the product"
    catalog = getattr(producer, "_catalog", None)
    if catalog is not None:
        try:
            found = catalog.products_for(
                tenant_id=tenant_id,
                brand_id=brief.brand_id,
                product_ref=str(item.product.product_id),
            )
        except Exception:  # noqa: BLE001 — a name is not worth failing the scene
            found = ()
        name = getattr(found[0], "name", None) if found else None
        if isinstance(name, str) and name.strip():
            product_name = name.strip()
    brand_name = ""
    names = getattr(producer, "_brand_names", None)
    if names is not None:
        try:
            brand_name = str(names(tenant_id=tenant_id, brand_id=brief.brand_id) or "")
        except Exception:  # noqa: BLE001 — a name is not worth failing the scene
            brand_name = ""
    return product_name, brand_name


def scene_provenance(
    item: CharacterSceneItem,
    *,
    character: CharacterReference,
    provider: str,
    model_id: str,
    task_id: Any,
    seconds: Any,
    cost_usd: Decimal,
) -> dict[str, Any]:
    """What the scene's asset records (§12.7; the Clip's `params.local.character_scenes`
    copies it when it is assembled)."""
    return {
        "version": CHARACTER_SCENE_VERSION,
        "provider": provider,
        "model_id": model_id,
        "prompt_version": SCENE_PROMPT_VERSION,
        "request_digest": scene_digest(item),
        "character_id": str(item.character_id),
        "character": dict(character.provenance),
        "character_drawn_at": character.drawn_at.isoformat() if character.drawn_at else None,
        "product_id": str(item.product.product_id),
        "product_photo_key": item.product.photo_key,
        "background_key": item.background.key,
        "background_source": item.background.source,
        "line": item.line,
        "line_suggested": item.line_suggested,
        "line_prompt_version": item.line_prompt_version,
        "seconds_requested": item.duration,
        "seconds": seconds,
        "draft_task_id": task_id,
        "draft_cost_usd": str(cost_usd),
    }


# -- the store: what the daily cap and the month read ----------------------------------------


class CharacterSceneStore(Protocol):
    def scenes_of(self, *, tenant_id: UUID, clip_id: UUID) -> tuple[UUID, ...]: ...

    def scenes_made_today(self, *, tenant_id: UUID) -> int: ...

    def pending_scene_seconds(self, *, tenant_id: UUID, brand_id: UUID) -> tuple[int, int]: ...


class PostgresCharacterSceneStore:
    """Every read through `tenant_session` (RLS)."""

    def scenes_of(self, *, tenant_id: UUID, clip_id: UUID) -> tuple[UUID, ...]:
        """The Clip's scenes, by slot."""
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            rows = session.execute(
                text("""
                SELECT d.id FROM content_drafts d JOIN content_briefs b ON b.id = d.brief_id
                WHERE d.parent_draft_id = :c AND b.kind = 'character_scene'
                ORDER BY d.part_index
            """),
                {"c": clip_id},
            ).all()
        return tuple(row.id for row in rows)

    def scenes_made_today(self, *, tenant_id: UUID) -> int:
        """§9's daily count, which counts avatar blocks AND scenes (each attempt that
        paid, retries included), under the business's lock."""
        from qualify_api.creative.clip_avatar import PostgresClipAvatarStore  # noqa: PLC0415

        return PostgresClipAvatarStore().blocks_made_today(tenant_id=tenant_id)

    def pending_scene_seconds(self, *, tenant_id: UUID, brand_id: UUID) -> tuple[int, int]:
        """(scenes, requested seconds) of the brand's live scenes not charged yet whose
        Clip is not approved nor failed — in any Clip, whatever month (§12.1, P6)."""
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            rows = session.execute(
                text("""
                SELECT COALESCE((b.media->'character_scenes'->0->>'duration')::int, 0) AS s
                FROM content_drafts d
                JOIN content_briefs b ON b.id = d.brief_id
                JOIN content_drafts p ON p.tenant_id = d.tenant_id AND p.id = d.parent_draft_id
                WHERE d.brand_id = :brand AND b.kind = 'character_scene'
                  AND d.part_removed_at IS NULL AND d.status <> 'failed'
                  AND p.status NOT IN ('approved', 'staged', 'published', 'failed')
                  AND p.media_purged_at IS NULL AND d.media_purged_at IS NULL
                  AND NOT EXISTS (SELECT 1 FROM creation_charges c
                                  WHERE c.draft_id = d.id AND c.videos > 0)
            """),
                {"brand": brand_id},
            ).all()
        return len(rows), sum(int(row.s) for row in rows)


# -- the service -----------------------------------------------------------------------------


@dataclass(frozen=True)
class ClipWithScenes:
    """What `create_clip_with_scenes` gives back: the Clip and its scenes, by slot."""

    clip_id: UUID
    scene_ids: tuple[UUID, ...]


class CharacterSceneService:
    """Creates a `local` Clip with its «Personajes» track: the Clip and one child draft
    per scene, born together. Built over the `ContentService` that owns drafts, quota and
    dispatch, and over `ClipAvatarService`'s transaction helpers."""

    def __init__(
        self,
        content: Any,
        *,
        references: CharacterReferenceSource,
        store: CharacterSceneStore | None = None,
        env: Mapping[str, str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        from qualify_api.creative.clip_avatar import ClipAvatarService  # noqa: PLC0415

        self._content = content
        self._references = references
        self._store = store or PostgresCharacterSceneStore()
        self._env = env
        self._clock = clock or (lambda: datetime.now(UTC))
        # its transaction and insert helpers (the lock, the unit of work, the bare insert)
        self._tx = ClipAvatarService(content, store=_NoBlocks(), env=env)

    def scenes_left_today(self, *, tenant_id: UUID) -> int:
        """How many scenes the business may still create today (for the screen)."""
        used = int(self._store.scenes_made_today(tenant_id=tenant_id))
        return max(0, SCENE_DAILY_CAP - used)

    def create_clip_with_scenes(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        user_id: UUID,
        brief: ContentBrief,
        request_key: UUID | None = None,
    ) -> ClipWithScenes:
        """A `local` Clip and its character scenes (`brief.media.character_scenes`), born
        together and dispatched after ONE commit: each scene is made as a 480p draft, the
        Clip waits for them. Every rule is checked BEFORE anything is written and before
        any paid call (paid calls only start in the worker, after the commit): the
        switch, the recipe with its scenes, the files, the characters, the brand, today's
        cap, the month's vistas previas and video seconds, the Clip's own price.
        `request_key`: the same «Crear» again returns what it made and dispatches
        nothing (`ClipAvatarRefused`, `NotEnoughCreations`, `BrandNotReady`,
        `RouteBlockedByPolicy`, `RecipeRefused` otherwise)."""
        from qualify_api.creative.media import owned_by  # noqa: PLC0415
        from qualify_api.creative.service import DuplicateDraftRequest  # noqa: PLC0415
        from qualify_api.creative.video_pipeline.local import is_local_recipe  # noqa: PLC0415

        # 1. what needs no read
        refuse_if_off(self._env)
        media = brief.media
        scenes = media.character_scenes
        if not scenes:
            raise ValueError("a Clip with scenes has at least one")
        if brief.brand_id != brand_id:
            raise ValueError("brief.brand_id does not match brand_id")
        if media.clip_avatar_plan or media.clip_avatar_block:
            raise ValueError("a Clip with character scenes has no avatar plan")
        if media.part is not None or not is_local_recipe(brief):
            raise ClipAvatarRefused(NOT_LOCAL, NOT_LOCAL_TEXT)
        refuse_scene_problems(timeline_problems(brief))
        for number, item in enumerate(scenes):
            keys = (item.product.photo_key, item.background.key)
            if any(not owned_by(tenant_id, key) for key in keys):
                raise ClipAvatarRefused(
                    FILE_NOT_OWNED, FILE_NOT_OWNED_TEXT, raw="a file of another", block=number
                )
        now = self._clock()
        for number, character_id in _distinct(item.character_id for item in scenes):
            reference = self._references.scene_character(
                tenant_id=tenant_id, brand_id=brand_id, character_id=character_id
            )
            try:
                check_character(reference, now)
            except ClipAvatarRefused as refused:
                raise ClipAvatarRefused(
                    refused.code, refused.owner_message, raw=str(refused), block=number
                ) from refused
        # 2. reads, nothing written
        repo = self._content.repository
        if request_key is not None:
            existing = repo.draft_id_for_request(tenant_id=tenant_id, request_key=request_key)
            if existing is not None:
                return self._made(tenant_id, existing)
        inputs = self._content.new_draft_inputs(tenant_id=tenant_id, brand_id=brand_id, brief=brief)
        clip_brief = inputs.brief
        if clip_brief.media.character_scenes != scenes:  # the producer's stamp keeps them
            raise RuntimeError("a Clip's character scenes were lost while being prepared")
        prepared = [
            self._content.prepare_new_generation(
                tenant_id=tenant_id, brand_id=brand_id, brief=scene_brief(clip_brief, item)
            )
            for item in sorted(scenes, key=lambda s: s.start)
        ]
        seconds = sum(item.duration for item in scenes)

        # 3. one transaction under the business's lock
        def write() -> list[UUID]:
            if request_key is not None:
                existing = repo.draft_id_for_request(tenant_id=tenant_id, request_key=request_key)
                if existing is not None:
                    raise DuplicateDraftRequest(existing)
            self._check_daily_cap(tenant_id, asking=len(scenes))
            self._check_month(tenant_id, brand_id, scenes=len(scenes), seconds=seconds)
            insert = self._tx._bare_insert()  # noqa: SLF001
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
            for slot, (stamped, voice_version, pipeline_version) in enumerate(prepared, 1):
                scene_id = insert(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    brief=stamped,
                    voice_profile_version=voice_version,
                    pipeline_version=pipeline_version,
                    request_key=None,
                    parent_draft_id=clip_id,
                    part_index=slot,
                )
                if creations is not None:
                    # 1 vista previa now (D7), given back by the run when nothing comes
                    # out; its seconds are taken at the Clip's approval
                    creations.charge(
                        tenant_id=tenant_id,
                        brand_id=brand_id,
                        draft_id=scene_id,
                        revision=1,
                        price=character_scene_price(stamped.media.character_scenes[0].duration),
                    )
                made.append(scene_id)
            # the scenes first, then the Clip (it waits for them)
            return [*made, clip_id]

        try:
            ids = self._tx._write_and_dispatch(tenant_id, write)  # noqa: SLF001
        except DuplicateDraftRequest as duplicate:
            return self._made(tenant_id, duplicate.draft_id)
        clip_id, scene_ids = ids[-1], tuple(ids[:-1])
        logger.info(
            "clip %s: created with %d character scene(s) (%ss) it waits for",
            clip_id,
            len(scene_ids),
            seconds,
        )
        return ClipWithScenes(clip_id=clip_id, scene_ids=scene_ids)

    def _made(self, tenant_id: UUID, clip_id: UUID) -> ClipWithScenes:
        """What an earlier «Crear» with the same key made: the Clip and its scenes."""
        ids = self._store.scenes_of(tenant_id=tenant_id, clip_id=clip_id)
        return ClipWithScenes(clip_id=clip_id, scene_ids=tuple(ids))

    def _check_daily_cap(self, tenant_id: UUID, *, asking: int) -> None:
        used = int(self._store.scenes_made_today(tenant_id=tenant_id))
        if used + asking <= SCENE_DAILY_CAP:
            return
        left = max(0, SCENE_DAILY_CAP - used)
        words = DAILY_CAP_TEXT if left == 0 else daily_left_text(left, asking)
        raise ClipAvatarRefused(
            SCENE_DAILY_CAP_CODE,
            words,
            raw=f"{used} scenes today, cap {SCENE_DAILY_CAP}, asking {asking}",
        )

    def _check_month(self, tenant_id: UUID, brand_id: UUID, *, scenes: int, seconds: int) -> None:
        """No paid call without quota: 1 vista previa per scene now, and the month's video
        must pay at approval these seconds plus every uncharged scene of the brand."""
        creations = self._content.creations
        if creations is None:
            return
        from qualify_api.creative.creations import NotEnoughCreations  # noqa: PLC0415

        balance = creations.balance(tenant_id=tenant_id, brand_id=brand_id)
        if not balance.can_pay(0, previews=scenes):
            raise NotEnoughCreations(
                previews=scenes if balance.preview_quota > 0 else 0,
                previews_left=balance.previews_left,
            )
        pending, pending_seconds = self._store.pending_scene_seconds(
            tenant_id=tenant_id, brand_id=brand_id
        )
        needed = seconds + pending_seconds if balance.video_in_seconds else scenes + pending
        short = balance.video_shortfall(needed)
        if short is not None:
            raise short


class _NoBlocks:
    """`ClipAvatarService` is only used here for its transaction helpers: it reads no
    block."""

    def blocks_made_today(self, *, tenant_id: UUID) -> int:  # pragma: no cover
        return 0


def _distinct(values: Iterable[UUID]) -> list[tuple[int, UUID]]:
    seen: dict[UUID, int] = {}
    for number, value in enumerate(values):
        seen.setdefault(value, number)
    return [(number, value) for value, number in seen.items()]


def timeline_problems(brief: ContentBrief) -> tuple[SceneProblem, ...]:
    """`scene_problems` on a `local` Clip's own recipe: its output length and the blends
    of its stretches as the block join draws them (`recipe.block_overlaps`)."""
    from qualify_api.creative.video_pipeline.recipe import (  # noqa: PLC0415
        SPEED_FPS,
        block_overlaps,
        clip_seconds,
        recipe_of,
    )

    (part,) = recipe_of(brief)
    overlaps = [frames / SPEED_FPS for frames in block_overlaps(part)]
    lengths = [segment.output_seconds for segment in part.segments]
    return scene_problems(
        brief.media.character_scenes,
        clip_seconds=clip_seconds(part),
        effects=brief.media.effects,
        joins=stretch_joins(lengths, overlaps),
    )


def seconds_of(scenes: Sequence[CharacterSceneItem]) -> int:
    """The month's video seconds a Clip with these scenes takes at approval."""
    return sum(math.ceil(scene.duration) for scene in scenes)
