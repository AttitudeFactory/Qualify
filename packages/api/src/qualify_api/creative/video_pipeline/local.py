"""«Tu video, con efectos» made here, at cost 0 (EF-06, m-25026574, ADR 50): a `local`
Clip — or a `local` part of a video by parts, a child Clip — is the owner's OWN stretches
(`segments`: videos and still photos) prepared, sped up and laid end to end. No vendor is
called, no `vendor_slots` slot is held and nothing is charged (D3).

How it runs. `ContentService` stamps `effects_pipeline_version = LOCAL_EFFECTS_PIPELINE_
VERSION` on a new brief whose recipe is a `local` part with stretches
(`effects_version_for`); `MediaProducer._produce` hands such a Clip to `produce_local`
BEFORE any Brand Kit read, resource selection or vendor call. It runs in the
`creative-worker`'s preparation of the draft's `preview` job (`PipelinePreparation` →
`run_generation`): the job never leaves `queued` for a slot — `_settle_local` closes it
like an image's, once the draft is `generated`. Outside the worker (the `inline`
dispatcher, a Reflex thread) it is refused: nothing is decoded inside Reflex.

The steps, per stretch in the recipe's order:

1. its file is copied from R2 to a temporary folder through the tenant-checking door
   (`R2ReadingMediaStore.copy_to_file` → `qualify_shared.objects.ObjectGate`), after
   `validate_recipe(…, tenant_id=…)` and `owned_by` refused any key that is not this
   business's — another business's stretch is never read;
2. a video is «Preparado» (EF-03: upright, 9:16, its `[start_s, end_s)`) and its SOUND
   kept beside it, cut to the same instants (m-25049580, `prepare(keep_audio=True)`: a
   16-bit WAV sidecar, none when the file has no sound); a photo is held still for its
   `end_s` seconds (`video.photo_hold`, D-T1) at the prepared size;
3. «Cámara rápida» (EF-04) lays every stretch end to end at its `speed` (a photo at 1), 30
   fps, hard cuts, no gaps: the video lasts the sum of the stretches at their speed. Its
   sound (m-25049580, `render_speed(resolve_audio=…)`) is ONE AAC-LC 48 kHz stereo 128
   kbps track for the whole video — `join`'s format: a ×1 stretch keeps its original sound,
   trimmed to its picture; a sped-up stretch, a photo or a file without sound is silence of
   its length; 80 ms fades at the cuts. The layers and the texts (4, 5) copy that track as
   it is;
4. «Humo», «Brasas», «Vapor» (EF-08, `qualify_creative.video.layer_overlay`): each use of
   a library layer in the part's `effects` (its entry at its version, through
   `TimedEffectLayer.from_entry` and the read-only `effects.layer_loop_file`; its params, or
   the entry's defaults) is screen-blended over the built video for its `[start_s, end_s)`
   — seconds of THIS part's output — BEFORE the texts, so the words stay on top and
   readable; skipped (no second encode) when there is no layer; with texts the layers and
   the texts go in ONE pass (`compose_text_layers(..., effect_layers=...)` →
   `layer_overlay.overlay_layers_and_texts`: one decode, one encode);
5. «Textos sobre el video» (EF-05, `compose.compose_text_layers`): the part's (or Clip's)
   `text_layers` drawn by our own render service (Remotion, cost 0, in the Brand Kit's
   typeface and palette) and laid over the built video with each text's own fade
   (`fade_s`); skipped when there is no text;
6. the MP4 (and a poster) are kept in R2 under the draft's revision (`_Saver`, retried);
7. its contact sheet (EF-18, `contact_sheet.keep_contact_sheet`): six frames of the
   composed video kept beside it, in `params["contact_sheet"]` — best effort, still
   inside the heavy-video gate.

Provenance (rule 6) in the asset's `params.local`: the recipe contract, the effects
pipeline version, the pricing table (`LOCAL_PRICING_VERSION`, where `local_video` costs
0.00 a second), the steps' versions, the speed step's own `SpeedResult.params()` (its
`sound`: format and stretches with their own sound), `sound` (per stretch of the recipe,
whether it carries its original sound and why not), and, when
there are texts, the compose step's own `params["text_layers"]`, and, when there are
layers, `effect_layers` (each use's `TimedEffectLayer.params()`: effect, version,
intensity, zone, span, the loop's sha256, cost 0) with `steps["layer_compose"]`. The
asset carries no `draft` block (there is no Seedance final to order: it is publishable
as it is) and `ai_generated=False` — Instagram's «hecho con IA» is read from what was
made, not from the kind.

Idempotent: a retried preparation renders again into the same revision's keys and the
service rewrites the same revision's assets; the charge is one zero row per revision.
"""

from __future__ import annotations

import io
import logging
import tempfile
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from qualify_creative.enums import ContentKind, FailureReason
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.schemas import ContentBrief, PartRecipe, PartRef, SourceSegment

from qualify_api.creative.contact_sheet import CONTACT_SHEET_PARAMS_KEY, keep_contact_sheet
from qualify_api.creative.heavy_video import assembling
from qualify_api.creative.media import (
    JPEG,
    MP4,
    MediaOutcome,
    MediaUsage,
    MediaWrite,
    owned_by,
)
from qualify_api.creative.video_pipeline.local_sources import LocalSources, with_provenance
from qualify_api.creative.video_pipeline.recipe import (
    is_built_layer,
    recipe_of,
    validate_recipe,
)

logger = logging.getLogger(__name__)

#: The `effects_pipeline_version` the server stamps on a `local` recipe with stretches.
LOCAL_EFFECTS_PIPELINE_VERSION = 1
#: The pricing table that prices a local video (`local_video`: 0.00 a second). A new
#: price is a new table, never an edit of this one.
LOCAL_PRICING_VERSION = "v10"
LOCAL_MODEL_ID = "local_video"
LOCAL_PROVIDER = "local"
LOCAL_UNIT = "per_second"
#: Version of this module's recipe (the order of the steps) — provenance. v2
#: (m-25049580): the ×1 stretches keep their original sound.
LOCAL_RECIPE_VERSION = "local-v2"
#: The recipe contract the stretches were read with (ED-15, m-25029105: v2).
RECIPE_CONTRACT_VERSION = 2
#: The temporary folder's prefix (one per run, removed when it ends).
_WORKDIR_PREFIX = "qualify-local-"

#: What the owner reads when the video could not be made (Spanish, `qualify-copy-es`:
#: the screen calls them «Fotos y videos»; no button is named — a failed piece shows its
#: own action).
LOCAL_SOURCE_FAILED_TEXT = (
    "No pudimos armar tu video con las fotos y videos que elegiste. Prueba con otras o "
    "inténtalo de nuevo."
)
LOCAL_MISSING_TEXT = (
    "Ya no encontramos una de las fotos o videos que elegiste. Cámbiala por otra y vuelve a "
    "crear el video."
)
LOCAL_READ_FAILED_TEXT = (
    "No pudimos abrir tus fotos y videos en este momento. Inténtalo de nuevo en un rato."
)
LOCAL_SAVE_FAILED_TEXT = "No pudimos guardar tu video. Inténtalo de nuevo en un rato."
LOCAL_PART_SAVE_FAILED_TEXT = (
    "No pudimos guardar el video de esta parte. Inténtalo de nuevo en un rato."
)
LOCAL_PART_FAILED_TEXT = (
    "No pudimos armar esta parte con las fotos y videos que elegiste. Prueba con otras o "
    "inténtalo de nuevo."
)
#: Outside the creative worker (the `inline` dispatcher): never decoded in Reflex.
LOCAL_NEEDS_WORKER_TEXT = (
    "Por ahora no podemos armar videos con tus fotos y videos. Elige otra forma de crearlo."
)
#: The texts could not be laid over the built video for a reason of ours (the built video
#: unreadable or not 9:16, `TextOverlayError`): that error's message is technical and in
#: English, never shown. A local piece never takes a creation, so the promise holds.
LOCAL_COMPOSE_FAILED_TEXT = (
    "No pudimos terminar tu video por un problema nuestro. No se descontó de tus creaciones. "
    "Inténtalo de nuevo en unos minutos."
)
LOCAL_PART_COMPOSE_FAILED_TEXT = (
    "No pudimos terminar el video de esta parte por un problema nuestro. No se descontó de "
    "tus creaciones. Inténtalo de nuevo en unos minutos."
)
#: A layer (smoke, embers, steam) could not be laid for a reason of ours (EF-08,
#: `LayerOverlayError`): its own notice, which also offers the way out — removing the
#: effect finishes the piece now.
LOCAL_LAYER_FAILED_TEXT = (
    "No pudimos poner el efecto en tu video por un problema nuestro. No se descontó de tus "
    "creaciones. Inténtalo de nuevo en unos minutos o quita el efecto para terminarlo ya."
)
LOCAL_PART_LAYER_FAILED_TEXT = (
    "No pudimos poner el efecto en esta parte por un problema nuestro. No se descontó de tus "
    "creaciones. Inténtalo de nuevo en unos minutos o quita el efecto para terminarlo ya."
)
#: m-25042483: a video stretch takes over `SEGMENT_SOURCE_MAX_S` (60 s) of its video —
#: the owner's to fix (refused before anything is created, `segment_source_too_long`;
#: this is the worker's backstop and the words the editor shows in «Cortar»). Reviewed
#: by ux-designer 2026-11-17: «tomar … aunque lo aceleres» (the reel may last 9 s), «1
#: minuto» (not compared with the reel's seconds), both ways out.
LOCAL_SOURCE_TOO_LONG_TEXT = (
    "Cada pedazo puede tomar hasta 1 minuto de tu video, aunque lo aceleres. Acorta el "
    "pedazo más largo o pártelo en dos con «Cortar», y vuelve a crear el video."
)
LOCAL_PART_SOURCE_TOO_LONG_TEXT = (
    "Cada pedazo puede tomar hasta 1 minuto de tu video, aunque lo aceleres. Acorta el "
    "pedazo más largo o pártelo en dos con «Cortar», y vuelve a crear esta parte."
)
#: A part says «esta parte» where the whole piece says «tu video».
_PART_TEXTS = {
    LOCAL_SOURCE_FAILED_TEXT: LOCAL_PART_FAILED_TEXT,
    LOCAL_SAVE_FAILED_TEXT: LOCAL_PART_SAVE_FAILED_TEXT,
    LOCAL_COMPOSE_FAILED_TEXT: LOCAL_PART_COMPOSE_FAILED_TEXT,
    LOCAL_LAYER_FAILED_TEXT: LOCAL_PART_LAYER_FAILED_TEXT,
    LOCAL_SOURCE_TOO_LONG_TEXT: LOCAL_PART_SOURCE_TOO_LONG_TEXT,
}
#: How often the preparation's lease is renewed while the video is made (None =
#: `lease_kept`'s own, a third of the lease). Tests shorten it.
LEASE_RENEW_EVERY_S: float | None = None


class LocalVideoFailed(Exception):
    """The local video could not be made: `failure` (a `FailureReason` value), a stable
    `code` (`unreadable`, `missing`, `read_failed`, `save_failed`, `foreign`, `source`,
    `price`, the layer step's `layer_overlay_failed`, and the compose step's
    `text_layer_unavailable`, `text_layer_rejected`, `text_layer_refused`,
    `text_overlay_failed`), the owner's `detail`; `raw` only reaches
    the log. None of them charges anything: a local piece never takes a creation."""

    def __init__(self, failure: str, detail: str, raw: str = "", *, code: str = "source") -> None:
        super().__init__(raw or detail)
        self.failure = failure
        self.detail = detail
        self.raw = raw
        self.code = code


def is_local_recipe(brief: ContentBrief) -> bool:
    """A Clip (a normal one, or a part's child) whose recipe is ONE `local` part made of
    stretches — what this module produces. Pure."""
    if brief.kind is not ContentKind.CLIP:
        return False
    parts = recipe_of(brief)
    return len(parts) == 1 and parts[0].mode == "local" and bool(parts[0].segments)


def effects_version_for(brief: ContentBrief) -> int:
    """The `effects_pipeline_version` the server stamps on a NEW brief: this module's for
    a `local` recipe with stretches, EF-14's for a Clip made by Seedance with texts or
    layers to compose (`recompose.composes_over_seedance`), 0 (made as before EF-06) for
    anything else. Pure."""
    from qualify_api.creative.video_pipeline.recompose import (  # noqa: PLC0415
        SEEDANCE_COMPOSE_EFFECTS_VERSION,
        composes_over_seedance,
    )

    if is_local_recipe(brief):
        return LOCAL_EFFECTS_PIPELINE_VERSION
    return SEEDANCE_COMPOSE_EFFECTS_VERSION if composes_over_seedance(brief) else 0


def local_price(seconds: float) -> Decimal:
    """What `seconds` of local video cost, read off `LOCAL_PRICING_VERSION` — the price
    guard of a step that calls no vendor: anything but 0 is refused by the caller."""
    rate = JsonPricingTable(LOCAL_PRICING_VERSION).unit_price(
        model_id=LOCAL_MODEL_ID, unit=LOCAL_UNIT
    )
    return (rate * Decimal(str(round(seconds, 3)))).quantize(Decimal("0.01"))


@dataclass(frozen=True)
class LocalRender:
    """The rendered video on disk and what its asset records."""

    path: Path
    width: int
    height: int
    seconds: float
    frames: int
    speed: dict[str, Any]
    steps: dict[str, Any]
    warnings: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    #: The compose step's provenance (`compose_text_layers(...).params["text_layers"]`),
    #: None when the part has no text (the step did not run).
    text_layers: dict[str, Any] | None = None
    #: The layer step's provenance (`compose_version` and each use's `params()`), None
    #: when the part has no layer (the step did not run).
    effect_layers: dict[str, Any] | None = None
    #: m-25042483: the video stretches' files as read (`local_sources.LocalSources`): each
    #: one's original key, normalized copy and normalizer version for the provenance.
    sources: Any = None
    #: m-25049580: the sound's provenance (`_sound_provenance`), None for a silent render.
    sound: dict[str, Any] | None = None


def _reference(index: int, segment: SourceSegment) -> str:
    """The speed step's opaque reference of a stretch: its place and its file (a file may
    give several stretches, each prepared on its own)."""
    return f"segments[{index}]:{segment.key}"


def _missing(exc: BaseException) -> bool:
    from qualify_api.creative.part_join import _missing as missing  # noqa: PLC0415

    return missing(exc)


def _fetch(store: Any, tenant_id: UUID, key: str, path: Path) -> None:
    """One stretch's file to disk, through the tenant-checking door: streamed from R2
    when the store can (`copy_to_file` checks `owned_by` and reads through `ObjectGate`),
    else read whole (a test's memory store, a development `LocalMediaStore`)."""
    if not owned_by(tenant_id, key):
        raise LocalVideoFailed(
            FailureReason.ROUTE_BLOCKED_BY_POLICY.value,
            LOCAL_SOURCE_FAILED_TEXT,
            raw="a stretch of another business",
            code="foreign",
        )
    copy = getattr(store, "copy_to_file", None)
    try:
        if callable(copy):
            copy(tenant_id, key, path)
        else:
            path.write_bytes(store.read(key))
    except LocalVideoFailed:
        raise
    except Exception as exc:
        if _missing(exc):
            raise LocalVideoFailed(
                FailureReason.INVALID_PARAMETERS.value,
                LOCAL_MISSING_TEXT,
                raw=f"missing {key}",
                code="missing",
            ) from exc
        raise LocalVideoFailed(
            FailureReason.PROVIDER_ERROR.value,
            LOCAL_READ_FAILED_TEXT,
            raw=f"{key}: {type(exc).__name__}: {exc}",
            code="read_failed",
        ) from exc


def render_local_part(
    part: PartRecipe,
    *,
    tenant_id: UUID,
    store: Any,
    root: Path,
    beat: Callable[[], None] | None = None,
    brand: Any = None,
    render_client: Any = None,
    draft_id: UUID | None = None,
    source_jobs: Any = None,
) -> LocalRender:
    """Make `part`'s video in `root` (see the module): prepared stretches and held photos,
    sped up and laid end to end, then the part's texts over it. Raises `LocalVideoFailed`;
    a picture problem of the pixels' own (`VideoSourceError`: unreadable, rotated, out of
    range, too short or too long once sped up) is the owner's to fix, not retried.

    `brand` is the tenant's `BrandKit` (its typeface and palette draw the texts) and
    `render_client` the render service's `RemotionRenderClient` (or a callable that builds
    one): both used only when the part has a text. Without a client a text fails as the
    service being down — never a video without the texts the owner chose."""
    from qualify_creative.video._source import VideoSourceError  # noqa: PLC0415
    from qualify_creative.video.memory import release_memory  # noqa: PLC0415
    from qualify_creative.video.photo_hold import HOLD_VERSION, render_photo_hold  # noqa: PLC0415
    from qualify_creative.video.prepare import (  # noqa: PLC0415
        PREPARE_VERSION,
        TARGET_SIZE,
        PrepareSegment,
        apply_prepare,
        plan_prepare,
        read_source,
    )
    from qualify_creative.video.sound import SOUND_VERSION  # noqa: PLC0415
    from qualify_creative.video.speed import SpeedSegment, plan_speed, render_speed  # noqa: PLC0415

    files: dict[str, str] = {}
    lengths: dict[str, float] = {}
    # m-25049580: each video stretch's sound sidecar (None: the file has no sound)
    sounds: dict[str, str | None] = {}
    warnings: list[dict[str, Any]] = []
    # m-25041163: every local part comes out 1080×1920 — `prepare` never enlarges (its file
    # is an intermediate), the photos are held at it, and `render_speed` enlarges a smaller
    # stretch bicubic in the ONE encode at that size (not a second one in `prepare`)
    size = TARGET_SIZE
    # m-25042483: only ever a source of at most 4K 8 bits is decoded — a bigger or 10-bit
    # file is read as its normalized copy, or the video waits for the media-worker to make
    # it (`LocalSourceNormalizing`, before anything is decoded); see `local_sources`
    sources = LocalSources.open(
        part,
        tenant_id=tenant_id,
        fetch_file=lambda key, path: _fetch(store, tenant_id, key, path),
        jobs=source_jobs,
        draft_id=draft_id,
        brand_id=getattr(brand, "brand_id", None),
    )
    try:
        for index, segment in enumerate(part.segments):
            if segment.kind != "video":
                continue
            source = root / f"source-{index}"
            sources.fetch(segment.key, source)
            info = read_source(source)
            plan = plan_prepare(
                info.width,
                info.height,
                info.rotation,
                PrepareSegment(
                    key=segment.key,
                    start_s=segment.start_s,
                    end_s=segment.end_s,
                    rotate=int(segment.rotate),
                ),
                info.duration_s,
                index=index,
            )
            prepared = apply_prepare(source, plan, root / f"prepared-{index}.mp4", keep_audio=True)
            source.unlink(missing_ok=True)  # the original is not needed any more
            reference = _reference(index, segment)
            files[reference] = prepared.path
            sounds[reference] = prepared.audio_path
            lengths[reference] = prepared.duration_s
            warnings.extend({"segment": index, **w.to_dict()} for w in prepared.warnings)
            if beat is not None:
                beat()
        # m-25042483: each step starts from what is in use, not what the last one freed
        release_memory()
        photos = False
        for index, segment in enumerate(part.segments):
            if segment.kind != "photo":
                continue
            photos = True
            source = root / f"photo-{index}"
            _fetch(store, tenant_id, segment.key, source)
            held = render_photo_hold(
                source,
                root / f"photo-{index}.mp4",
                seconds=segment.end_s,
                size=size,
                rotate=int(segment.rotate),
            )
            reference = _reference(index, segment)
            files[reference] = str(held.path)
            lengths[reference] = held.duration_s
        stretches = [
            SpeedSegment(
                source=_reference(index, segment),
                start_s=0.0,
                end_s=lengths[_reference(index, segment)],
                speed=segment.speed if segment.kind == "video" else 1.0,
            )
            for index, segment in enumerate(part.segments)
        ]
        # a total outside 3-60 s is refused here as today (`speed_duration_out_of_range`)
        # m-25049580: always one sound track — a ×1 stretch's own sound, silence elsewhere
        result = render_speed(
            plan_speed(stretches),
            root / "local.mp4",
            resolve=files.__getitem__,
            size=size,
            resolve_audio=sounds.get,
        )
        for sidecar in sounds.values():  # read into the AAC track: not needed any more
            if sidecar is not None:
                Path(sidecar).unlink(missing_ok=True)
    except VideoSourceError as exc:
        raise LocalVideoFailed(
            FailureReason.INVALID_PARAMETERS.value,
            LOCAL_SOURCE_FAILED_TEXT,
            raw=f"{type(exc).__name__}({exc.reason}): {exc}",
            code="unreadable" if exc.reason == "unreadable" else "source",
        ) from exc
    except LocalVideoFailed:
        raise
    except Exception as exc:
        # a decoder or picture error the steps did not wrap themselves (PyAV's own,
        # Pillow's `DecompressionBombError`): the owner's file cannot be read — never a
        # vendor error; anything else (the disk, a bug) still goes up as it is
        if not _unreadable(exc):
            raise
        raise LocalVideoFailed(
            FailureReason.INVALID_PARAMETERS.value,
            LOCAL_SOURCE_FAILED_TEXT,
            raw=f"{type(exc).__name__}: {exc}",
            code="unreadable",
        ) from exc
    release_memory()  # the speed step's decoder and encoder, before the layers and texts
    # EF-08: the library's layers (smoke, embers, steam) BEFORE the texts, so the words
    # stay on top; same clock as the texts (seconds of THIS part's output, from 0)
    # — with texts too, ONE pass (one encode): the layers under the texts, in the compose
    video = result.path
    effect_layers = _effect_layers(part)
    layered: tuple[Path, dict[str, Any]] | None = None
    if effect_layers and not part.text_layers:
        layered = _lay_effects(effect_layers, video, root / "local-layers.mp4")
        video.unlink(missing_ok=True)  # never two large files on disk without need
        video = layered[0]
        if beat is not None:
            beat()
    elif effect_layers:
        layered = (video, _layers_provenance(effect_layers))
    # EF-05: the part's texts (`part.text_layers`, seconds of THIS part's output from 0,
    # speed applied — the recipe's own clock) drawn over the video already built
    composed = _compose(part, video, root / "local-texts.mp4", brand, render_client, effect_layers)
    if composed.composed:
        if Path(composed.path) != Path(video):
            Path(video).unlink(missing_ok=True)
        if beat is not None:
            # the render and the second encode can take minutes: mark the draft alive again
            beat()
    steps: dict[str, Any] = {
        "prepare": PREPARE_VERSION,
        "speed": result.recipe_version,
        "sound": SOUND_VERSION,
    }
    if photos:
        steps["photo_hold"] = HOLD_VERSION
    if layered is not None:
        steps["layer_compose"] = layered[1]["compose_version"]
    text_params: dict[str, Any] | None = None
    if composed.composed:
        text_params = dict(composed.params["text_layers"])
        steps["compose"] = text_params["compose_version"]
    release_memory()  # the compose's, before the poster and the save
    return LocalRender(
        path=composed.path,
        width=result.width,
        height=result.height,
        seconds=result.duration_s,
        frames=result.frames,
        speed=result.params(),
        steps=steps,
        warnings=tuple(warnings),
        text_layers=text_params,
        effect_layers=layered[1] if layered is not None else None,
        sources=sources,
        sound=_sound_provenance(part, result.sound),
    )


def _sound_provenance(
    part: PartRecipe, speed_sound: dict[str, Any] | None
) -> dict[str, Any] | None:
    """m-25049580: the track's format and, per stretch of the recipe (its index), whether it
    carries its original sound — `kept` — or is silence and why: `sped_up` (faster than ×1, no
    time-stretching), `photo`, `no_audio` (the file has no sound track or it could not be
    decoded). None when the render had no sound track."""
    if speed_sound is None:
        return None
    kept = set(speed_sound.get("original_sound", ()))
    stretches = []
    for index, segment in enumerate(part.segments):
        if index in kept:
            why = "kept"
        elif segment.kind != "video":
            why = "photo"
        elif segment.speed != 1.0:
            why = "sped_up"
        else:
            why = "no_audio"
        stretches.append({"segment": index, "original_sound": why == "kept", "why": why})
    return {
        "version": speed_sound["version"],
        "format": {key: speed_sound[key] for key in ("codec", "sample_rate", "layout", "bit_rate")},
        "crossfade_s": speed_sound["crossfade_s"],
        "segments": stretches,
    }


def _layer_failed(exc: BaseException) -> LocalVideoFailed:
    """A layer that could not be laid: ours (the loop or the built video unreadable, the
    encode) — the technical message only reaches the log; a local piece is never charged."""
    return LocalVideoFailed(
        FailureReason.RENDER_ERROR.value,
        LOCAL_LAYER_FAILED_TEXT,
        raw=f"{type(exc).__name__}: {exc}",
        code="layer_overlay_failed",
    )


def _effect_layers(part: PartRecipe) -> list[Any]:
    """EF-08: every use of a library layer in `part.effects` as a `TimedEffectLayer` (its
    entry at its version, through the read-only `effects.layer_loop_file`; its params or
    the entry's defaults; its span in seconds of this part's output). Any other effect is
    not drawn here (`unbuilt_recipe_problems` refuses it before any row)."""
    from qualify_creative.effects import NotALibraryLayer, load_effects  # noqa: PLC0415
    from qualify_creative.video.layer_overlay import TimedEffectLayer  # noqa: PLC0415

    library = load_effects()
    layers: list[Any] = []
    try:
        for use in part.effects:
            if not is_built_layer(use, library):
                continue
            entry = library.get(use.effect_id, use.version)
            assert entry is not None  # `is_built_layer` found it
            layers.append(
                TimedEffectLayer.from_entry(
                    entry, dict(use.params), start_s=use.start_s, end_s=use.end_s
                )
            )
    except (NotALibraryLayer, ValueError) as exc:
        raise _layer_failed(exc) from exc
    return layers


def _layers_provenance(layers: list[Any]) -> dict[str, Any]:
    """The layer step's provenance: its version, cost 0 and each use's `params()`."""
    from qualify_creative.video.layer_overlay import LAYER_COMPOSE_VERSION  # noqa: PLC0415

    return {
        "compose_version": LAYER_COMPOSE_VERSION,
        "cost_usd": "0.00",
        "layers": [layer.params() for layer in layers],
    }


def _lay_effects(layers: list[Any], video: Path, out: Path) -> tuple[Path, dict[str, Any]]:
    """The layers alone (a part with no text) screen-blended over `video` into `out`
    (`overlay_effect_layers`), with their provenance; `video` is left as it was."""
    from qualify_creative.video import layer_overlay  # noqa: PLC0415

    try:
        made = layer_overlay.overlay_effect_layers(video, out, layers)
    except layer_overlay.LayerOverlayError as exc:
        raise _layer_failed(exc) from exc
    return made.path, _layers_provenance(layers)


def _no_render_client() -> Any:
    """No render service wired (a producer built without one): a text cannot be drawn —
    `compose_text_layers` reads it as the service being down (`ComposeUnavailable`)."""
    raise RuntimeError("no render client wired for the local video's texts")


def _compose(
    part: PartRecipe,
    video: Path,
    out: Path,
    brand: Any,
    render_client: Any,
    effect_layers: list[Any] | None = None,
) -> Any:
    """EF-05's compose over the built `video` (no text: nothing runs and `video` is kept),
    with EF-08's `effect_layers` under the texts in the same single pass; its failures as
    `LocalVideoFailed` with what the owner reads. None charges anything (a local piece
    takes no creation; ADR 49 §6) and each leaves `video` as it was."""
    from qualify_creative.video.layer_overlay import LayerOverlayError  # noqa: PLC0415
    from qualify_creative.video.text_overlay import TextOverlayError  # noqa: PLC0415

    from qualify_api.creative.video_pipeline.compose import (  # noqa: PLC0415
        ComposeRejected,
        ComposeUnavailable,
        TextLayerRefused,
        compose_text_layers,
    )

    try:
        return compose_text_layers(
            video,
            out,
            part.text_layers,
            brand,
            render_client=render_client if render_client is not None else _no_render_client,
            effect_layers=tuple(effect_layers or ()),
        )
    except TextLayerRefused as exc:
        # one text does not fit in its place: the owner's to change, named in his words
        raise LocalVideoFailed(
            FailureReason.INVALID_PARAMETERS.value,
            exc.owner_message,
            raw=str(exc),
            code=exc.code,
        ) from exc
    except ComposeUnavailable as exc:
        # the render service down or timed out, or refusing what we sent (`ComposeRejected`,
        # not transient): ours, said with the stage's own message (nothing discounted)
        raise LocalVideoFailed(
            (
                FailureReason.INVALID_PARAMETERS.value
                if isinstance(exc, ComposeRejected)
                else FailureReason.DEPENDENCY_FAILED.value
            ),
            exc.owner_message,
            raw=exc.detail,
            code=exc.code,
        ) from exc
    except LayerOverlayError as exc:
        raise _layer_failed(exc) from exc
    except TextOverlayError as exc:
        # the built video itself unreadable or not 9:16: a bug of ours — its message is
        # technical (English) and only reaches the log
        raise LocalVideoFailed(
            FailureReason.RENDER_ERROR.value,
            LOCAL_COMPOSE_FAILED_TEXT,
            raw=f"{type(exc).__name__}: {exc}",
            code="text_overlay_failed",
        ) from exc


def _unreadable(exc: BaseException) -> bool:
    """A picture the decoders refused: PyAV's `FFmpegError` or Pillow's bomb guard.
    Not the machine's own failures, which go up as they are (transient, never the
    owner's file): an errno (`av.error.OSError` — a full disk —, `MemoryError`), a
    library outside FFmpeg (`ExternalError`) or FFmpeg's own bug (`BugError`)."""
    try:
        import av  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415
    except ImportError:  # pragma: no cover — the worker always has both
        return False
    if isinstance(exc, OSError | MemoryError | av.error.ExternalError | av.error.BugError):
        return False
    return isinstance(exc, av.error.FFmpegError | Image.DecompressionBombError)


def _poster(path: Path) -> bytes | None:
    """The video's first frame as a JPEG (the piece's thumbnail), or None."""
    try:
        import av  # noqa: PLC0415

        with av.open(str(path)) as container:
            for frame in container.decode(container.streams.video[0]):
                out = io.BytesIO()
                frame.to_image().save(out, format="JPEG", quality=88)
                return out.getvalue()
    except Exception:  # noqa: BLE001 — a thumbnail is a nicety, never the piece
        logger.warning("local video poster not made", exc_info=True)
    return None


def _contact_sheet(save: Any, path: Path, key: str) -> dict[str, Any] | None:
    """EF-18: the composed video's contact sheet kept in the revision's folder beside it
    (`save.optional`: a refused file leaves the sheet out, never the piece), or None."""
    optional = getattr(save, "optional", None)
    if not callable(optional):
        return None
    try:
        return keep_contact_sheet(
            path,
            lambda name, data: optional(name, data, JPEG),
            source={
                "stage": "local",
                "object_key": key,
                "revision": getattr(save, "revision", None),
            },
        )
    except Exception:  # noqa: BLE001 — never the piece: it goes on without its sheet
        logger.warning("local video contact sheet failed: left out", exc_info=True)
        return None


def _keep_video(save: Any, store: Any, tenant_id: UUID, path: Path) -> str:
    """Keep the MP4 under the draft's revision: streamed from disk when the store can
    (`keep_file`: retried, an existing key is reused), else through `save` (retried)."""
    keep_file = getattr(store, "keep_file", None)
    key_for = getattr(save, "key_for", None)
    if callable(keep_file) and callable(key_for):
        key = str(key_for("local.mp4"))
        if not keep_file(tenant_id, key, path, MP4):
            raise LocalVideoFailed(
                FailureReason.PROVIDER_ERROR.value,
                LOCAL_SAVE_FAILED_TEXT,
                raw=f"local video not kept in R2 ({key})",
                code="save_failed",
            )
        return key
    return str(save("local.mp4", path.read_bytes(), MP4))


def _part_meta(part: PartRef, key: str, seconds: float) -> dict[str, Any]:
    """`params.part` of a `local` part (VE-10a's shape): what the join reads — its mode,
    its planned `seconds`, the length it really has (`generation_seconds`: the join keeps
    its first `seconds`, or the whole when it is shorter) and the file it joins."""
    return {
        "index": part.index,
        "mode": part.mode,
        "seconds": part.seconds,
        "generation_seconds": round(seconds, 3),
        "analysis_id": str(part.analysis_id) if part.analysis_id else None,
        "shot_indexes": list(part.shot_indexes),
        "trim_start_s": part.trim_start_s,
        "trim_end_s": part.trim_end_s,
        "window": None,
        "raw_key": None,
        "clean_key": key,
        "logo": "sin logo",
    }


def _lease(run: Any, store: Any) -> AbstractContextManager[None]:
    """The preparation's lease kept alive for the block (`lease_kept`), or nothing outside
    a preparation (a test, a script)."""
    if run is None:
        return nullcontext()
    from qualify_api.creative.pipeline import PipelineStore, lease_kept  # noqa: PLC0415

    return lease_kept(store or PipelineStore(), run, every_s=LEASE_RENEW_EVERY_S)


def produce_local(
    *,
    tenant_id: UUID,
    draft_id: UUID,
    brief: ContentBrief,
    store: Any,
    save: Any,
    beat: Callable[[], None] | None = None,
    allowed: bool = True,
    run: Any = None,
    lease_store: Any = None,
    brand: Any = None,
    render_client: Any = None,
) -> MediaOutcome:
    """The `local` Clip of `brief` as the producer's outcome — never raises for the
    owner's files: the outcome carries the failure. `allowed` is False outside the
    creative worker: refused before anything is read.

    `run` is the worker's preparation (`pipeline.current_preparation()`): its lease is
    renewed while the video is made (`pipeline.lease_kept`, as the parts' join does) —
    preparing and speeding up a minute of 1080×1920 can outlast it, and a lost lease
    would throw the video away at the final write and make it again on every pass.
    `lease_store` is the `PipelineStore` (a test's double). `brand` and `render_client`
    draw the recipe's texts (`render_local_part`), inside the same kept lease."""
    part_ref = brief.media.part
    in_part = part_ref is not None
    failed_text = LOCAL_PART_FAILED_TEXT if in_part else LOCAL_SOURCE_FAILED_TEXT
    if not allowed:
        logger.warning("draft %s: a local video outside the creative worker: refused", draft_id)
        return MediaOutcome(
            failure=FailureReason.INVALID_PARAMETERS.value, detail=LOCAL_NEEDS_WORKER_TEXT
        )
    parts = recipe_of(brief)
    if len(parts) != 1 or parts[0].mode != "local" or not parts[0].segments:
        return MediaOutcome(failure=FailureReason.INVALID_PARAMETERS.value, detail=failed_text)
    (part,) = parts
    # the recipe again, with the business: a stretch of another one is never read
    problems = validate_recipe(parts, video_by_parts=in_part, tenant_id=tenant_id)
    if problems:
        logger.warning(
            "draft %s: local recipe refused before any read: %s",
            draft_id,
            ", ".join(p.code for p in problems),
        )
        foreign = any(p.code in ("foreign_key", "malformed_key") for p in problems)
        too_long = any(p.code == "segment_source_too_long" for p in problems)
        return MediaOutcome(
            failure=(
                FailureReason.ROUTE_BLOCKED_BY_POLICY.value
                if foreign
                else FailureReason.INVALID_PARAMETERS.value
            ),
            # m-25042483: a stretch over 60 s of its video says so, «esta parte» in a part
            detail=(
                (LOCAL_PART_SOURCE_TOO_LONG_TEXT if in_part else LOCAL_SOURCE_TOO_LONG_TEXT)
                if too_long and not foreign
                else failed_text
            ),
        )
    try:
        with (
            # m-25042483: never alongside a part join — with one in flight this raises
            # `LocalAssemblyWait` before anything is read: the next pass makes the video
            assembling(),
            _lease(run, lease_store),
            tempfile.TemporaryDirectory(prefix=_WORKDIR_PREFIX) as folder,
        ):
            made = render_local_part(
                part,
                tenant_id=tenant_id,
                store=store,
                root=Path(folder),
                beat=beat,
                brand=brand,
                render_client=render_client,
                draft_id=draft_id,
            )
            cost = local_price(made.seconds)
            if cost != 0:  # the price guard: a local video never pays a vendor
                raise LocalVideoFailed(
                    FailureReason.BUDGET_EXCEEDED.value,
                    failed_text,
                    raw=f"{LOCAL_PRICING_VERSION} prices local video at {cost}",
                    code="price",
                )
            key = _keep_video(save, store, tenant_id, made.path)
            poster = _poster(made.path)
            # EF-18: the composed video's contact sheet, still inside the gate
            sheet = _contact_sheet(save, made.path, key)
        poster_key = save.optional("first-frame.jpg", poster, JPEG) if poster else None
    except LocalVideoFailed as exc:
        logger.warning("draft %s: local video not made: %s", draft_id, exc.raw or exc.detail)
        detail = _PART_TEXTS.get(exc.detail, exc.detail) if in_part else exc.detail
        return MediaOutcome(failure=exc.failure, detail=detail)
    params: dict[str, Any] = {
        "thumbnail_key": poster_key,
        "duration_seconds": round(made.seconds, 3),
        "resolution": f"{made.height}p",
        "reference_mode": "local",
        "ai_generated": False,
        "local": {
            "recipe_version": LOCAL_RECIPE_VERSION,
            "recipe_contract": RECIPE_CONTRACT_VERSION,
            "effects_pipeline_version": brief.media.effects_pipeline_version,
            "pricing_version": LOCAL_PRICING_VERSION,
            "model_id": LOCAL_MODEL_ID,
            "cost_usd": str(cost),
            "steps": made.steps,
            "effect_version": made.speed["effect_version"],
            "speed": made.speed,
            # m-25042483: each video stretch with its file's provenance (original key,
            # normalized copy, normalizer version)
            "segments": with_provenance(part.segments, made.sources),
            # m-25049580: which stretches keep their original sound, and the track's format
            "sound": made.sound,
            "frames": made.frames,
            "warnings": list(made.warnings),
        },
    }
    if sheet is not None:
        params[CONTACT_SHEET_PARAMS_KEY] = sheet
    if made.effect_layers is not None:
        # EF-08's provenance: each layer laid, its loop's sha256, the compose version
        params["local"]["effect_layers"] = made.effect_layers
    if made.text_layers is not None:
        # EF-05's provenance: design, pixel revisions, fade chosen and applied, hashes
        params["local"]["text_layers"] = made.text_layers
    if part_ref is not None:
        params["part"] = _part_meta(part_ref, key, made.seconds)
    write = MediaWrite(
        position=0,
        media_type="video",
        media_url=key,
        object_key=key,
        width=made.width,
        height=made.height,
        aspect_ratio="9:16",
        model_id=LOCAL_MODEL_ID,
        provider=LOCAL_PROVIDER,
        content_type=MP4,
        ai_generated=False,
        params=params,
    )
    usage = MediaUsage(
        provider=LOCAL_PROVIDER,
        model_id=LOCAL_MODEL_ID,
        unit="second",
        quantity=max(1, round(made.seconds)),
        cost_usd=cost,
        pricing_table_version=LOCAL_PRICING_VERSION,
    )
    return MediaOutcome(media=(write,), usage=(usage,))


__all__ = [
    "LOCAL_COMPOSE_FAILED_TEXT",
    "LOCAL_LAYER_FAILED_TEXT",
    "LOCAL_PART_LAYER_FAILED_TEXT",
    "LOCAL_PART_SOURCE_TOO_LONG_TEXT",
    "LOCAL_SOURCE_TOO_LONG_TEXT",
    "LOCAL_EFFECTS_PIPELINE_VERSION",
    "LOCAL_PART_COMPOSE_FAILED_TEXT",
    "LOCAL_MODEL_ID",
    "LOCAL_PRICING_VERSION",
    "LOCAL_PROVIDER",
    "LOCAL_RECIPE_VERSION",
    "LocalRender",
    "LocalVideoFailed",
    "effects_version_for",
    "is_local_recipe",
    "local_price",
    "produce_local",
    "render_local_part",
]
