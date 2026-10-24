"""UI presentation layer over the real C-05 permission -> capability matrix.

The matrix itself lives in `qualify_models.permission_capability`: which abstract
scope gates which capability, whether that gate is still `provisional`, and the
`ASSESSMENT_VERSION` stamped on every verdict. This module imports it verbatim and
adds only what is genuinely a presentation concern — the Spanish, operator-facing
label and reason for each capability.

Why the reason is re-worded here instead of rendered from the verdict: the real
`CapabilityVerdict.reason` is engineering prose in English that cites the founder
ruling and the QUA-95 documentary evidence ("CONFIRMED (QUA-95, 2026-08-27)
against Meta's own documentation..."). That text is correct for a developer
reading a persisted verdict and wrong for a shop owner reading a screen. The
*decision* (enabled/disabled, provisional) is never restated here — only its
wording.

`CAPABILITY_LABELS` / `CAPABILITY_DISABLED_REASONS` are asserted exhaustive against
the real `Capability` enum by `tests_connections.py`, so a capability added upstream
fails a test instead of raising `KeyError` in a running page.

`KNOWN_INFRASTRUCTURE_SCOPES` (QUA-96) is a second, orthogonal presentation table: it
does NOT feed `resolve_scope_keys` and is never merged into `SCOPE_LITERALS`/`ScopeKey`
upstream. Those model OAuth-plumbing scopes — granted by Meta to complete the login/
Page-enumeration flow (ADR 25/R4), not because they gate a product capability — so
`resolve_scope_keys` correctly reports them as unrecognized. Without this table, the
screen shows that unrecognized status with the same "Sin reconocer" alarm text it uses
for a genuinely new/renamed Meta scope. This table only softens that wording for the
four literals already confirmed as expected plumbing; it changes no logic upstream.
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
    "KNOWN_INFRASTRUCTURE_SCOPES",
    "SCOPE_KEY_LABELS",
    "Capability",
    "CapabilityVerdict",
    "ScopeKey",
    "assess_capabilities",
    "assessment_is_provisional",
    "resolve_scope_keys",
]


CAPABILITY_LABELS: dict[Capability, str] = {
    Capability.CONNECT_ACCOUNT: "Tu cuenta está conectada",
    Capability.PUBLISH_CONTENT: "Publicar reels (videos cortos) e historias",
    Capability.READ_COMMENTS: "Ver comentarios",
    Capability.ANALYZE_COMMENTS: "Saber de qué hablan tus comentarios",
    Capability.REPLY_COMMENTS: "Responder comentarios",
    Capability.MANAGE_DMS: "Ver mensajes",
    Capability.READ_INSIGHTS: "Ver tus resultados",
    # WhatsApp (WA-05)
    Capability.WA_SEND: "Enviar mensajes de WhatsApp",
    Capability.WA_TEMPLATES: "Plantillas de mensajes",
    Capability.WA_AUTOMATION: "Menú automático y bienvenida",
}

# Shown under a greyed-out capability. Each names the missing permission and what
# still works without it — the screen must explain, never surface a runtime 403.
CAPABILITY_DISABLED_REASONS: dict[Capability, str] = {
    Capability.CONNECT_ACCOUNT: (
        "No concediste el permiso básico de Instagram; es la base sobre la que se "
        "apoya todo lo demás."
    ),
    Capability.PUBLISH_CONTENT: (
        "No concediste el permiso para publicar. Los comentarios y los mensajes siguen funcionando."
    ),
    Capability.READ_COMMENTS: "No concediste el permiso de comentarios.",
    Capability.ANALYZE_COMMENTS: (
        "No concediste el permiso de comentarios; sin él no podemos decirte de qué "
        "hablan tus comentarios."
    ),
    Capability.REPLY_COMMENTS: ("No concediste el permiso para moderar y responder comentarios."),
    Capability.MANAGE_DMS: (
        "No concediste el permiso de mensajes directos. Publicar y los comentarios "
        "siguen funcionando."
    ),
    Capability.READ_INSIGHTS: (
        "No concediste el permiso de resultados de la cuenta; no entra en el permiso básico."
    ),
    # WhatsApp (WA-05): the "permission" here is on the system-user token the
    # administrator generated in Meta Business Settings, not on a consent screen.
    Capability.WA_SEND: (
        "El acceso de WhatsApp no incluye los dos permisos necesarios para enviar "
        "(mensajería y administración). Genera el acceso de nuevo con ambos."
    ),
    Capability.WA_TEMPLATES: (
        "El acceso de WhatsApp no incluye el permiso de administración; sin él no se "
        "pueden gestionar plantillas."
    ),
    Capability.WA_AUTOMATION: (
        "El acceso de WhatsApp no incluye el permiso de administración; sin él no se "
        "puede publicar el menú automático ni la bienvenida."
    ),
}

# Chips rendered on a connection card for each granted scope family.
SCOPE_KEY_LABELS: dict[ScopeKey, str] = {
    ScopeKey.BASIC: "Básico",
    ScopeKey.CONTENT_PUBLISH: "Publicación",
    ScopeKey.MANAGE_COMMENTS: "Comentarios",
    ScopeKey.MANAGE_MESSAGES: "Mensajes",
    ScopeKey.MANAGE_INSIGHTS: "Métricas",
    # WhatsApp (WA-05)
    ScopeKey.WA_MESSAGING: "WhatsApp: mensajería",
    ScopeKey.WA_MANAGEMENT: "WhatsApp: administración",
}

# Scopes Meta grants as a side effect of completing the OAuth/Page-enumeration flow
# (ADR 25/R4) or automatically with Facebook Login (`public_profile`) — never because
# they gate a product capability. Confirmed granted on the real `qualifymkt.co`
# connection (2026-08-27). Deliberately separate from `SCOPE_LITERALS`/`ScopeKey`: those
# model (granted scope -> product capability), this models (unrecognized literal ->
# "expected OAuth plumbing" vs. "genuinely unknown"). `_scope_labels` in
# `connections_provider.py` is the only reader.
KNOWN_INFRASTRUCTURE_SCOPES: dict[str, str] = {
    "business_management": "requerido para enumerar Páginas de un Business Portfolio (ADR 25)",
    "pages_read_engagement": "requerido para enumerar las Páginas del usuario (ADR 25)",
    "pages_show_list": "requerido para enumerar las Páginas del usuario (ADR 25)",
    "public_profile": "Meta lo concede automáticamente con Facebook Login, no se pide",
}
