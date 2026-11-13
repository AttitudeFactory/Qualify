"""«Stickers y videos de tu marca» (m-24976895, spec `docs/ux-stickers-videos.md`): the
season library in Tu marca, the three-step «Crear para esta temporada» flow, and the
batch in «Por aprobar» (Aprobar · Pedir otro · Aprobar los listos). Nothing is approved
by default; reads land only for the load that asked (`_gen`); a batch being prepared is
polled until it is done or the screen goes away."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import reflex as rx

from .auth_state import AuthState
from .planner_vm import KIND_PARAM, tab_label
from .seasonal_provider import gateway
from .seasonal_vm import (
    ACTION_FAILED,
    AI_LIMIT,
    AI_UNAVAILABLE,
    APPROVED_STICKERS_HREF,
    APPROVED_TOAST,
    APPROVED_TOAST_ACTION,
    CREATE_FAILED,
    DELETE_FAILED,
    KIND_ALL,
    LOAD_FAILED,
    MAX_OTHER_NAME,
    MISSING_MATERIAL,
    MODE_AI,
    MODE_FREE,
    NO_SESSION,
    OTHER_KEY,
    OTHER_NAME_MISSING,
    PHOTOS_CHANGED,
    PRODUCT_SEASON_KEY,
    STARTED_TOAST,
    STEP_HOW,
    STEP_OCCASION,
    STEP_REVIEW,
    STICKER,
    UNDO_LABEL,
    VIDEO,
    AiPhotoVM,
    OccasionVM,
    SeasonVM,
    ai_create_button,
    ai_title,
    another_ai_question,
    approve_ready_question,
    approved_seasons,
    archived_here_toast,
    archived_toast,
    build_season,
    deleted_toast,
    month_spend_line,
    name_count,
    occasion_choices,
    occasions_from_calendar,
    order_seasons,
    other_occasion,
    photos_line,
    price_changed,
    restored_toast,
    review_text,
    total_line,
    upcoming_occasions,
    usd_label,
    without_piece,
)
from .seasonal_vm import approved_count as count_approved
from .seasonal_vm import pending_count as count_pending
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_PRICE_CHANGED = "__price_changed__"
_PHOTOS_CHANGED = "__photos_changed__"

_TOAST_MS = 6000
#: How often a batch being prepared is re-read («3 de 10 listos»).
POLL_SECONDS = 5.0
#: A poll gives up after this many rounds (≈ 10 min) — the owner can reload.
POLL_ROUNDS = 120
FLOW_STEPS = 3


def _worded(exc: BaseException, what: str, fallback: str = ACTION_FAILED) -> str:
    """The service's own Spanish `message` for its refusals (`SeasonalError`: nothing to
    make, wrong state…), else the generic line — never the exception's text otherwise."""
    from qualify_api.whatsapp.seasonal import SeasonalError  # noqa: PLC0415

    if isinstance(exc, SeasonalError):
        return exc.message
    logger.error("seasonal %s failed: %s", what, type(exc).__name__)
    return fallback


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


class SeasonalState(rx.State):
    seasons: list[SeasonVM] = []
    loaded: bool = False
    loading: bool = False
    error: str = ""
    action_error: str = ""
    #: Pieces with an «Aprobar» / «Pedir otro» in flight.
    busy_ids: list[str] = []
    current_key: str = ""

    # -- the flow -------------------------------------------------------------------------
    flow_open: bool = False
    flow_step: int = 1
    occasions: list[OccasionVM] = []
    occasion_key: str = ""
    other_name: str = ""
    mode: str = MODE_FREE
    #: «US$0,05» from the pricing table via the service; "" → no IA option.
    ai_cost: str = ""
    #: m-24976893 «Crear con IA»: the quote's total, why it is off, the photos it animates
    ai_total: str = ""
    ai_videos: int = 0
    ai_unavailable: str = ""
    #: «Con IA» is off by configuration: the card is not drawn at all (UX review); it
    #: shows disabled only for `NoPhotoToAnimate`, with its reason.
    ai_hidden: bool = False
    ai_quoting: bool = False
    ai_photos: list[AiPhotoVM] = []
    #: «Este mes llevas US$Z en videos con IA.» ("" when nothing was spent)
    month_spend: str = ""
    _ai_per_usd: str = ""
    _ai_total_usd: str = ""
    #: The quoted photos' draft ids — exactly what `plan_batch` must get back.
    _ai_draft_ids: list[str] = []
    _quote_gen: int = 0
    #: «Pedir otro» on an IA video: ONE video's price (`ai_video_price_usd`), apart from
    #: the batch quote; "" while «Con IA» is off (then it is not offered on IA pieces).
    ai_redo_cost: str = ""
    _ai_redo_usd: str = ""
    creating: bool = False
    flow_error: str = ""
    #: `NothingToMake`: the flow shows «Subir mi logo» and «Ir a Por aprobar».
    flow_missing: bool = False

    # -- confirmations ----------------------------------------------------------------------
    confirm_season: str = ""  # «Aprobar los listos» of this season
    confirm_another: str = ""  # «Pedir otro» of a piece made with IA
    confirm_count: int = 0
    _confirm_ids: list[str] = []
    #: Stickers the owner tapped to see (with `prefers-reduced-motion` nothing moves first).
    shown_ids: list[str] = []
    #: «Aprobados»' type filter: all · sticker · video (`&tipo=`).
    kind_filter: str = KIND_ALL

    #: (stickers, videos) of the standard batch per mode, from the backend.
    batch_counts: dict[str, list[int]] = {}
    #: Step 1's dated seasons from the backend; None-equivalent [] + `_calendar_ok` False
    #: means the read failed and the client list is the fallback.
    calendar: list[OccasionVM] = []
    _calendar_ok: bool = False
    _today: str = ""
    _gen: int = 0
    _poll_gen: int = 0
    _brand: str = ""
    _country: str = ""

    # -- computed ---------------------------------------------------------------------------

    @rx.var
    def library(self) -> list[SeasonVM]:
        # m-25017912: «De tus productos» shows up once one of them is approved
        return [
            s
            for s in order_seasons(self.seasons, self.current_key)
            if not s.archived and (s.key != PRODUCT_SEASON_KEY or s.approved_pieces)
        ]

    @rx.var
    def archived(self) -> list[SeasonVM]:
        return [s for s in self.seasons if s.archived]

    @rx.var
    def to_review(self) -> list[SeasonVM]:
        """Por aprobar: the live seasons with something being prepared, ready or failed."""
        return [s for s in self.library if s.to_review]

    @rx.var
    def is_empty(self) -> bool:
        return self.loaded and not self.seasons

    # -- m-24986801: «Por aprobar» and «Aprobados» › Stickers y videos ----------------------

    @rx.var
    def pending_count(self) -> int:
        return count_pending(self.seasons)

    @rx.var
    def approved_count(self) -> int:
        return count_approved(self.seasons)

    @rx.var
    def pending_tab_label(self) -> str:
        """«Stickers y videos (5)» — the bare name until the number is known."""
        return tab_label("Stickers y videos", self.pending_count, known=self.loaded)

    @rx.var
    def approved_tab_label(self) -> str:
        return tab_label("Stickers y videos", self.approved_count, known=self.loaded)

    @rx.var
    def approved_library(self) -> list[SeasonVM]:
        """«Aprobados»: live seasons with their approved pieces of the chosen kind."""
        return approved_seasons(self.seasons, self.kind_filter, self.current_key)

    @rx.var
    def archived_title(self) -> str:
        return f"Archivadas ({len(self.archived)})"

    @rx.var
    def other_count(self) -> str:
        return name_count(self.other_name)

    @rx.var
    def flow_title(self) -> str:
        # with IA too: «Revisa y crea» (the photos are shown, not chosen, in the beta)
        return {1: STEP_OCCASION, 2: STEP_HOW}.get(self.flow_step, STEP_REVIEW)

    @rx.var
    def ai_ready(self) -> bool:
        """«Crear con IA» is offered only when the backend quoted it."""
        return self.ai_unavailable == "" and self._ai_total_usd != "" and not self.ai_quoting

    @rx.var
    def ai_photos_line(self) -> str:
        return photos_line(len(self.ai_photos))

    @rx.var
    def ai_total_line(self) -> str:
        return total_line(self.ai_total)

    @rx.var
    def chosen_label(self) -> str:
        if self.occasion_key == OTHER_KEY:
            return other_occasion(self.other_name, date.today().year)[1]
        return next((o.label for o in self.occasions if o.key == self.occasion_key), "")

    @rx.var
    def flow_can_next(self) -> bool:
        if self.flow_step == 1:
            return self.occasion_key != "" and self.chosen_label != ""
        if self.flow_step == 2:
            return self.mode == MODE_FREE or (self.mode == MODE_AI and self.ai_ready)
        return not self.creating

    @rx.var
    def ai_title(self) -> str:
        return ai_title(self.ai_cost)

    @rx.var
    def review_line(self) -> str:
        stickers, videos = (self.batch_counts.get(self.mode) or [0, 0])[:2]
        return review_text(self.chosen_label, self.mode, stickers, videos, self.ai_videos)

    @rx.var
    def create_label(self) -> str:
        return ai_create_button(self.ai_total, self.ai_videos) if self.mode == MODE_AI else "Crear"

    @rx.var
    def confirm_question(self) -> str:
        season = next((s for s in self.seasons if s.key == self.confirm_season), None)
        return approve_ready_question(self.confirm_count, season.label) if season else ""

    @rx.var
    def another_question(self) -> str:
        return another_ai_question(self.ai_redo_cost)

    # -- plumbing --------------------------------------------------------------------------

    async def _tenant(self) -> UUID | None:
        auth = await self.get_state(AuthState)
        return tenant_uuid(auth.session_tenant_id) if auth.session_tenant_id else None

    async def _read(self, tenant_id: UUID) -> tuple[Any, ...]:
        """(seasons, brand, country, ai cost, batch counts, calendar) — blocking calls off
        the loop. `calendar` is (occasions, today ISO), or None when the backend's read
        failed (then the client list is the fallback)."""
        gw = gateway()
        brand = await asyncio.to_thread(gw.brand, tenant_id)
        if brand is None:
            raise PermissionError
        country = await asyncio.to_thread(gw.country, tenant_id)
        rows = await asyncio.to_thread(gw.seasons, tenant_id, brand)
        reasons = gw.reason_texts()
        seasons: list[SeasonVM] = []
        for row in rows:
            items = await asyncio.to_thread(gw.season_items, tenant_id, brand, row.key)

            def src(item: Any) -> str:
                return gw.preview_src(tenant_id, brand, item)

            seasons.append(
                await asyncio.to_thread(
                    build_season, row.key, row.label, row.archived, items, src, reasons
                )
            )
        try:
            spent = await asyncio.to_thread(gw.month_ai_total, tenant_id, brand)
        except Exception as exc:  # noqa: BLE001 — only the line is lost
            logger.warning("seasonal month spend failed: %s", type(exc).__name__)
            spent = None
        try:
            redo = await asyncio.to_thread(gw.ai_video_price, tenant_id, brand)
        except Exception as exc:  # noqa: BLE001 — not offered without a price
            logger.warning("seasonal ai price failed: %s", type(exc).__name__)
            redo = None
        cost = (month_spend_line(spent), redo)
        counts = {mode: list(gw.batch_counts(mode)) for mode in (MODE_FREE, MODE_AI)}
        calendar: tuple[list[OccasionVM], str] | None
        try:
            upcoming, today = await asyncio.to_thread(gw.calendar, tenant_id, 3)
            calendar = (occasions_from_calendar(upcoming, today), today.isoformat())
        except Exception as exc:  # noqa: BLE001 — the client list stands in (fallback)
            logger.warning("season calendar read failed: %s", type(exc).__name__)
            calendar = None
        return seasons, str(brand), country, cost, counts, calendar

    # -- load and poll --------------------------------------------------------------------

    @rx.event(background=True)
    async def load(self) -> AsyncIterator[Any]:
        """Tu marca's section or Por aprobar mounted."""
        async with self:
            self._gen += 1
            gen = self._gen
            self.loading = not self.loaded
            self.error = ""
            tenant_id = await self._tenant()
            try:
                path = str(self.router.url.path or "")
            except Exception:  # noqa: BLE001 — no router outside a page (tests)
                path = ""
        preparing = await self._refresh(tenant_id, gen, quiet=False)
        # m-24986801: Por aprobar / Aprobados may open on «Stickers y videos» when the
        # publications are empty — only there; Tu marca and WhatsApp never touch it
        if path.startswith(("/drafts", "/aprobados")):
            from .gallery_state import GalleryState  # noqa: PLC0415 — no import cycle

            yield GalleryState.stickers_read
        # the per-video price for «Pedir otro» on an IA video (once per mount, not per poll)
        yield SeasonalState.quote_ai
        if preparing:
            yield SeasonalState.poll

    async def _refresh(self, tenant_id: UUID | None, gen: int, *, quiet: bool) -> bool:
        """Read everything; True while a batch is still being prepared."""
        error, seasons, brand, country, cost, counts, read = "", [], "", "", "", {}, None
        try:
            if tenant_id is None:
                raise PermissionError
            seasons, brand, country, cost, counts, read = await self._read(tenant_id)
        except PermissionError:
            error = NO_SESSION
        except Exception as exc:  # noqa: BLE001 — worded, never shown
            logger.error("seasonal load failed: %s", type(exc).__name__)
            error = LOAD_FAILED
        async with self:
            if gen != self._gen:
                return False  # a newer load (or a logout) owns the screen now
            self.loading = False
            if error:
                if not quiet or not self.loaded:
                    self.error = error
                return False
            self.seasons, self._brand, self._country = seasons, brand, country
            self.month_spend, redo = cost
            self._ai_redo_usd = str(redo) if redo is not None else ""
            self.ai_redo_cost = usd_label(redo) if redo is not None else ""
            self.batch_counts = counts
            if read is not None:
                self.calendar, self._today, self._calendar_ok = read[0], read[1], True
            # a failed read keeps the last good backend calendar; the client list stands in
            # only when none was ever read (`_calendar_ok` stays False)
            dated = (
                self.calendar
                if self._calendar_ok
                else upcoming_occasions(date.today(), country, count=1)
            )
            self.current_key = dated[0].key if dated else ""
            self.loaded = True
            return any(s.preparing for s in seasons)

    @rx.event(background=True)
    async def poll(self) -> None:
        """Re-read while something is «Preparando…» (one poller at a time)."""
        async with self:
            self._poll_gen += 1
            mine = self._poll_gen
        for _ in range(POLL_ROUNDS):
            await asyncio.sleep(POLL_SECONDS)
            async with self:
                if mine != self._poll_gen:
                    return
                gen = self._gen
                tenant_id = await self._tenant()
            if not await self._refresh(tenant_id, gen, quiet=True):
                return

    @rx.event
    def stop_poll(self) -> None:
        self._poll_gen += 1

    @rx.event
    def set_kind_filter(self, value: str):
        """«Tipo» in «Aprobados» › Stickers y videos, written to the address."""
        from .nav_url import replace_url_script, with_query  # noqa: PLC0415

        self.kind_filter = value if value in (STICKER, VIDEO) else KIND_ALL
        tipo = "" if self.kind_filter == KIND_ALL else self.kind_filter
        return rx.call_script(
            replace_url_script(with_query("/aprobados", ver="stickers", **{KIND_PARAM: tipo}))
        )

    @rx.event
    def read_kind_filter(self) -> None:
        """`/aprobados` on_load: `?ver=stickers&tipo=sticker|video`."""
        try:
            params = self.router.url.query_parameters
        except Exception:  # noqa: BLE001 — no router outside a page (tests)
            params = {}
        value = str(params.get(KIND_PARAM, "") or "").strip().lower()
        self.kind_filter = value if value in (STICKER, VIDEO) else KIND_ALL

    # -- the flow ---------------------------------------------------------------------------

    @rx.event(background=True)
    async def quote_ai(self) -> None:
        """The IA batch's price and the photos it will animate — read when the flow
        opens, again after `CostNotConfirmed`; never a price written in the screen."""
        async with self:
            if self.ai_quoting:
                return
            self.ai_quoting = True
            self._quote_gen += 1
            gen, brand = self._quote_gen, _uuid(self._brand)
            tenant_id = await self._tenant()
        await self._quote(tenant_id, brand, gen)

    async def _quote(self, tenant_id: UUID | None, brand: UUID | None, gen: int) -> None:
        """One quote, for the business and the round that asked (`gen`): a result that
        lands after a business switch (or a newer quote) is dropped, never shown."""
        quote, photos, failed = None, [], False
        try:
            if tenant_id is None or brand is None:
                raise PermissionError
            gw = gateway()
            quote = await asyncio.to_thread(gw.ai_quote, tenant_id, brand)
            # the quote's OWN photos: what is shown is what gets animated
            photos = [AiPhotoVM(id=p.id, title=p.title, src=p.src) for p in quote.photos]
        except Exception as exc:  # noqa: BLE001 — the paid option stays off
            if not isinstance(exc, PermissionError):
                logger.warning("seasonal ai quote failed: %s", type(exc).__name__)
            failed = True
        async with self:
            if gen != self._quote_gen:
                return  # a newer quote owns the screen (and the flag)
            self.ai_quoting = False
            if str(brand) != self._brand:
                return  # the business changed meanwhile: its photos are not shown
            if failed or quote is None:
                self.ai_unavailable, self.ai_cost, self.ai_total = AI_UNAVAILABLE, "", ""
                self.ai_hidden = True
                self._ai_per_usd = self._ai_total_usd = ""
                return
            self.ai_unavailable = quote.unavailable
            self.ai_hidden = quote.mode_off
            self.ai_cost = usd_label(quote.per_video_usd)
            self.ai_total = usd_label(quote.total_usd)
            self.ai_videos = quote.videos
            self._ai_per_usd = str(quote.per_video_usd or "")
            self._ai_total_usd = str(quote.total_usd or "") if not quote.unavailable else ""
            self.ai_photos = photos
            self._ai_draft_ids = [p.id for p in photos]
            if self.mode == MODE_AI and not self.ai_ready:
                self.mode = MODE_FREE

    @rx.event
    def open_flow(self) -> Any:
        """«Crear para esta temporada»: step 1 with the next season already chosen and
        «Con lo que ya tienes» as the way (never IA by default)."""
        today = date.fromisoformat(self._today) if self._today else date.today()
        self.occasions = occasion_choices(
            today, self._country, self.calendar if self._calendar_ok else None
        )
        self.occasion_key = self.occasions[0].key if self.occasions else ""
        self.other_name = ""
        self.mode = MODE_FREE
        self.flow_step = 1
        self.flow_error = ""
        self.flow_missing = False
        self.creating = False
        self.flow_open = True
        return SeasonalState.quote_ai

    @rx.event
    def open_from_query(self) -> None:
        """`?crear=temporada` (Por aprobar's empty state): the flow opens by itself."""
        params = self.router.url.query_parameters
        if params.get("crear") == "temporada" and not self.flow_open:
            self.open_flow()
            # «Crear para Navidad» from «Tu semana»: that season chosen, straight to step 2
            wanted = params.get("temporada")
            if isinstance(wanted, str) and any(o.key == wanted for o in self.occasions):
                self.occasion_key = wanted
                self.flow_step = 2

    @rx.event
    def set_flow_open(self, is_open: bool) -> None:
        if not is_open and not self.creating:
            self.flow_open = False

    @rx.event
    def upload_logo(self) -> Any:
        """«Subir mi logo»: the flow closes and Tu marca opens its Logo section."""
        from .brand_kit_editor import BrandEditState  # noqa: PLC0415

        self.flow_open = False
        return BrandEditState.open_and_show("brandboard")

    @rx.event
    def choose_occasion(self, key: str) -> None:
        if isinstance(key, str) and any(o.key == key for o in self.occasions):
            self.occasion_key = key
            self.flow_error = ""

    @rx.event
    def set_other_name(self, value: str) -> None:
        self.other_name = value[:MAX_OTHER_NAME] if isinstance(value, str) else ""
        if self.other_name:
            self.occasion_key = OTHER_KEY
        self.flow_error = ""

    @rx.event
    def choose_mode(self, mode: str) -> None:
        """«Crear con IA» only with the backend's quote (and never by default)."""
        if mode == MODE_FREE or (mode == MODE_AI and self.ai_ready):
            self.mode = mode

    @rx.event
    def flow_next(self) -> None:
        if self.flow_step == 1 and self.occasion_key == OTHER_KEY and not self.chosen_label:
            self.flow_error = OTHER_NAME_MISSING
            return
        if self.flow_can_next and self.flow_step < FLOW_STEPS:
            self.flow_step += 1
            self.flow_error = ""

    @rx.event
    def flow_back(self) -> None:
        """«‹ Atrás» keeps everything chosen; on step 1 it closes."""
        if self.creating:
            return
        if self.flow_step <= 1:
            self.flow_open = False
            return
        self.flow_step -= 1
        self.flow_error = ""

    @rx.event(background=True)
    async def create(self) -> AsyncIterator[Any]:
        """«Crear» / «Crear el video · unos US$0,05»: `plan_batch`, then the batch goes to
        Por aprobar (nothing is approved, nothing is sent)."""
        async with self:
            if self.creating or self.flow_step != FLOW_STEPS or not self.flow_open:
                return
            if self.occasion_key == OTHER_KEY:
                key, label = other_occasion(self.other_name, date.today().year)
            else:
                key, label = self.occasion_key, self.chosen_label
            mode, brand = self.mode, _uuid(self._brand)
            # the TOTAL and the PHOTOS the owner saw on «¿Qué fotos animamos?» — that quote
            ai_total = self._ai_total_usd if mode == MODE_AI else ""
            accepted = Decimal(ai_total) if ai_total else None
            drafts = [UUID(d) for d in self._ai_draft_ids] if mode == MODE_AI else None
            if not key or not label or brand is None:
                self.flow_error = OTHER_NAME_MISSING if not label else NO_SESSION
                return
            self.creating = True
            self.flow_error = ""
            self.flow_missing = False
            tenant_id = await self._tenant()
        error, missing = "", False
        try:
            if tenant_id is None:
                raise PermissionError
            gw = gateway()
            user = await asyncio.to_thread(gw.acting_user, tenant_id)
            await asyncio.to_thread(
                gw.plan, tenant_id, brand, key, label, mode, user, accepted, drafts
            )
        except PermissionError:
            error = NO_SESSION
        except Exception as exc:  # noqa: BLE001
            # the price guard (ADR 41) says it in its own type; the service in its words
            limited = "Limit" in type(exc).__name__ or "Budget" in type(exc).__name__
            missing = type(exc).__name__ == "NothingToMake"
            if missing:
                error = MISSING_MATERIAL
            elif type(exc).__name__ == "SelectionChanged":  # a CostNotConfirmed: first
                error = _PHOTOS_CHANGED  # re-quoted below, the new photos shown
            elif type(exc).__name__ == "CostNotConfirmed":
                error = _PRICE_CHANGED  # re-quoted below, then said with the new total
            elif type(exc).__name__ in ("ModeNotAvailable", "NoPhotoToAnimate"):
                error = getattr(exc, "message", "") or AI_UNAVAILABLE
            elif limited and mode == MODE_AI:
                error = AI_LIMIT
            else:
                error = _worded(exc, "plan", CREATE_FAILED)
        if error in (_PRICE_CHANGED, _PHOTOS_CHANGED):
            changed = error
            async with self:  # the same flag and round as `quote_ai`: never two at once
                self.ai_quoting = True
                self._quote_gen += 1
                quote_gen = self._quote_gen
            await self._quote(tenant_id, brand, quote_gen)
            async with self:
                if not self.ai_ready:
                    error = self.ai_unavailable
                elif changed == _PHOTOS_CHANGED:
                    error = PHOTOS_CHANGED
                else:
                    error = price_changed(self.ai_total)
        async with self:
            self.creating = False
            if error:
                self.flow_error = error
                self.flow_missing = missing
                return
            self.flow_open = False
        yield rx.toast.success(STARTED_TOAST, duration=_TOAST_MS)
        yield SeasonalState.load

    # -- Por aprobar ------------------------------------------------------------------------

    @rx.event
    def show(self, media_id: str) -> None:
        if isinstance(media_id, str) and media_id not in self.shown_ids:
            self.shown_ids = [*self.shown_ids, media_id]

    def _find(self, media_id: str) -> Any:
        for season in self.seasons:
            for item in season.pieces:
                if item.id == media_id:
                    return item
        return None

    @rx.event(background=True)
    async def approve(self, media_id: str) -> AsyncIterator[Any]:
        async for event in self._approve([media_id]):
            yield event

    @rx.event
    def ask_approve_ready(self, season_key: str) -> None:
        """The question names exactly the pieces ready NOW; a refresh meanwhile cannot add
        one the owner never saw."""
        season = next((s for s in self.seasons if s.key == season_key and s.ready_count), None)
        if season is not None:
            self.confirm_season = season_key
            self._confirm_ids = list(season.ready_ids)
            self.confirm_count = len(season.ready_ids)

    @rx.event
    def cancel_confirm(self) -> None:
        self.confirm_season = ""
        self.confirm_another = ""
        self._confirm_ids = []

    @rx.event(background=True)
    async def approve_ready(self) -> AsyncIterator[Any]:
        """The confirmation's «Aprobar»: exactly the pieces that were ready when asked."""
        async with self:
            ids, self._confirm_ids = list(self._confirm_ids), []
            self.confirm_season = ""
        async for event in self._approve(ids):
            yield event

    async def _approve(self, ids: list[str]) -> AsyncIterator[Any]:
        async with self:
            wanted = [i for i in ids if (item := self._find(i)) is not None and item.ready]
            wanted = [i for i in wanted if i not in self.busy_ids]
            brand = _uuid(self._brand)
            if not wanted or brand is None:
                return
            self.busy_ids = [*self.busy_ids, *wanted]
            self.action_error = ""
            gen = self._gen
            tenant_id = await self._tenant()
        error = ""
        try:
            if tenant_id is None:
                raise PermissionError
            gw = gateway()
            user = await asyncio.to_thread(gw.acting_user, tenant_id)
            await asyncio.to_thread(gw.approve, tenant_id, brand, [UUID(i) for i in wanted], user)
        except PermissionError:
            error = NO_SESSION
        except Exception as exc:  # noqa: BLE001
            error = _worded(exc, "approve")
        async with self:
            self.busy_ids = [i for i in self.busy_ids if i not in wanted]
            if error:
                self.action_error = error
                return
        if not error:
            # m-24986801: it leaves Por aprobar — the toast says where it went
            yield rx.toast.success(
                APPROVED_TOAST,
                duration=_TOAST_MS,
                action={
                    "label": APPROVED_TOAST_ACTION,
                    "on_click": rx.redirect(APPROVED_STICKERS_HREF),
                },
            )
        await self._refresh(tenant_id, gen, quiet=True)

    @rx.event(background=True)
    async def another(self, media_id: str) -> AsyncIterator[Any]:
        """«Pedir otro»: a piece made with IA asks first (it costs)."""
        async with self:
            item = self._find(media_id) if isinstance(media_id, str) else None
            if item is None or media_id in self.busy_ids:
                return
            if item.paid and not self._ai_redo_usd:
                return  # «Con IA» is off: «Pedir otro» is not offered on an IA piece
            if item.paid and self.confirm_another != media_id:
                self.confirm_another = media_id
                return
            self.confirm_another = ""
            # checked and marked in the SAME locked block: a second tap finds it busy
            self.busy_ids = [*self.busy_ids, media_id]
            self.action_error = ""
            gen, brand = self._gen, _uuid(self._brand)
            # the price the dialog showed (`ai_video_price_usd`), not the batch quote
            accepted = Decimal(self._ai_redo_usd) if item.paid else None
            tenant_id = await self._tenant()
        async for event in self._another(media_id, tenant_id, gen, brand, accepted):
            yield event

    async def _another(
        self,
        media_id: str,
        tenant_id: UUID | None,
        gen: int,
        brand: UUID | None,
        accepted: Decimal | None = None,
    ) -> AsyncIterator[Any]:
        error = ""
        try:
            if tenant_id is None:
                raise PermissionError
            gw = gateway()
            if brand is None:
                raise PermissionError
            user = await asyncio.to_thread(gw.acting_user, tenant_id)
            await asyncio.to_thread(gw.another, tenant_id, brand, UUID(media_id), user, accepted)
        except PermissionError:
            error = NO_SESSION
        except Exception as exc:  # noqa: BLE001
            error = _worded(exc, "another")
        async with self:
            self.busy_ids = [i for i in self.busy_ids if i != media_id]
            if error:
                self.action_error = error
                return
        if await self._refresh(tenant_id, gen, quiet=True):
            yield SeasonalState.poll

    @rx.event(background=True)
    async def delete(self, media_id: str) -> AsyncIterator[Any]:
        """«Eliminar» (m-25016851), after the card's question: the piece leaves Por aprobar,
        Aprobados and the chat; its files are deleted. A second tap finds it busy."""
        async with self:
            item = self._find(media_id) if isinstance(media_id, str) else None
            brand = _uuid(self._brand)
            if item is None or brand is None or media_id in self.busy_ids:
                return
            is_video = item.is_video
            self.busy_ids = [*self.busy_ids, media_id]
            self.confirm_another = "" if self.confirm_another == media_id else self.confirm_another
            self.action_error = ""
            gen = self._gen
            tenant_id = await self._tenant()
        error = ""
        try:
            if tenant_id is None:
                raise PermissionError
            gw = gateway()
            user = await asyncio.to_thread(gw.acting_user, tenant_id)
            await asyncio.to_thread(gw.delete, tenant_id, brand, UUID(media_id), user)
        except PermissionError:
            error = NO_SESSION
        except Exception as exc:  # noqa: BLE001
            error = _worded(exc, "delete", DELETE_FAILED)
        async with self:
            self.busy_ids = [i for i in self.busy_ids if i != media_id]
            if error:
                self.action_error = error
        if error:
            # the card may sit far below the callout on a phone: say it where they look
            yield rx.toast.error(error, duration=_TOAST_MS)
            return
        async with self:
            # it leaves the screen now; the re-read below confirms it
            self.seasons = [without_piece(s, media_id) for s in self.seasons]
        yield rx.toast.success(deleted_toast(is_video), duration=_TOAST_MS)
        await self._refresh(tenant_id, gen, quiet=True)

    # -- library ------------------------------------------------------------------------------

    @rx.event(background=True)
    async def archive(self, season_key: str) -> AsyncIterator[Any]:
        async for event in self._set_archived(season_key, archived=True):
            yield event

    @rx.event(background=True)
    async def archive_from_approved(self, season_key: str) -> AsyncIterator[Any]:
        """«Archivar» in «Aprobados»: the toast says it is folded below (with «Deshacer»)."""
        async for event in self._set_archived(season_key, archived=True, here=True):
            yield event

    @rx.event(background=True)
    async def restore(self, season_key: str) -> AsyncIterator[Any]:
        async for event in self._set_archived(season_key, archived=False):
            yield event

    async def _set_archived(
        self, season_key: str, *, archived: bool, here: bool = False
    ) -> AsyncIterator[Any]:
        async with self:
            season = next((s for s in self.seasons if s.key == season_key), None)
            brand = _uuid(self._brand)
            if season is None or brand is None or season.archived == archived:
                return
            if archived and season_key == PRODUCT_SEASON_KEY:
                return  # m-25017912: the product stickers are for every day, never archived
            label, gen = season.label, self._gen
            self.action_error = ""
            tenant_id = await self._tenant()
        error = ""
        try:
            if tenant_id is None:
                raise PermissionError
            gw = gateway()
            call = gw.archive if archived else gw.restore
            await asyncio.to_thread(call, tenant_id, brand, season_key)
        except PermissionError:
            error = NO_SESSION
        except Exception as exc:  # noqa: BLE001
            logger.error("seasonal archive failed: %s", type(exc).__name__)
            error = ACTION_FAILED
        async with self:
            if error:
                self.action_error = error
                return
            self.seasons = [
                s if s.key != season_key else dataclasses.replace(s, archived=archived)
                for s in self.seasons
            ]
        if archived:
            yield rx.toast.success(
                archived_here_toast(label) if here else archived_toast(label),
                duration=_TOAST_MS,
                action={"label": UNDO_LABEL, "on_click": SeasonalState.restore(season_key)},
            )
        else:
            yield rx.toast.success(restored_toast(label), duration=_TOAST_MS)
        await self._refresh(tenant_id, gen, quiet=True)
