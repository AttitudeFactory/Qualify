"""«Descubrir reels» in /create (§ request 2026-10-15): the most viewed reels of the
brand's referentes — only the ones of its own product — in two tabs, «Esta semana» and «Este
mes». The pipeline is `reels_discovery`; this module is its state and its view.

Reading is scraping (a paid vendor read per referente plus a model check), so it shows a
spinner beside the sentence that says so (`docs/design-system.md` §5.4), and the result
is remembered per brand (`reels_discovery.cached_discover`) — «Actualizar» reads again.
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


WINDOWS = (("week", "Esta semana"), ("month", "Este mes"))


class DiscoverReelsState(rx.State):
    """What the «Descubrir reels» view shows. Cards are `reels_discovery.reel_card`."""

    window: str = "week"
    loading: bool = False
    error: str = ""
    week: list[dict[str, str]] = []
    month: list[dict[str, str]] = []
    referentes: int = 0
    read: int = 0
    failed: list[str] = []
    dropped: int = 0
    reviewed: bool = True
    #: Why the product check did not run (`reels_discovery.CHECK_*`), "" when it did.
    check: str = ""
    #: Why it did not run, in a few words (`DiscoveredReels.check_detail`), "" if unknown.
    check_detail: str = ""
    fetched_at: float = 0.0
    #: `fetched_at` as the browser renders it («actualizado hace 3 minutos», `rx.moment`
    #: ages it client-side — no server round trip just to move a label).
    fetched_iso: str = ""
    #: Whether a read finished once this session (an empty result is a result).
    loaded: bool = False
    #: The reel playing inside its own card (its `key`), "" when none — one at a time,
    #: so starting another stops the previous (its iframe unmounts).
    playing_key: str = ""

    @rx.var
    def reels(self) -> list[dict[str, str]]:
        """The window's cards — only the ones the check called the brand's PRODUCT: a
        card from an older read (another rule, or kept while a new read loads or fails)
        never shows a reel of another product."""
        cards = self.week if self.window == "week" else self.month
        return [c for c in cards if c.get("affinity") in reels_ai.FITS]

    @rx.var
    def unchecked_note(self) -> str:
        """The «inténtalo más tarde» body, with the reason the check failed when known."""
        base = (
            "El servicio que comprueba que cada reel sea de tu producto o tu categoría no respondió"
        )
        if self.check_detail:
            return f"{base}: {self.check_detail}. Inténtalo más tarde."
        return f"{base}. Inténtalo más tarde."

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
        return next((c for c in [*self.week, *self.month] if c.get("key") == key), None)

    def _set_transcript(self, key: str, text: str) -> None:
        """Write the transcript into the card in both windows — a reel can be in both."""
        state = "said" if text else "none"

        def update(cards: list[dict[str, str]]) -> list[dict[str, str]]:
            return [
                {**c, "transcript": text, "transcript_state": state} if c.get("key") == key else c
                for c in cards
            ]

        self.week = update(self.week)
        self.month = update(self.month)

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

    @rx.var
    def summary(self) -> str:
        """«De 8 referentes · 153 reels del mes · 47 de otro producto»; the toolbar
        appends «actualizado hace …» from `fetched_iso`."""
        if not self.fetched_at:
            return ""
        noun = "referente" if self.referentes == 1 else "referentes"
        parts = [f"De {self.referentes} {noun}"]
        if self.read:
            parts.append(f"{self.read} reels del mes")
        if self.dropped:
            parts.append(f"{self.dropped} de otro producto")
        return " · ".join(parts)

    @rx.var
    def failed_note(self) -> str:
        if not self.failed:
            return ""
        return "No pudimos leer " + ", ".join(self.failed) + " (privada, sin reels o no existe)."

    @rx.event
    def set_window(self, value: str | list[str]) -> None:
        if isinstance(value, str) and value in dict(WINDOWS):
            self.window = value

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
            self.week = found.week
            self.month = found.month
            self.referentes = found.referentes
            self.read = found.read
            self.failed = found.failed
            self.dropped = found.dropped
            self.reviewed = found.reviewed
            self.check = found.check
            self.check_detail = found.check_detail
            self.fetched_at = found.fetched_at
            self.fetched_iso = datetime.fromtimestamp(found.fetched_at, tz=UTC).isoformat()
            self.loaded = True
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
        rx.text(
            DiscoverReelsState.summary,
            rx.cond(
                DiscoverReelsState.fetched_iso != "",
                rx.fragment(
                    " · actualizado ",
                    # «hace 3 minutos», aged by the browser itself (react-moment re-renders
                    # every minute); nothing reaches the server for it
                    rx.moment(date=DiscoverReelsState.fetched_iso, from_now=True, locale="es"),
                ),
            ),
            size="1",
            color=T.TEXT_MUTED,
        ),
        rx.spacer(),
        rx.button(
            rx.cond(
                DiscoverReelsState.loading,
                loading_spinner("sm"),
                rx.icon("refresh-cw", size=14),
            ),
            "Actualizar",
            variant="soft",
            color_scheme="gray",
            size="2",
            on_click=DiscoverReelsState.load(True),
            disabled=DiscoverReelsState.loading,
        ),
        width="100%",
        align="center",
        spacing="3",
        flex_wrap="wrap",
    )


def _notices() -> rx.Component:
    return rx.vstack(
        rx.cond(DiscoverReelsState.error != "", callout(DiscoverReelsState.error, "error")),
        rx.cond(
            DiscoverReelsState.failed_note != "", callout(DiscoverReelsState.failed_note, "info")
        ),
        spacing="2",
        width="100%",
    )


def _body() -> rx.Component:
    loading = rx.hstack(
        loading_spinner("sm"),
        rx.text(
            "Buscando los reels de tus referentes y comprobando que sean de tu producto…",
            size="2",
            color=T.TEXT_MUTED,
        ),
        spacing="2",
        align="center",
        padding_y="2rem",
        justify="center",
        width="100%",
    )
    no_referentes = empty_state(
        "users",
        "Aún no tienes referentes",
        "Marca cuentas como referente en tu Brand Kit (o agrégalas a mano) y aquí verás "
        "sus reels con más vistas.",
        rx.link(rx.button("Ir a mi Brand Kit", variant="soft"), href="/brand/kit"),
    )
    no_reels = empty_state(
        "film",
        rx.cond(
            DiscoverReelsState.window == "week",
            "Esta semana tus referentes no publicaron reels de tu producto",
            "Este mes tus referentes no publicaron reels de tu producto",
        ),
        rx.cond(
            DiscoverReelsState.window == "week",
            "Mira los del mes, o vuelve en unos días.",
            "Agrega más referentes en tu Brand Kit para ver más reels.",
        ),
    )
    # § founder 2026-10-16: without the product check NOTHING is shown — never a list of
    # unchecked reels where another product's promo can slip through
    unchecked = rx.cond(
        DiscoverReelsState.check == reels_discovery.CHECK_NO_BRIEF,
        empty_state(
            "search",
            "Aún no sabemos qué vende tu marca",
            "Ejecuta la búsqueda de referentes en tu Brand Kit: con ella filtramos los "
            "reels para mostrarte solo los de tu producto.",
            rx.link(rx.button("Ir a mi Brand Kit", variant="soft"), href="/brand/kit"),
        ),
        empty_state(
            "clock",
            "No pudimos filtrar los reels ahora mismo",
            DiscoverReelsState.unchecked_note,
            rx.button(
                rx.icon("refresh-cw", size=14),
                "Intentar de nuevo",
                variant="soft",
                on_click=DiscoverReelsState.load(True),
                disabled=DiscoverReelsState.loading,
            ),
        ),
    )
    grid = rx.box(
        rx.foreach(DiscoverReelsState.reels, _reel_tile),
        class_name="q-dr-grid",
        role="list",
        aria_label="Reels de tus referentes",
    )
    return rx.cond(
        DiscoverReelsState.loading & (DiscoverReelsState.reels.length() == 0),
        loading,
        rx.cond(
            DiscoverReelsState.loaded & (DiscoverReelsState.referentes == 0),
            no_referentes,
            rx.cond(
                DiscoverReelsState.reels.length() > 0,
                grid,
                rx.cond(
                    DiscoverReelsState.loaded,
                    rx.cond(DiscoverReelsState.check != "", unchecked, no_reels),
                    loading,
                ),
            ),
        ),
    )


def discover_view() -> rx.Component:
    """The centre of /create when «Descubrir reels» is chosen. Reads on mount (the
    remembered read when there is one)."""
    return card(
        rx.vstack(
            _toolbar(),
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
