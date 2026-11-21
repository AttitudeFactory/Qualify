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
   recipe and the step's provenance go into the asset's `params["compose"]`.
2. **The final.** When the 1080p final of that draft arrives (`MediaProducer.finalize`, in
   the creative worker), the SAME frozen recipe (`stored_recipe(asset.params)`, never the
   brief as it reads today: «si la receta cambió de versión entre borrador y final, se usa
   la del borrador») is composed again over the fitted final, after its logo and
   subtitles, and its provenance (`final`: from which final task, raw file and source
   sha256) joins the preview's. Idempotent: the final's file has one key per order
   (`{stem}-final-{attempt}.mp4`); a retry that finds that key already kept takes the
   file as it is (`reused`) instead of composing a second one, and the raw 1080p is
   never paid twice (`raw_final`). A compose that fails fails the final with the raw
   1080p kept, so «Reintentar» costs the vendor nothing.

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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from qualify_creative.enums import ContentFormat, ContentKind, FailureReason
from qualify_creative.schemas import ContentBrief, EffectUse, VideoTextLayer

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


class ClipComposeFailed(Exception):
    """The compose could not run. `owner_message` is what the owner reads; `owner_fault`
    True = his text does not fit (he changes it), False = ours (try again);
    `failure` the `FailureReason` value; `code` stable for the log and the tests."""

    def __init__(
        self,
        owner_message: str,
        *,
        failure: str,
        code: str,
        raw: str = "",
        owner_fault: bool = False,
    ) -> None:
        super().__init__(raw or code)
        self.owner_message = owner_message
        self.failure = failure
        self.code = code
        self.raw = raw
        self.owner_fault = owner_fault


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
]
