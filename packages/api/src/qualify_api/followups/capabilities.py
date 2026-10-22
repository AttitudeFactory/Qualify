"""Per-origin capabilities of Fase C (m-24789646): which ways of continuing a commercial
query in private this deployment may use.

Every Meta operation Fase C needs and that is not verified against the real API sits
behind one of these switches, OFF by default (B6). A switch is an environment variable
read once per composition; exactly `on` (any case) turns it on, anything else — unset
included — leaves it off, the same rule as `QUALIFY_STORY_COMMENTS` (m-24789644), which
this registry reuses rather than duplicates.

Each capability also carries its STATE in the ticket's vocabulary — the reason the UI
shows next to «no disponible todavía»:

- `meta_limitation` — the API does not allow it; documented, not built.
- `pending_config` — the API allows it, a permission/subscription/panel setting is missing.
- `not_implemented` — Meta allows it and the code is missing.
- `to_verify` — built against the documented contract, waiting for a real test.
- `verified` — a real test, recorded in `docs/conversaciones-limitaciones-meta.md`.

A `not_implemented` capability is never enabled, whatever its switch says: there is no
code behind it to run. Moving a state is a code change with its evidence, never a
setting. The normal DM to a thread whose 24 h window is open is NOT here: it was verified
in production by QUA-226 and is always available.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from qualify_api.inbox.composition import STORY_COMMENTS_ENV


class Capability(StrEnum):
    COMMENT_PRIVATE_REPLY = "comment_private_reply"
    STORY_COMMENTS = "story_comments"
    STORY_REPLY_CONTEXT = "story_reply_context"
    PUBLIC_NOTICE = "public_notice"


class CapabilityState(StrEnum):
    VERIFIED = "verified"
    TO_VERIFY = "to_verify"
    PENDING_CONFIG = "pending_config"
    NOT_IMPLEMENTED = "not_implemented"
    META_LIMITATION = "meta_limitation"


STATE_LABELS: Final[Mapping[CapabilityState, str]] = {
    CapabilityState.VERIFIED: "Verificado",
    CapabilityState.TO_VERIFY: "Por verificar",
    CapabilityState.PENDING_CONFIG: "Configuración pendiente",
    CapabilityState.NOT_IMPLEMENTED: "No implementado en Qualify",
    CapabilityState.META_LIMITATION: "Limitación de Meta",
}


@dataclass(frozen=True)
class CapabilitySpec:
    capability: Capability
    env_var: str
    state: CapabilityState
    # Spanish, shown to the operator next to «no disponible todavía».
    reason: str


REGISTRY: Final[Mapping[Capability, CapabilitySpec]] = {
    spec.capability: spec
    for spec in (
        CapabilitySpec(
            Capability.COMMENT_PRIVATE_REPLY,
            "QUALIFY_COMMENT_PRIVATE_REPLY",
            CapabilityState.VERIFIED,
            "La respuesta privada a un comentario (un solo mensaje, dentro de 7 días) se "
            "verificó con Meta el 2026-10-22 (R1).",
        ),
        CapabilitySpec(
            Capability.STORY_COMMENTS,
            STORY_COMMENTS_ENV,
            CapabilityState.META_LIMITATION,
            "Meta no entrega por la API los comentarios de las historias («Comments cannot "
            "be made on story media», prueba real del 2026-10-21).",
        ),
        CapabilitySpec(
            Capability.STORY_REPLY_CONTEXT,
            "QUALIFY_STORY_REPLY_CONTEXT",
            CapabilityState.VERIFIED,
            "Qualify lee a qué historia responde un mensaje directo y le contesta por DM; "
            "verificado con Meta el 2026-10-22 (R3).",
        ),
        CapabilitySpec(
            Capability.PUBLIC_NOTICE,
            "QUALIFY_PUBLIC_NOTICE",
            CapabilityState.VERIFIED,
            "El aviso público «Te enviamos la información por DM 💬» (una respuesta pública "
            "al comentario, solo tras confirmar el mensaje privado) se verificó con Meta el "
            "2026-10-22 (R4).",
        ),
    )
}

_SWITCHED_OFF_REASON: Final = "{reason} Desactivada en este despliegue ({env_var})."


@dataclass(frozen=True)
class Availability:
    capability: Capability
    enabled: bool
    state: CapabilityState
    # Empty when enabled; otherwise why it is not available (Spanish).
    reason: str

    @property
    def state_label(self) -> str:
        return STATE_LABELS[self.state]


def _switched_on(value: str | None) -> bool:
    return (value or "").strip().lower() == "on"


@dataclass(frozen=True)
class Capabilities:
    """The switches of one deployment. Build it with `from_env` at composition time and
    pass it down; nothing below the composition reads the environment."""

    switched_on: frozenset[Capability] = frozenset()

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Capabilities:
        env = os.environ if environ is None else environ
        return cls(
            frozenset(cap for cap, spec in REGISTRY.items() if _switched_on(env.get(spec.env_var)))
        )

    def availability(self, capability: Capability) -> Availability:
        spec = REGISTRY[capability]
        if spec.state is CapabilityState.NOT_IMPLEMENTED:
            return Availability(capability, False, spec.state, spec.reason)
        if capability not in self.switched_on:
            reason = spec.reason
            if spec.state is not CapabilityState.META_LIMITATION:
                reason = _SWITCHED_OFF_REASON.format(reason=spec.reason, env_var=spec.env_var)
            return Availability(capability, False, spec.state, reason)
        return Availability(capability, True, spec.state, "")

    def enabled(self, capability: Capability) -> bool:
        return self.availability(capability).enabled
