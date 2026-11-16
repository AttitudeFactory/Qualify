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
2. a video is «Preparado» (EF-03: upright, 9:16, its `[start_s, end_s)`); a photo is held
   still for its `end_s` seconds (`video.photo_hold`, D-T1) at the prepared size;
3. «Cámara rápida» (EF-04) lays every stretch end to end at its `speed` (a photo at 1), 30
   fps, hard cuts, no gaps: the video lasts the sum of the stretches at their speed;
4. `# EF-05`: the compose step (the part's texts over the built video) goes here;
5. the MP4 (and a poster) are kept in R2 under the draft's revision (`_Saver`, retried).

Provenance (rule 6) in the asset's `params.local`: the recipe contract, the effects
pipeline version, the pricing table (`LOCAL_PRICING_VERSION`, where `local_video` costs
0.00 a second), the steps' versions and the speed step's own `SpeedResult.params()`. The
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

from qualify_api.creative.media import (
    JPEG,
    MP4,
    MediaOutcome,
    MediaUsage,
    MediaWrite,
    owned_by,
)
from qualify_api.creative.video_pipeline.recipe import recipe_of, validate_recipe

logger = logging.getLogger(__name__)

#: The `effects_pipeline_version` the server stamps on a `local` recipe with stretches.
LOCAL_EFFECTS_PIPELINE_VERSION = 1
#: The pricing table that prices a local video (`local_video`: 0.00 a second). A new
#: price is a new table, never an edit of this one.
LOCAL_PRICING_VERSION = "v10"
LOCAL_MODEL_ID = "local_video"
LOCAL_PROVIDER = "local"
LOCAL_UNIT = "per_second"
#: Version of this module's recipe (the order of the steps) — provenance.
LOCAL_RECIPE_VERSION = "local-v1"
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
#: A part says «esta parte» where the whole piece says «tu video».
_PART_TEXTS = {
    LOCAL_SOURCE_FAILED_TEXT: LOCAL_PART_FAILED_TEXT,
    LOCAL_SAVE_FAILED_TEXT: LOCAL_PART_SAVE_FAILED_TEXT,
}
#: How often the preparation's lease is renewed while the video is made (None =
#: `lease_kept`'s own, a third of the lease). Tests shorten it.
LEASE_RENEW_EVERY_S: float | None = None


class LocalVideoFailed(Exception):
    """The local video could not be made: `failure` (a `FailureReason` value), a stable
    `code` (`unreadable`, `missing`, `read_failed`, `save_failed`, `foreign`, `source`,
    `price`), the owner's `detail`; `raw` only reaches the log."""

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
    a `local` recipe with stretches, 0 (made as before EF-06) for anything else. Pure."""
    return LOCAL_EFFECTS_PIPELINE_VERSION if is_local_recipe(brief) else 0


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
) -> LocalRender:
    """Make `part`'s video in `root` (see the module): prepared stretches and held photos,
    sped up and laid end to end. Raises `LocalVideoFailed`; a picture problem of the
    pixels' own (`VideoSourceError`: unreadable, rotated, out of range, too short or too
    long once sped up) is the owner's to fix, not retried."""
    from qualify_creative.video._source import VideoSourceError  # noqa: PLC0415
    from qualify_creative.video.photo_hold import HOLD_VERSION, render_photo_hold  # noqa: PLC0415
    from qualify_creative.video.prepare import (  # noqa: PLC0415
        PREPARE_VERSION,
        TARGET_SIZE,
        PrepareSegment,
        apply_prepare,
        plan_prepare,
        read_source,
    )
    from qualify_creative.video.speed import SpeedSegment, plan_speed, render_speed  # noqa: PLC0415

    files: dict[str, str] = {}
    lengths: dict[str, float] = {}
    warnings: list[dict[str, Any]] = []
    size: tuple[int, int] | None = None
    try:
        for index, segment in enumerate(part.segments):
            if segment.kind != "video":
                continue
            source = root / f"source-{index}"
            _fetch(store, tenant_id, segment.key, source)
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
            prepared = apply_prepare(source, plan, root / f"prepared-{index}.mp4")
            source.unlink(missing_ok=True)  # the original is not needed any more
            reference = _reference(index, segment)
            files[reference] = prepared.path
            lengths[reference] = prepared.duration_s
            warnings.extend({"segment": index, **w.to_dict()} for w in prepared.warnings)
            size = size or (prepared.width, prepared.height)
            if beat is not None:
                beat()
        size = size or TARGET_SIZE
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
        result = render_speed(plan_speed(stretches), root / "local.mp4", resolve=files.__getitem__)
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
    # EF-05: the compose step goes here — the part's texts (`part.text_layers`, seconds of
    # THIS part's output from 0, speed applied: `result.plan.segments[i].out_start_s` /
    # `out_end_s` place each stretch on that clock) drawn over `result.path`, the video
    # already built. Until it lands, `unbuilt_recipe_problems` refuses any text.
    steps: dict[str, Any] = {"prepare": PREPARE_VERSION, "speed": result.version}
    if photos:
        steps["photo_hold"] = HOLD_VERSION
    return LocalRender(
        path=result.path,
        width=result.width,
        height=result.height,
        seconds=result.duration_s,
        frames=result.frames,
        speed=result.params(),
        steps=steps,
        warnings=tuple(warnings),
    )


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
) -> MediaOutcome:
    """The `local` Clip of `brief` as the producer's outcome — never raises for the
    owner's files: the outcome carries the failure. `allowed` is False outside the
    creative worker: refused before anything is read.

    `run` is the worker's preparation (`pipeline.current_preparation()`): its lease is
    renewed while the video is made (`pipeline.lease_kept`, as the parts' join does) —
    preparing and speeding up a minute of 1080×1920 can outlast it, and a lost lease
    would throw the video away at the final write and make it again on every pass.
    `lease_store` is the `PipelineStore` (a test's double)."""
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
        return MediaOutcome(
            failure=(
                FailureReason.ROUTE_BLOCKED_BY_POLICY.value
                if foreign
                else FailureReason.INVALID_PARAMETERS.value
            ),
            detail=failed_text,
        )
    try:
        with (
            _lease(run, lease_store),
            tempfile.TemporaryDirectory(prefix=_WORKDIR_PREFIX) as folder,
        ):
            made = render_local_part(
                part, tenant_id=tenant_id, store=store, root=Path(folder), beat=beat
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
            "segments": [segment.model_dump(mode="json") for segment in part.segments],
            "frames": made.frames,
            "warnings": list(made.warnings),
        },
    }
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
    "LOCAL_EFFECTS_PIPELINE_VERSION",
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
