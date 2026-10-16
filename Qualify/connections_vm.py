"""View-models for the connections screen (C-06) — the security boundary.

Because **every Reflex var is serialized to the client**, the "never show or log
credential material" acceptance criterion (QUA-18) is enforced *structurally*: the
`ConnectionsState` only ever holds these whitelisted dataclasses, never an ORM row
of `social_connections` / `oauth_credentials`. There is no field here that can
carry a token, ciphertext, or `key_id`, so there is no route from the DB to the
browser. Same pattern as the existing `MentionRow` in `state.py`.

Keep this module free of Reflex and network imports so the whitelist can be
asserted by a plain unit test (`test_connections.py`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .capabilities import (
    CAPABILITY_DISABLED_REASONS,
    CAPABILITY_LABELS,
    CapabilityVerdict,
)

# Connection health states — the FSM surface of C-03.3 that the UI renders.
# "pending" exists in the FSM but is transient (mid-OAuth) and not listed here as a
# steady display state; the three below are what a loaded connection shows.
ConnectionStatus = str  # "active" | "degraded" | "revoked"


@dataclass(frozen=True)
class CapabilityVM:
    """Display-ready projection of a C-05 CapabilityVerdict. No credential fields."""

    key: str  # Capability enum value, stable id for rx.match / keys
    label: str  # UI-facing Spanish label
    enabled: bool
    reason: str  # motive shown when disabled ("" when enabled)
    provisional: bool  # C-05.4: capability rests on an unverified Meta doc row


@dataclass
class ConnectionVM:
    """Display-ready projection of one `social_connections` row.

    Whitelisted on purpose — adding a credential-bearing field here would be a
    security regression caught by `test_connection_vm_has_no_credential_fields`.
    """

    id: str
    platform: str  # "instagram" | "facebook" | "whatsapp" (WA-05)
    brand: str
    # The card's title. Instagram: the @username. WhatsApp: the display number, plus the
    # verified name when `whatsapp_phone_numbers` has one (WA-05) — see `whatsapp_label`.
    external_username: str
    status: ConnectionStatus
    last_verified_at: str  # PRE-FORMATTED server-side (never a raw datetime var)
    granted_scopes: list[str]  # human-readable scope labels, never the raw token
    # QUA-91: distinct from `last_verified_at` above — that one reflects the connect-flow
    # verification (QUA-16), this one reflects the LAST manual "Verificar ahora" click.
    # Conflating the two is exactly the UX gap this field closes: before it existed, a
    # click ran /debug_token for real but nothing on screen changed. PRE-FORMATTED
    # server-side, same discipline as `last_verified_at`.
    last_health_checked_at: str = "Sin verificar"
    enabled_capabilities: list[CapabilityVM] = field(default_factory=list)
    disabled_capabilities: list[CapabilityVM] = field(default_factory=list)
    # QUA-91: the data-access-window warning, INDEPENDENT of `status`/the FSM. Empty
    # string means "nothing to show" — never confuse this with `status == "degraded"`,
    # which is the real, evidence-based (401/190) case. `data_access_state` is a closed
    # vocabulary ("" | "warning_soon" | "warning_overdue") so the page can pick the icon
    # without re-deriving it; `data_access_message` is pre-formatted, same discipline as
    # `last_verified_at`.
    data_access_state: str = ""
    data_access_message: str = ""
    # NOTE: there is deliberately no `auth_url` field. The C-04 authorization URL is
    # minted by `start_connect`, which registers a one-shot `state` jti in Redis per
    # call; precomputing one per row at page load would burn a token for every
    # connection the operator never reconnects, and age it until it expired. The
    # reconnect buttons call the event handler instead.
    # True when any shown capability is provisional (C-05.4) — drives an honest
    # "por verificar" marker in the UI rather than asserting an unverified row.
    has_provisional_capabilities: bool = False


# WA-05: a WhatsApp number is connected by an administrator with a system-user token
# (`qualify_api.whatsapp.connect`), not through Meta's consent screen — so its degraded/
# revoked banners carry this hint instead of the Instagram «Reconectar» button, which
# would start the wrong flow. Self-service connect is QUA-203, deliberately out of scope.
WHATSAPP_RECONNECT_HINT = (
    "Los números de WhatsApp se conectan desde la administración de Qualify, no desde "
    "esta pantalla. Pide al equipo de Qualify que vuelva a ejecutar la conexión del número."
)


def whatsapp_label(display_phone_number: str, verified_name: str | None) -> str:
    """The card title of a WhatsApp connection: «+57 300 1234567 · Bianki» when Meta
    reported a verified name, the bare number otherwise. Pre-composed server-side so the
    client receives one string, same discipline as every other formatted field here."""
    name = (verified_name or "").strip()
    return f"{display_phone_number} · {name}" if name else display_phone_number


def _capability_vm(verdict: CapabilityVerdict) -> CapabilityVM:
    """Project a verdict for display: Spanish copy, and a reason only when disabled.

    The real C-05 verdict always carries a `reason` (English engineering prose) even
    when enabled; the client receives neither — the operator-facing wording comes from
    `CAPABILITY_DISABLED_REASONS`, and an enabled capability ships no reason at all.
    """
    return CapabilityVM(
        key=str(verdict.capability),
        label=CAPABILITY_LABELS[verdict.capability],
        enabled=verdict.enabled,
        reason="" if verdict.enabled else CAPABILITY_DISABLED_REASONS[verdict.capability],
        provisional=verdict.provisional,
    )


def build_connection_vm(
    *,
    connection_id: str,
    platform: str,
    brand: str,
    external_username: str,
    status: ConnectionStatus,
    last_verified_at: str,
    granted_scope_labels: list[str],
    verdicts: tuple[CapabilityVerdict, ...],
    last_health_checked_at: str = "Sin verificar",
    data_access_state: str = "",
    data_access_message: str = "",
) -> ConnectionVM:
    """Assemble a whitelisted VM, partitioning capabilities enabled/disabled here.

    Partitioning happens in this builder (called from the loader/handler), not in a
    computed var, so the frontend never receives the full verdict objects — only the
    two whitelisted lists it renders.
    """
    enabled: list[CapabilityVM] = []
    disabled: list[CapabilityVM] = []
    provisional_shown = False
    for verdict in verdicts:
        vm = _capability_vm(verdict)
        if vm.provisional and vm.enabled:
            provisional_shown = True
        (enabled if vm.enabled else disabled).append(vm)
    return ConnectionVM(
        id=connection_id,
        platform=platform,
        brand=brand,
        external_username=external_username,
        status=status,
        last_verified_at=last_verified_at,
        granted_scopes=granted_scope_labels,
        enabled_capabilities=enabled,
        disabled_capabilities=disabled,
        has_provisional_capabilities=provisional_shown,
        last_health_checked_at=last_health_checked_at,
        data_access_state=data_access_state,
        data_access_message=data_access_message,
    )


# QUA-123: the OAuth callback ends with `303 → /connections?connect=<code>`. The code is a
# closed vocabulary — the four `ConnectOutcome` values plus the route's `invalid_state` and
# `denied` — so this table is the whole contract. Each entry is (message, tone); the tone
# is a design-system tone (`ok`/`warn`/`info`), never a raw colour.
CONNECT_RESULT_NOTICES: dict[str, tuple[str, str]] = {
    "active": ("Cuenta conectada. Ya aparece en la lista con sus permisos.", "ok"),
    "degraded": (
        "La cuenta se conectó, pero Meta no confirmó el acceso. "
        "Usa «Verificar ahora» en su tarjeta en unos minutos.",
        "warn",
    ),
    "link_required": (
        "Meta no devolvió ninguna Página con una cuenta de Instagram vinculada. "
        "Vincula tu cuenta profesional de Instagram a tu Página de Facebook y vuelve a "
        "conectar.",
        "warn",
    ),
    "page_access_required": (
        "Meta no compartió ninguna Página con Qualify. Al conectar, selecciona la Página "
        "de Facebook vinculada a tu Instagram y vuelve a intentarlo.",
        "warn",
    ),
    "denied": ("Cancelaste la conexión con Meta. No se guardó nada.", "info"),
    "invalid_state": (
        "El enlace de conexión expiró o ya se usó. Pulsa «Conectar cuenta» de nuevo.",
        "warn",
    ),
}


def connect_result_notice(code: str) -> tuple[str, str]:
    """(message, tone) for a `?connect=` code; ("", "info") for none or an unknown one —
    the parameter arrives in the URL, so junk is ignored rather than echoed."""
    return CONNECT_RESULT_NOTICES.get(code, ("", "info"))


# --------------------------------------------------------------------------------------
# QUA-202: guided connection. Everything below is copy for a non-technical operator —
# no "OAuth", no "scope", no "token" anywhere in it (`test_guidance_copy_has_no_jargon`).
# --------------------------------------------------------------------------------------

# The path inside the Instagram app that every Page step shares. One constant so the
# three places that spell it out never drift.
_IG_PAGE_PATH = "Instagram → Editar perfil → Información pública de la empresa → Página"


@dataclass(frozen=True)
class ConnectRequirementVM:
    """One of the three things the operator needs BEFORE pressing «Conectar cuenta».
    A pre-flight hint (R4a), never a verification: the screen cannot check any of it."""

    key: str
    title: str
    summary: str
    steps: list[str]


CONNECT_REQUIREMENTS: list[ConnectRequirementVM] = [
    ConnectRequirementVM(
        key="professional",
        title="Tu Instagram es una cuenta profesional",
        summary="Tipo Empresa o Creador. Una cuenta personal no se puede conectar.",
        steps=[
            "En Instagram, abre tu perfil y toca el menú ☰ → Configuración y actividad.",
            "Entra en «Tipo de cuenta y herramientas» → «Cambiar a cuenta profesional».",
            "Elige «Empresa» y termina el asistente (puedes omitir lo que no apliques).",
        ],
    ),
    ConnectRequirementVM(
        key="page",
        title="Tienes una Página de Facebook de tu negocio",
        summary=(
            "Qualify habla con Meta a través de esa Página. Si no tienes, "
            "se crea en dos minutos desde la app de Instagram."
        ),
        steps=[
            f"{_IG_PAGE_PATH}.",
            "Toca «Conectar o crear» → «Crear una nueva Página de Facebook».",
            "Ponle el nombre de tu negocio y guarda. Ya está vinculada a tu Instagram.",
        ],
    ),
    ConnectRequirementVM(
        key="linked",
        title="Tu Instagram está vinculado a esa Página",
        summary="Es lo que más se olvida: tener la Página no basta, hay que unirlas.",
        steps=[
            f"{_IG_PAGE_PATH}.",
            "Toca «Conectar o crear» y elige la Página de tu negocio.",
            "Al conectar con Qualify, Meta te preguntará qué Páginas compartir: "
            "marca la de tu negocio.",
        ],
    ),
]


@dataclass(frozen=True)
class ConnectGuidance:
    """The guided panel for a dead-end `?connect=` result: what happened (with the two
    R9(e.1) counts the callback adds to the URL), the steps that fix exactly THIS case,
    and whether the retry must ask Meta to show the Page picker again (`rerequest`).

    `code == ""` means "no panel": the plain `connect_result_notice` is shown instead."""

    code: str = ""
    title: str = ""
    summary: str = ""
    steps: list[str] = field(default_factory=list)
    rerequest: bool = False


def _count(raw: str) -> int | None:
    """A `?pages=` / `?linked=` value: a small non-negative integer, or nothing. The
    value arrives in the URL, so anything else is ignored rather than rendered."""
    if not raw.isdigit() or len(raw) > 4:
        return None
    return int(raw)


def _pages_phrase(pages: int) -> str:
    return "1 Página de Facebook" if pages == 1 else f"{pages} Páginas de Facebook"


def connect_result_guidance(code: str, pages: str = "", linked: str = "") -> ConnectGuidance:
    """The guided panel for `link_required` / `page_access_required`; an empty guidance
    for every other code. The two outcomes need OPPOSITE instructions (R9f): one says
    "vincula tu Instagram a la Página", the other "marca la Página en la ventana de
    Meta" — collapsing them into one message is the bug QUA-123's sentence had."""
    count = _count(pages)
    if code == "link_required":
        shown = (
            f"Meta nos mostró {_pages_phrase(count)}, pero ninguna tiene tu Instagram vinculado."
            if count
            else "Meta no encontró ninguna Página de Facebook con tu Instagram vinculado."
        )
        return ConnectGuidance(
            code=code,
            title="Falta vincular tu Instagram a tu Página de Facebook",
            summary=f"{shown} Sin ese vínculo, Qualify no puede trabajar con tu cuenta.",
            steps=[
                f"Abre {_IG_PAGE_PATH}.",
                "Toca «Conectar o crear» y elige la Página de tu negocio "
                "(o crea una nueva si no tienes).",
                "Vuelve aquí y pulsa «Volver a conectar».",
            ],
            rerequest=False,
        )
    if code == "page_access_required":
        return ConnectGuidance(
            code=code,
            title="Meta no compartió ninguna Página con Qualify",
            summary=(
                "En la ventana de Meta no quedó marcada ninguna Página de Facebook. "
                "Sin ella, Qualify no puede trabajar con tu Instagram."
            ),
            steps=[
                "Pulsa «Volver a conectar»: Meta volverá a preguntarte qué compartir.",
                "Cuando pregunte por las Páginas, marca la Página de tu negocio y continúa.",
                f"¿No tienes Página? Créala desde {_IG_PAGE_PATH} → «Conectar o crear».",
            ],
            rerequest=True,
        )
    return ConnectGuidance()
