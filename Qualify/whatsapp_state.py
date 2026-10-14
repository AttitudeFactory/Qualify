"""Reflex state for the `/whatsapp` screen (WA-12): the shell (numbers, selector, tabs)
and the Conexión / Perfil / QR tabs.

Holds only the frozen VMs of `whatsapp_vm.py` — never an ORM row, never a Graph client,
never a token — so nothing credential-bearing can be serialized to the browser. The
tenant comes from `AuthState` (set only by a real login, QUA-66).

Every Postgres or Graph call runs in a background event: SQLAlchemy is synchronous (the
provider wraps it in `asyncio.to_thread`) and a Graph round trip can take seconds, and a
foreground handler would hold this session's state lock for all of it.

**Tab loading.** The page renders the active tab only, inside a box keyed by
`selected_connection_id`, so a tab's root `on_mount` fires on tab entry and on every
number switch. Perfil and QR load there (`ensure_profile_loaded` / `ensure_qr_loaded`),
guarded by `*_loaded_for`/`*_loading_for` so a double mount (React dev mode) or a revisit
of an already-loaded tab costs no second Graph call. WA-11/WA-16 use the same hook from
their own files without touching this one.
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
from collections.abc import AsyncIterator
from uuid import UUID

import httpx
import reflex as rx
from qualify_api.connections.credential_reader import CredentialNotFound
from qualify_api.connections.token_health import TokenHealthError
from qualify_api.whatsapp.client import WhatsAppApiError
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .tenant import tenant_uuid
from .whatsapp_provider import (
    UnknownWhatsAppNumber,
    create_qr_code,
    delete_qr_code,
    list_qr_codes,
    load_profile,
    numbers_for,
    save_profile,
    set_profile_picture,
    verify_number,
)
from .whatsapp_vm import (
    EMPTY_NUMBER,
    EMPTY_PROFILE,
    GRAPH_UNAVAILABLE,
    MAX_QR_MESSAGE_CHARS,
    QR_DEFAULT_CHANNEL,
    TAB_KEYS,
    BusinessProfileVM,
    ProfileForm,
    QrCodeVM,
    WhatsAppNumberVM,
    compose_qr_message,
    graph_error_notice,
    resolve_tab,
    validate_profile_form,
)

logger = logging.getLogger(__name__)

_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_LOAD_FAILED = "No se pudieron cargar tus números de WhatsApp. Vuelve a intentarlo en un momento."
_NOT_FOUND = "Ese número ya no está conectado. Actualizamos la lista con el estado real."
_VERIFY_OK = "Verificado con Meta. Los datos del número están al día."
_VERIFY_DEGRADED = (
    "Meta ya no acepta el acceso de este número. Quedó marcado como degradado; "
    "pide al equipo de Qualify que vuelva a conectarlo."
)
_VERIFY_FAILED = "No se pudo verificar el número con Meta. Vuelve a intentarlo en un momento."
_PROFILE_SAVED = "Perfil guardado en WhatsApp."
_PHOTO_SAVED = "Foto de perfil actualizada en WhatsApp."
_PHOTO_INVALID = "Sube una foto JPG o PNG de hasta 5 MB."
_QR_CREATED = "Código QR creado."
_QR_DELETED = "Código QR eliminado."
_QR_EMPTY = "Elige un canal o escribe el mensaje con el que llega el cliente."
_QR_TOO_LONG = f"El mensaje admite hasta {MAX_QR_MESSAGE_CHARS} caracteres."

# Profile photo: what Meta accepts for a WhatsApp business profile picture.
_PHOTO_TYPES = frozenset({"image/jpeg", "image/png"})
_PHOTO_MAX_BYTES = 5 * 1024 * 1024

_PROFILE_FIELDS = frozenset(
    {"about", "address", "description", "email", "website_1", "website_2", "vertical"}
)

# Failures that are infrastructure, not a verdict from Meta. Only the TYPE is logged.
_INFRA_ERRORS = (CredentialNotFound, TokenHealthError, httpx.HTTPError, SQLAlchemyError)


def _graph_banner(exc: Exception) -> tuple[str, str]:
    """Any failure of a Graph-backed action → (message, tone). Never Meta's text."""
    if isinstance(exc, WhatsAppApiError):
        return graph_error_notice(
            code=exc.code, is_auth_error=exc.is_auth_error, is_transport=exc.is_transport
        )
    if isinstance(exc, UnknownWhatsAppNumber):
        return _NOT_FOUND, "warn"
    return GRAPH_UNAVAILABLE, "error"


class WhatsAppState(rx.State):
    """State for `/whatsapp`."""

    # -- shell ---------------------------------------------------------------------------
    numbers: list[WhatsAppNumberVM] = []
    selected_connection_id: str = ""
    active_tab: str = resolve_tab("")
    is_loading: bool = False
    load_error: str = ""

    # -- Conexión ------------------------------------------------------------------------
    verifying: bool = False
    connection_banner: str = ""
    connection_banner_tone: str = "info"

    # -- Perfil --------------------------------------------------------------------------
    profile: BusinessProfileVM = EMPTY_PROFILE
    form_about: str = ""
    form_address: str = ""
    form_description: str = ""
    form_email: str = ""
    form_website_1: str = ""
    form_website_2: str = ""
    form_vertical: str = ""
    profile_loaded_for: str = ""
    profile_loading_for: str = ""
    profile_saving: bool = False
    photo_uploading: bool = False
    profile_banner: str = ""
    profile_banner_tone: str = "info"
    # Backend-only (underscore): the dropped photo waits here for the background upload,
    # so the bytes never travel to the browser and back as an event argument.
    _pending_photo: tuple[bytes, str, str] | None = None

    # -- QR ------------------------------------------------------------------------------
    qr_codes: list[QrCodeVM] = []
    qr_loaded_for: str = ""
    qr_loading_for: str = ""
    qr_channel: str = QR_DEFAULT_CHANNEL
    qr_text: str = ""
    qr_creating: bool = False
    qr_deleting_code: str = ""
    qr_banner: str = ""
    qr_banner_tone: str = "info"
    # Backend-only: Meta returns a code's PNG on create only; keep it for this session.
    _qr_images: dict[str, str] = {}

    # ==================================================================================
    # Computed vars
    # ==================================================================================

    @rx.var
    def has_numbers(self) -> bool:
        return len(self.numbers) > 0

    @rx.var
    def has_many_numbers(self) -> bool:
        return len(self.numbers) > 1

    @rx.var
    def show_empty_state(self) -> bool:
        return not self.is_loading and not self.load_error and len(self.numbers) == 0

    @rx.var
    def selected_number(self) -> WhatsAppNumberVM:
        for number in self.numbers:
            if number.connection_id == self.selected_connection_id:
                return number
        return EMPTY_NUMBER

    # Perfil/QR content renders ONLY once it was read for the number on screen. An
    # empty form after a failed read would let «Guardar» wipe the real profile on Meta
    # with blanks, and an empty QR list would claim "no codes" when the read failed.
    # So each tab is tri-state: ready (content) / failed (banner + retry) / else
    # skeleton (loading, or about to be — `on_mount` has not landed yet). A forced
    # re-read of a number already on screen stays "ready": no skeleton flash.
    @rx.var
    def profile_ready(self) -> bool:
        return self.profile_loaded_for != "" and (
            self.profile_loaded_for == self.selected_connection_id
        )

    @rx.var
    def profile_failed(self) -> bool:
        return (
            self.profile_loaded_for != self.selected_connection_id
            and self.profile_loading_for == ""
            and self.profile_banner != ""
        )

    @rx.var
    def qr_ready(self) -> bool:
        return self.qr_loaded_for != "" and self.qr_loaded_for == self.selected_connection_id

    @rx.var
    def qr_failed(self) -> bool:
        return (
            self.qr_loaded_for != self.selected_connection_id
            and self.qr_loading_for == ""
            and self.qr_banner != ""
        )

    @rx.var
    def qr_preview(self) -> str:
        return compose_qr_message(self.qr_channel, self.qr_text)

    @rx.var
    def qr_preview_count(self) -> str:
        return f"{len(compose_qr_message(self.qr_channel, self.qr_text))}/{MAX_QR_MESSAGE_CHARS}"

    # ==================================================================================
    # Shell
    # ==================================================================================

    @rx.event
    def enter_page(self) -> rx.event.EventSpec:
        """`/whatsapp` on_load: pick the tab from `?tab=` and load the numbers."""
        requested = str(self.router.url.query_parameters.get("tab", "") or "")
        self.active_tab = resolve_tab(requested)
        return WhatsAppState.load_numbers

    @rx.event
    def select_tab(self, tab: str | list[str]) -> None:
        """`on_change` of the tab strip (a segmented control: `str | list[str]`)."""
        if isinstance(tab, str) and tab in TAB_KEYS:
            self.active_tab = tab

    @rx.event
    def select_connection(self, connection_id: str) -> None:
        """The number selector. The tab body is keyed by the selection, so its `on_mount`
        loads the new number's data; everything tied to the old one is dropped here."""
        if connection_id == self.selected_connection_id:
            return
        if connection_id not in {n.connection_id for n in self.numbers}:
            return  # arrived over the wire; refuse an id the list does not hold
        self.selected_connection_id = connection_id
        self._reset_number_scoped()

    def _reset_number_scoped(self) -> None:
        self.connection_banner = ""
        self.profile = EMPTY_PROFILE
        self._fill_form(EMPTY_PROFILE)
        self.profile_loaded_for = ""
        self.profile_loading_for = ""
        self.profile_banner = ""
        self.qr_codes = []
        self.qr_loaded_for = ""
        self.qr_loading_for = ""
        self.qr_banner = ""
        self._qr_images = {}

    async def _session_tenant(self) -> tuple[str, UUID | None]:
        auth = await self.get_state(AuthState)
        session_tenant_id = auth.session_tenant_id
        return session_tenant_id, tenant_uuid(session_tenant_id) if session_tenant_id else None

    @rx.event(background=True)
    async def load_numbers(self) -> None:
        async with self:
            self.is_loading = True
            self.load_error = ""
            session_tenant_id, tenant_id = await self._session_tenant()
        if tenant_id is None:
            async with self:
                self.is_loading = False
                self.load_error = _NO_SESSION
            return
        try:
            data = await asyncio.to_thread(numbers_for, tenant_id)
        except SQLAlchemyError as exc:
            logger.error("whatsapp numbers load failed: %s", type(exc).__name__)
            async with self:
                self.is_loading = False
                self.load_error = _LOAD_FAILED
            return
        async with self:
            auth = await self.get_state(AuthState)
            if session_tenant_id != auth.session_tenant_id:
                return  # a logout/login raced this load
            self.numbers = data
            self.is_loading = False
            ids = {n.connection_id for n in data}
            if self.selected_connection_id not in ids:
                self.selected_connection_id = data[0].connection_id if data else ""
                self._reset_number_scoped()

    # ==================================================================================
    # Conexión
    # ==================================================================================

    @rx.event(background=True)
    async def verify_now(self) -> AsyncIterator[rx.event.EventSpec]:
        """«Verificar ahora»: `/debug_token` + `GET /{PHONE_NUMBER_ID}`, then reload the
        numbers so the card shows what Meta said. Manual only — no timer calls this."""
        async with self:
            if self.verifying or not self.selected_connection_id:
                return
            self.verifying = True
            self.connection_banner = ""
            connection_id = self.selected_connection_id
            _session, tenant_id = await self._session_tenant()
        if tenant_id is None:
            async with self:
                self.verifying = False
                self.connection_banner, self.connection_banner_tone = _NO_SESSION, "error"
            return
        try:
            healthy = await verify_number(tenant_id, UUID(connection_id))
        except (WhatsAppApiError, UnknownWhatsAppNumber) as exc:
            message, tone = _graph_banner(exc)
            async with self:
                self.verifying = False
                self.connection_banner, self.connection_banner_tone = message, tone
            yield WhatsAppState.load_numbers
            return
        except _INFRA_ERRORS as exc:
            logger.error("whatsapp verify failed: %s", type(exc).__name__)
            async with self:
                self.verifying = False
                self.connection_banner, self.connection_banner_tone = _VERIFY_FAILED, "error"
            return
        async with self:
            self.verifying = False
            if healthy:
                self.connection_banner, self.connection_banner_tone = _VERIFY_OK, "ok"
            else:
                self.connection_banner, self.connection_banner_tone = _VERIFY_DEGRADED, "error"
        yield WhatsAppState.load_numbers

    # ==================================================================================
    # Perfil
    # ==================================================================================

    def _fill_form(self, profile: BusinessProfileVM) -> None:
        self.form_about = profile.about
        self.form_address = profile.address
        self.form_description = profile.description
        self.form_email = profile.email
        self.form_website_1 = profile.website_1
        self.form_website_2 = profile.website_2
        self.form_vertical = profile.vertical

    @rx.event
    def set_profile_field(self, field: str, value: str) -> None:
        """One setter for the seven form fields; anything outside the whitelist is junk."""
        if field in _PROFILE_FIELDS and isinstance(value, str):
            setattr(self, f"form_{field}", value)

    @rx.event
    def reset_profile_form(self) -> None:
        self._fill_form(self.profile)
        self.profile_banner = ""

    @rx.event(background=True)
    async def ensure_profile_loaded(self) -> None:
        await self._load_profile(force=False)

    @rx.event(background=True)
    async def reload_profile(self) -> None:
        await self._load_profile(force=True)

    async def _load_profile(self, *, force: bool) -> None:
        async with self:
            connection_id = self.selected_connection_id
            if not connection_id or self.profile_loading_for == connection_id:
                return
            if not force and self.profile_loaded_for == connection_id:
                return
            self.profile_loading_for = connection_id
            if not force:
                self.profile_banner = ""
            _session, tenant_id = await self._session_tenant()
        if tenant_id is None:
            async with self:
                self.profile_loading_for = ""
                self.profile_banner, self.profile_banner_tone = _NO_SESSION, "error"
            return
        try:
            profile = await load_profile(tenant_id, UUID(connection_id))
        except (WhatsAppApiError, UnknownWhatsAppNumber, *_INFRA_ERRORS) as exc:
            if not isinstance(exc, (WhatsAppApiError, UnknownWhatsAppNumber)):
                logger.error("whatsapp profile load failed: %s", type(exc).__name__)
            message, tone = _graph_banner(exc)
            async with self:
                if self.selected_connection_id == connection_id:
                    self.profile_loading_for = ""
                    self.profile_banner, self.profile_banner_tone = message, tone
            return
        async with self:
            if self.selected_connection_id != connection_id:
                return  # the operator switched numbers while Meta answered
            self.profile = profile
            self._fill_form(profile)
            self.profile_loaded_for = connection_id
            self.profile_loading_for = ""

    @rx.event(background=True)
    async def save_profile_form(self) -> None:
        async with self:
            if self.profile_saving or not self.selected_connection_id:
                return
            form = ProfileForm(
                about=self.form_about,
                address=self.form_address,
                description=self.form_description,
                email=self.form_email,
                website_1=self.form_website_1,
                website_2=self.form_website_2,
                vertical=self.form_vertical,
            )
            problem = validate_profile_form(form)
            if problem:
                self.profile_banner, self.profile_banner_tone = problem, "warn"
                return
            self.profile_saving = True
            self.profile_banner = ""
            connection_id = self.selected_connection_id
            _session, tenant_id = await self._session_tenant()
        if tenant_id is None:
            async with self:
                self.profile_saving = False
                self.profile_banner, self.profile_banner_tone = _NO_SESSION, "error"
            return
        try:
            await save_profile(tenant_id, UUID(connection_id), form)
        except ValueError:
            # The client's own limit check — `validate_profile_form` should have caught
            # it first; the English message is for engineers and is not shown.
            async with self:
                self.profile_saving = False
                self.profile_banner = (
                    "Revisa los datos del perfil: alguno supera lo que Meta admite."
                )
                self.profile_banner_tone = "warn"
            return
        except (WhatsAppApiError, UnknownWhatsAppNumber, *_INFRA_ERRORS) as exc:
            if not isinstance(exc, (WhatsAppApiError, UnknownWhatsAppNumber)):
                logger.error("whatsapp profile save failed: %s", type(exc).__name__)
            message, tone = _graph_banner(exc)
            async with self:
                self.profile_saving = False
                self.profile_banner, self.profile_banner_tone = message, tone
            return
        async with self:
            self.profile_saving = False
            self.profile_banner, self.profile_banner_tone = _PROFILE_SAVED, "ok"
        await self._load_profile(force=True)

    @rx.event
    async def handle_photo_upload(self, files: list[rx.UploadFile]) -> rx.event.EventSpec | None:
        """Foreground (it receives the files), parks the bytes backend-side and chains
        the background upload."""
        if not files or not self.selected_connection_id or self.photo_uploading:
            return None
        upload = files[0]
        try:
            data = await upload.read()
        except Exception:
            self.profile_banner, self.profile_banner_tone = _PHOTO_INVALID, "warn"
            return None
        name = upload.name or "perfil.jpg"
        content_type = (getattr(upload, "content_type", None) or "").lower()
        if content_type not in _PHOTO_TYPES:
            content_type = (mimetypes.guess_type(name)[0] or "").lower()
        if content_type not in _PHOTO_TYPES or not data or len(data) > _PHOTO_MAX_BYTES:
            self.profile_banner, self.profile_banner_tone = _PHOTO_INVALID, "warn"
            return None
        self._pending_photo = (data, content_type, name)
        return WhatsAppState.upload_pending_photo

    @rx.event(background=True)
    async def upload_pending_photo(self) -> None:
        async with self:
            pending = self._pending_photo
            self._pending_photo = None
            if pending is None or self.photo_uploading or not self.selected_connection_id:
                return
            self.photo_uploading = True
            self.profile_banner = ""
            connection_id = self.selected_connection_id
            _session, tenant_id = await self._session_tenant()
        if tenant_id is None:
            async with self:
                self.photo_uploading = False
                self.profile_banner, self.profile_banner_tone = _NO_SESSION, "error"
            return
        data, content_type, name = pending
        try:
            await set_profile_picture(tenant_id, UUID(connection_id), data, content_type, name)
        except ValueError:
            async with self:
                self.photo_uploading = False
                self.profile_banner, self.profile_banner_tone = _PHOTO_INVALID, "warn"
            return
        except (WhatsAppApiError, UnknownWhatsAppNumber, *_INFRA_ERRORS) as exc:
            if not isinstance(exc, (WhatsAppApiError, UnknownWhatsAppNumber)):
                logger.error("whatsapp photo upload failed: %s", type(exc).__name__)
            message, tone = _graph_banner(exc)
            async with self:
                self.photo_uploading = False
                self.profile_banner, self.profile_banner_tone = message, tone
            return
        async with self:
            self.photo_uploading = False
            self.profile_banner, self.profile_banner_tone = _PHOTO_SAVED, "ok"
        await self._load_profile(force=True)

    # ==================================================================================
    # QR
    # ==================================================================================

    @rx.event
    def set_qr_channel(self, channel: str | list[str]) -> None:
        if isinstance(channel, str):
            self.qr_channel = channel

    @rx.event
    def set_qr_text(self, value: str) -> None:
        self.qr_text = value

    def _with_images(self, codes: list[QrCodeVM]) -> list[QrCodeVM]:
        """Re-attach the PNG Meta returned at create time to codes the list omits it for."""
        merged: list[QrCodeVM] = []
        for qr in codes:
            image = qr.image_url or self._qr_images.get(qr.code, "")
            merged.append(
                qr
                if image == qr.image_url
                else QrCodeVM(
                    code=qr.code,
                    prefilled_message=qr.prefilled_message,
                    deep_link_url=qr.deep_link_url,
                    image_url=image,
                    channel_label=qr.channel_label,
                )
            )
        return merged

    @rx.event(background=True)
    async def ensure_qr_loaded(self) -> None:
        await self._load_qr(force=False)

    @rx.event(background=True)
    async def reload_qr(self) -> None:
        await self._load_qr(force=True)

    async def _load_qr(self, *, force: bool) -> None:
        async with self:
            connection_id = self.selected_connection_id
            if not connection_id or self.qr_loading_for == connection_id:
                return
            if not force and self.qr_loaded_for == connection_id:
                return
            self.qr_loading_for = connection_id
            _session, tenant_id = await self._session_tenant()
        if tenant_id is None:
            async with self:
                self.qr_loading_for = ""
                self.qr_banner, self.qr_banner_tone = _NO_SESSION, "error"
            return
        try:
            codes = await list_qr_codes(tenant_id, UUID(connection_id))
        except (WhatsAppApiError, UnknownWhatsAppNumber, *_INFRA_ERRORS) as exc:
            if not isinstance(exc, (WhatsAppApiError, UnknownWhatsAppNumber)):
                logger.error("whatsapp qr list failed: %s", type(exc).__name__)
            message, tone = _graph_banner(exc)
            async with self:
                if self.selected_connection_id == connection_id:
                    self.qr_loading_for = ""
                    self.qr_banner, self.qr_banner_tone = message, tone
            return
        async with self:
            if self.selected_connection_id != connection_id:
                return
            self.qr_codes = self._with_images(codes)
            self.qr_loaded_for = connection_id
            self.qr_loading_for = ""

    @rx.event(background=True)
    async def create_qr(self) -> None:
        async with self:
            if self.qr_creating or not self.selected_connection_id:
                return
            message = compose_qr_message(self.qr_channel, self.qr_text)
            if not message:
                self.qr_banner, self.qr_banner_tone = _QR_EMPTY, "warn"
                return
            if len(message) > MAX_QR_MESSAGE_CHARS:
                self.qr_banner, self.qr_banner_tone = _QR_TOO_LONG, "warn"
                return
            self.qr_creating = True
            self.qr_banner = ""
            connection_id = self.selected_connection_id
            _session, tenant_id = await self._session_tenant()
        if tenant_id is None:
            async with self:
                self.qr_creating = False
                self.qr_banner, self.qr_banner_tone = _NO_SESSION, "error"
            return
        try:
            qr = await create_qr_code(tenant_id, UUID(connection_id), message)
        except (WhatsAppApiError, UnknownWhatsAppNumber, ValueError, *_INFRA_ERRORS) as exc:
            if isinstance(exc, ValueError):
                notice = (_QR_TOO_LONG, "warn")
            else:
                if not isinstance(exc, (WhatsAppApiError, UnknownWhatsAppNumber)):
                    logger.error("whatsapp qr create failed: %s", type(exc).__name__)
                notice = _graph_banner(exc)
            async with self:
                self.qr_creating = False
                self.qr_banner, self.qr_banner_tone = notice
            return
        async with self:
            self.qr_creating = False
            if qr.image_url:
                self._qr_images = {**self._qr_images, qr.code: qr.image_url}
            if self.selected_connection_id == connection_id:
                self.qr_codes = [qr, *[c for c in self.qr_codes if c.code != qr.code]]
            self.qr_text = ""
            self.qr_banner, self.qr_banner_tone = _QR_CREATED, "ok"

    @rx.event(background=True)
    async def delete_qr(self, code: str) -> None:
        async with self:
            if self.qr_deleting_code or not self.selected_connection_id:
                return
            if code not in {c.code for c in self.qr_codes}:
                return  # arrived over the wire; only codes on screen can be deleted
            self.qr_deleting_code = code
            self.qr_banner = ""
            connection_id = self.selected_connection_id
            _session, tenant_id = await self._session_tenant()
        if tenant_id is None:
            async with self:
                self.qr_deleting_code = ""
                self.qr_banner, self.qr_banner_tone = _NO_SESSION, "error"
            return
        try:
            await delete_qr_code(tenant_id, UUID(connection_id), code)
        except (WhatsAppApiError, UnknownWhatsAppNumber, *_INFRA_ERRORS) as exc:
            if not isinstance(exc, (WhatsAppApiError, UnknownWhatsAppNumber)):
                logger.error("whatsapp qr delete failed: %s", type(exc).__name__)
            message, tone = _graph_banner(exc)
            async with self:
                self.qr_deleting_code = ""
                self.qr_banner, self.qr_banner_tone = message, tone
            return
        async with self:
            self.qr_deleting_code = ""
            self.qr_codes = [c for c in self.qr_codes if c.code != code]
            self._qr_images = {k: v for k, v in self._qr_images.items() if k != code}
            self.qr_banner, self.qr_banner_tone = _QR_DELETED, "ok"
