"""EF-13 (m-25026589, ADR 50 D5): a «Con IA» effect asked of Seedance as «an object in a
zone of the frame».

A `seedance_prompt` entry of the effects library (`fuego_lena_base`, `vapor_sobre_comida`,
`humo_denso`…) is a prompt template with two slots, `{zone}` (the band of the frame the
owner chose: `top`, `middle`, `bottom`) and `{subject}` (the piece's product). Filled
(`qualify_creative.effects.seedance_effect_line`), it is ONE line added at the end of the
part's own Seedance prompt — the same request, the same 480p draft and 1080p final as
today, the same price guard and the same video seconds charged: an effect adds no call.

What makes one buildable (`is_built_seedance_effect`, read by
`recipe.unbuilt_recipe_problems` on every NEW request, before any row, charge or call):

- the switch `QUALIFY_SEEDANCE_EFFECTS` is `on` (default `off`: refused as before EF-13,
  `recipe_unavailable` — production does not change until Deivid turns it on);
- the part (or Clip) is made by Seedance in `reference` mode (D4: never `edit` or `extend`
  of the owner's video; `local` has no Seedance at all, `local_with_ai_effect`);
- the use covers the whole part (no `start_s`/`end_s`: Seedance draws the whole shot).

Whether the effect is OFFERED (measured over D5's bar, `Measured.passes`) and its params
are valid is `validate_recipe`'s, against the library, like every effect: an unmeasured
template is `not_offered` whatever the switch says. Today no template is measured, so
none is offered.

Provenance (rule 6): `SeedanceEffect.provenance` — effect id and version, the template's
`prompt_version`, the fill version, the library, the zone and the line itself — goes into
the asset's params and its draft block, so the final carries it too. Idempotent: the line
is a pure function of the stored brief and the library, so a resumed run asks the same.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Final

from qualify_creative.effects import (
    EFFECTS_LIBRARY_VERSION,
    SEEDANCE_EFFECT_FILL_VERSION,
    EffectEntry,
    EffectsLibrary,
    effect_subject,
    effect_zone,
    load_effects,
    seedance_effect_line,
)
from qualify_creative.enums import ContentKind
from qualify_creative.schemas import ContentBrief, EffectUse

logger = logging.getLogger(__name__)

#: Deivid's switch for EF-13: `off` (the default) refuses every Seedance effect as before
#: (`recipe_unavailable`); `on` lets a measured, offered one through.
SEEDANCE_EFFECTS_SWITCH: Final = "QUALIFY_SEEDANCE_EFFECTS"
#: The key of the provenance block in an asset's params and its draft block.
SEEDANCE_EFFECT_PARAMS_KEY: Final = "seedance_effect"


def seedance_effects_on() -> bool:
    """Whether `QUALIFY_SEEDANCE_EFFECTS` is `on`. Anything else but `off`/empty is logged
    and read as off: never an effect by a typo."""
    value = os.environ.get(SEEDANCE_EFFECTS_SWITCH, "off").strip().lower()
    if value in ("", "off"):
        return False
    if value == "on":
        return True
    logger.error("%s must be off or on, not %r: read as off", SEEDANCE_EFFECTS_SWITCH, value)
    return False


def _entry(use: EffectUse, library: EffectsLibrary | None) -> EffectEntry | None:
    return (library or load_effects()).get(use.effect_id, use.version)


def is_seedance_effect(use: EffectUse, library: EffectsLibrary | None = None) -> bool:
    """Whether `use` names a Seedance template of the library (stage `seedance_prompt`)."""
    entry = _entry(use, library)
    return entry is not None and entry.stage == "seedance_prompt"


def is_built_seedance_effect(
    use: EffectUse, mode: str, library: EffectsLibrary | None = None
) -> bool:
    """Whether the engine makes `use` today (see the module): the switch on, a Seedance
    template, a `reference` part or Clip, over the whole part. Pure but for the switch."""
    return (
        mode == "reference"
        and use.start_s is None
        and use.end_s is None
        and is_seedance_effect(use, library)
        and seedance_effects_on()
    )


@dataclass(frozen=True)
class SeedanceEffect:
    """The Seedance effect of one piece, filled: the line its prompt ends with and the
    provenance the asset keeps."""

    entry: EffectEntry
    use: EffectUse
    zone: str
    subject: str
    line: str

    @property
    def provenance(self) -> dict[str, Any]:
        return {
            "effect_id": self.entry.id,
            "version": self.entry.version,
            "prompt_version": self.entry.prompt_version,
            "fill_version": SEEDANCE_EFFECT_FILL_VERSION,
            "library_version": EFFECTS_LIBRARY_VERSION,
            "zone": self.zone,
            "line": self.line,
        }


def seedance_effect_of(
    brief: ContentBrief, library: EffectsLibrary | None = None
) -> SeedanceEffect | None:
    """The Seedance effect of a Clip (a normal one or a part's child), filled — or None
    when it carries none. At most one per part (`too_many_ai_effects` refused it before);
    the first is taken. Pure (the library is cached)."""
    from qualify_api.creative.video_pipeline.recipe import recipe_of  # noqa: PLC0415

    if brief.kind is not ContentKind.CLIP:
        return None  # a parent's parts are made as their own Clips
    library = library or load_effects()
    for part in recipe_of(brief)[:1]:
        for use in part.effects:
            entry = library.get(use.effect_id, use.version)
            if entry is None or entry.stage != "seedance_prompt":
                continue
            subject = effect_subject(brief.product_ref)
            return SeedanceEffect(
                entry=entry,
                use=use,
                zone=effect_zone(entry, use),
                subject=subject,
                line=seedance_effect_line(entry, use, subject=subject),
            )
    return None


__all__ = [
    "SEEDANCE_EFFECTS_SWITCH",
    "SEEDANCE_EFFECT_PARAMS_KEY",
    "SeedanceEffect",
    "is_built_seedance_effect",
    "is_seedance_effect",
    "seedance_effect_of",
    "seedance_effects_on",
]
