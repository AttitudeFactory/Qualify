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


@dataclass(frozen=True)
class ConnectionHintVM:
    """One thing a connected account is missing, and the guide step that fixes it.

    `step_key` is a `CONNECT_REQUIREMENTS` key; `step_number` is its position, shown as
    «Paso N» so the card and the guide speak the same numbers."""

    key: str
    title: str
    detail: str
    step_key: str
    step_number: int


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
    # m-24840590: what this account is missing and which guide step fixes it.
    # Derived from the stored scope NAMES (never the token) — see `connection_hints`.
    hints: list[ConnectionHintVM] = field(default_factory=list)


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
    hints: list[ConnectionHintVM] | None = None,
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
        hints=list(hints or []),
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
    """One step of the connection guide (QUA-202, rewritten for m-24840590): what the
    operator does in Instagram or in Meta's window, BEFORE or WHILE pressing «Conectar
    cuenta». A pre-flight hint (R4a), never a verification: the screen cannot check
    the Instagram side of any of it — the card hints below cover what it can detect."""

    key: str
    title: str
    summary: str
    steps: list[str]


# m-24840590: the four things only the client can do. Fase C (private reply, public
# notice, story replies, Instagram Direct) needs the messages permission AND the
# Instagram «Permitir acceso a los mensajes» switch; neither existed in the old
# three-item checklist, which stopped at "Instagram linked to a Page".
CONNECT_REQUIREMENTS: list[ConnectRequirementVM] = [
    ConnectRequirementVM(
        key="professional",
        title="Tu Instagram es profesional y está vinculado a tu Página de Facebook",
        summary=(
            "Tipo Empresa o Creador, unido a la Página de Facebook de tu negocio. "
            "Una cuenta personal no se puede conectar."
        ),
        steps=[
            "En Instagram, abre tu perfil y toca el menú ☰ → Configuración y actividad → "
            "«Tipo de cuenta y herramientas» → «Cambiar a cuenta profesional».",
            "Elige «Empresa» o «Creador» y termina el asistente.",
            f"Luego ve a {_IG_PAGE_PATH}, toca «Conectar o crear» y elige la Página de tu "
            "negocio. Si no tienes, ahí mismo puedes crearla.",
        ],
    ),
    ConnectRequirementVM(
        key="messages",
        title="Permite el acceso a tus mensajes",
        summary=(
            "Sin este permiso de Instagram, Qualify no puede leer ni responder tus "
            "mensajes directos, aunque la cuenta esté conectada."
        ),
        steps=[
            "En la app de Instagram, abre tu perfil y toca el menú ☰ → Configuración y "
            "actividad.",
            "Entra en «Mensajes y respuestas a historias» → «Controles de mensajes».",
            "En «Herramientas conectadas», activa «Permitir acceso a los mensajes».",
        ],
    ),
    ConnectRequirementVM(
        key="permissions",
        title="Conecta y acepta todos los permisos",
        summary=(
            "Meta te muestra una lista de permisos. Si desmarcas alguno, la función que "
            "depende de él no estará disponible."
        ),
        steps=[
            "Pulsa «Conectar cuenta» en esta pantalla.",
            "Cuando Meta te pregunte qué compartir, marca la Página y el Instagram de tu "
            "negocio.",
            "Deja todos los permisos marcados y continúa hasta el final.",
        ],
    ),
    ConnectRequirementVM(
        key="reconnect",
        title="¿Ya estaba conectada? Vuelve a conectarla",
        summary=(
            "Cuando Qualify suma una función nueva, Meta pide un permiso nuevo. Volver a "
            "conectar lo agrega sin borrar nada."
        ),
        steps=[
            "En la tarjeta de tu cuenta, pulsa «Volver a conectar».",
            "Acepta los permisos nuevos que te pida Meta.",
            "Revisa que la función aparezca en «Disponible» en la tarjeta.",
        ],
    ),
]

# The step number shown next to each key — the card hints say «Paso 3», so the number
# is derived from the list order, never typed twice.
REQUIREMENT_NUMBERS: dict[str, int] = {
    requirement.key: number for number, requirement in enumerate(CONNECT_REQUIREMENTS, start=1)
}


# --------------------------------------------------------------------------------------
# m-24840590: per-card «qué falta» hints, from the scopes stored on the connection.
# --------------------------------------------------------------------------------------

# The Facebook-Login scopes production asks for (`QUALIFY_META_SCOPES`, docs/
# conversaciones-limitaciones-meta.md §7) that a card can check. The capability matrix
# covers the Instagram ones by family (any spelling); the two Page scopes below are
# not capability gates there, so they are checked as literals — and ONLY on a
# connection that came through a Facebook Page (`linked_page_id`), the only path on
# which Meta can grant them.
PAGE_MESSAGING_SCOPE = "pages_messaging"
PAGE_METADATA_SCOPE = "pages_manage_metadata"


def _hint(key: str, title: str, detail: str, step_key: str) -> ConnectionHintVM:
    return ConnectionHintVM(
        key=key,
        title=title,
        detail=detail,
        step_key=step_key,
        step_number=REQUIREMENT_NUMBERS[step_key],
    )


def connection_hints(
    *,
    platform: str,
    status: ConnectionStatus,
    granted_literals: frozenset[str],
    resolved_keys: frozenset[str],
    has_linked_page: bool,
) -> list[ConnectionHintVM]:
    """What this Instagram account is missing, in the client's words.

    Detected from data the connection already stores — nothing here calls Meta:
    - `resolved_keys`: the capability-matrix scope families granted (any spelling);
    - `granted_literals`: the raw Meta permission names, for the two Page scopes;
    - `has_linked_page`: whether the account came through a Facebook Page.

    Only an `active` Instagram card gets hints: a degraded or revoked one already
    shows its own reconnect banner, and WhatsApp is connected by an administrator.
    The Instagram «Permitir acceso a los mensajes» switch cannot be read from here —
    the guide's step 2 covers it, and the messages hint points there too.
    """
    if platform != "instagram" or status != "active":
        return []
    hints: list[ConnectionHintVM] = []

    missing_features = [
        phrase
        for family, phrase in (
            ("content_publish", "publicar"),
            ("manage_comments", "leer y responder comentarios"),
        )
        if family not in resolved_keys
    ]
    if missing_features:
        features = " ni ".join(missing_features)
        hints.append(
            _hint(
                "permissions",
                "Faltan permisos de Instagram",
                f"Sin ellos, Qualify no puede {features}. Vuelve a conectar la cuenta y "
                "deja todos los permisos marcados.",
                "permissions",
            )
        )

    messages_missing = "manage_messages" not in resolved_keys or (
        has_linked_page and PAGE_MESSAGING_SCOPE not in granted_literals
    )
    if messages_missing:
        hints.append(
            _hint(
                "messages",
                "Los mensajes directos no están activos",
                "Falta el permiso de mensajes. Antes de volver a conectar, revisa que "
                "Instagram permita el acceso a los mensajes (paso 2) y luego acepta todos "
                "los permisos.",
                "messages",
            )
        )

    if has_linked_page and PAGE_METADATA_SCOPE not in granted_literals:
        hints.append(
            _hint(
                "page",
                "Falta un permiso nuevo de tu Página",
                "Qualify lo necesita para recibir tus mensajes al momento. Vuelve a "
                "conectar la cuenta para agregarlo.",
                "reconnect",
            )
        )
    return hints


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
