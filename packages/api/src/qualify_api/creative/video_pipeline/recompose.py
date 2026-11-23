"""Texts and layers over a Clip made by Seedance, and its 1080p final composed again with
the same recipe (EF-14, m-25026592; ADR 50 §1.1 steps 5 and 7, D1).

A normal Clip (no parent) made by Seedance in `reference` mode (`motion`), 9:16, may carry
the owner's texts (`text_layers`) and the library's recorded layers (smoke, embers,
steam: `recipe.is_built_layer`) — the same compose step a `local` piece runs
(`compose.compose_text_layers`, `qualify_creative.video.layer_overlay`), at cost 0.

1. **The preview.** `compose_recipe_of(brief, kit)` freezes what the compose needs — the
   texts, the layer uses at their library versions and the Brand Kit's typeface and
   palette (`render.video_text.brand_props`) — and `ClipComposer.draw` asks our render
   service for every text BEFORE Seedance is paid: a text that does not fit, or a render
   service that is down, fails the piece with nothing spent. Once the clip arrives (logo
   and subtitles laid as before), `ClipComposer.compose` lays the layers and the texts in
   one pass. Seedance 2.5's 480p draft is 496x864 — not 9:16 within the overlay's 1 %
   (`text_overlay.ASPECT_TOLERANCE`) — so it is first cut to 9:16 (`nine_sixteen_size`:
   486x864, 5 px off each side) by the fitter; the layers are drawn for a 9:16 frame and
   sit at the same place relative to it in the preview and in the final. The frozen
   recipe and the step's provenance go into the asset's `params["compose"]`, and the
   text PNGs the render service drew are kept beside the piece in R2 (`compose.texts`:
   key and sha256 of each, `text_images_params`). When this generation's Seedance task
   is already recorded (a resumed run: the clip is paid), a failed drawing is not fatal:
   it is tried again after the clip and the preview degrades with the warning.
2. **The final.** When the 1080p final of that draft arrives (`MediaProducer.finalize`, in
   the creative worker), the SAME frozen recipe (`stored_recipe(asset.params)`, never the
   brief as it reads today: «si la receta cambió de versión entre borrador y final, se usa
   la del borrador») is composed again over the fitted final, after its logo and
   subtitles, with the preview's OWN text PNGs (`stored_text_images`, checked by sha256:
   exactly the texts approved, the render service not asked again; drawn again only when
   one is missing or altered), and its provenance (`final`: from which final task, raw
   file and source sha256, `texts_reused`) joins the preview's. Idempotent: the final's
   file has one key per order (`{stem}-final-{attempt}.mp4`); a retry that finds that
   key already kept takes the file as it is (`reused`) BEFORE any fit, subtitle or
   compose, and the raw 1080p is never paid twice (`raw_final`). A compose that fails
   fails the final with the raw 1080p kept, so «Reintentar» costs the vendor nothing.

Where it runs. Only in the creative worker (`process.is_worker_process`): elsewhere the
compose fails closed — the preview keeps its clip with the warning, the final fails with
its raw 1080p kept (a free retry); drawing texts alone, a call to our render service, runs
anywhere. Every compose (and the preview's cut to 9:16) holds the worker's heavy-video
gate (`heavy_video.assembling`, m-25042483): with a part join in flight it raises
`LocalAssemblyWait` and the job waits for a later pass — nothing is paid again (the final's
raw 1080p is kept; the preview is replayed through the queue's checkpoints) — so a compose
never overlaps a join inside the worker's 768m (measured: 416 MiB anon for a 15 s final
with 3 texts and 3 layers, `deploy/measure/recompose-memory.sh`).

What is still refused before any row (`recipe.unbuilt_recipe_problems`): texts or layers
over a PART made by Seedance (its final is joined by `part_final`/`part_join`, which do
not compose yet), over an `edit` Clip (its size is the reel's, any aspect) or a Clip that
is not 9:16, and any effect that is not a built layer. Pieces stamped
`effects_pipeline_version` 0 are never composed again (out of scope for EF-14).

Cost: US$0 (our render service and PyAV); the price guard of the Seedance call is
untouched — the compose is never priced, never charged.
"""

from __future__ import annotations

import hashlib
import io
import logging
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from qualify_creative.enums import ContentFormat, ContentKind, FailureReason
from qualify_creative.schemas import ContentBrief, EffectUse, VideoTextLayer

if TYPE_CHECKING:
    from qualify_api.creative.heavy_video import LocalAssemblyWait, LocalVideoWait

logger = logging.getLogger(__name__)

#: Version of this stage over a Seedance clip (how the recipe is frozen, cut to 9:16 and
#: composed again on the final). Bumped with any change that moves a pixel.
RECOMPOSE_VERSION = "seedance-compose-v1"
#: The key of the asset's params that holds the frozen recipe and the provenance.
COMPOSE_PARAMS_KEY = "compose"
#: The `effects_pipeline_version` stamped on a Seedance Clip with texts or layers.
SEEDANCE_COMPOSE_EFFECTS_VERSION = 1
#: The only formats the layers are drawn for (a 1080x1920 canvas).
COMPOSE_FORMATS = frozenset({ContentFormat.REELS_9_16, ContentFormat.STORY_9_16})
#: How far a video may be off 9:16 and still be cut to it (Seedance's 496x864 is 2 %):
#: farther off is a bug, never cropped silently.
CUT_TOLERANCE = 0.03
_ASPECT = 9 / 16
_WORKDIR_PREFIX = "qualify-recompose-"

#: What the owner reads (Spanish, `qualify-copy-es`).
#: The preview: the clip is paid and kept without the texts; he may make it again.
COMPOSE_NOT_ADDED = "text_layers_not_added"
COMPOSE_NOT_ADDED_TEXT = (
    "No pudimos poner tus textos y efectos sobre el video; lo dejamos sin ellos. "
    "Puedes generarlo de nuevo."
)
#: The final: the 1080p file is kept, so trying again costs nothing more.
FINAL_COMPOSE_FAILED_TEXT = (
    "No pudimos poner tus textos y efectos sobre el video final. Inténtalo de nuevo."
)


def _loose_clip_part(brief: ContentBrief) -> Any | None:
    from qualify_api.creative.video_pipeline.recipe import recipe_of  # noqa: PLC0415

    if brief.kind is not ContentKind.CLIP or brief.media.part is not None:
        return None
    parts = recipe_of(brief)
    return parts[0] if parts else None


def seedance_compose_allowed(brief: ContentBrief) -> bool:
    """Whether the compose runs over this piece made by Seedance: a normal Clip (no
    parent), `reference` mode, 9:16. Pure."""
    part = _loose_clip_part(brief)
    return part is not None and part.mode == "reference" and brief.format in COMPOSE_FORMATS


def _built_layers(effects: Sequence[EffectUse]) -> tuple[EffectUse, ...]:
    from qualify_api.creative.video_pipeline.recipe import is_built_layer  # noqa: PLC0415

    return tuple(use for use in effects if is_built_layer(use))


def composes_over_seedance(brief: ContentBrief) -> bool:
    """A Clip made by Seedance that carries texts or library layers to compose. Pure."""
    if not seedance_compose_allowed(brief):
        return False
    part = _loose_clip_part(brief)
    return bool(part.text_layers or _built_layers(part.effects))


@dataclass(frozen=True)
class ComposeRecipe:
    """What the compose needs, frozen when the preview is made: the texts as the owner
    wrote them, the layer uses at their library versions (an entry is never edited in
    place: a version keeps meaning the same pixels) and the brand's typeface and palette
    as the texts were drawn with."""

    text_layers: tuple[VideoTextLayer, ...] = ()
    effects: tuple[EffectUse, ...] = ()
    brand: Mapping[str, Any] = field(default_factory=dict)
    effects_pipeline_version: int = SEEDANCE_COMPOSE_EFFECTS_VERSION

    @property
    def empty(self) -> bool:
        return not self.text_layers and not self.effects

    def to_params(self) -> dict[str, Any]:
        return {
            "text_layers": [layer.model_dump(mode="json") for layer in self.text_layers],
            "effects": [use.model_dump(mode="json") for use in self.effects],
            "brand": dict(self.brand),
            "effects_pipeline_version": self.effects_pipeline_version,
        }

    @classmethod
    def from_params(cls, block: Mapping[str, Any]) -> ComposeRecipe:
        return cls(
            text_layers=tuple(
                VideoTextLayer.model_validate(layer) for layer in block.get("text_layers") or ()
            ),
            effects=tuple(EffectUse.model_validate(use) for use in block.get("effects") or ()),
            brand=dict(block.get("brand") or {}),
            effects_pipeline_version=int(block.get("effects_pipeline_version") or 0),
        )

    def digest(self) -> str:
        """sha256 of the frozen recipe (provenance: what the preview and the final share)."""
        import json  # noqa: PLC0415

        canonical = json.dumps(self.to_params(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compose_recipe_of(brief: ContentBrief, kit: Any) -> ComposeRecipe | None:
    """The recipe to compose over this piece's Seedance clip, or None (nothing to compose,
    or a piece the compose does not run over). Pure but for the cached effects library."""
    from qualify_creative.render.video_text import brand_props  # noqa: PLC0415

    if not seedance_compose_allowed(brief):
        return None
    if brief.media.effects_pipeline_version < SEEDANCE_COMPOSE_EFFECTS_VERSION:
        return None  # out of scope: pieces from before the engine are made as they were
    part = _loose_clip_part(brief)
    recipe = ComposeRecipe(
        text_layers=tuple(part.text_layers),
        effects=_built_layers(part.effects),
        brand=brand_props(kit),
        effects_pipeline_version=brief.media.effects_pipeline_version,
    )
    return None if recipe.empty else recipe


def stored_recipe(params: Mapping[str, Any] | None) -> ComposeRecipe | None:
    """The recipe frozen with the preview (`params["compose"]["recipe"]`), or None — a
    piece composed before EF-14, or with nothing to compose (stamped 0: never again)."""
    block = (params or {}).get(COMPOSE_PARAMS_KEY)
    if not isinstance(block, Mapping):
        return None
    raw = block.get("recipe")
    if not isinstance(raw, Mapping):
        return None
    try:
        recipe = ComposeRecipe.from_params(raw)
    except Exception:  # noqa: BLE001 — an unreadable block composes nothing, said in the log
        logger.warning("compose recipe unreadable: the final is left without it", exc_info=True)
        return None
    if recipe.empty or recipe.effects_pipeline_version < SEEDANCE_COMPOSE_EFFECTS_VERSION:
        return None
    return recipe


def text_images_params(
    drawn: Sequence[Any], keep: Callable[[int, bytes], str | None]
) -> list[dict[str, Any]] | None:
    """The preview's text PNGs kept beside the piece (`keep(index, png)` → its key, or
    None when the store refused it), each with its sha256 and what its provenance and
    report say — `params["compose"]["texts"]`, read back by `stored_text_images`. None
    when one could not be kept: the final then draws them again, as before."""
    kept: list[dict[str, Any]] = []
    for index, image in enumerate(drawn):
        png = bytes(image.png)
        key = keep(index, png)
        if not key:
            return None
        kept.append(
            {
                "key": key,
                "sha256": hashlib.sha256(png).hexdigest(),
                "job_id": getattr(image, "job_id", None),
                "width": getattr(image, "width", None),
                "height": getattr(image, "height", None),
                "report": _plain(getattr(image, "report", None)),
                "provenance": _plain(getattr(image, "provenance", None)),
                "warnings": [str(w) for w in getattr(image, "warnings", ()) or ()],
            }
        )
    return kept


def _plain(value: Any) -> dict[str, Any]:
    """A JSON-safe copy of a mapping (anything that is not is dropped to its str)."""
    import json  # noqa: PLC0415

    if not isinstance(value, Mapping):
        return {}
    return json.loads(json.dumps(dict(value), default=str))


def stored_text_images(
    block: Mapping[str, Any], recipe: ComposeRecipe, read: Callable[[str], bytes | None]
) -> tuple[Any, ...] | None:
    """The preview's own text PNGs (`params["compose"]["texts"]`), read back and checked
    by sha256, one per text of `recipe` in order — what the final lays, so its texts are
    exactly the approved ones and the render service is not asked again. None when any
    is missing, unreadable or altered (a piece from before they were kept): the final
    draws them again. `read(key)` returns None for a key that is not the business's."""
    from qualify_creative.render.video_text import VideoTextImage  # noqa: PLC0415

    texts = block.get("texts")
    if not recipe.text_layers:
        return ()
    if not isinstance(texts, list) or len(texts) != len(recipe.text_layers):
        return None
    images: list[Any] = []
    for entry in texts:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("key"), str):
            return None
        try:
            png = read(entry["key"])
        except Exception:  # noqa: BLE001 — gone or unreadable: drawn again
            logger.warning("compose text %s unreadable: drawn again", entry.get("key"))
            return None
        if not png or hashlib.sha256(png).hexdigest() != entry.get("sha256"):
            return None
        images.append(
            VideoTextImage(
                job_id=str(entry.get("job_id") or ""),
                png=png,
                width=entry.get("width"),
                height=entry.get("height"),
                report=dict(entry.get("report") or {}),
                provenance=dict(entry.get("provenance") or {}),
                warnings=tuple(str(w) for w in entry.get("warnings") or ()),
            )
        )
    return tuple(images)


def nine_sixteen_size(width: int, height: int) -> tuple[int, int] | None:
    """The 9:16 size (even, same height) to cut a video of `width`x`height` to before its
    layers are laid, or None when it already is 9:16 within the overlay's tolerance.
    Raises `ValueError` when it is farther off than `CUT_TOLERANCE` (a bug, not a crop)."""
    from qualify_creative.video.text_overlay import ASPECT_TOLERANCE  # noqa: PLC0415

    if width <= 0 or height <= 0:
        raise ValueError(f"a {width}x{height} video has no size")
    off = abs(width / height - _ASPECT)
    if off <= ASPECT_TOLERANCE:
        return None
    if off > CUT_TOLERANCE:
        raise ValueError(f"a {width}x{height} video is not 9:16")
    target = round(height * _ASPECT)
    return target - target % 2, height - height % 2


#: How long a waiting compose keeps the draft out of the worker's passes (`heavy_video.
#: hold`): a part join takes ~1-2 min; the render service, if down, needs longer.
JOIN_RETRY_AFTER_SECONDS = 30.0
RENDER_RETRY_AFTER_SECONDS = 60.0


def compose_waits_for_join(detail: str) -> LocalAssemblyWait:
    """A `heavy_video.LocalAssemblyWait` with `retry_after_s` > 0: a part join holds the
    worker's heavy-video gate, so this compose waits — nothing read, drawn or fitted on
    this pass, the draft out of the passes for `JOIN_RETRY_AFTER_SECONDS`."""
    from qualify_api.creative.heavy_video import LocalAssemblyWait  # noqa: PLC0415

    wait = LocalAssemblyWait(detail)
    wait.retry_after_s = JOIN_RETRY_AFTER_SECONDS
    return wait


def compose_waits_for_render(detail: str) -> LocalVideoWait:
    """A `heavy_video.LocalVideoWait` with `retry_after_s` > 0: our render service did not
    answer (a passing outage, never the owner's text) — the pass stops and a later one
    draws the texts. In the queue the pass that brings Seedance's clip replays it from its
    checkpoint, so waiting never pays it twice and never fails a paid clip."""
    from qualify_api.creative.heavy_video import LocalVideoWait  # noqa: PLC0415

    wait = LocalVideoWait(detail)
    wait.retry_after_s = RENDER_RETRY_AFTER_SECONDS
    return wait


#: How long a piece waits for the render service, from its FIRST failure — under the
#: reaper's 20 min, as `image_pipeline.compose_run.OUTAGE_WINDOW` (10 min).
COMPOSE_OUTAGE_WINDOW = timedelta(minutes=10)
#: The pipeline step that keeps the piece's first render failure (saved once, never reset).
#: Apart from `compose_run`'s -200… and `layer_run`'s -100…: an EF-14 clip runs neither.
COMPOSE_FIRST_FAILURE_STEP = -300
#: The pipeline step that keeps the preview's drawn text PNGs (`text_images_params`: key +
#: sha256 of each), saved BEFORE Seedance is ordered: every later pass reuses them.
COMPOSE_TEXTS_STEP = -301


def wait_for_render_or_give_up(
    code: str, *, store: Any = None, now: datetime | None = None
) -> None:
    """Inside a worker preparation, when the render service did not answer (and nothing
    is paid yet): record the piece's first failure (`COMPOSE_FIRST_FAILURE_STEP`) and
    RAISE `compose_waits_for_render` while `COMPOSE_OUTAGE_WINDOW` has not passed since
    then. Returns (None) only when the piece must fail — the window has passed, or there
    is no preparation (no queue to wait in) — and the caller fails it, normal refund."""
    from qualify_api.creative.pipeline import PipelineStore, current_preparation  # noqa: PLC0415

    run = current_preparation()
    if run is None:
        return
    store = store or PipelineStore()
    now = now or datetime.now(UTC)
    row = store.load_step(run, COMPOSE_FIRST_FAILURE_STEP)
    if row is None:
        row = store.save_step(
            run,
            COMPOSE_FIRST_FAILURE_STEP,
            {"first_failure_at": now.isoformat(), "error": code},
            None,
        )
    first = datetime.fromisoformat(str(row["request"]["first_failure_at"]))
    if now - first >= COMPOSE_OUTAGE_WINDOW:
        logger.warning("clip texts: render service down for %s, giving up", now - first)
        return
    raise compose_waits_for_render(f"render service: {code}")


@contextmanager
def heavy_gate() -> Iterator[None]:
    """`heavy_video.assembling()` for a compose: held for the encode; when a part join
    took the gate in between, `compose_waits_for_join` (with its `retry_after_s`)."""
    from qualify_api.creative.heavy_video import LocalAssemblyWait, assembling  # noqa: PLC0415

    gate = assembling()
    try:
        gate.__enter__()
    except LocalAssemblyWait as exc:
        raise compose_waits_for_join(str(exc)) from exc
    try:
        yield
    finally:
        gate.__exit__(None, None, None)  # releases the gate, whatever happened inside


def wait_if_heavy_video_busy() -> None:
    """`compose_waits_for_join` BEFORE any read, drawing or fit, when a part join holds the
    gate — so a waiting compose does not redo its whole pass on every turn of the loop."""
    from qualify_api.creative.heavy_video import busy  # noqa: PLC0415

    if busy():
        raise compose_waits_for_join("a part join is running: the compose waits")


class ClipComposeFailed(Exception):
    """The compose could not run. `owner_message` is what the owner reads; `owner_fault`
    True = his text does not fit (he changes it), False = ours (try again);
    `failure` the `FailureReason` value; `code` stable for the log and the tests;
    `transient` True only for an outage of the render service (waited for in the queue)."""

    def __init__(
        self,
        owner_message: str,
        *,
        failure: str,
        code: str,
        raw: str = "",
        owner_fault: bool = False,
        transient: bool = False,
    ) -> None:
        super().__init__(raw or code)
        self.owner_message = owner_message
        self.failure = failure
        self.code = code
        self.raw = raw
        self.owner_fault = owner_fault
        #: the render service did not answer (transport, 502/503/504, a timeout): an
        #: outage that may pass — the only failure a queued piece waits for
        self.transient = transient


@dataclass(frozen=True)
class ComposedClip:
    """The composed video and what its asset records."""

    data: bytes
    width: int
    height: int
    poster: bytes | None
    params: Mapping[str, Any]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _poster(path: Path) -> bytes | None:
    """The composed video's first frame as a JPEG (texts included), or None."""
    try:
        import av  # noqa: PLC0415

        with av.open(str(path)) as container:
            for frame in container.decode(container.streams.video[0]):
                out = io.BytesIO()
                frame.to_image().save(out, format="JPEG", quality=88)
                return out.getvalue()
    except Exception:  # noqa: BLE001 — a thumbnail is a nicety, never the piece
        logger.warning("composed clip poster not made", exc_info=True)
    return None


class ClipComposer:
    """Draws a recipe's texts (our render service) and lays them, with its layers, over a
    clip (PyAV). `render_client`: a `RemotionRenderClient` or a no-argument factory; None
    = no service wired, which reads as the service being down."""

    def __init__(self, render_client: Any = None) -> None:
        self._render_client = render_client

    def _client(self) -> Any:
        if self._render_client is not None:
            return self._render_client

        def missing() -> Any:
            raise RuntimeError("no render client wired for the clip's texts")

        return missing

    def draw(self, recipe: ComposeRecipe) -> tuple[Any, ...]:
        """Every text of `recipe` drawn, nothing encoded (before anything is paid)."""
        from qualify_api.creative.video_pipeline.compose import (  # noqa: PLC0415
            ComposeRejected,
            ComposeUnavailable,
            TextLayerRefused,
            draw_text_layers,
        )

        try:
            return draw_text_layers(recipe.text_layers, recipe.brand, render_client=self._client())
        except TextLayerRefused as exc:
            raise ClipComposeFailed(
                exc.owner_message,
                failure=FailureReason.INVALID_PARAMETERS.value,
                code=exc.code,
                raw=str(exc),
                owner_fault=True,
            ) from exc
        except ComposeUnavailable as exc:
            raise ClipComposeFailed(
                exc.owner_message,
                failure=(
                    FailureReason.INVALID_PARAMETERS.value
                    if isinstance(exc, ComposeRejected)
                    else FailureReason.DEPENDENCY_FAILED.value
                ),
                code=exc.code,
                raw=exc.detail,
                transient=exc.outage,
            ) from exc

    def compose(
        self,
        video: bytes,
        recipe: ComposeRecipe,
        *,
        drawn: Sequence[Any] | None = None,
        stage: str,
    ) -> ComposedClip:
        """`recipe` laid over `video` (already 9:16 within the overlay's tolerance): the
        layers under the texts in one pass. `drawn`: the texts `draw` made (None = drawn
        now). `stage`: `preview` or `final` (provenance). Writes only to a temporary
        folder; `video` is never touched. Raises `ClipComposeFailed`."""
        from qualify_creative.effects import NotALibraryLayer, load_effects  # noqa: PLC0415
        from qualify_creative.video import layer_overlay  # noqa: PLC0415
        from qualify_creative.video.layer_overlay import TimedEffectLayer  # noqa: PLC0415
        from qualify_creative.video.text_overlay import TextOverlayError  # noqa: PLC0415

        from qualify_api.creative.video_pipeline.compose import (  # noqa: PLC0415
            ComposeUnavailable,
            TextLayerRefused,
            compose_text_layers,
        )

        images = tuple(drawn) if drawn is not None else self.draw(recipe)
        library = load_effects()
        try:
            layers = []
            for use in recipe.effects:
                entry = library.get(use.effect_id, use.version)
                if entry is None:
                    raise NotALibraryLayer(f"{use.effect_id} v{use.version} is not in the library")
                layers.append(
                    TimedEffectLayer.from_entry(
                        entry, dict(use.params), start_s=use.start_s, end_s=use.end_s
                    )
                )
        except (NotALibraryLayer, ValueError) as exc:
            raise self._ours(exc) from exc
        with tempfile.TemporaryDirectory(prefix=_WORKDIR_PREFIX) as folder:
            src, out = Path(folder) / "clip.mp4", Path(folder) / "composed.mp4"
            src.write_bytes(video)
            params: dict[str, Any] = {}
            try:
                if recipe.text_layers:
                    result = compose_text_layers(
                        src,
                        out,
                        recipe.text_layers,
                        recipe.brand,
                        render_client=self._client(),
                        effect_layers=tuple(layers),
                        drawn_images=images,
                    )
                    params.update(result.params)
                    size = tuple(result.params["text_layers"]["size"])
                else:
                    made = layer_overlay.overlay_effect_layers(src, out, tuple(layers))
                    size = (made.width, made.height)
            except (TextLayerRefused, ComposeUnavailable) as exc:
                # the texts were drawn already: only reachable if they were not given
                raise self._ours(exc) from exc
            except (layer_overlay.LayerOverlayError, TextOverlayError) as exc:
                raise self._ours(exc) from exc
            data = out.read_bytes()
            poster = _poster(out)
        if layers:
            params["effect_layers"] = {
                "compose_version": layer_overlay.LAYER_COMPOSE_VERSION,
                "cost_usd": "0.00",
                "layers": [layer.params() for layer in layers],
            }
        width, height = int(size[0]), int(size[1])
        return ComposedClip(
            data=data,
            width=width,
            height=height,
            poster=poster,
            params={
                "stage": stage,
                "version": RECOMPOSE_VERSION,
                "recipe_sha256": recipe.digest(),
                "source_sha256": _sha256(video),
                "output_sha256": _sha256(data),
                "size": [width, height],
                "cost_usd": "0.00",
                **params,
            },
        )

    @staticmethod
    def _ours(exc: BaseException) -> ClipComposeFailed:
        return ClipComposeFailed(
            COMPOSE_NOT_ADDED_TEXT,
            failure=FailureReason.RENDER_ERROR.value,
            code="compose_failed",
            raw=f"{type(exc).__name__}: {exc}",
        )


__all__ = [
    "COMPOSE_FORMATS",
    "COMPOSE_NOT_ADDED",
    "COMPOSE_NOT_ADDED_TEXT",
    "COMPOSE_PARAMS_KEY",
    "COMPOSE_TEXTS_STEP",
    "CUT_TOLERANCE",
    "FINAL_COMPOSE_FAILED_TEXT",
    "RECOMPOSE_VERSION",
    "SEEDANCE_COMPOSE_EFFECTS_VERSION",
    "ClipComposeFailed",
    "ClipComposer",
    "ComposeRecipe",
    "ComposedClip",
    "compose_recipe_of",
    "composes_over_seedance",
    "nine_sixteen_size",
    "seedance_compose_allowed",
    "stored_recipe",
    "stored_text_images",
    "text_images_params",
]
