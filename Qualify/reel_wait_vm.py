"""The create flow's wait for a reel's analysis (ADR 44 UI-2, m-24921076) — pure.

«Hacer uno parecido» (UI-1) asks for the reel's shared analysis; while it is not `ok`,
step 2 («Qué mostrar») shows «Mirando el reel» and «Siguiente» waits. This module turns
what the backend answers — `request_analysis`'s outcome and `get_analysis_status`'s
`AnalysisStatus` (`qualify_api.referentes.reel_analysis_types`) — into what the screen
shows: the stage over the bar, the bar's value, the error and its buttons, and whether
«Siguiente» is blocked. No I/O, no Reflex: `CreativeState` stores the result field by
field (explicit vars, no `getattr` in a computed var).

Copy: `docs/traspasos/historias-video-por-partes-backend.md` §3 and
`docs/ux-video-por-planos.md` §3a/§4, with the brief's decisions where they disagree
(no «Intentar de nuevo»: re-queueing is the worker's call).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from qualify_api.referentes.reel_analysis_types import (
    ERROR_SOURCE_EXPIRED,
    ERROR_SOURCE_UNAVAILABLE,
    STAGE_DESCRIBING,
    STAGE_DETECTING,
    STAGE_DOWNLOADING,
    STATUS_DAILY_LIMIT,
    STATUS_FAILED,
    STATUS_NO_VIDEO,
    STATUS_OK,
    STATUS_QUEUED,
    STATUS_RUNNING,
    AnalysisStatus,
)

# -- phases ---------------------------------------------------------------------------

#: No analysis rides with the piece (a normal Clip, or «Armar sin el reel»): no new UI.
PHASE_IDLE = "idle"
#: Queued or running: «Mirando el reel» and the bar.
PHASE_WAITING = "waiting"
#: `ok` read, the plan not counted yet: «Armando tu propuesta».
PHASE_PLANNING = "planning"
#: The plan is counted: «Encontramos {n} partes»; «Siguiente» goes on.
PHASE_READY = "ready"
#: The analysis will not come: the error and its way forward.
PHASE_ERROR = "error"

#: What `request_similar` answers when it could not ask (it returned None).
OUTCOME_UNASKED = "unasked"

#: Past this wait (seconds since it was asked) the screen offers «Armar sin el reel».
SLOW_AFTER_S = 300.0

# -- copy -----------------------------------------------------------------------------

WAIT_TITLE = "Mirando el reel"
WAIT_DETAIL = "Puedes salir: guardamos lo que encontremos. No usa tus videos del mes."
STAGE_QUEUED_TEXT = "Estamos mirando este reel…"
STAGE_RETRYING_TEXT = "Seguimos mirando este reel"
STAGE_DOWNLOADING_TEXT = "Bajando el video"
STAGE_DETECTING_TEXT = "Mirando qué pasa"
STAGE_DESCRIBING_TEXT = "Revisando si aparece alguien"
STAGE_PLANNING_TEXT = "Armando tu propuesta"
QUEUE_AHEAD_TEXT = "Hay otros reels antes que este."
SLOW_TEXT = "Esto está tardando más de lo normal. Puedes armar tu video por partes sin el reel."
#: The fleet's daily model-call cap is spent: this reel waits for tomorrow (Deivid,
#: 2026-11-07). Wins over `SLOW_TEXT` when both apply.
PAUSED_TEXT = (
    "Hoy ya miramos muchos reels. Terminamos de mirar este mañana; mientras, puedes "
    "armar tu video por partes sin él."
)
BLOCKED_REASON = "Disponible cuando terminemos de mirar el reel."
ERROR_REASON = "Para seguir, toca «Armar sin el reel»."

PICK_OTHER_LABEL = "Elegir otro reel"
WITHOUT_LABEL = "Armar sin el reel"

ERROR_SOURCE_TITLE = "No pudimos bajar el video de este reel."
ERROR_SOURCE_BODY = "A veces la red lo retira. Elige otro o arma tu video por partes sin él."
ERROR_FAILED_TITLE = "No pudimos mirar este reel."
ERROR_FAILED_BODY = "Arma tu video por partes sin él."
ERROR_DAILY_TITLE = "Por hoy no podemos mirar más reels para tu negocio."
ERROR_DAILY_BODY = "Mañana puedes mirar otro; mientras, arma tu video por partes sin reel."

SINGLE_PART_TITLE = "Este reel no cambia de escena."
# UI-3/UI-4 restore «; si quieres, agrega otras.» together with the «Añadir parte» button
SINGLE_PART_BODY = "Lo hacemos como una sola parte."


def parts_found_text(n: int) -> str:
    """«Encontramos {n} partes» — n from the PLAN (`plan_from_analysis`), not the shots."""
    return "Encontramos 1 parte" if n == 1 else f"Encontramos {n} partes"


# -- the stages over the bar ----------------------------------------------------------

#: The running stages in order, with their label and the bar's value (0-100).
_STAGES: tuple[tuple[str, str, int], ...] = (
    (STAGE_DOWNLOADING, STAGE_DOWNLOADING_TEXT, 20),
    (STAGE_DETECTING, STAGE_DETECTING_TEXT, 45),
    (STAGE_DESCRIBING, STAGE_DESCRIBING_TEXT, 70),
)
_PLANNING_VALUE = 90
#: The step list's keys for the two stages that are not the worker's.
_KEY_QUEUED = "queued"
_KEY_PLANNING = "planning"
_KEY_DONE = "done"


def _steps(
    running: str, *, queued_label: str = STAGE_QUEUED_TEXT, n: int = 0
) -> list[dict[str, str]]:
    """`progress_panel` stages (`{"title", "status"}`): the one `running` is the comment
    over the bar; the ones before it are done, the ones after pending."""
    order = [
        (_KEY_QUEUED, queued_label),
        *((key, label) for key, label, _ in _STAGES),
        (_KEY_PLANNING, STAGE_PLANNING_TEXT),
        (_KEY_DONE, parts_found_text(n)),
    ]
    keys = [key for key, _ in order]
    at = keys.index(running)
    return [
        {
            "title": label,
            "status": "done" if i < at else ("running" if i == at else "pending"),
        }
        for i, (_key, label) in enumerate(order)
    ]


# -- what the screen shows ------------------------------------------------------------


@dataclass(frozen=True)
class ReelWait:
    """Everything step 2 shows about the analysis. `value` is the bar (0-100), or -1 for
    the bar that creeps by time (no stage informs it). `blocks_next`: «Siguiente» (and the
    step bar forward) waits; `reason` says why beside the button."""

    phase: str = PHASE_IDLE
    stage: str = ""
    value: int = -1
    steps: list[dict[str, str]] = field(default_factory=list)
    queue_note: str = ""
    slow: bool = False
    #: The note under the bar while still waiting (`SLOW_TEXT` or `PAUSED_TEXT`),
    #: shown with «Armar sin el reel»; "" when the wait is going as usual.
    notice: str = ""
    error_title: str = ""
    error_body: str = ""
    pick_other: bool = False
    without: bool = False
    parts: int = 0
    single_part: bool = False
    blocks_next: bool = False
    reason: str = ""

    @property
    def terminal(self) -> bool:
        """Nothing more to poll: ready, error or idle."""
        return self.phase in (PHASE_IDLE, PHASE_READY, PHASE_ERROR)


IDLE = ReelWait()


def _error(title: str, body: str, *, pick_other: bool = False) -> ReelWait:
    return ReelWait(
        phase=PHASE_ERROR,
        error_title=title,
        error_body=body,
        pick_other=pick_other,
        without=True,
        blocks_next=True,
        reason=ERROR_REASON,
    )


def source_error() -> ReelWait:
    """The reel's video could not be downloaded (removed, expired, or no usable link)."""
    return _error(ERROR_SOURCE_TITLE, ERROR_SOURCE_BODY, pick_other=True)


def failed_error() -> ReelWait:
    """The reel could not be looked at — also every case the screen cannot read (fail
    closed): an unknown code, a missing row, a request that could not be made."""
    return _error(ERROR_FAILED_TITLE, ERROR_FAILED_BODY, pick_other=True)


def daily_error() -> ReelWait:
    """The platform's on-demand quota for today is spent (platform-wide: never «tu
    negocio»)."""
    return _error(ERROR_DAILY_TITLE, ERROR_DAILY_BODY)


def _waiting(
    running: str, value: int, *, queued_label: str, queue_ahead: int, notice: str = ""
) -> ReelWait:
    label = next(
        (
            s["title"]
            for s in _steps(running, queued_label=queued_label)
            if s["status"] == "running"
        ),
        "",
    )
    return ReelWait(
        phase=PHASE_WAITING,
        stage=label,
        value=value,
        steps=_steps(running, queued_label=queued_label),
        queue_note=QUEUE_AHEAD_TEXT if queue_ahead > 0 else "",
        slow=bool(notice),
        notice=notice,
        without=bool(notice),
        blocks_next=True,
        reason=BLOCKED_REASON,
    )


def planning() -> ReelWait:
    """`ok` read; the plan is being counted."""
    return ReelWait(
        phase=PHASE_PLANNING,
        stage=STAGE_PLANNING_TEXT,
        value=_PLANNING_VALUE,
        steps=_steps(_KEY_PLANNING),
        blocks_next=True,
        reason=BLOCKED_REASON,
    )


def ready(parts: int) -> ReelWait:
    """The plan is counted: «Encontramos {n} partes»; one part says so and goes on as
    one. No parts at all (an `ok` with no shots) fails closed."""
    if parts < 1:
        return failed_error()
    return ReelWait(
        phase=PHASE_READY,
        stage=parts_found_text(parts),
        value=100,
        steps=_steps(_KEY_DONE, n=parts),
        parts=parts,
        single_part=parts == 1,
    )


def from_request(outcome: str) -> ReelWait:
    """Right after «Hacer uno parecido»: what `request_analysis` answered (`status` of
    its `AnalysisRef`, or `OUTCOME_UNASKED`), before the first poll. "" = no analysis."""
    if not outcome:
        return IDLE
    if outcome == STATUS_NO_VIDEO:
        return source_error()
    if outcome == STATUS_DAILY_LIMIT:
        return daily_error()
    if outcome == STATUS_OK:
        return planning()
    if outcome in (STATUS_QUEUED, STATUS_RUNNING, STATUS_FAILED):
        # a failed row's code is read by the first poll, in the same breath
        return _waiting(_KEY_QUEUED, -1, queued_label=STAGE_QUEUED_TEXT, queue_ahead=0)
    return failed_error()


def from_status(status: AnalysisStatus | None) -> ReelWait:
    """One poll's `AnalysisStatus` (None: the row could not be read → fail closed). An
    `ok` answers `planning()`: the caller counts the plan and then calls `ready(n)`."""
    if status is None:
        return failed_error()
    # the paused fleet says why (it waits for tomorrow); else a long wait says so
    if status.fleet_paused:
        notice = PAUSED_TEXT
    elif status.queued_for_s > SLOW_AFTER_S:
        notice = SLOW_TEXT
    else:
        notice = ""
    if status.status == STATUS_QUEUED:
        label = STAGE_RETRYING_TEXT if status.retryable else STAGE_QUEUED_TEXT
        return _waiting(
            _KEY_QUEUED, -1, queued_label=label, queue_ahead=status.queue_ahead, notice=notice
        )
    if status.status == STATUS_RUNNING:
        known = {key: value for key, _label, value in _STAGES}
        if status.stage in known:
            return _waiting(
                status.stage,
                known[status.stage],
                queued_label=STAGE_QUEUED_TEXT,
                queue_ahead=0,
                notice=notice,
            )
        # running with no (or a finished) stage: still the worker's, by time
        return _waiting(
            _KEY_QUEUED, -1, queued_label=STAGE_QUEUED_TEXT, queue_ahead=0, notice=notice
        )
    if status.status == STATUS_OK:
        return planning()
    if status.status == STATUS_FAILED:
        if status.error_code in (ERROR_SOURCE_UNAVAILABLE, ERROR_SOURCE_EXPIRED):
            return source_error()
        return failed_error()
    return failed_error()


__all__ = [
    "BLOCKED_REASON",
    "ERROR_REASON",
    "IDLE",
    "OUTCOME_UNASKED",
    "PHASE_ERROR",
    "PHASE_IDLE",
    "PHASE_PLANNING",
    "PHASE_READY",
    "PHASE_WAITING",
    "PICK_OTHER_LABEL",
    "SINGLE_PART_BODY",
    "SINGLE_PART_TITLE",
    "PAUSED_TEXT",
    "SLOW_TEXT",
    "WAIT_DETAIL",
    "WAIT_TITLE",
    "WITHOUT_LABEL",
    "ReelWait",
    "daily_error",
    "failed_error",
    "from_request",
    "from_status",
    "parts_found_text",
    "planning",
    "ready",
    "source_error",
]
