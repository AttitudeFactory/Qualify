"""Reflex state for «Variaciones» — the Crear pieza option of ticket 24803289.

The flow this state owns is the one before any image is paid for:

1. pick a CATALOG product (requirement 1 — never a stock pick),
2. see it as the engine sees it (its photos, the price it will print, or the «no price»
   note of requirement 8),
3. pick a preset, with the reason when one cannot be used,
4. read the plan (what the images would cost),
5. ask Claude for the angles — ONE paid call — and review them, discarding the ones
   that do not convince before anything else is spent.

Generating the pieces, their gallery, the retry and the approval are the next slice;
this state stops at the reviewed proposal.

Custody rules, inherited from `catalog_state.py`:

- holds only `variations_vm` frozen dataclasses and plain strings, never a service
  record (its `UUID`/`Decimal` fields a Reflex var cannot carry);
- the tenant comes from `AuthState.session_tenant_id`, parsed by `tenant.tenant_uuid`
  right before it reaches the provider; the brand is the tenant's one brand;
- every provider call blocks (SQLAlchemy, and a Claude call of several seconds), so
  background handlers run them with `asyncio.to_thread`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from uuid import UUID

import reflex as rx

from .auth_state import AuthState
from .catalog_vm import VARIATIONS_MODE, create_mode_from_query, product_id_from_query
from .creative_provider import (
    acting_user_id,
    catalog_products,
    creations_balance,
    default_brand_id,
)
from .creative_vm import pieces_use_notice
from .tenant import tenant_uuid
from .variations_provider import (
    approve_variation_angle,
    archive_variation_set,
    create_variation_set,
    discard_variation_angle,
    discard_variation_angles,
    edit_variation_angle,
    generate_variation_pieces,
    list_variation_sets,
    regenerate_variation_angle,
    retry_variation_angle,
    save_variation_angle,
    save_variation_angles,
    variation_plan,
    variation_presets,
    variation_set_detail,
)
from .variations_vm import (
    AngleVM,
    PresetVM,
    SetSummaryVM,
    any_in_flight,
    summarize_warnings,
    variation_error_message,
)

logger = logging.getLogger(__name__)

_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_NO_BRAND = "Este negocio no tiene ninguna marca provisionada todavía."
_LOAD_FAILED = "No se pudo cargar tu catálogo. Inténtalo de nuevo."
_NO_PRODUCTS = (
    "Tu catálogo todavía no tiene productos. Agrégalos en Tus productos para usar Variaciones."
)
_PICK_PRODUCT = "Elige primero un producto del catálogo."
_PICK_PRESET = "Elige un estilo antes de generar los ángulos."
_NOTHING_TO_GENERATE = "No queda ningún ángulo por generar."
_APPROVED = "Pieza aprobada."
_RETRYING = "Reintentando esa pieza."
_REGENERATING = "Generando otra toma de ese escenario."
_EDITED = "Propuesta guardada. La próxima pieza de ese ángulo saldrá del nuevo texto."
_EMPTY_SCENE = "Escribe la escena antes de guardar."
_EMPTY_TITLE = "La propuesta necesita un título."
_NOTHING_TO_DISCARD = "No queda ninguna propuesta por eliminar."
_NOTHING_TO_SAVE = "No queda ninguna propuesta por guardar."
_SAVED_ONE = "Guardada para después."
_GROUP_EMPTY = "No queda ninguna propuesta en este grupo: ya no aparece en la lista."
_GROUP_DELETED = "Grupo eliminado."
_RESUMED_ONE = "De vuelta en la revisión."

#: Polling of the gallery while pieces are being made: every 3 s, giving up after 20
#: minutes — the generator's own schedule (`creative_state._GEN_POLL_*`), for the same
#: reason: an image lands in seconds, but a busy provider can take much longer.
_POLL_SECONDS = 3.0
_POLL_BUDGET_SECONDS = 20 * 60
#: How long a confirmation stays in the corner — long enough to read a count.
_TOAST_MS = 6000


def _toast(message: str, tone: str) -> rx.event.EventSpec:
    """A transient confirmation, bottom right, in the tone of what happened
    (docs/design-system.md §5.4: «confirmaciones transitorias → rx.toast»). What went
    wrong, with its details, stays on the page as a callout instead."""
    show = {"ok": rx.toast.success, "error": rx.toast.error, "warn": rx.toast.warning}.get(
        tone, rx.toast.info
    )
    return show(message, duration=_TOAST_MS)


def _save_true(tenant_id: UUID, angle_id: str) -> None:
    save_variation_angle(tenant_id, angle_id, True)


def _save_false(tenant_id: UUID, angle_id: str) -> None:
    save_variation_angle(tenant_id, angle_id, False)


class VariationsState(rx.State):
    """State of the «Variaciones» view inside /create."""

    # -- the catalog picker --------------------------------------------------------------
    #: Flat rows (`creative_provider.catalog_products`): id, name, photo_key, counts_label…
    products: list[dict[str, str]] = []
    products_loading: bool = False
    product_id: str = ""

    # -- the chosen product, as the engine sees it ---------------------------------------
    product_name: str = ""
    product_photo_count: int = 0
    price_label: str = ""
    price_missing: bool = False
    price_note: str = ""
    checking: bool = False

    # -- presets and plan ------------------------------------------------------------------
    presets: list[PresetVM] = []
    preset_key: str = ""
    plan_count: int = 0
    plan_images_label: str = ""
    plan_note: str = ""

    # -- the set, once Claude answered -----------------------------------------------------
    set_id: str = ""
    set_status_label: str = ""
    set_status_tone: str = ""
    set_price_note: str = ""
    set_failure_text: str = ""
    kept_count: int = 0
    pending_count: int = 0
    angles: list[AngleVM] = []
    creating: bool = False
    busy_angle_id: str = ""
    #: The angles put aside with «Guardar para después» leave the grid; this shows them
    #: again so one can be taken up.
    show_saved: bool = False

    # -- generating the pieces --------------------------------------------------------------
    generating: bool = False
    outcome_message: str = ""
    outcome_tone: str = ""
    outcome_details: list[str] = []
    poll_timed_out: bool = False
    #: The brand's sets, newest first — so a set left open yesterday can be reopened.
    sets: list[SetSummaryVM] = []
    #: «Eliminar grupo» (request 2026-10-22): the dialog is open while these name it.
    archive_set_id: str = ""
    archive_set_name: str = ""

    # -- the lightbox: one piece at full size (both empty = closed) ----------------------
    lightbox_title: str = ""
    lightbox_url: str = ""  # an R2 object's short-lived path (through `/r2media`)
    lightbox_key: str = ""  # a local upload's key (`rx.get_upload_url`)

    # -- the scene editor ("" = closed) ----------------------------------------------------
    editor_angle_id: str = ""
    editor_title: str = ""
    editor_scene: str = ""
    editor_composition: str = ""
    #: The rest of what Claude proposed (request 2026-10-22: everything is editable).
    editor_name: str = ""
    editor_hook: str = ""
    editor_cta: str = ""
    editor_rationale: str = ""
    editor_can_regenerate: bool = False
    saving: bool = False

    error: str = ""
    _brand_id: str = ""

    # -- derived ----------------------------------------------------------------------------

    @rx.var
    def has_products(self) -> bool:
        return len(self.products) > 0

    @rx.var
    def product_chosen(self) -> bool:
        return self.product_id != ""

    @rx.var
    def has_set(self) -> bool:
        return self.set_id != ""

    @rx.var
    def can_create(self) -> bool:
        """«Generar los ángulos» is live only with a product, an available preset and no
        call already in flight — the screen never offers a paid call it cannot make."""
        if not (self.product_id and self.preset_key) or self.creating:
            return False
        return any(p.key == self.preset_key and p.available for p in self.presets)

    @rx.var
    def kept_label(self) -> str:
        """«3 ángulos en pie» — what survives the review, under the set's name."""
        kept = self.kept_count
        return ("1 ángulo" if kept == 1 else f"{kept} ángulos") + " en pie"

    @rx.var
    def in_flight(self) -> bool:
        """Whether a piece of this set is being made right now."""
        return any_in_flight(self.angles)

    @rx.var
    def visible_angles(self) -> list[AngleVM]:
        """The tiles on the grid: never a deleted one (request 2026-10-22: «eliminar es
        eliminar»), and the ones put aside only while `show_saved`."""
        return [
            a for a in self.angles if a.status != "discarded" and (self.show_saved or not a.saved)
        ]

    @rx.var
    def saved_count(self) -> int:
        return sum(1 for a in self.angles if a.saved and a.status != "discarded")

    @rx.var
    def savable_count(self) -> int:
        return sum(1 for a in self.angles if a.can_save)

    @rx.var
    def saved_toggle_label(self) -> str:
        n = self.saved_count
        if self.show_saved:
            return "Ocultar guardadas"
        return f"Ver guardadas ({n})" if n else "Ver guardadas"

    @rx.var
    def save_rest_label(self) -> str:
        n = self.savable_count
        return f"Guardar las demás ({n})" if n else "Guardar las demás"

    @rx.event
    def toggle_saved(self) -> None:
        self.show_saved = not self.show_saved

    @rx.var
    def discardable_count(self) -> int:
        """How many angles «Descartar las demás» would discard: the ones still open
        (never an approved one, never one already discarded)."""
        return sum(1 for a in self.angles if self._bulk_discardable(a))

    @staticmethod
    def _bulk_discardable(angle: AngleVM) -> bool:
        """What «Eliminar las demás» sweeps: open, not approved — and never one put aside
        with «Guardar para después» (review 2026-10-22: deleting is final here)."""
        return angle.can_discard and angle.status != "approved" and not angle.saved

    @rx.var
    def discard_rest_label(self) -> str:
        n = self.discardable_count
        return f"Eliminar las demás ({n})" if n else "Eliminar las demás"

    @rx.var
    def composition_notes(self) -> list[str]:
        """What the composition left out, once per distinct warning across the set."""
        return list(summarize_warnings(self.angles))

    @rx.var
    def can_generate(self) -> bool:
        return self.pending_count > 0 and not self.generating

    #: CREAR-5: the month's creations (-1 = no quota wired: nothing is said).
    creations_left: int = -1
    creations_quota: int = 0

    @rx.var
    def creations_text(self) -> str:
        """What generating the kept ideas uses and what would be left — or what is
        missing, in which case nothing is generated."""
        if self.creations_left < 0 or not self.pending_count:
            return ""
        return pieces_use_notice(self.pending_count, self.creations_left, self.creations_quota)

    @rx.var
    def creations_short(self) -> bool:
        return 0 <= self.creations_left < self.pending_count

    async def _refresh_creations(self, tenant_id: UUID, brand_id: UUID) -> None:
        try:
            balance = await asyncio.to_thread(creations_balance, tenant_id, brand_id)
        except Exception as exc:  # noqa: BLE001 — the service still refuses what it cannot pay
            logger.warning("variations: creations unreadable: %s", type(exc).__name__)
            return
        async with self:
            self.creations_left, self.creations_quota = balance if balance else (-1, 0)

    @rx.var
    def generate_label(self) -> str:
        pending = self.pending_count
        if pending == 1:
            return "Generar 1 pieza"
        return f"Generar {pending} piezas"

    @rx.var
    def has_sets(self) -> bool:
        return len(self.sets) > 0

    @rx.var
    def lightbox_open(self) -> bool:
        return self.lightbox_url != "" or self.lightbox_key != ""

    @rx.var
    def editor_open(self) -> bool:
        return self.editor_angle_id != ""

    @rx.var
    def photo_count_label(self) -> str:
        count = self.product_photo_count
        if not count:
            return "Sin fotos"
        return "1 foto" if count == 1 else f"{count} fotos"

    @rx.var
    def plan_count_label(self) -> str:
        return f"{self.plan_count} ángulos"

    # -- session -----------------------------------------------------------------------------

    async def _session_ids(self) -> tuple[UUID, UUID, UUID | None] | None:
        """(tenant, brand, acting user) or None with the reason already in `error`."""
        async with self:
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
            cached_brand_id = self._brand_id
        tenant_id = tenant_uuid(session_tenant_id) if session_tenant_id else None
        if tenant_id is None:
            async with self:
                self.error = _NO_SESSION
            return None
        brand_id: UUID | None
        if cached_brand_id:
            brand_id = UUID(cached_brand_id)
        else:
            brand_id = await asyncio.to_thread(default_brand_id, tenant_id)
            if brand_id is not None:
                async with self:
                    self._brand_id = str(brand_id)
        if brand_id is None:
            async with self:
                self.error = _NO_BRAND
            return None
        user_id = await asyncio.to_thread(acting_user_id, tenant_id)
        return tenant_id, brand_id, user_id

    # -- opening ------------------------------------------------------------------------------

    @rx.event(background=True)
    async def load(self) -> None:
        """The catalog products of the picker. Idempotent: re-entering the view does not
        lose the product already chosen."""
        await self._load_products()

    @rx.event(background=True)
    async def load_from_query(self) -> None:
        """`/create`'s on_load. Back from «Agregar producto» (m-24842973, N4) the URL is
        `/create?modo=variaciones&producto=<id>`: the picker is re-read — so the new
        product is in it — and, when this business's catalog lists it, that product is
        chosen. An id it does not list (another tenant's, a deleted one) or a malformed
        one is ignored without an error; the one already chosen is not chosen again. Any
        other `/create` visit does nothing here."""
        async with self:
            try:
                params = self.router.url.query_parameters
            except AttributeError:  # no router outside a request
                params = {}
        if create_mode_from_query(params) != VARIATIONS_MODE:
            return
        product_id = product_id_from_query(params)
        if not await self._load_products() or not product_id:
            return
        async with self:
            known = any(row.get("id") == product_id for row in self.products)
            already = self.product_id == product_id
        if known and not already:
            await self._choose(product_id)

    async def _load_products(self) -> bool:
        """Read the picker's products and the sets; False when nothing was read."""
        async with self:
            if self.products_loading:
                return False
            self.products_loading = True
            self.error = ""
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.products_loading = False
            return False
        tenant_id, brand_id, _ = ids
        await self._refresh_creations(tenant_id, brand_id)
        try:
            rows = await asyncio.to_thread(catalog_products, tenant_id, brand_id)
        except Exception as exc:  # noqa: BLE001 — any read failure reads the same here
            logger.error("variations: catalog load failed: %s", type(exc).__name__)
            async with self:
                self.products_loading = False
                self.error = _LOAD_FAILED
            return False
        try:
            sets = await asyncio.to_thread(list_variation_sets, tenant_id, brand_id)
        except Exception as exc:  # noqa: BLE001 — the list is not worth failing the view
            logger.warning("variations: set list failed: %s", type(exc).__name__)
            sets = ()
        async with self:
            self.products = [dict(row) for row in rows]
            self.sets = list(sets)
            self.products_loading = False
            if not self.products:
                self.error = _NO_PRODUCTS
        return True

    @rx.event
    def start_over(self) -> None:
        """Back to the picker, keeping the products already read."""
        self.product_id = ""
        self.product_name = ""
        self.product_photo_count = 0
        self.price_label = ""
        self.price_missing = False
        self.price_note = ""
        self.presets = []
        self.preset_key = ""
        self.plan_count = 0
        self.plan_images_label = ""
        self.plan_note = ""
        self._clear_set()
        self.error = ""

    def _clear_set(self) -> None:
        self._close_lightbox()
        self.show_saved = False
        self.set_id = ""
        self.set_status_label = ""
        self.set_status_tone = ""
        self.set_price_note = ""
        self.set_failure_text = ""
        self.kept_count = 0
        self.pending_count = 0
        self.angles = []
        self.busy_angle_id = ""
        self.generating = False
        self.outcome_message = ""
        self.outcome_tone = ""
        self.outcome_details = []
        self.poll_timed_out = False
        self._close_lightbox()
        self._close_editor()

    def _close_lightbox(self) -> None:
        self.lightbox_title = ""
        self.lightbox_url = ""
        self.lightbox_key = ""

    def _close_editor(self) -> None:
        self.editor_angle_id = ""
        self.editor_title = ""
        self.editor_scene = ""
        self.editor_composition = ""
        self.editor_name = ""
        self.editor_hook = ""
        self.editor_cta = ""
        self.editor_rationale = ""
        self.editor_can_regenerate = False
        self.saving = False

    def _angle(self, angle_id: str) -> AngleVM | None:
        return next((a for a in self.angles if a.id == angle_id), None)

    # -- the product --------------------------------------------------------------------------

    @rx.event(background=True)
    async def choose_product(self, product_id: str) -> None:
        """The product's facts and every preset's availability — read before anything is
        paid. Choosing another product drops the set under review."""
        await self._choose(product_id)

    async def _choose(self, product_id: str) -> None:
        async with self:
            if self.checking:
                return
            self.checking = True
            self.error = ""
            self.product_id = product_id
            self.preset_key = ""
            self._clear_set()
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.checking = False
            return
        tenant_id, brand_id, _ = ids
        try:
            check, presets = await asyncio.to_thread(
                variation_presets, tenant_id, brand_id, product_id
            )
            plan = await asyncio.to_thread(variation_plan)
        except Exception as exc:  # noqa: BLE001 — turned into words for the operator
            logger.warning("variations: product check failed: %s", type(exc).__name__)
            async with self:
                self.checking = False
                self.product_id = ""
                self.error = variation_error_message(exc)
            return
        async with self:
            self.product_name = check.name
            self.product_photo_count = check.photo_count
            self.price_label = check.price_label
            self.price_missing = check.price_missing
            self.price_note = check.price_note
            self.presets = list(presets)
            self.plan_count = plan.count
            self.plan_images_label = plan.images_label
            self.plan_note = plan.note
            first = next((p.key for p in presets if p.available), "")
            self.preset_key = first
            self.checking = False

    @rx.event
    def choose_preset(self, preset_key: str) -> None:
        """One preset of the list. An unavailable one is never selected: its reason is
        what the card shows instead."""
        if not any(p.key == preset_key and p.available for p in self.presets):
            return
        self.preset_key = preset_key
        self.error = ""

    # -- the angles -----------------------------------------------------------------------------

    @rx.event(background=True)
    async def create_set(self) -> None:
        """ONE paid Claude call: the angles of the chosen product and preset. A second
        click while it is in flight is ignored, so it is never paid twice."""
        async with self:
            if self.creating:
                return
            if not self.product_id:
                self.error = _PICK_PRODUCT
                return
            if not self.preset_key:
                self.error = _PICK_PRESET
                return
            product_id, preset_key = self.product_id, self.preset_key
            self.creating = True
            self.error = ""
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.creating = False
            return
        tenant_id, brand_id, user_id = ids
        if user_id is None:
            async with self:
                self.creating = False
                self.error = _NO_SESSION
            return
        try:
            set_id = await asyncio.to_thread(
                create_variation_set,
                tenant_id,
                brand_id,
                user_id,
                product_id,
                preset_key,
            )
        except Exception as exc:  # noqa: BLE001 — turned into words for the operator
            logger.warning("variations: set creation failed: %s", type(exc).__name__)
            async with self:
                self.creating = False
                self.error = variation_error_message(exc)
            return
        async with self:
            self.set_id = set_id
        await self._read_set(tenant_id, set_id)
        async with self:
            self.creating = False

    async def _read_set(self, tenant_id: UUID, set_id: str) -> None:
        """The set as the screen shows it. A read that fails leaves the angles already
        on screen untouched — only the message changes."""
        if not set_id:
            return
        try:
            detail = await asyncio.to_thread(variation_set_detail, tenant_id, set_id)
        except Exception as exc:  # noqa: BLE001 — turned into words for the operator
            logger.warning("variations: set read failed: %s", type(exc).__name__)
            async with self:
                self.error = variation_error_message(exc)
            return
        async with self:
            self.product_name = detail.product_name
            self.set_status_label = detail.status_label
            self.set_status_tone = detail.status_tone
            self.set_price_note = detail.price_note
            self.set_failure_text = detail.failure_text
            self.kept_count = detail.kept_count
            self.pending_count = detail.pending_count
            self.angles = list(detail.angles)

    @rx.event(background=True)
    async def open_set(self, set_id: str) -> AsyncIterator[rx.event.EventSpec]:
        """Reopen a set from the list — its angles, its pieces and whatever is still
        being made (the poll picks that up)."""
        async with self:
            self._clear_set()
            self.error = ""
            self.set_id = set_id
        ids = await self._session_ids()
        if ids is None:
            return
        await self._read_set(ids[0], set_id)
        async with self:
            running = self.in_flight
        if running:
            yield VariationsState.poll_set

    # -- the pieces -----------------------------------------------------------------------------

    @rx.event(background=True)
    async def generate_pieces(self) -> AsyncIterator[rx.event.EventSpec]:
        """One piece per angle still proposed — each a PAID image generation, dispatched
        out of band. The service reserves every angle first, so a second click creates no
        second piece; this flag only keeps the button quiet meanwhile."""
        async with self:
            if self.generating or not self.set_id:
                return
            if not self.pending_count:
                self.error = _NOTHING_TO_GENERATE
                return
            set_id = self.set_id
            self.generating = True
            self.error = ""
            self.outcome_message = ""
            self.outcome_details = []
            self.poll_timed_out = False
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.generating = False
            return
        tenant_id, brand_id, user_id = ids
        if user_id is None:
            async with self:
                self.generating = False
                self.error = _NO_SESSION
            return
        try:
            outcome = await asyncio.to_thread(
                generate_variation_pieces, tenant_id, set_id, user_id, None
            )
        except Exception as exc:  # noqa: BLE001 — turned into words for the operator
            logger.warning("variations: generation failed: %s", type(exc).__name__)
            await self._refresh_creations(tenant_id, brand_id)
            async with self:
                self.generating = False
                self.error = variation_error_message(exc)
            return
        await self._refresh_creations(tenant_id, brand_id)
        async with self:
            # what went wrong stays on the page with its details; what went right is a
            # toast (request 2026-10-22: «10 en generación» used to sit there for good)
            keep = bool(outcome.failed or outcome.unresolved)
            self.outcome_message = outcome.message if keep else ""
            self.outcome_tone = outcome.tone if keep else ""
            self.outcome_details = list(outcome.details) if keep else []
        yield _toast(outcome.message, outcome.tone)
        await self._read_set(tenant_id, set_id)
        async with self:
            self.generating = False
            running = self.in_flight
        if running:
            yield VariationsState.poll_set

    @rx.event(background=True)
    async def poll_set(self) -> None:
        """While pieces are being made, re-read the set — the same schedule the
        generator polls a single draft with. Stops when nothing is in flight any more,
        when the operator leaves the set, or when the budget runs out."""
        async with self:
            set_id = self.set_id
        if not set_id:
            return
        ids = await self._session_ids()
        if ids is None:
            return
        tenant_id = ids[0]
        started = time.monotonic()
        while True:
            await asyncio.sleep(_POLL_SECONDS)
            async with self:
                if self.set_id != set_id:
                    return
            await self._read_set(tenant_id, set_id)
            async with self:
                if self.set_id != set_id:
                    return
                if not self.in_flight:
                    return
                if time.monotonic() - started > _POLL_BUDGET_SECONDS:
                    self.poll_timed_out = True
                    return

    @rx.event(background=True)
    async def retry_angle(self, angle_id: str) -> AsyncIterator[rx.event.EventSpec]:
        """Generate this angle's piece again. The service refuses one that is not
        retryable, and never charges for a successful piece twice."""
        async with self:
            if self.busy_angle_id:
                return
            self.busy_angle_id = angle_id
            self.error = ""
            self.outcome_message = ""
            set_id = self.set_id
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.busy_angle_id = ""
            return
        tenant_id, _, user_id = ids
        if user_id is None:
            async with self:
                self.busy_angle_id = ""
                self.error = _NO_SESSION
            return
        try:
            await asyncio.to_thread(retry_variation_angle, tenant_id, angle_id, user_id)
        except Exception as exc:  # noqa: BLE001 — turned into words for the operator
            logger.warning("variations: retry failed: %s", type(exc).__name__)
            async with self:
                self.busy_angle_id = ""
                self.error = variation_error_message(exc)
            return
        await self._read_set(tenant_id, set_id)
        async with self:
            self.busy_angle_id = ""
            running = self.in_flight
        yield _toast(_RETRYING, "info")
        if running:
            yield VariationsState.poll_set

    @rx.event(background=True)
    async def approve_angle(self, angle_id: str) -> AsyncIterator[rx.event.EventSpec]:
        """Approve this angle's piece. The service refuses when the copy quotes a price
        that is not the catalog's — that refusal is what the card then shows."""
        async with self:
            if self.busy_angle_id:
                return
            self.busy_angle_id = angle_id
            self.error = ""
            self.outcome_message = ""
            set_id = self.set_id
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.busy_angle_id = ""
            return
        tenant_id, _, user_id = ids
        if user_id is None:
            async with self:
                self.busy_angle_id = ""
                self.error = _NO_SESSION
            return
        try:
            await asyncio.to_thread(approve_variation_angle, tenant_id, angle_id, user_id)
        except Exception as exc:  # noqa: BLE001 — turned into words for the operator
            logger.warning("variations: approval refused: %s", type(exc).__name__)
            async with self:
                self.busy_angle_id = ""
                self.error = variation_error_message(exc)
            await self._read_set(tenant_id, set_id)
            return
        await self._read_set(tenant_id, set_id)
        async with self:
            self.busy_angle_id = ""
        yield _toast(_APPROVED, "ok")

    @rx.event(background=True)
    async def regenerate_angle(self, angle_id: str) -> AsyncIterator[rx.event.EventSpec]:
        """Another take of a piece that did not convince — a PAID image. The service
        rejects the old piece and briefs the new one as the next take of the same scene;
        this handler only keeps the card quiet meanwhile and resumes the poll."""
        async with self:
            if self.busy_angle_id:
                return
            self.busy_angle_id = angle_id
            self.error = ""
            self.outcome_message = ""
            set_id = self.set_id
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.busy_angle_id = ""
            return
        tenant_id, _, user_id = ids
        if user_id is None:
            async with self:
                self.busy_angle_id = ""
                self.error = _NO_SESSION
            return
        try:
            await asyncio.to_thread(regenerate_variation_angle, tenant_id, angle_id, user_id)
        except Exception as exc:  # noqa: BLE001 — turned into words for the operator
            logger.warning("variations: regeneration failed: %s", type(exc).__name__)
            async with self:
                self.busy_angle_id = ""
                self.error = variation_error_message(exc)
            return
        await self._read_set(tenant_id, set_id)
        async with self:
            self.busy_angle_id = ""
            running = self.in_flight
        yield _toast(_REGENERATING, "info")
        if running:
            yield VariationsState.poll_set

    @rx.event(background=True)
    async def discard_angle(self, angle_id: str) -> AsyncIterator[rx.event.EventSpec]:
        if await self._angle_action(angle_id, discard_variation_angle, with_user=True):
            async for event in self._leave_if_empty():
                yield event

    async def _leave_if_empty(self) -> AsyncIterator[rx.event.EventSpec]:
        """A group with nothing standing is nothing to look at (request 2026-10-22: «si
        fallaron no guardes nada»): back to the start, the list re-read without it."""
        async with self:
            empty = bool(self.set_id) and self.kept_count == 0
            if empty:
                self._clear_set()
        if not empty:
            return
        ids = await self._session_ids()
        if ids is not None:
            sets = await asyncio.to_thread(list_variation_sets, ids[0], ids[1])
            async with self:
                self.sets = list(sets)
        yield _toast(_GROUP_EMPTY, "info")

    @rx.event(background=True)
    async def discard_rest(self) -> AsyncIterator[rx.event.EventSpec]:
        """Discard every angle still open in one gesture (request 2026-10-22), leaving
        the approved ones; each can still be recovered one by one. Reversible, so no
        confirmation — the toast says how many went."""
        async with self:
            if self.busy_angle_id or not self.set_id:
                return
            ids = [a.id for a in self.angles if self._bulk_discardable(a)]
            if not ids:
                yield _toast(_NOTHING_TO_DISCARD, "info")
                return
            self.busy_angle_id = ids[0]
            self.error = ""
            set_id = self.set_id
        ids_tuple = tuple(ids)
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.busy_angle_id = ""
            return
        tenant_id, _, user_id = ids
        if user_id is None:
            async with self:
                self.busy_angle_id = ""
                self.error = _NO_SESSION
            return
        done = await asyncio.to_thread(discard_variation_angles, tenant_id, ids_tuple, user_id)
        await self._read_set(tenant_id, set_id)
        async with self:
            self.busy_angle_id = ""
        word = "propuesta eliminada" if done == 1 else "propuestas eliminadas"
        yield _toast(f"{done} {word}.", "ok")
        async for event in self._leave_if_empty():
            yield event

    # -- the list of groups ------------------------------------------------------------------

    @rx.event(background=True)
    async def close_set(self) -> None:
        """Back to the list of groups, the product still chosen (request 2026-10-22)."""
        async with self:
            self._clear_set()
        ids = await self._session_ids()
        if ids is None:
            return
        sets = await asyncio.to_thread(list_variation_sets, ids[0], ids[1])
        async with self:
            self.sets = list(sets)

    @rx.event
    def ask_archive_set(self, set_id: str, name: str) -> None:
        self.archive_set_id = set_id
        self.archive_set_name = name

    @rx.event
    def set_archive_open(self, value: bool) -> None:
        if not value:
            self.archive_set_id = ""
            self.archive_set_name = ""

    @rx.event(background=True)
    async def confirm_archive_set(self) -> AsyncIterator[rx.event.EventSpec]:
        """The group leaves the list for good; its open proposals are deleted with it."""
        async with self:
            set_id, self.archive_set_id, self.archive_set_name = self.archive_set_id, "", ""
            if not set_id or self.busy_angle_id:
                return
            self.error = ""
        ids = await self._session_ids()
        if ids is None:
            return
        tenant_id, brand_id, user_id = ids
        if user_id is None:
            async with self:
                self.error = _NO_SESSION
            return
        try:
            await asyncio.to_thread(archive_variation_set, tenant_id, set_id, user_id)
        except Exception as exc:  # noqa: BLE001 — turned into words for the operator
            logger.warning("variations: archive failed: %s", type(exc).__name__)
            async with self:
                self.error = variation_error_message(exc)
            return
        sets = await asyncio.to_thread(list_variation_sets, tenant_id, brand_id)
        async with self:
            if self.set_id == set_id:
                self._clear_set()
            self.sets = list(sets)
        yield _toast(_GROUP_DELETED, "ok")

    # -- «guardar para después» ------------------------------------------------------------

    @rx.event(background=True)
    async def save_angle(self, angle_id: str) -> AsyncIterator[rx.event.EventSpec]:
        """Put this one aside: out of the review, untouched, to take up later."""
        if await self._angle_action(angle_id, _save_true):
            yield _toast(_SAVED_ONE, "ok")

    @rx.event(background=True)
    async def unsave_angle(self, angle_id: str) -> AsyncIterator[rx.event.EventSpec]:
        if await self._angle_action(angle_id, _save_false):
            yield _toast(_RESUMED_ONE, "ok")

    @rx.event(background=True)
    async def save_rest(self) -> AsyncIterator[rx.event.EventSpec]:
        """Every angle still open goes aside in one gesture (request 2026-10-22: «una en
        específico o todas las demás»); the approved ones stay."""
        async with self:
            if self.busy_angle_id or not self.set_id:
                return
            ids = [a.id for a in self.angles if a.can_save]
            if not ids:
                yield _toast(_NOTHING_TO_SAVE, "info")
                return
            self.busy_angle_id = ids[0]
            self.error = ""
            set_id = self.set_id
        ids_tuple = tuple(ids)
        session = await self._session_ids()
        if session is None:
            async with self:
                self.busy_angle_id = ""
            return
        tenant_id = session[0]
        done = await asyncio.to_thread(save_variation_angles, tenant_id, ids_tuple)
        await self._read_set(tenant_id, set_id)
        async with self:
            self.busy_angle_id = ""
        word = "propuesta guardada" if done == 1 else "propuestas guardadas"
        yield _toast(f"{done} {word} para después.", "ok")

    async def _angle_action(  # noqa: ANN001 — provider fn
        self, angle_id: str, action, *, with_user: bool = False
    ) -> bool:
        """Discard, restore or edit, then re-read the set: the service decides what the
        angle now is, never the screen. True when the action went through."""
        async with self:
            if self.busy_angle_id:
                return False
            self.busy_angle_id = angle_id
            self.error = ""
            set_id = self.set_id
        ids = await self._session_ids()
        if ids is None:
            async with self:
                self.busy_angle_id = ""
            return False
        tenant_id, _, user_id = ids
        if with_user and user_id is None:
            async with self:
                self.busy_angle_id = ""
                self.error = _NO_SESSION
            return False
        args = (tenant_id, angle_id, user_id) if with_user else (tenant_id, angle_id)
        try:
            await asyncio.to_thread(action, *args)
        except Exception as exc:  # noqa: BLE001 — turned into words for the operator
            logger.warning("variations: angle action failed: %s", type(exc).__name__)
            async with self:
                self.busy_angle_id = ""
                self.error = variation_error_message(exc)
            return False
        await self._read_set(tenant_id, set_id)
        async with self:
            self.busy_angle_id = ""
        return True

    # -- the lightbox -----------------------------------------------------------------------------

    @rx.event
    def open_lightbox(self, angle_id: str) -> None:
        """The piece of this angle at full size. The source is the state's own (the
        angle's preview, as the last read of the set left it), never one the browser
        passes in."""
        angle = self._angle(angle_id)
        if angle is None or not (angle.preview_url or angle.preview_key):
            return
        self.lightbox_title = f"{angle.position}. {angle.title}"
        self.lightbox_url = angle.preview_url
        self.lightbox_key = angle.preview_key

    @rx.event
    def set_lightbox_open(self, is_open: bool) -> None:
        if not is_open:
            self._close_lightbox()

    # -- the scene editor --------------------------------------------------------------------------

    @rx.event
    def open_editor(self, angle_id: str) -> None:
        angle = self._angle(angle_id)
        if angle is None or not angle.can_edit:
            return
        self.error = ""
        self.editor_angle_id = angle.id
        self.editor_title = f"{angle.position}. {angle.title}"
        self.editor_scene = angle.scene
        self.editor_composition = angle.composition
        self.editor_name = angle.title
        self.editor_hook = angle.hook
        self.editor_cta = angle.cta
        self.editor_rationale = angle.rationale
        self.editor_can_regenerate = angle.can_regenerate

    @rx.event
    def set_editor_open(self, is_open: bool) -> None:
        if not is_open and not self.saving:
            self._close_editor()

    @rx.event
    def set_editor_scene(self, value: str) -> None:
        self.editor_scene = value

    @rx.event
    def set_editor_composition(self, value: str) -> None:
        self.editor_composition = value

    @rx.event
    def set_editor_name(self, value: str) -> None:
        self.editor_name = value

    @rx.event
    def set_editor_hook(self, value: str) -> None:
        self.editor_hook = value

    @rx.event
    def set_editor_cta(self, value: str) -> None:
        self.editor_cta = value

    @rx.event
    def set_editor_rationale(self, value: str) -> None:
        self.editor_rationale = value

    @rx.event(background=True)
    async def save_edit(self) -> AsyncIterator[rx.event.EventSpec]:
        """Store the new scene; the next piece of that angle is briefed from it."""
        if await self._save_edit():
            yield _toast(_EDITED, "ok")

    @rx.event(background=True)
    async def save_edit_and_regenerate(self) -> AsyncIterator[rx.event.EventSpec]:
        """Store the new scene and make another take of it right away — the one
        gesture for «this scene, but not like that»."""
        angle_id = await self._save_edit()
        if angle_id:
            yield VariationsState.regenerate_angle(angle_id)

    async def _save_edit(self) -> str:
        """The edited angle's id when the service took the words, "" otherwise."""
        async with self:
            if self.saving or not self.editor_angle_id:
                return ""
            angle_id = self.editor_angle_id
            scene = " ".join(self.editor_scene.split())
            composition = " ".join(self.editor_composition.split())
            name = " ".join(self.editor_name.split())
            hook = " ".join(self.editor_hook.split())
            cta = " ".join(self.editor_cta.split())
            rationale = " ".join(self.editor_rationale.split())
            if not scene:
                self.error = _EMPTY_SCENE
                return ""
            if not name:
                self.error = _EMPTY_TITLE
                return ""
            self.saving = True
            self.error = ""

        def _edit(tenant_id: UUID, angle_id: str) -> None:
            edit_variation_angle(
                tenant_id,
                angle_id,
                scene,
                composition,
                title=name,
                hook=hook,
                cta=cta,
                rationale=rationale,
            )

        saved = await self._angle_action(angle_id, _edit)
        async with self:
            self.saving = False
            if saved:
                self._close_editor()
        return angle_id if saved else ""
