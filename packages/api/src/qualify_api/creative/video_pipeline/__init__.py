"""The video-with-effects pipeline (ADR 50, epic «Video automático con efectos, por pasos»).

One engine for both screens: it works on the `CLIP` piece — a normal Clip, or a part of a
video by parts, which is a child `CLIP` — and the parent of a video by parts only adds
what goes between its parts. EF-02 builds the recipe and its pure checks:

- `recipe` — `PartRecipe`; `recipe_of(brief)` (1 part for a Clip, N for a parent); the
  pure `validate_recipe` (and, ED-15, `validate_video_recipe` for the parent's whole-video
  recipe); the fail-closed gate `refuse_unbuilt_recipe`.

The later stages (Preparar, local tools, compose, contact sheet: EF-03 onwards) join this
package; pixels stay in `qualify_creative.video`. `media.MediaProducer._clip` delegates
here only when `effects_pipeline_version >= 1`, which nothing stamps yet.
"""

from qualify_api.creative.video_pipeline.recipe import (
    PartRecipe,
    RecipeRefused,
    recipe_of,
    refuse_unbuilt_recipe,
    validate_brief_recipe,
    validate_recipe,
    validate_video_recipe,
)

__all__ = [
    "PartRecipe",
    "RecipeRefused",
    "recipe_of",
    "refuse_unbuilt_recipe",
    "validate_brief_recipe",
    "validate_recipe",
    "validate_video_recipe",
]
