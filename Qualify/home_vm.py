"""Inicio's view models (m-24842962, NAV-4) — pure, tested in `test_home_vm.py`.

`build_home_vm` turns the backend's `HomeCounts` into what the screen prints, in the
owner's words, and decides which blocks show:

- «Hoy tienes»: up to four tappable cards, only the ones with something pending, each
  linking to the list already filtered (N11).
- «Para tu primera publicación»: the checklist with its progress («Llevas 1 de 2»); a
  finished step stays visible with ✓ «Listo» and stops being a link (N2). The whole
  block goes away once every step is done.
- «Todo al día»: nothing pending and nothing missing — never an empty screen (N8).
- «Así te fue esta semana»: three figures of the last 7 days, each linking to its
  detail; without Instagram connected and with nothing to count, it says what to connect;
  connected but a quiet week, it suggests a new publication instead of three zeros (N8).

Which figures matter to the owner is a *hypothesis* (perfil-cliente-pyme §5, pregunta 7).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from qualify_api.home import HomeCounts

# Destinations. A query names the filter the list opens with (N11); the receiving
# screens read it (`conversations_vm.filter_from_param`, `planner_vm.gallery_filter_from_param`).
CONVERSATIONS_PENDING_URL = "/conversations?filtro=pendientes"
DRAFTS_TO_APPROVE_URL = "/drafts?estado=por-completar"
# founder 2026-10-24: the same list, every piece, the soonest-expiring vistas previas first
VIDEOS_EXPIRING_URL = "/drafts?estado=por-completar&orden=vence"
COMMENTS_URL = "/inbox"
CONVERSATIONS_URL = "/conversations"
WHATSAPP_CHATS_URL = "/whatsapp?tab=chats"
# m-24843003: mentions are Resultados › «Quién habla de ti».
MENTIONS_URL = "/resultados?tab=menciones"
CONNECTIONS_URL = "/connections"
CREATE_URL = "/create"
BRAND_URL = "/brand"
#: PASOS-4 (m-24852243): Tu marca left halfway is the first thing to finish (N2: Inicio
#: shows what was left halfway). Only listed while the kit is unfinished; the caller
#: passes the line with what is left (`brand_minimal_vm.brand_left_label`).
BRAND_STEP_LABEL = "Termina tu marca"


@dataclass(frozen=True)
class TodayCardVM:
    key: str
    count: int
    label: str
    href: str
    icon: str


@dataclass(frozen=True)
class FirstStepVM:
    key: str
    label: str
    href: str
    icon: str
    #: Done: the row stays, with ✓ «Listo», and is no longer a link.
    done: bool = False


@dataclass(frozen=True)
class WeekStatVM:
    key: str
    label: str
    value: int
    hint: str
    href: str


@dataclass(frozen=True)
class HomeVM:
    today: list[TodayCardVM] = field(default_factory=list)
    first_steps: list[FirstStepVM] = field(default_factory=list)
    week: list[WeekStatVM] = field(default_factory=list)
    #: «Así te fue» has nothing to count yet and Instagram is not connected.
    week_needs_connection: bool = True
    #: Instagram is connected but the week counted nothing: a way out, not three zeros.
    week_quiet: bool = False

    @property
    def steps_done(self) -> int:
        return sum(1 for step in self.first_steps if step.done)

    @property
    def first_steps_pending(self) -> bool:
        return self.steps_done < len(self.first_steps)

    @property
    def first_steps_progress(self) -> str:
        return first_steps_progress_label(self.steps_done, len(self.first_steps))

    @property
    def all_clear(self) -> bool:
        return not self.today and not self.first_steps_pending


def _plural(n: int, one: str, many: str) -> str:
    return (one if n == 1 else many).format(n=n)


def people_waiting_label(n: int) -> str:
    return _plural(n, "{n} persona espera tu respuesta", "{n} personas esperan tu respuesta")


def drafts_to_approve_label(n: int) -> str:
    # The action the owner takes in that list (review), not a one-tap promise.
    return _plural(
        n,
        "{n} publicación espera tu revisión",
        "{n} publicaciones esperan tu revisión",
    )


def videos_expiring_label(n: int) -> str:
    """Founder 2026-10-24: from 2 days before a vista previa expires."""
    return _plural(n, "{n} video vence pronto", "{n} videos vencen pronto")


def comments_unanswered_label(n: int) -> str:
    # The count covers the last 7 days only; the label says so.
    return _plural(
        n,
        "{n} comentario de esta semana sin responder",
        "{n} comentarios de esta semana sin responder",
    )


def first_steps_progress_label(done: int, total: int) -> str:
    return f"Llevas {done} de {total}"


def _today(counts: HomeCounts) -> list[TodayCardVM]:
    cards = [
        TodayCardVM(
            "people",
            counts.people_waiting,
            people_waiting_label(counts.people_waiting),
            CONVERSATIONS_PENDING_URL,
            "messages-square",
        ),
        TodayCardVM(
            "drafts",
            counts.drafts_to_approve,
            drafts_to_approve_label(counts.drafts_to_approve),
            DRAFTS_TO_APPROVE_URL,
            "layout-list",
        ),
        # founder 2026-10-24: a vista previa about to expire loses its video final
        TodayCardVM(
            "expiring",
            counts.videos_expiring_soon,
            videos_expiring_label(counts.videos_expiring_soon),
            VIDEOS_EXPIRING_URL,
            "clock",
        ),
        TodayCardVM(
            "comments",
            counts.comments_unanswered,
            comments_unanswered_label(counts.comments_unanswered),
            COMMENTS_URL,
            "message-circle",
        ),
    ]
    return [card for card in cards if card.count > 0]


def _first_steps(
    counts: HomeCounts, *, brand_done: bool = True, brand_label: str = BRAND_STEP_LABEL
) -> list[FirstStepVM]:
    connected = counts.instagram_connected
    created = counts.has_publication
    brand = [] if brand_done else [FirstStepVM("brand", brand_label, BRAND_URL, "palette")]
    return brand + [
        FirstStepVM(
            "connect",
            "Conectaste tu Instagram"
            if connected
            else "Conecta tu Instagram para publicar desde aquí",
            CONNECTIONS_URL,
            "link",
            done=connected,
        ),
        FirstStepVM(
            "create",
            "Creaste tu primera publicación"
            if created
            else "Crea tu primera publicación con la foto de un producto",
            CREATE_URL,
            "wand-sparkles",
            done=created,
        ),
    ]


def _messages_hint(counts: HomeCounts) -> str:
    return f"{counts.messages_week_dm} por Instagram · {counts.messages_week_whatsapp} por WhatsApp"


def _week(counts: HomeCounts) -> list[WeekStatVM]:
    return [
        WeekStatVM(
            "messages",
            "Te escribieron",
            counts.messages_week,
            _messages_hint(counts),
            # Always the same place, whichever channel carried the week.
            CONVERSATIONS_URL,
        ),
        WeekStatVM(
            "comments", "Comentaron", counts.comments_week, "En tus publicaciones", COMMENTS_URL
        ),
        WeekStatVM(
            "mentions", "Hablaron de ti", counts.mentions_week, "Te etiquetaron", MENTIONS_URL
        ),
    ]


def build_home_vm(
    counts: HomeCounts, *, brand_done: bool = True, brand_label: str = BRAND_STEP_LABEL
) -> HomeVM:
    """``brand_done=False`` (Tu marca unfinished) puts «Termina tu marca» first, said
    as ``brand_label`` (what is left)."""
    week = _week(counts)
    nothing_counted = all(stat.value == 0 for stat in week)
    return HomeVM(
        today=_today(counts),
        first_steps=_first_steps(counts, brand_done=brand_done, brand_label=brand_label),
        week=week,
        week_needs_connection=nothing_counted and not counts.instagram_connected,
        week_quiet=nothing_counted and counts.instagram_connected,
    )


EMPTY_HOME = build_home_vm(HomeCounts())

__all__ = [
    "BRAND_STEP_LABEL",
    "BRAND_URL",
    "COMMENTS_URL",
    "CONNECTIONS_URL",
    "CONVERSATIONS_PENDING_URL",
    "CONVERSATIONS_URL",
    "CREATE_URL",
    "DRAFTS_TO_APPROVE_URL",
    "EMPTY_HOME",
    "MENTIONS_URL",
    "WHATSAPP_CHATS_URL",
    "FirstStepVM",
    "HomeVM",
    "TodayCardVM",
    "WeekStatVM",
    "build_home_vm",
    "comments_unanswered_label",
    "drafts_to_approve_label",
    "first_steps_progress_label",
    "people_waiting_label",
]
