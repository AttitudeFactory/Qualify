"""Galería › the products in the owner's WhatsApp catalog (m-25017357) — pure view models.

The backend (ADR 48, `qualify_api.whatsapp.catalog_sync.service`) says, per product, one of
`not_uploaded`, `queued`, `uploading`, `synced`, `out_of_date`, `error`, `not_eligible`
with a `reason` (the eligibility reason, or the item's error code). This module turns that
into the owner's words (`ux-galeria-catalogo-whatsapp.md`, `qualify-copy-es`): the one
badge a card carries, the editor's «En WhatsApp» block, the bulk callout over «Productos»,
the confirmation dialog's lines and the closing summary.

Nothing here is ever uploaded on its own: every verb below is the owner's tap (assisted,
never autonomous). The verbs are «Subir» and «Actualizar» — never the technical word.
No Reflex, no DB: everything is a plain function of plain values, tested offline.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field

# -- the backend's vocabulary (service.py / planning.py / models.py) ----------------------

CONNECTED = "connected"
NOT_CONNECTED = "none"
LOST_ACCESS = frozenset({"missing_permission", "auth_error"})
IN_FLIGHT = frozenset({"queued", "uploading"})
#: A run that will not change any more (`CATALOG_RUN_STATUSES`).
RUN_DONE = frozenset({"finished", "partial", "failed"})

# -- words ---------------------------------------------------------------------------------

BENEFIT = (
    "Tus clientes ven tus productos y precios dentro de WhatsApp. Si cambias un precio "
    "aquí, lo actualizas allá con un toque."
)
SECTION_LABEL = "En WhatsApp"

UPLOAD_ONE = "Subir a WhatsApp"
SAVE_AND_UPLOAD = "Guardar y subir a WhatsApp"
UPDATE_ONE = "Actualizar en WhatsApp"
RETRY_ONE = "Intentar de nuevo"
UPLOADING_ONE = "Subiendo a WhatsApp…"
UPDATING_ONE = "Actualizando en WhatsApp…"

UPLOAD_ALL_FIRST = "Subir mis productos a WhatsApp"
UPDATE_ALL = "Actualizar mi catálogo de WhatsApp"
SHOW_ALL = "Ver todos los productos"

#: «D. Sin catálogo conectado»: the team connects it; one notice and one way to ask.
NO_CATALOG_TEXT = (
    "Tus clientes pueden ver tus productos y precios dentro de WhatsApp. Lo dejamos listo "
    "nosotros: escríbenos y lo activamos."
)
ASK_CATALOG = "Pedir mi catálogo de WhatsApp"
ASK_CATALOG_MESSAGE = "Quiero que mis clientes vean mis productos en el catálogo de WhatsApp."
ASK_CATALOG_SCREEN = "catalog_whatsapp"
#: «E. Qualify perdió el permiso».
LOST_ACCESS_TEXT = (
    "Qualify ya no tiene permiso para cambiar tu catálogo de WhatsApp. Escríbenos y lo "
    "reconectamos; tus productos aquí no cambian."
)
ASK_RECONNECT = "Escribir al equipo"
ASK_RECONNECT_MESSAGE = (
    "Qualify perdió el permiso para cambiar mi catálogo de WhatsApp. Quiero reconectarlo."
)
ASK_RECONNECT_SCREEN = "catalog_whatsapp_access"
LOST_ACCESS_REASON = "Para volver a subir productos, primero hay que reconectar tu catálogo."

TEAM_SENT = (
    "Listo, le escribimos al equipo (solicitud #{reference}). Te contactarán a {email} en "
    "menos de un día hábil."
)
TEAM_SAVED = (
    "Tu solicitud #{reference} quedó registrada. Te escribiremos a {email} en cuanto una "
    "persona del equipo la tome."
)
TEAM_NO_EMAIL = "No encontramos el correo de tu cuenta. Escríbenos a contacto@attitudefactory.co."
TEAM_FAILED = (
    "No pudimos enviar tu solicitud. Vuelve a intentarlo en un momento o escríbenos a "
    "contacto@attitudefactory.co."
)

PROGRESS_DETAIL = "Puedes seguir usando la pantalla. Te avisamos al terminar."
UP_TO_DATE_TOAST = "Tu catálogo de WhatsApp está al día"
ALREADY_UP_TO_DATE = "Ya estaba al día en WhatsApp."
ALREADY_ON_ITS_WAY = "Ya lo estamos subiendo. Tarda unos segundos."
UPDATED_TOAST = "Actualizado en WhatsApp"
PLAN_CHANGED = "Algo cambió mientras mirabas. Estas son las cuentas de ahora."
NOTHING_TO_SEND = "No hay nada nuevo para subir: tu catálogo de WhatsApp ya está al día."

NOT_CONNECTED_ERROR = (
    "Tu catálogo de WhatsApp todavía no está conectado. Escríbenos y lo dejamos listo."
)
MEDIA_UNAVAILABLE_ERROR = (
    "Algo falló de nuestro lado al preparar las fotos para WhatsApp. Inténtalo de nuevo en "
    "un rato; si sigue igual, escríbenos."
)
PRODUCT_GONE_ERROR = "Ese producto ya no está en tus productos. Vuelve a la lista."
DB_ERROR = "Algo falló de nuestro lado. Inténtalo otra vez en un minuto."
NO_SESSION_ERROR = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."

# -- per product: why it cannot go up (§4) -------------------------------------------------

#: reason → (badge, editor help). `inactive` is never listed: a deleted product leaves
#: the grid, and its removal is said in the bulk dialog.
NOT_ELIGIBLE: dict[str, tuple[str, str]] = {
    "no_price": (
        "Le falta el precio",
        "Para subirlo a WhatsApp le falta el precio. Escríbelo arriba en «Precio» y guarda.",
    ),
    "no_currency": (
        "Le falta la moneda",
        "Para subirlo a WhatsApp le falta la moneda. Elige en qué moneda cobras este "
        "producto (arriba, junto al precio) y guarda.",
    ),
    "no_photo": (
        "Le falta la foto",
        "Para subirlo a WhatsApp le falta la foto. Súbela abajo, en «Fotos y videos».",
    ),
    "photo_too_small": (
        "Foto muy pequeña",
        "La foto principal es muy pequeña para WhatsApp. Sube una más grande (de al menos "
        "500 × 500) en «Fotos y videos» y déjala como principal.",
    ),
    "photo_format": (
        "Foto en otro formato",
        "WhatsApp necesita la foto principal en JPG o PNG. Sube una en uno de esos formatos "
        "en «Fotos y videos» y déjala como principal.",
    ),
}
NOT_ELIGIBLE_FALLBACK = (
    "Le falta algo",
    "Para subirlo a WhatsApp le falta un dato. Revisa el precio, la moneda y la foto.",
)
#: The dialog's «{j} no se pueden subir todavía: les falta {qué}» — what is missing, by
#: reason (a photo that is too small or in another format still «needs» a better one).
MISSING_NOUN: dict[str, str] = {
    "no_price": "el precio",
    "no_currency": "la moneda",
    "no_photo": "la foto",
    "photo_too_small": "una foto más grande",
    "photo_format": "una foto en JPG o PNG",
}

# -- per product: why WhatsApp did not take it (§4; `CATALOG_ITEM_ERRORS`) ----------------

#: error code → (editor help, whether «Intentar de nuevo» can fix it).
ITEM_ERRORS: dict[str, tuple[str, bool]] = {
    # The backend does not keep Meta's own words, so there is no {motivo}: say what to
    # check and that the team helps if it repeats.
    "meta_rejected": (
        "WhatsApp no lo aceptó. Revisa que el nombre, el precio y la foto estén bien y "
        "vuelve a intentarlo. Si se repite, escríbenos y lo revisamos.",
        True,
    ),
    "meta_unconfirmed": (
        "WhatsApp no nos confirmó que lo recibió. No es por tu producto: inténtalo de "
        "nuevo en un rato.",
        True,
    ),
    "send_failed": (
        "WhatsApp no respondió esta vez. No es por tu producto: inténtalo de nuevo en un rato.",
        True,
    ),
    "no_permission": (LOST_ACCESS_TEXT, False),
}
ITEM_ERROR_FALLBACK = (
    "WhatsApp no lo aceptó y no nos dijo por qué. Escríbenos y lo revisamos.",
    True,
)

ERROR_BADGE = "No se subió"
SYNCED_BADGE = "En WhatsApp"
OUT_OF_DATE_BADGE = "Por actualizar"
IN_FLIGHT_BADGE = "Subiendo…"
NOT_UPLOADED_BADGE = "No está en WhatsApp"

# -- the card's one badge ------------------------------------------------------------------

#: What `card_badge` returns as `kind` (the page matches on it; "" = no badge).
CARD_SYNCED = "synced"
CARD_UPLOADING = "uploading"
CARD_OUT_OF_DATE = "out_of_date"
CARD_ERROR = "error"
CARD_MISSING = "missing"


def card_badge(state: str, reason: str | None, *, photo_count: int) -> tuple[str, str]:
    """(kind, text) of the ONE WhatsApp badge a product card carries. «No está en
    WhatsApp» carries none (300 cards of it would be noise); «Le falta la foto» carries
    none either when the card already says «Falta la foto»."""
    if state in IN_FLIGHT:
        return CARD_UPLOADING, IN_FLIGHT_BADGE
    if state == "synced":
        return CARD_SYNCED, SYNCED_BADGE
    if state == "out_of_date":
        return CARD_OUT_OF_DATE, OUT_OF_DATE_BADGE
    if state == "error":
        return CARD_ERROR, ERROR_BADGE
    if state == "not_eligible":
        if reason == "inactive" or (reason == "no_photo" and photo_count == 0):
            return "", ""
        return CARD_MISSING, NOT_ELIGIBLE.get(reason or "", NOT_ELIGIBLE_FALLBACK)[0]
    return "", ""


# -- the editor's «En WhatsApp» block -------------------------------------------------------

#: `EditorWa.action` values.
ACTION_UPLOAD = "upload"
ACTION_UPDATE = "update"
ACTION_RETRY = "retry"
ACTION_NONE = "none"
ACTION_BUSY = "busy"


@dataclass(frozen=True)
class EditorWa:
    """One product as the editor shows it: badge (text, tone, icon), the help under it and
    the one action (`ACTION_*`)."""

    badge: str
    tone: str
    icon: str
    help: str
    action: str


def editor_view(state: str, reason: str | None) -> EditorWa:
    if state in IN_FLIGHT:
        return EditorWa(
            IN_FLIGHT_BADGE,
            "info",
            "loader",
            "Lo estamos subiendo. Tarda unos segundos; puedes cerrar esto.",
            ACTION_BUSY,
        )
    if state == "synced":
        return EditorWa(
            SYNCED_BADGE,
            "ok",
            "check",
            "Tus clientes lo ven con este precio y esta foto.",
            ACTION_NONE,
        )
    if state == "out_of_date":
        return EditorWa(
            OUT_OF_DATE_BADGE,
            "warn",
            "refresh-cw",
            "Cambiaste este producto. En WhatsApp sigue como estaba antes.",
            ACTION_UPDATE,
        )
    if state == "error":
        text, retry = ITEM_ERRORS.get(reason or "", ITEM_ERROR_FALLBACK)
        return EditorWa(
            ERROR_BADGE, "error", "triangle-alert", text, ACTION_RETRY if retry else ACTION_NONE
        )
    if state == "not_eligible":
        badge, text = NOT_ELIGIBLE.get(reason or "", NOT_ELIGIBLE_FALLBACK)
        return EditorWa(badge, "warn", "triangle-alert", text, ACTION_NONE)
    return EditorWa(
        NOT_UPLOADED_BADGE,
        "neutral",
        "message-circle",
        "Todavía no está en tu catálogo de WhatsApp.",
        ACTION_UPLOAD,
    )


def action_label(action: str, *, dirty: bool) -> str:
    """The editor's button. With unsaved changes, «Subir» saves first (N6)."""
    if action == ACTION_UPLOAD:
        return SAVE_AND_UPLOAD if dirty else UPLOAD_ONE
    if action == ACTION_UPDATE:
        return UPDATE_ONE
    if action == ACTION_RETRY:
        return RETRY_ONE
    return ""


def is_problem(state: str, reason: str | None) -> bool:
    """«Ver los {m} con problemas»: what the owner must fix (or retry) before it shows in
    WhatsApp. A deleted product is not a problem: the next update removes it."""
    if state == "error":
        return True
    return state == "not_eligible" and reason != "inactive"


# -- the screen's read, reduced -----------------------------------------------------------


@dataclass(frozen=True)
class Counts:
    """The active products by what the bulk action would do with them, plus the deleted
    ones still in WhatsApp (`removals`)."""

    total: int = 0
    new: int = 0
    changed: int = 0
    failed: int = 0
    synced: int = 0
    not_eligible: int = 0
    in_flight: int = 0
    removals: int = 0
    #: Something was ever sent (a live, failed or in-flight item exists).
    ever_sent: bool = False


def count_states(
    states: Mapping[str, tuple[str, str | None]], active_ids: Collection[str]
) -> Counts:
    """`states` is product id → (state, reason) for every product of the brand (deleted
    ones too); `active_ids` the products the grid lists."""
    active = set(active_ids)
    new = changed = failed = synced = blocked = flying = removals = 0
    ever = False
    for product_id, (state, reason) in states.items():
        if state in IN_FLIGHT:
            flying += 1
            ever = True
            continue
        if product_id not in active:
            # deleted here: a live item is removed by the next «Actualizar mi catálogo»
            if state == "out_of_date":
                removals += 1
                ever = True
            continue
        if state == "not_uploaded":
            new += 1
        elif state == "out_of_date":
            changed += 1
            ever = True
        elif state == "error":
            failed += 1
            ever = True
        elif state == "synced":
            synced += 1
            ever = True
        elif state == "not_eligible":
            blocked += 1
    return Counts(
        total=len([p for p in active if p in states]),
        new=new,
        changed=changed,
        failed=failed,
        synced=synced,
        not_eligible=blocked,
        in_flight=flying,
        removals=removals,
        ever_sent=ever,
    )


def _n(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def _join(parts: Sequence[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " y " + parts[-1]


@dataclass(frozen=True)
class Bulk:
    """The block over «Productos»: a callout (text + tone; "" = none) and its button
    ("" = none)."""

    text: str = ""
    tone: str = "info"
    button: str = ""


def bulk_view(counts: Counts) -> Bulk:
    """§3's table. Errors are retried by the bulk action, so they count as pending."""
    pending = counts.new + counts.changed + counts.failed
    if not counts.ever_sent:
        if counts.new == 0:
            return Bulk(
                "Para que tus clientes vean tus productos en WhatsApp, cada uno necesita "
                "precio y foto.",
                "info",
            )
        return Bulk(
            f"Tus clientes pueden ver tus {_n(counts.new, 'producto', 'productos')} con su "
            "precio dentro de WhatsApp."
            if counts.new > 1
            else "Tus clientes pueden ver tu producto con su precio dentro de WhatsApp.",
            "info",
            UPLOAD_ALL_FIRST,
        )
    if pending == 0 and counts.removals == 0:
        if counts.synced == 0:
            return Bulk()
        return Bulk(
            "Tu producto está en WhatsApp con su precio de hoy."
            if counts.synced == 1
            else f"Tus {counts.synced} productos están en WhatsApp con su precio de hoy.",
            "ok",
        )
    sentences: list[str] = []
    parts = []
    if counts.new:
        parts.append(_n(counts.new, "nuevo", "nuevos"))
    if counts.changed:
        parts.append(f"{counts.changed} con cambios")
    if counts.failed:
        parts.append(
            f"{counts.failed} que no se "
            + ("pudo subir" if counts.failed == 1 else "pudieron subir")
        )
    if parts:
        verb = "no está" if pending == 1 else "no están"
        sentences.append(f"{_join(parts)} todavía {verb} en WhatsApp.")
    if counts.removals:
        sentences.append(
            "1 que borraste aquí todavía se ve en WhatsApp."
            if counts.removals == 1
            else f"{counts.removals} que borraste aquí todavía se ven en WhatsApp."
        )
    sentence = " ".join(sentences)
    return Bulk(sentence[:1].upper() + sentence[1:], "warn", UPDATE_ALL)


def problems_label(count: int, *, active: bool) -> str:
    if active:
        return SHOW_ALL
    return "Ver el que tiene problemas" if count == 1 else f"Ver los {count} con problemas"


# -- the confirmation dialog ---------------------------------------------------------------


@dataclass(frozen=True)
class Dialog:
    title: str
    lines: tuple[str, ...]
    #: «Se quitan de WhatsApp…» — said apart, in bold ("" = nothing is removed).
    removal: str
    footer: str
    confirm: str


def missing_reasons(not_eligible: Mapping[str, int]) -> list[str]:
    """The reasons that block some product (`inactive` aside: those are removals), the
    most common first; ties go to the order of §4."""
    order = list(MISSING_NOUN)
    present = [r for r, c in not_eligible.items() if r != "inactive" and c > 0]
    return sorted(present, key=lambda r: (-not_eligible[r], order.index(r) if r in order else 99))


def _or(parts: Sequence[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " o " + parts[-1]


def dialog_view(
    *,
    new: int,
    changed: int,
    deletes: int,
    not_eligible: Mapping[str, int],
    first_time: bool,
    removal_names: Sequence[str] = (),
) -> Dialog:
    """Only the lines whose count is above zero (§3)."""
    lines: list[str] = []
    if new:
        lines.append(
            "Se sube 1 producto nuevo." if new == 1 else f"Se suben {new} productos nuevos."
        )
    if changed:
        lines.append(
            "Se actualiza 1 que cambiaste."
            if changed == 1
            else f"Se actualizan {changed} que cambiaste."
        )
    removal = ""
    if deletes:
        removal = (
            "Se quita de WhatsApp 1 que borraste aquí."
            if deletes == 1
            else f"Se quitan de WhatsApp {deletes} que borraste aquí."
        )
        if removal_names and len(removal_names) == deletes and deletes <= 5:
            removal = removal[:-1] + ": " + _join([f"«{n}»" for n in removal_names]) + "."
        removal += " Tus clientes ya no " + ("lo verán." if deletes == 1 else "los verán.")
    blocked = sum(c for r, c in not_eligible.items() if r != "inactive")
    if blocked:
        # every reason present is named (most common first): «les falta el precio» would
        # be untrue of the ones that only miss a photo
        what = _or([MISSING_NOUN.get(r, "un dato") for r in missing_reasons(not_eligible)[:3]])
        if blocked == 1:
            lines.append(
                f"1 no se puede subir todavía: le falta {what}. Lo verás después para corregirlo."
            )
        else:
            lines.append(
                f"{blocked} no se pueden subir todavía: les falta {what}. Los verás después "
                "para corregirlos."
            )
    return Dialog(
        title="¿Subir tus productos a WhatsApp?"
        if first_time
        else "¿Actualizar tu catálogo de WhatsApp?",
        lines=tuple(lines),
        removal=removal,
        footer="Los productos que creaste directamente en WhatsApp no se tocan.",
        confirm="Sí, subir" if first_time else "Sí, actualizar",
    )


# -- the running update and its closing summary --------------------------------------------


def progress_title(done: int, total: int) -> str:
    total = max(total, 0)
    done = min(max(done, 0), total)
    return f"Subiendo a WhatsApp: {done} de {total}"


def progress_value(done: int, total: int) -> int:
    if total <= 0:
        return 0
    return min(100, max(0, round(100 * done / total)))


@dataclass(frozen=True)
class Summary:
    text: str
    tone: str
    problems: int = 0


def run_summary(
    *,
    status: str,
    new: int,
    changed: int,
    deletes: int,
    failed: int,
    error_code: str | None = None,
) -> Summary:
    """The callout that replaces the progress card once the update ends."""
    if status == "failed" and (error_code in LOST_ACCESS or error_code == "no_permission"):
        return Summary(LOST_ACCESS_TEXT, "error", failed)
    if status == "failed" and failed == 0:
        failed = new + changed
    if failed:
        # The run does not say WHICH items failed: count what went through as a whole.
        went = max(new + changed - failed, 0)
        head = (
            f"Listo: {_n(went, 'producto ya está', 'productos ya están')} en WhatsApp."
            if went
            else "WhatsApp no recibió tus productos esta vez."
        )
        return Summary(f"{head} {failed} con problemas.", "warn", failed)
    parts = []
    if new:
        parts.append(_n(new, "subido", "subidos"))
    if changed:
        parts.append(_n(changed, "actualizado", "actualizados"))
    if deletes:
        parts.append(_n(deletes, "quitado", "quitados"))
    text = f"Listo: {_join(parts)}." if parts else UP_TO_DATE_TOAST + "."
    return Summary(text, "ok", 0)


# -- everything the page shows, from one read ---------------------------------------------


@dataclass(frozen=True)
class ScreenWa:
    """The whole WhatsApp layer of Galería for the active products, as plain values."""

    connection: str
    card_kind: dict[str, str] = field(default_factory=dict)
    card_text: dict[str, str] = field(default_factory=dict)
    editor: dict[str, EditorWa] = field(default_factory=dict)
    problem_ids: tuple[str, ...] = ()
    counts: Counts = Counts()
    bulk: Bulk = Bulk()


def screen_view(
    connection: str,
    states: Mapping[str, tuple[str, str | None]],
    photo_counts: Mapping[str, int],
) -> ScreenWa:
    """`photo_counts` is the active products (id → photos), in the grid's order."""
    if connection != CONNECTED and connection not in LOST_ACCESS:
        return ScreenWa(connection=connection)
    kind: dict[str, str] = {}
    text: dict[str, str] = {}
    editor: dict[str, EditorWa] = {}
    problems: list[str] = []
    for product_id, photos in photo_counts.items():
        state, reason = states.get(product_id, ("not_uploaded", None))
        k, t = card_badge(state, reason, photo_count=photos)
        if k:
            kind[product_id] = k
            text[product_id] = t
        editor[product_id] = editor_view(state, reason)
        if is_problem(state, reason):
            problems.append(product_id)
    counts = count_states(states, list(photo_counts))
    return ScreenWa(
        connection=connection,
        card_kind=kind,
        card_text=text,
        editor=editor,
        problem_ids=tuple(problems),
        counts=counts,
        bulk=bulk_view(counts) if connection == CONNECTED else Bulk(),
    )


def removed_ids(
    states: Mapping[str, tuple[str, str | None]], active_ids: Collection[str]
) -> list[str]:
    """The deleted products still in WhatsApp (named in the dialog when they are few)."""
    active = set(active_ids)
    return [
        pid for pid, (state, _) in states.items() if pid not in active and state == "out_of_date"
    ]


def finished_toasts(
    before: Mapping[str, str], after: Mapping[str, tuple[str, str | None]], names: Mapping[str, str]
) -> list[tuple[str, str]]:
    """(tone, text) for each product the owner sent one by one in this tab that is no
    longer in flight: «"{nombre}" ya está en WhatsApp», or that it did not go up."""
    out: list[tuple[str, str]] = []
    for product_id, verb in before.items():
        state, _ = after.get(product_id, ("", None))
        if state in IN_FLIGHT or not state:
            continue
        name = names.get(product_id, "")
        if state == "synced":
            if verb == ACTION_UPLOAD and name:
                out.append(("ok", f"«{name}» ya está en WhatsApp"))
            else:
                out.append(("ok", UPDATED_TOAST))
        elif state == "error":
            subject = f"«{name}»" if name else "El producto"
            out.append(("error", f"{subject} no se subió a WhatsApp. Ábrelo para ver qué pasó."))
    return out
