"""Brand readiness: the server-side guard of design §6.1, amended by D4.

`compute_readiness` is pure — kit in, verdict out — so the gates are unit-testable with
no database. The `readiness(...)` wrapper is the service face §4.4 names: it reads
through the sanctioned doors and delegates every decision to the pure function.

Two amendments to the §6.1 sketch, both deliberate:
- **No credential gate (D4):** the platform pays for generation in the MVP, so no
  BYOK key is required to be "ready" and no `budget_remaining_usd` appears here.
- **Completeness is weighted, not counted.** The design's own UX note (§6.2) says the
  copy examples move the output more than the palette — so `do_examples`,
  `dont_examples` and the tone axes carry most of the score, and the visual fields
  (palette, logo) carry the least. A kit that is "half full" of the wrong half is not
  half ready.

Completeness is computed here, never stored (see `models.BrandKit`'s docstring: a
persisted derivable is a staleness bug waiting to be believed).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from qualify_creative.schemas import BrandKit

from qualify_api.creative.brand_service import BrandKitService
from qualify_api.creative.voice_service import VoiceProfileService

# The `missing` marker for the voice gate — not a kit field, so named apart.
ACTIVE_VOICE_GAP = "active_voice_profile"

# Weighted kit fields, in display order. Weights sum to 1.0; the ordering inside the
# tuple is also the order `missing` reports, so the UI lists the highest-impact gap
# first. Copy substance (examples + tone axes) outweighs visual polish by design.
_WEIGHTS: tuple[tuple[str, float], ...] = (
    ("positioning", 0.15),
    ("audience", 0.15),
    ("tone_axes", 0.15),
    ("do_examples", 0.20),
    ("dont_examples", 0.15),
    ("cta_patterns", 0.10),
    ("palette_rgb", 0.05),
    ("logo_asset_key", 0.05),
)

# What `can_distill` requires (task ruling): positioning + audience + tone axes +
# at least one do-example. Everything else improves output; these make it possible.
_DISTILL_REQUIRED: frozenset[str] = frozenset(
    {"positioning", "audience", "tone_axes", "do_examples"}
)


@dataclass(frozen=True)
class BrandReadiness:
    has_kit: bool
    kit_completeness: float  # 0..1, weighted over the fields that move the output
    has_active_voice: bool
    missing: tuple[str, ...]  # weighted-field names + ACTIVE_VOICE_GAP, gap-first order

    @property
    def can_distill(self) -> bool:
        """Kit complete enough to propose a voice profile from."""
        return self.has_kit and _DISTILL_REQUIRED.isdisjoint(self.missing)

    @property
    def can_generate(self) -> bool:
        """The gate on /create: a distillable kit plus an approved voice. No credential
        check — D4 removed it, the platform pays in the MVP."""
        return self.can_distill and self.has_active_voice


def _satisfied(kit: BrandKit) -> dict[str, bool]:
    return {
        "positioning": bool(kit.positioning.strip()),
        "audience": bool(kit.audience.strip()),
        # The schema requires tone axes on every kit, so presence follows from the kit
        # existing; kept as a named field so its weight and gap-reporting are explicit.
        "tone_axes": True,
        "do_examples": len(kit.do_examples) >= 1,
        "dont_examples": len(kit.dont_examples) >= 1,
        "cta_patterns": len(kit.cta_patterns) >= 1,
        "palette_rgb": len(kit.palette_rgb) >= 1,
        "logo_asset_key": kit.logo_asset_key is not None,
    }


def compute_readiness(kit: BrandKit | None, has_active_voice: bool) -> BrandReadiness:
    """Pure verdict: no clock, no database, no network."""
    if kit is None:
        completeness = 0.0
        missing = tuple(name for name, _ in _WEIGHTS)
    else:
        satisfied = _satisfied(kit)
        completeness = round(sum(weight for name, weight in _WEIGHTS if satisfied[name]), 4)
        missing = tuple(name for name, _ in _WEIGHTS if not satisfied[name])
    if not has_active_voice:
        missing = (*missing, ACTIVE_VOICE_GAP)
    return BrandReadiness(
        has_kit=kit is not None,
        kit_completeness=completeness,
        has_active_voice=has_active_voice,
        missing=missing,
    )


def readiness(*, tenant_id: UUID, brand_id: UUID) -> BrandReadiness:
    """Service wrapper (§4.4): read the kit and the active voice, judge purely."""
    kit = BrandKitService().get_kit(tenant_id=tenant_id, brand_id=brand_id)
    active = VoiceProfileService().active_profile(tenant_id=tenant_id, brand_id=brand_id)
    return compute_readiness(kit, active is not None)
