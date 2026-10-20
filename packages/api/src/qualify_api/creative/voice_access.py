"""Which voice reads a brand's script (§ request 2026-10-05: "cierra esa vulnerabilidad
porque otro usuario / marca pueda usar la voz clonada de otro usuario/marca"; Seed Speech
since 2026-10-16).

Every brand's cloned voice lives in the ONE BytePlus Seed Speech account Qualify pays
for, so the vendor itself would happily read brand A's script in brand B's voice: the
isolation is Qualify's to enforce. Since the move to Seed Speech the browser never names
a cloned voice at all — the brief carries either `BRAND_VOICE` ("my brand's own voice")
or the id of a PUBLIC voice, and this module turns that into the speaker the vendor
gets:

- `BRAND_VOICE` → the brand's OWN clone, read through the tenant's RLS session; only a
  ready Seed Speech clone qualifies (a HeyGen clone of before 2026-10-16 does not);
- a public voice id → accepted only if it is in the closed list the picker shows
  (`byteplus_speech.PUBLIC_VOICE_IDS`);
- anything else — another brand's speaker id above all, but also an id made up by hand —
  is refused BEFORE anything is synthesized or rendered, as a policy failure, so nothing
  is spent on it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from qualify_creative.adapters.byteplus_speech import (
    CLONE_RESOURCE,
    PUBLIC_RESOURCE,
    PUBLIC_SPANISH_VOICES,
    PUBLIC_VOICE_IDS,
)

#: What the brief carries for "the brand's own cloned voice" — never the clone's id.
BRAND_VOICE = "brand"


class VoiceRefused(Exception):
    """The voice the brief asks for is not this brand's to use. `args[0]` is the
    operator-facing text."""


NO_BRAND_VOICE = "Tu voz clonada no está lista. Clónala en el Brand Kit (Tu voz) o elige otra voz."
UNKNOWN_VOICE = (
    "La voz elegida no está disponible para esta marca: solo puedes usar tu propia voz "
    "clonada o una de las voces disponibles."
)


@dataclass(frozen=True)
class ResolvedVoice:
    speaker: str
    resource_id: str
    brand_clone: bool
    #: The clone's language tag (`es-MX`…) — what `explicit_language` should say.
    language: str = "es"
    #: A brand clone never synthesized yet: its first real read charges the slot.
    charges_slot: bool = False


CloneLookup = Callable[[UUID, UUID], tuple[str, str, bool] | None]
"""(tenant_id, brand_id) → (speaker id, language, never used yet) of the brand's READY
Seed Speech clone, or None."""


def _db_clone_lookup(tenant_id: UUID, brand_id: UUID) -> tuple[str, str] | None:
    from .voice_clone import VoiceCloneService  # noqa: PLC0415 — keeps the DB out of tests

    clone = VoiceCloneService().current(tenant_id=tenant_id, brand_id=brand_id)
    if clone is None or not clone.is_ready:
        return None
    return clone.voice_id, clone.language or "es", clone.activated_at is None


def default_public_voice(gender: str = "female") -> str:
    """The first public voice of `gender` — what a brief with no voice reads with."""
    for voice in PUBLIC_SPANISH_VOICES:
        if voice["gender"] == gender:
            return voice["id"]
    return PUBLIC_SPANISH_VOICES[0]["id"]


def _explicit_language(tag: str) -> str:
    return "es-mx" if tag.lower().startswith("es-mx") else "es"


class BrandVoiceResolver:
    """The production resolver: the brand's own clone, or a public voice."""

    def __init__(self, *, clone_lookup: CloneLookup = _db_clone_lookup) -> None:
        self._clone_lookup = clone_lookup

    def __call__(self, *, tenant_id: UUID, brand_id: UUID, choice: str) -> ResolvedVoice:
        choice = (choice or "").strip()
        if choice == BRAND_VOICE:
            found = self._clone_lookup(tenant_id, brand_id)
            if found is None:
                raise VoiceRefused(NO_BRAND_VOICE)
            speaker, language, fresh = found
            return ResolvedVoice(
                speaker=speaker,
                resource_id=CLONE_RESOURCE,
                brand_clone=True,
                language=_explicit_language(language),
                charges_slot=fresh,
            )
        if choice in PUBLIC_VOICE_IDS:
            return ResolvedVoice(speaker=choice, resource_id=PUBLIC_RESOURCE, brand_clone=False)
        raise VoiceRefused(UNKNOWN_VOICE)
