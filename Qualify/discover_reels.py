"""«Descubrir reels» in /create (§ request 2026-10-15): the most viewed reels of the
brand's referentes — only the ones of its own product — in three tabs, «Esta semana»,
«Este mes» and «90 días». The pipeline is `reels_discovery`; this module is its state and
its view.

Reading is scraping (a paid vendor read per referente plus a model check), so it shows a
spinner beside the sentence that says so (`docs/design-system.md` §5.4), and the result
is remembered per brand (`reels_discovery.cached_discover`) — «Actualizar» reads again.

§ m-24820844 (2026-10-20): the week and the month come from ONE month read; the 90 days
are a deeper read of their own, made only after the tab shows what it costs, and then
remembered too. The platform and referente filters only cut the cards already read: no
vendor call, no model call.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import reflex as rx
from qualify_api.referentes import reels_ai

from . import reels_discovery
from .auth_state import AuthState
from .creative_provider import default_brand_id
from .r2_media import BACKEND_BASE
from .tenant import tenant_uuid
from .ui import callout, card, empty_state, loading_spinner
from .ui import tokens as T

logger = logging.getLogger(__name__)


def _failure_hint(exc: BaseException) -> str:
    """A few words on why a whole read failed, for the error callout (Spanish)."""
    if isinstance(exc, LookupError):
        return "no encontramos la marca de esta sesión"
    name = type(exc).__name__
    if "OperationalError" in name or "Connection" in name:
        return "no pudimos conectar con la base de datos o el proveedor"
    if "ScrapeCreators" in name:
        return "el proveedor de reels falló"
    return f"error inesperado: {name}"


WINDOWS = (("week", "Esta semana"), ("month", "Este mes"), ("quarter", "90 días"))
#: The filters' «everything» value (a Radix select item cannot be "").
ALL = "all"
NETWORK_FILTERS = ((ALL, "Todas"), *reels_discovery.NETWORK_LABELS.items())


#: What the 90-day tab says before reading (§ founder 2026-10-20: a plain «cargo extra»,
#: no credits or dollars on screen).
QUARTER_NOTE = (
    "Ver los reels de los últimos 90 días tiene un cargo extra. Una vez leídos quedan "
    "guardados 6 horas: volver a esta pestaña no se cobra de nuevo."
)
QUARTER_REFRESH_TITLE = "Vuelve a leer los 90 días (tiene un cargo extra)"


#: Which read a window shows: the week and the month come from the month read.
READ_OF_WINDOW = {"week": "month", "month": "month", "quarter": "quarter"}


class DiscoverReelsState(rx.State):
    """What the «Descubrir reels» view shows. Cards are `reels_discovery.reel_card`.

    Every card of a read stays on the backend (`_cards`, by window, and `_reads`, what
    each read said besides its cards — keyed `"month"` / `"quarter"`): the browser only
    receives `reels`, the window's cut through the filters, at most `SHOWN_PER_WINDOW`
    — a read can hold some 70 checked cards per window, transcripts included. The 90-day
    read is loaded only on demand (`load_quarter`)."""

    window: str = "week"
    #: The filters (`ALL` or a network / an `account_key`): they cut the read's cards.
    network: str = ALL
    account: str = ALL
    #: The accounts read (`reels_discovery.account_option`), in influence order.
    accounts: list[dict[str, str]] = []
    #: Referentes the last month read had — 0 says «Aún no tienes referentes».
    referentes: int = 0
    #: A read in progress, and why a whole read failed (before it gave any result).
    loading: bool = False
    quarter_loading: bool = False
    error: str = ""
    quarter_error: str = ""
    #: The reel playing inside its own card (its `key`), "" when none — one at a time,
    #: so starting another stops the previous (its iframe unmounts).
    playing_key: str = ""

    #: window → every card the check kept (backend only).
    _cards: dict[str, list[dict[str, str]]] = {}
    #: read → `check`, `check_detail`, `fetched_iso` (`rx.moment` ages it client-side, no
    #: round trip just to move «hace 3 minutos») and `failed` (handles, comma-joined).
    _reads: dict[str, dict[str, str]] = {}

    def _read(self) -> dict[str, str]:
        return self._reads.get(READ_OF_WINDOW.get(self.window, "month"), {})

    def _window_cards(self) -> list[dict[str, str]]:
        """The window's cards — only the ones the check called the brand's PRODUCT or
        category: a card from an older read (another rule, or kept while a new read loads
        or fails) never shows a reel of another product."""
        cards = self._cards.get(self.window, [])
        return [c for c in cards if c.get("affinity") in reels_ai.FITS]

    @rx.var
    def reels(self) -> list[dict[str, str]]:
        """The window's cards through the filters, the most viewed `SHOWN_PER_WINDOW`."""
        shown = [
            c
            for c in self._window_cards()
            if self.network in (ALL, c.get("network")) and self.account in (ALL, c.get("account"))
        ]
        return shown[: reels_discovery.SHOWN_PER_WINDOW]

    @rx.var
    def filtered_out(self) -> bool:
        """The window has reels, but none passes the filters."""
        return bool(self._window_cards()) and not self.reels

    @rx.var
    def loaded(self) -> bool:
        """Whether the month read finished once this session (an empty one counts)."""
        return "month" in self._reads

    @rx.var
    def quarter_loaded(self) -> bool:
        return "quarter" in self._reads

    @rx.var
    def filtering(self) -> bool:
        return self.network != ALL or self.account != ALL

    @rx.var
    def networks(self) -> list[str]:
        """The networks of the accounts read — the platform filter shows only with two."""
        return list(dict.fromkeys(a["network"] for a in self.accounts))

    @rx.var
    def network_options(self) -> list[list[str]]:
        present = set(self.networks)
        return [[v, label] for v, label in NETWORK_FILTERS if v == ALL or v in present]

    @rx.var
    def account_options(self) -> list[list[str]]:
        """`[key, label]` of the referente filter, of the chosen network only."""
        multi = len(self.networks) > 1
        return [
            [a["key"], f"{a['handle']} · {reels_discovery.NETWORK_LABELS[a['network']]}"]
            if multi and self.network == ALL
            else [a["key"], a["handle"]]
            for a in self.accounts
            if self.network in (ALL, a["network"])
        ]

    @rx.var
    def shown_check(self) -> str:
        """Why the window's read could not check its reels (`reels_discovery.CHECK_*`)."""
        return self._read().get("check", "")

    @rx.var
    def unchecked_note(self) -> str:
        """The «inténtalo más tarde» body, with the reason the check failed when known."""
        base = (
            "El servicio que comprueba que cada reel sea de tu producto o tu categoría no respondió"
        )
        detail = self._read().get("check_detail", "")
        if detail:
            return f"{base}: {detail}. Inténtalo más tarde."
        return f"{base}. Inténtalo más tarde."

    @rx.var
    def shown_iso(self) -> str:
        """When the read on screen was made — the toolbar says only that, «Actualizado
        hace 2 minutos» (§ founder 2026-10-20: no counts). "" until that read exists."""
        return self._read().get("fetched_iso", "")

    @rx.var
    def failed_note(self) -> str:
        failed = self._read().get("failed", "")
        if not failed:
            return ""
        return f"No pudimos leer {failed} (privada, sin reels o no existe)."

    @rx.var
    def shown_error(self) -> str:
        return self.quarter_error if self.window == "quarter" else self.error

    @rx.event
    def set_window(self, value: str | list[str]) -> None:
        if isinstance(value, str) and value in dict(WINDOWS):
            self.window = value

    @rx.event
    def set_network(self, value: str | list[str]) -> None:
        """Pick a platform; a referente of another one is let go. No read."""
        if not isinstance(value, str) or value not in dict(NETWORK_FILTERS):
            return
        self.network = value
        if value != ALL and not self.account.startswith(f"{value}:"):
            self.account = ALL

    @rx.event
    def set_account(self, value: str) -> None:
        """Pick a referente (or `ALL`). No read."""
        if value == ALL or any(a["key"] == value for a in self.accounts):
            self.account = value

    @rx.event
    def clear_filters(self) -> None:
        self.network = ALL
        self.account = ALL

    def _keep_valid_filters(self) -> None:
        """After a read: a filter on a network or a referente the brand no longer has
        would hide every card behind a control that is not on screen any more."""
        if self.network != ALL and self.network not in {a["network"] for a in self.accounts}:
            self.network = ALL
        if self.account != ALL and not any(a["key"] == self.account for a in self.accounts):
            self.account = ALL

    def _store(self, depth: str, found: reels_discovery.DiscoveredReels) -> None:
        """Keep the read `found` (`"month"` or `"quarter"`) on the backend, for its windows."""
        windows = ("quarter",) if depth == "quarter" else ("week", "month")
        self._cards = {**self._cards, **{w: getattr(found, w) for w in windows}}
        self._reads = {
            **self._reads,
            depth: {
                "check": found.check,
                "check_detail": found.check_detail,
                "fetched_iso": datetime.fromtimestamp(found.fetched_at, tz=UTC).isoformat(),
                "failed": ", ".join(found.failed),
            },
        }
        if depth == "month" or not self.accounts:
            self.accounts = found.accounts
            self._keep_valid_filters()
        if depth == "month":
            self.referentes = found.referentes

    @rx.event
    def play(self, key: str) -> None:
        """Play the reel `key` inside its card, in the network's own player."""
        self.playing_key = key

    @rx.event
    def stop(self) -> None:
        self.playing_key = ""

    #: Reels whose own MP4 would not play (its signed CDN URL died, ~24-33 h after the
    #: read): they play in the network's embed instead.
    failed_videos: list[str] = []

    @rx.event
    def video_failed(self, key: str) -> None:
        if key not in self.failed_videos:
            self.failed_videos = [*self.failed_videos, key]

    #: Cards whose «Detalles» is open (an accordion under the figures).
    expanded: list[str] = []

    @rx.event
    def toggle_details(self, key: str) -> None:
        if key in self.expanded:
            self.expanded = [k for k in self.expanded if k != key]
        else:
            self.expanded = [*self.expanded, key]

    #: The reel whose transcript is being fetched ("" = none), and the last failure.
    transcript_loading: str = ""
    transcript_error: str = ""

    def _card(self, key: str) -> dict[str, str] | None:
        cards = (c for window in self._cards.values() for c in window)
        return next((c for c in cards if c.get("key") == key), None)

    def _set_transcript(self, key: str, text: str) -> None:
        """Write the transcript into the card in every window — a reel can be in all."""
        state = "said" if text else "none"
        self._cards = {
            window: [
                {**c, "transcript": text, "transcript_state": state} if c.get("key") == key else c
                for c in cards
            ]
            for window, cards in self._cards.items()
        }

    @rx.event(background=True)
    async def load_transcript(self, key: str) -> None:
        """«Ver transcripción» (§ request 2026-10-15): fetch ONE reel's transcript on
        demand — Instagram 1 credit, TikTok free — instead of paying for every reel."""
        async with self:
            card = self._card(key)
            if card is None or self.transcript_loading:
                return
            self.transcript_loading = key
            self.transcript_error = ""
        try:
            text = await asyncio.to_thread(reels_discovery.transcript_for_card, card)
        except Exception as exc:  # noqa: BLE001 — the card says it; the log keeps why
            logger.warning("transcript of %s failed: %s: %s", key, type(exc).__name__, exc)
            async with self:
                self.transcript_loading = ""
                self.transcript_error = key
            return
        async with self:
            self._set_transcript(key, text)
            self.transcript_loading = ""

    @rx.event(background=True)
    async def load_quarter(self, refresh: bool = False) -> None:
        """Read the 90 days (§ m-24820844) — only when asked, after the tab said it has
        an extra charge — or take the remembered read. A second call while one runs is
        dropped."""
        async with self:
            if self.quarter_loading:
                return
            self.quarter_loading = True
            self.quarter_error = ""
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        try:
            tenant_id = tenant_uuid(session_tenant_id) if session_tenant_id else None
            brand_id = await asyncio.to_thread(default_brand_id, tenant_id) if tenant_id else None
            if tenant_id is None or brand_id is None:
                raise LookupError("no brand in this session")
            found = await asyncio.to_thread(
                reels_discovery.cached_discover,
                tenant_id,
                brand_id,
                refresh=bool(refresh),
                days=reels_discovery.QUARTER_DAYS,
            )
        except Exception as exc:  # noqa: BLE001 — the view says it, the log keeps why
            logger.warning("90-day reel read failed: %s: %s", type(exc).__name__, exc, exc_info=exc)
            async with self:
                self.quarter_loading = False
                self.quarter_error = (
                    "No pudimos leer los 90 días de tus referentes "
                    f"({_failure_hint(exc)}). Inténtalo de nuevo en unos minutos."
                )
            return
        async with self:
            self._store("quarter", found)
            self.quarter_loading = False

    @rx.event(background=True)
    async def load(self, refresh: bool = False) -> None:
        """Read the reels (or take the remembered read). A second call while one runs is
        dropped."""
        async with self:
            if self.loading:
                return
            self.loading = True
            self.error = ""
            auth = await self.get_state(AuthState)
            # the logged-in tenant only: a pre-login Brand Kit draft never opens /create
            session_tenant_id = auth.session_tenant_id
        try:
            tenant_id = tenant_uuid(session_tenant_id) if session_tenant_id else None
            brand_id = await asyncio.to_thread(default_brand_id, tenant_id) if tenant_id else None
            if tenant_id is None or brand_id is None:
                raise LookupError("no brand in this session")
            found = await asyncio.to_thread(
                reels_discovery.cached_discover, tenant_id, brand_id, refresh=bool(refresh)
            )
            # a 90-day read already paid for shows at once on its tab — never a new read
            deep = reels_discovery.remembered(
                tenant_id, brand_id, days=reels_discovery.QUARTER_DAYS
            )
        except Exception as exc:  # noqa: BLE001 — the view says it, the log keeps why
            logger.warning("reel discovery failed: %s: %s", type(exc).__name__, exc, exc_info=exc)
            async with self:
                self.loading = False
                self.error = (
                    "No pudimos leer los reels de tus referentes "
                    f"({_failure_hint(exc)}). Inténtalo de nuevo en unos minutos."
                )
            return
        async with self:
            self._store("month", found)
            if deep is not None and not self.quarter_loading:
                self._store("quarter", deep)
            self.loading = False


# --------------------------------------------------------------------------------------
# view
# --------------------------------------------------------------------------------------


class _ReelVideo(rx.el.Video):
    """The reel's own MP4. Reflex's `video` element declares no `error` trigger; this
    one does, so a signed CDN URL that already died hands the card over to the
    network's embed (`DiscoverReelsState.video_failed`)."""

    on_error: rx.EventHandler[rx.event.no_args_event_spec]


def _detail(label: str, value: rx.Var[str]) -> rx.Component:
    return rx.fragment(
        rx.text(label, size="1", color=T.TEXT_MUTED),
        rx.text(value, size="1", weight="medium"),
    )


def _reel_media(reel: rx.Var[dict[str, str]]) -> rx.Component:
    """The card's picture, and its player (§ request 2026-10-15): the cover with the
    lift, the network and the length over it; a click plays JUST the video in its place
    — the reel's own MP4, streamed from the network's CDN, no page around it — or, when
    the reel has no MP4 or its signed URL already died, the network's own embed."""
    key = reel["key"]
    cover = rx.box(
        rx.cond(
            reel["cover"] != "",
            rx.image(
                src=BACKEND_BASE + reel["cover"],
                alt="",
                loading="lazy",
                class_name="q-dr-cover-img",
            ),
            rx.center(rx.icon("film", size=28, color=T.TEXT_FAINT), class_name="q-dr-cover-img"),
        ),
        rx.cond(
            reel["lift"] != "",
            rx.box(
                rx.text(reel["lift"], size="1", weight="bold"),
                class_name=rx.cond(
                    reel["lift_tone"] == "ok", "q-dr-lift q-dr-lift--ok", "q-dr-lift"
                ),
            ),
        ),
        rx.box(
            rx.text(reel["network_label"], size="1", weight="medium"),
            class_name="q-cr-mark",
            top="0.45rem",
            right="0.45rem",
            padding="0.1rem 0.45rem",
        ),
        rx.cond(
            reel["seconds"] != "",
            rx.box(
                rx.text(reel["seconds"], size="1", weight="medium"),
                class_name="q-cr-mark",
                bottom="0.45rem",
                right="0.45rem",
                padding="0.1rem 0.45rem",
            ),
        ),
        rx.center(rx.icon("play", size=22), class_name="q-dr-play", aria_hidden="true"),
        class_name="q-dr-cover",
    )
    embed_only = DiscoverReelsState.failed_videos.contains(key) | (reel["video"] == "")
    player = rx.box(
        rx.cond(
            embed_only,
            rx.el.iframe(
                src=reel["embed"],
                title="Reproductor del reel",
                allow="autoplay; fullscreen; encrypted-media; picture-in-picture",
                allow_full_screen=True,
                class_name="q-dr-embed",
            ),
            _ReelVideo.create(
                src=reel["video"],
                auto_play=True,
                controls=True,
                loop=True,
                plays_inline=True,
                preload="auto",
                class_name="q-dr-video",
                on_error=DiscoverReelsState.video_failed(key),
            ),
        ),
        rx.icon_button(
            rx.icon("x", size=14),
            size="1",
            variant="solid",
            color_scheme="gray",
            high_contrast=True,
            radius="full",
            aria_label="Cerrar video",
            title="Cerrar video",
            on_click=DiscoverReelsState.stop,
            class_name="q-dr-close",
        ),
        class_name=rx.cond(embed_only, "q-dr-cover q-dr-cover--embed", "q-dr-cover"),
    )
    return rx.cond(
        DiscoverReelsState.playing_key == key,
        player,
        rx.el.button(
            cover,
            type="button",
            on_click=DiscoverReelsState.play(key),
            class_name="q-dr-cover-button",
            aria_label="Ver el reel aquí",
        ),
    )


def _transcript_block(reel: rx.Var[dict[str, str]]) -> rx.Component:
    """The transcript, fetched on demand only (§ 2026-10-15): a button until someone
    asks, then the text — or «no tiene voz»."""
    loading = DiscoverReelsState.transcript_loading == reel["key"]
    ask = rx.vstack(
        rx.button(
            rx.cond(loading, loading_spinner("sm"), rx.icon("captions", size=13)),
            rx.cond(loading, "Transcribiendo…", "Ver transcripción"),
            size="1",
            variant="soft",
            on_click=DiscoverReelsState.load_transcript(reel["key"]),
            disabled=DiscoverReelsState.transcript_loading != "",
            title=rx.cond(
                reel["network"] == "instagram",
                "Usa 1 crédito de lectura (gratis si ya se transcribió)",
                "Gratis: son los subtítulos del propio video",
            ),
        ),
        rx.cond(
            DiscoverReelsState.transcript_error == reel["key"],
            rx.text("No pudimos transcribirlo; inténtalo de nuevo.", size="1", color=T.TEXT_MUTED),
        ),
        spacing="1",
        align_items="start",
    )
    return rx.cond(
        reel["transcript"] != "",
        rx.vstack(
            rx.hstack(
                rx.icon("captions", size=13, color=T.TEXT_MUTED),
                rx.text("Lo que se dice", size="1", weight="medium"),
                spacing="1",
                align="center",
            ),
            rx.text(reel["transcript"], size="1", color=T.TEXT_MUTED, class_name="q-dr-transcript"),
            spacing="1",
            align_items="start",
            width="100%",
        ),
        rx.cond(
            reel["transcript_state"] == "none",
            rx.text("Este video no tiene voz.", size="1", color=T.TEXT_MUTED),
            ask,
        ),
    )


def _details_panel(reel: rx.Var[dict[str, str]]) -> rx.Component:
    """Everything else about the reel (§ request 2026-10-15): a «Detalles» bar that
    opens the card downwards — an accordion, by click, the same on a phone — with the
    other figures, the caption, the sound, why it is of the rubro and the transcript.
    Was a hover panel over the picture; the founder asked for something else."""
    figures = rx.box(
        _detail("Me gusta", reel["likes"]),
        _detail("Comentarios", reel["comments"]),
        rx.cond(reel["saves"] != "", _detail("Guardados", reel["saves"])),
        rx.cond(reel["seconds"] != "", _detail("Duración", reel["seconds"])),
        _detail("Publicado", reel["age"]),
        class_name="q-dr-figures",
    )
    panel = rx.vstack(
        figures,
        rx.cond(
            reel["caption"] != "",
            rx.text(reel["caption"], size="1", color=T.TEXT_MUTED, class_name="q-dr-caption"),
        ),
        rx.cond(
            reel["sound"] != "",
            rx.hstack(
                rx.icon("music", size=12, color=T.TEXT_FAINT, flex_shrink="0"),
                rx.text(reel["sound"], size="1", color=T.TEXT_MUTED, class_name="q-dr-ellipsis"),
                spacing="1",
                align="center",
                width="100%",
            ),
        ),
        rx.cond(
            reel["reason"] != "",
            rx.hstack(
                rx.icon("sparkles", size=12, color=T.TEXT_FAINT, flex_shrink="0"),
                rx.text(reel["reason"], size="1", color=T.TEXT_MUTED),
                spacing="1",
                align="start",
                width="100%",
            ),
        ),
        _transcript_block(reel),
        rx.link(
            rx.hstack(
                rx.icon("external-link", size=13),
                rx.text("Abrir en ", reel["network_label"], size="1"),
                spacing="1",
                align="center",
            ),
            href=reel["url"],
            is_external=True,
        ),
        spacing="2",
        width="100%",
        align_items="start",
        class_name="q-dr-more-panel",
    )
    open_ = DiscoverReelsState.expanded.contains(reel["key"])
    return rx.box(
        rx.el.button(
            rx.text(rx.cond(open_, "Menos", "Detalles"), size="1", weight="medium"),
            rx.icon(rx.cond(open_, "chevron-up", "chevron-down"), size=14),
            type="button",
            class_name="q-dr-more-bar",
            aria_expanded=rx.cond(open_, "true", "false"),
            on_click=DiscoverReelsState.toggle_details(reel["key"]),
        ),
        rx.cond(open_, panel),
        class_name="q-dr-more",
    )


def _reel_tile(reel: rx.Var[dict[str, str]]) -> rx.Component:
    """One reel as the «C» card (§ request 2026-10-15): the picture with how it does
    against its own account, who and how many views, what it is (format and hook), the
    rest folded into «Detalles», and «Replicar con mi marca»."""
    return card(
        rx.vstack(
            _reel_media(reel),
            rx.vstack(
                rx.hstack(
                    rx.text(reel["handle"], size="2", weight="bold", class_name="q-dr-ellipsis"),
                    rx.spacer(),
                    rx.text(reel["age"], size="1", color=T.TEXT_MUTED, white_space="nowrap"),
                    spacing="2",
                    align="center",
                    width="100%",
                ),
                # the three figures that rank a reel (§ 2026-10-15): «2.7M vistas ·
                # 92K/día · 15%» — views, views per day since it was published, and
                # interactions over views
                rx.hstack(
                    rx.text(reel["views"], " vistas", size="3", weight="medium"),
                    rx.cond(
                        reel["per_day"] != "",
                        rx.fragment(
                            rx.text("·", size="3", color=T.TEXT_FAINT),
                            rx.text(reel["per_day"], size="3", weight="medium"),
                        ),
                    ),
                    rx.cond(
                        reel["engagement"] != "",
                        rx.fragment(
                            rx.text("·", size="3", color=T.TEXT_FAINT),
                            rx.text(
                                reel["engagement"],
                                size="3",
                                weight="medium",
                                title="Interacciones sobre vistas",
                            ),
                        ),
                    ),
                    spacing="2",
                    align="center",
                    wrap="wrap",
                    class_name="q-dr-figures-line",
                ),
                # § 2026-10-20: the shown reels are the product OR its category again, so
                # the card says which (it had no pill while only the product was shown)
                rx.hstack(
                    rx.cond(
                        reel["affinity"] == "categoria",
                        rx.box(
                            rx.text("Tu categoría", size="1"),
                            class_name="q-dr-tag q-dr-tag--muted",
                            title="La misma clase de oferta que vendes, sin ser tu producto",
                        ),
                        rx.box(rx.text("Tu producto", size="1"), class_name="q-dr-tag"),
                    ),
                    rx.cond(
                        reel["format"] != "",
                        rx.box(
                            rx.text(reel["format"], size="1"),
                            class_name="q-dr-tag q-dr-tag--muted",
                        ),
                    ),
                    spacing="1",
                    wrap="wrap",
                ),
                spacing="1",
                width="100%",
                align_items="start",
            ),
            _details_panel(reel),
            rx.tooltip(
                rx.button(
                    rx.icon("copy", size=14),
                    "Replicar con mi marca",
                    size="2",
                    width="100%",
                    disabled=True,
                ),
                content="Muy pronto: crear tu versión de este reel con tu marca",
            ),
            spacing="2",
            width="100%",
            align_items="start",
        ),
        padding="0.6rem",
        width="100%",
        class_name="q-dr-card",
    )


def _toolbar() -> rx.Component:
    return rx.hstack(
        rx.segmented_control.root(
            *(rx.segmented_control.item(label, value=value) for value, label in WINDOWS),
            value=DiscoverReelsState.window,
            on_change=DiscoverReelsState.set_window,
            size="2",
            aria_label="Periodo",
        ),
        rx.cond(
            DiscoverReelsState.shown_iso != "",
            rx.text(
                "Actualizado ",
                # «hace 3 minutos», aged by the browser itself (react-moment re-renders
                # every minute); nothing reaches the server for it
                rx.moment(date=DiscoverReelsState.shown_iso, from_now=True, locale="es"),
                size="1",
                color=T.TEXT_MUTED,
            ),
        ),
        rx.spacer(),
        rx.cond(
            DiscoverReelsState.window == "quarter",
            # the 90 days refresh only once read, and say again that a new read is charged
            rx.cond(
                DiscoverReelsState.quarter_loaded,
                _refresh_button(
                    DiscoverReelsState.quarter_loading,
                    DiscoverReelsState.load_quarter(True),
                    QUARTER_REFRESH_TITLE,
                ),
            ),
            _refresh_button(
                DiscoverReelsState.loading,
                DiscoverReelsState.load(True),
                "Vuelve a leer el último mes de tus referentes",
            ),
        ),
        width="100%",
        align="center",
        spacing="3",
        flex_wrap="wrap",
    )


def _refresh_button(
    busy: rx.Var[bool], on_click: rx.EventSpec, title: str | rx.Var[str]
) -> rx.Component:
    return rx.button(
        rx.cond(busy, loading_spinner("sm"), rx.icon("refresh-cw", size=14)),
        "Actualizar",
        variant="soft",
        color_scheme="gray",
        size="2",
        on_click=on_click,
        disabled=busy,
        title=title,
    )


def _filters() -> rx.Component:
    """Platform and referente (§ m-24820844): they cut the cards already read — no
    vendor read, no model call. The platform shows only when the referentes are on two
    networks; nothing shows before the first read."""
    platform = rx.cond(
        DiscoverReelsState.networks.length() > 1,
        rx.segmented_control.root(
            rx.foreach(
                DiscoverReelsState.network_options,
                lambda option: rx.segmented_control.item(option[1], value=option[0]),
            ),
            value=DiscoverReelsState.network,
            on_change=DiscoverReelsState.set_network,
            size="1",
            aria_label="Plataforma",
        ),
    )
    referente = rx.select.root(
        rx.select.trigger(placeholder="Todos los referentes", aria_label="Referente"),
        rx.select.content(
            rx.select.item("Todos los referentes", value=ALL),
            rx.foreach(
                DiscoverReelsState.account_options,
                lambda option: rx.select.item(option[1], value=option[0]),
            ),
        ),
        value=DiscoverReelsState.account,
        on_change=DiscoverReelsState.set_account,
        size="1",
    )
    clear = rx.cond(
        DiscoverReelsState.filtering,
        rx.button(
            rx.icon("x", size=13),
            "Quitar filtros",
            variant="ghost",
            color_scheme="gray",
            size="1",
            on_click=DiscoverReelsState.clear_filters,
        ),
    )
    return rx.cond(
        DiscoverReelsState.accounts.length() > 0,
        rx.hstack(
            platform,
            referente,
            clear,
            spacing="2",
            align="center",
            flex_wrap="wrap",
            width="100%",
        ),
    )


def _notices() -> rx.Component:
    return rx.vstack(
        rx.cond(
            DiscoverReelsState.shown_error != "", callout(DiscoverReelsState.shown_error, "error")
        ),
        rx.cond(
            DiscoverReelsState.failed_note != "", callout(DiscoverReelsState.failed_note, "info")
        ),
        spacing="2",
        width="100%",
    )


def _waiting(text: str) -> rx.Component:
    """A read in progress, in the middle of the view (§ founder 2026-10-20: «céntrame el
    loader»): the spinner over the sentence that says what is happening, both centred in
    the card's free height, like `empty_state`."""
    return rx.center(
        rx.vstack(
            loading_spinner("md"),
            rx.text(text, size="2", color=T.TEXT_MUTED, text_align="center", max_width="440px"),
            spacing="3",
            align="center",
        ),
        padding=T.PAD_EMPTY,
        width="100%",
        flex="1",
    )


def _body() -> rx.Component:
    loading = _waiting(
        "Buscando los reels de tus referentes y comprobando que sean de tu producto…"
    )
    no_referentes = empty_state(
        "users",
        "Aún no tienes referentes",
        "Marca cuentas como referente en Tu marca (o agrégalas a mano) y aquí verás "
        "sus reels con más vistas.",
        rx.link(rx.button("Ir a Tu marca", variant="soft", size="3"), href="/brand/kit"),
    )
    window = DiscoverReelsState.window
    no_reels = empty_state(
        "film",
        rx.match(
            window,
            ("week", "Esta semana tus referentes no publicaron reels de tu producto"),
            ("month", "Este mes tus referentes no publicaron reels de tu producto"),
            "En 90 días tus referentes no publicaron reels de tu producto",
        ),
        rx.match(
            window,
            ("week", "Mira los del mes, o vuelve en unos días."),
            "Agrega más referentes en Tu marca para ver más reels.",
        ),
        # N8 (m-24842961): the button does what the sentence says.
        rx.cond(
            window == "week",
            rx.button(
                "Ver los del mes",
                on_click=DiscoverReelsState.set_window("month"),
                variant="soft",
                size="3",
            ),
            rx.link(rx.button("Ir a Tu marca", variant="soft", size="3"), href="/brand/kit"),
        ),
    )
    filtered_out = empty_state(
        "filter",
        "Ningún reel de tu producto con estos filtros",
        "Prueba con otro referente u otra plataforma, o mira otro periodo.",
        rx.button(
            rx.icon("x", size=14),
            "Quitar filtros",
            variant="soft",
            on_click=DiscoverReelsState.clear_filters,
        ),
    )
    # § m-24820844: the 90 days are a read of their own — the tab says it is charged
    # before anything is read, and reads only on the click
    quarter_ask = empty_state(
        "calendar-range",
        "Los reels de los últimos 90 días",
        QUARTER_NOTE,
        rx.button(
            rx.icon("download", size=14),
            "Leer",
            variant="soft",
            on_click=DiscoverReelsState.load_quarter(False),
            disabled=DiscoverReelsState.quarter_loading,
        ),
    )
    quarter_loading = _waiting(
        "Leyendo 90 días de reels de tus referentes y comprobando que sean de tu "
        "producto… es la lectura más larga, puede tardar un par de minutos."
    )
    # § founder 2026-10-16: without the product check NOTHING is shown — never a list of
    # unchecked reels where another product's promo can slip through
    retry_label = (rx.icon("refresh-cw", size=14), "Intentar de nuevo")
    retry = rx.cond(
        window == "quarter",
        rx.button(
            *retry_label,
            variant="soft",
            on_click=DiscoverReelsState.load_quarter(True),
            disabled=DiscoverReelsState.quarter_loading,
        ),
        rx.button(
            *retry_label,
            variant="soft",
            on_click=DiscoverReelsState.load(True),
            disabled=DiscoverReelsState.loading,
        ),
    )
    unchecked = rx.cond(
        DiscoverReelsState.shown_check == reels_discovery.CHECK_NO_BRIEF,
        empty_state(
            "search",
            "Aún no sabemos qué vende tu marca",
            "Ejecuta la búsqueda de referentes en Tu marca: con ella filtramos los "
            "reels para mostrarte solo los de tu producto.",
            rx.link(rx.button("Ir a Tu marca", variant="soft", size="3"), href="/brand/kit"),
        ),
        empty_state(
            "clock",
            "No pudimos filtrar los reels ahora mismo",
            DiscoverReelsState.unchecked_note,
            retry,
        ),
    )
    grid = rx.box(
        rx.foreach(DiscoverReelsState.reels, _reel_tile),
        class_name="q-dr-grid",
        role="list",
        aria_label="Reels de tus referentes",
    )
    # what a finished read shows, whichever window: its cards, or why there are none
    results = rx.cond(
        DiscoverReelsState.loaded & (DiscoverReelsState.referentes == 0),
        no_referentes,
        rx.cond(
            DiscoverReelsState.reels.length() > 0,
            grid,
            rx.cond(
                DiscoverReelsState.filtered_out,
                filtered_out,
                rx.cond(DiscoverReelsState.shown_check != "", unchecked, no_reels),
            ),
        ),
    )
    quarter = rx.cond(
        DiscoverReelsState.quarter_loading & (DiscoverReelsState.reels.length() == 0),
        quarter_loading,
        rx.cond(
            DiscoverReelsState.quarter_loaded,
            results,
            rx.cond(
                DiscoverReelsState.loaded & (DiscoverReelsState.referentes == 0),
                no_referentes,
                quarter_ask,
            ),
        ),
    )
    month_read = rx.cond(
        DiscoverReelsState.loading & (DiscoverReelsState.reels.length() == 0),
        loading,
        rx.cond(DiscoverReelsState.loaded, results, loading),
    )
    return rx.cond(window == "quarter", quarter, month_read)


def discover_view() -> rx.Component:
    """The centre of /create when «Descubrir reels» is chosen. Reads on mount (the
    remembered read when there is one)."""
    return card(
        rx.vstack(
            _toolbar(),
            _filters(),
            _notices(),
            _body(),
            spacing="4",
            width="100%",
            flex="1",
        ),
        padding="1.25rem",
        width="100%",
        flex="1",
        display="flex",
        on_mount=DiscoverReelsState.load(False),
    )
