"""UI presentation layer over the real C-05 permission -> capability matrix.

The matrix itself lives in `qualify_models.permission_capability`: which abstract
scope gates which capability, whether that gate is still `provisional`, and the
`ASSESSMENT_VERSION` stamped on every verdict. This module imports it verbatim and
adds only what is genuinely a presentation concern — the Spanish, operator-facing
label and reason for each capability.

Why the reason is re-worded here instead of rendered from the verdict: the real
`CapabilityVerdict.reason` is engineering prose in English that cites the founder
ruling and the harvested Meta corpus ("PROVISIONAL: encoded pessimistically
(founder ruling 2026-07-25)..."). That text is correct for a developer reading a
persisted verdict and wrong for a shop owner reading a screen. The *decision*
(enabled/disabled, provisional) is never restated here — only its wording.

`CAPABILITY_LABELS` / `CAPABILITY_DISABLED_REASONS` are asserted exhaustive against
the real `Capability` enum by `tests_connections.py`, so a capability added upstream
fails a test instead of raising `KeyError` in a running page.
"""

from __future__ import annotations

from qualify_models.permission_capability import (
    ASSESSMENT_VERSION,
    Capability,
    CapabilityVerdict,
    ScopeKey,
    assess_capabilities,
    assessment_is_provisional,
    resolve_scope_keys,
)

__all__ = [
    "ASSESSMENT_VERSION",
    "CAPABILITY_DISABLED_REASONS",
    "CAPABILITY_LABELS",
    "SCOPE_KEY_LABELS",
    "Capability",
    "CapabilityVerdict",
    "ScopeKey",
    "assess_capabilities",
    "assessment_is_provisional",
    "resolve_scope_keys",
]


CAPABILITY_LABELS: dict[Capability, str] = {
    Capability.CONNECT_ACCOUNT: "Conectar cuenta",
    Capability.PUBLISH_CONTENT: "Publicar reels y stories",
    Capability.READ_COMMENTS: "Leer comentarios",
    Capability.ANALYZE_COMMENTS: "Analizar sentiment y temas",
    Capability.REPLY_COMMENTS: "Responder comentarios",
    Capability.MANAGE_DMS: "Bandeja de mensajes directos",
    Capability.READ_INSIGHTS: "Métricas de la cuenta",
}

# Shown under a greyed-out capability. Each names the missing permission and what
# still works without it — the screen must explain, never surface a runtime 403.
CAPABILITY_DISABLED_REASONS: dict[Capability, str] = {
    Capability.CONNECT_ACCOUNT: (
        "No concediste el permiso básico de Instagram; es la base sobre la que se "
        "apoya todo lo demás."
    ),
    Capability.PUBLISH_CONTENT: (
        "No concediste el permiso de publicación. La lectura, los comentarios y los "
        "mensajes no se ven afectados."
    ),
    Capability.READ_COMMENTS: "No concediste el permiso de comentarios.",
    Capability.ANALYZE_COMMENTS: (
        "No concediste el permiso de comentarios; sin él no se puede analizar el "
        "sentiment ni los temas."
    ),
    Capability.REPLY_COMMENTS: ("No concediste el permiso para moderar y responder comentarios."),
    Capability.MANAGE_DMS: (
        "No concediste el permiso de mensajes directos. La publicación, los "
        "comentarios y el listening siguen funcionando."
    ),
    Capability.READ_INSIGHTS: (
        "No concediste el permiso de métricas de la cuenta; las métricas no entran "
        "en el permiso básico."
    ),
}

# Chips rendered on a connection card for each granted scope family.
SCOPE_KEY_LABELS: dict[ScopeKey, str] = {
    ScopeKey.BASIC: "Básico",
    ScopeKey.CONTENT_PUBLISH: "Publicación",
    ScopeKey.MANAGE_COMMENTS: "Comentarios",
    ScopeKey.MANAGE_MESSAGES: "Mensajes",
    ScopeKey.MANAGE_INSIGHTS: "Métricas",
}
