"""Read seam between the clarity module and the Reflex UI.

Same discipline as `leads_provider`: the UI never touches ORM rows or service
dataclasses directly — everything that reaches the browser is a whitelist of plain
strings/ints, because every Reflex var is serialized to the client. In particular the
Data Export token NEVER appears in any VM: `ClarityConfigVM` only says whether one is
stored. Blocking (Postgres and, on refresh, the Clarity API) — the state calls this
off the event loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from qualify_api.clarity import production_clarity_service
from qualify_api.clarity.repository import SnapshotRow
from qualify_api.support import SupportTicket, create_support_request
from qualify_api.tenancy.models import Tenant
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from .clarity_vm import (
    DEFAULT_TIMEZONE,
    HEADLINE_LABELS,
    TEAM_ALERT_SCREEN,
    TEAM_REQUEST_MESSAGE,
    TEAM_REQUEST_SCREEN,
    date_line,
    day_label,
    es_int,
    es_number,
    es_percent,
    needs_daily_refresh,
    page_path,
    team_alert_message,
    window_label,
)

# Metrics whose information rows are single aggregate objects worth headline cards.
_HEADLINE_METRIC = "Traffic"
_ENGAGEMENT_METRIC = "EngagementTime"

# The Data Export friction metrics, in the order the health row renders them. Each maps
# to (label, what it means for the site owner, what to do about it) — the raw metric
# names mean nothing to a tenant, so the translation IS the feature.
_FRICTION_METRICS: dict[str, tuple[str, str, str]] = {
    "RageClickCount": (
        "Toques repetidos con enojo",
        "La gente tocó varias veces lo mismo porque no respondía.",
        "Un botón o enlace parece no funcionar. Mira la grabación en Clarity y pide "
        "que lo arreglen o lo quiten.",
    ),
    "DeadClickCount": (
        "Toques en cosas que no hacen nada",
        "Tocaron algo que parece un botón, pero no lo es.",
        "Algo parece un botón sin serlo (un texto, una foto, una tarjeta). Pide que lo "
        "conviertan en enlace o que cambien cómo se ve.",
    ),
    "ErrorClickCount": (
        "Toques que rompieron la página",
        "Al tocar algo, la página falló.",
        "Algo que la gente toca hace fallar la página. Mira la grabación en Clarity y "
        "avísale a quien te hizo la página.",
    ),
    "ScriptErrorCount": (
        "Fallas de la página",
        "La página falló sola, sin que la gente hiciera nada raro.",
        "Avísale a quien te hizo la página: esto es urgente.",
    ),
    "QuickbackClick": (
        "Entraron y se fueron enseguida",
        "Abrieron una página y volvieron atrás de inmediato.",
        "La página no era lo que esperaban. Revisa el enlace que los trajo y lo primero "
        "que se ve al abrirla.",
    ),
    "ExcessiveScroll": (
        "Bajaron mucho buscando algo",
        "Bajaron y bajaron buscando algo que no encontraban.",
        "Lo que buscan está muy abajo o no está. Pon lo importante más arriba.",
    ),
}

# Owner-facing names for the other metrics and for the API's column keys (the raw tables
# under «Ver todos los números»). Unknown keys fall back to the API's own name.
_METRIC_LABELS: dict[str, str] = {
    _HEADLINE_METRIC: "Visitas",
    _ENGAGEMENT_METRIC: "Tiempo que se quedaron",
    "ScrollDepth": "Hasta dónde bajaron",
    "PopularPages": "Páginas más vistas",
    "Browser": "Navegador",
    "Device": "Dispositivo",
    "OS": "Sistema",
    "Country": "País",
    "PageTitle": "Título de la página",
    "ReferrerUrl": "De dónde llegaron",
    **{name: label for name, (label, _hint, _advice) in _FRICTION_METRICS.items()},
}

# Dimension names as the Data Export API spells them (request values) → what the owner
# reads. The state's select offers the Spanish names and maps them back.
DIMENSION_LABELS: dict[str, str] = {
    "URL": "Página",
    "Device": "Dispositivo",
    "OS": "Sistema",
    "Browser": "Navegador",
    "Source": "De dónde llegaron",
    "Channel": "Canal",
}

_COLUMN_LABELS: dict[str, str] = {
    **DIMENSION_LABELS,
    "Url": "Página",
    "Country": "País",
    "Medium": "Medio",
    "Campaign": "Campaña",
    "PageTitle": "Título de la página",
    "ReferrerUrl": "De dónde llegaron",
    "totalSessionCount": "Visitas",
    "totalBotSessionCount": "Visitas de robots",
    "distinctUserCount": "Personas",
    "distantUserCount": "Personas",
    "pagesPerSessionPercentage": "Páginas por visita",
    "PagesPerSessionPercentage": "Páginas por visita",
    "sessionsCount": "Visitas",
    "sessionsWithMetricPercentage": "% de visitas con esto",
    "sessionsWithoutMetricPercentage": "% de visitas sin esto",
    "subTotal": "Veces",
    "totalTime": "Tiempo total",
    "activeTime": "Tiempo que se quedaron",
    "averageScrollDepth": "Cuánto bajaron (promedio)",
    "visitsCount": "Visitas",
}


@dataclass(frozen=True)
class ClarityConfigVM:
    configured: bool
    project_id: str  # "" when not configured
    remaining_budget: int


@dataclass(frozen=True)
class MetricTableVM:
    """One Clarity metric rendered as a generic table: the API's column set varies per
    metric and per requested dimension, so the VM carries its own header row."""

    name: str
    columns: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)


@dataclass(frozen=True)
class FrictionCardVM:
    """One friction signal as a traffic-light card. `status` drives the color:
    "ok" (0 events), "warn" (some), "bad" (enough to act on)."""

    label: str
    total: str  # formatted count, e.g. "12"
    affected: str  # "8% de las visitas" or "" when zero
    status: str  # "ok" | "warn" | "bad"
    hint: str  # one-liner: what this signal means


@dataclass(frozen=True)
class ActionItemVM:
    """One concrete recommendation derived from the snapshot, ranked for the
    'qué atender ahora' list. Plain strings only — this reaches the browser."""

    severity: str  # "alta" | "media"
    title: str  # "Toques repetidos con enojo en /reservas"
    detail: str  # counts + the recommended action, in Spanish
    url: str = ""  # the full address, for the team's ticket only (never rendered)


@dataclass(frozen=True)
class SnapshotVM:
    fetched_at: str  # "15 de agosto" (business time zone); "" when no snapshot exists
    window: str  # "Últimos 3 días"
    dimensions: str  # "Página · Dispositivo" or "" — kept for the raw tables only
    stats: list[list[str]] = field(default_factory=list)  # [label, value] pairs
    friction: list[FrictionCardVM] = field(default_factory=list)
    actions: list[ActionItemVM] = field(default_factory=list)
    # RESULTADOS-3: what the owner reads first — visits and people, and only the
    # urgent («alta») problems; `has_minor` says whether anything smaller exists.
    headline: list[list[str]] = field(default_factory=list)
    urgent: list[ActionItemVM] = field(default_factory=list)
    has_minor: bool = False
    date_line: str = ""  # «Datos de hoy.» / «Datos del 22 de octubre.»
    traffic_note: str = ""  # low-sample warning; "" when the sample is fine
    tables: list[MetricTableVM] = field(default_factory=list)


def config_for(tenant_id: UUID) -> ClarityConfigVM:
    """The tenant's Clarity configuration status. Hits Postgres — call off-thread."""
    service = production_clarity_service()
    status = service.settings_status(tenant_id=tenant_id)
    return ClarityConfigVM(
        configured=status is not None and status.active,
        project_id=status.project_id if status else "",
        remaining_budget=service.remaining_budget(tenant_id=tenant_id),
    )


def save_config(tenant_id: UUID, *, project_id: str, api_token: str) -> None:
    """Persist project id + token (encrypted service-side). Raises ValueError on blanks."""
    production_clarity_service().configure(
        tenant_id=tenant_id, project_id=project_id, api_token=api_token
    )


def request_website_connection(tenant_id: UUID, *, contact_email: str) -> SupportTicket:
    """RESULTADOS-4: «Escribir al equipo» in Configuración — a support ticket asking the
    Qualify team to connect the business's website. Same service as the connections
    screen's «Pedir ayuda 1:1», topic `other`, with only the closed `screen` context key.

    Raises `InvalidSupportRequest` on a bad email. Blocking (Postgres + one HTTP call).
    """
    return create_support_request(
        tenant_id=tenant_id,
        topic="other",
        contact_email=contact_email,
        contact_whatsapp="",
        message=TEAM_REQUEST_MESSAGE,
        context={"screen": TEAM_REQUEST_SCREEN},
    )


def alert_team(
    tenant_id: UUID, *, contact_email: str, title: str, detail: str, url: str = ""
) -> SupportTicket:
    """RESULTADOS-3: «Avisar al equipo» on one urgent problem — a support ticket with the
    problem in plain words, topic `other`, only the closed `screen` context key.

    Raises `InvalidSupportRequest` on a bad email. Blocking (Postgres + one HTTP call).
    """
    return create_support_request(
        tenant_id=tenant_id,
        topic="other",
        contact_email=contact_email,
        contact_whatsapp="",
        message=team_alert_message(title, detail, url),
        context={"screen": TEAM_ALERT_SCREEN},
    )


def _tenant_timezone(tenant_id: UUID) -> str:
    """The business's IANA zone: dates on this screen and «already read today» use it."""
    with tenant_session(tenant_id) as session:
        zone = session.execute(
            select(Tenant.timezone).where(Tenant.id == tenant_id)
        ).scalar_one_or_none()
    return zone or DEFAULT_TIMEZONE


def latest_snapshot_for(tenant_id: UUID) -> SnapshotVM | None:
    snapshot = production_clarity_service().latest(tenant_id=tenant_id)
    return _to_vm(snapshot, tz=_tenant_timezone(tenant_id)) if snapshot else None


def latest_snapshot_and_staleness(
    tenant_id: UUID, *, now: datetime | None = None
) -> tuple[SnapshotVM | None, bool]:
    """The cached snapshot plus whether today's automatic read is still due
    (RESULTADOS-3: the screen refreshes itself once a day, counted in the business's
    time zone). Costs no API request."""
    tz = _tenant_timezone(tenant_id)
    moment = now or datetime.now(UTC)
    snapshot = production_clarity_service().latest(tenant_id=tenant_id)
    due = needs_daily_refresh(snapshot.fetched_at if snapshot else None, moment, tz)
    return (_to_vm(snapshot, tz=tz, now=moment) if snapshot else None), due


def refresh_snapshot(tenant_id: UUID, *, num_of_days: int, dimension: str) -> SnapshotVM:
    """Spend one live Data Export request. Raises the service/client error family."""
    snapshot = production_clarity_service().refresh(
        tenant_id=tenant_id,
        num_of_days=num_of_days,
        dimensions=[dimension] if dimension else [],
    )
    return _to_vm(snapshot, tz=_tenant_timezone(tenant_id))


def _to_vm(
    snapshot: SnapshotRow, *, tz: str = DEFAULT_TIMEZONE, now: datetime | None = None
) -> SnapshotVM:
    stats = _headline_stats(snapshot.payload)
    actions = _action_items(snapshot.payload)
    urgent = [item for item in actions if item.severity == "alta"]
    return SnapshotVM(
        fetched_at=day_label(snapshot.fetched_at, tz),
        window=window_label(snapshot.num_of_days),
        dimensions=" · ".join(DIMENSION_LABELS.get(d, d) for d in snapshot.dimensions),
        stats=stats,
        friction=_friction_cards(snapshot.payload),
        actions=actions,
        traffic_note=_traffic_note(snapshot.payload),
        tables=[table for table in map(_metric_table, snapshot.payload) if table.rows],
        headline=[stat for stat in stats if stat[0] in HEADLINE_LABELS],
        urgent=urgent,
        has_minor=len(urgent) < len(actions),
        date_line=date_line(snapshot.fetched_at, now or datetime.now(UTC), tz),
    )


def _metric_rows(payload: list[dict], name: str) -> list[dict]:
    for metric in payload:
        if metric.get("metricName") == name:
            return [row for row in metric.get("information", []) if isinstance(row, dict)]
    return []


def _headline_stats(payload: list[dict]) -> list[list[str]]:
    """Totals from the Traffic metric, summed across dimension rows. The API returns
    counts as strings; anything non-numeric sums as zero rather than crashing the UI."""
    rows = _metric_rows(payload, _HEADLINE_METRIC)
    if not rows:
        return []
    sessions = _sum_of(rows, "totalSessionCount")
    bots = _sum_of(rows, "totalBotSessionCount")
    # The live API spells it distinctUserCount; the docs' sample says distantUserCount.
    # Accept both — rows carry one or the other, never both.
    users = _sum_of(rows, "distinctUserCount") + _sum_of(rows, "distantUserCount")
    stats = [
        ["Visitas", es_int(sessions)],
        ["Visitas de robots", es_int(bots)],
        ["Personas", es_int(users)],
    ]
    engagement = _metric_rows(payload, _ENGAGEMENT_METRIC)
    if engagement:
        stats.append(["Tiempo que se quedaron", _format_seconds(_sum_of(engagement, "activeTime"))])
    return stats


def _format_seconds(total: int) -> str:
    minutes, seconds = divmod(max(0, total), 60)
    return f"{minutes} min {seconds} s" if minutes else f"{seconds} s"


# Act when at least this share of sessions hit the signal, or this many raw events.
_BAD_PCT = 10.0
_BAD_TOTAL = 10


def _friction_cards(payload: list[dict]) -> list[FrictionCardVM]:
    """One traffic-light card per friction metric present in the snapshot."""
    cards: list[FrictionCardVM] = []
    for name, (label, hint, _advice) in _FRICTION_METRICS.items():
        rows = _metric_rows(payload, name)
        if not rows:
            continue
        total = _sum_of(rows, "subTotal")
        pct = max((_as_float(row.get("sessionsWithMetricPercentage")) for row in rows), default=0)
        if total == 0:
            status, affected = "ok", ""
        else:
            status = "bad" if (pct >= _BAD_PCT or total >= _BAD_TOTAL) else "warn"
            affected = f"{es_percent(pct)} de las visitas" if pct else ""
        cards.append(
            FrictionCardVM(
                label=label, total=es_int(total), affected=affected, status=status, hint=hint
            )
        )
    return cards


def _action_items(payload: list[dict]) -> list[ActionItemVM]:
    """Per-page recommendations, worst first. Only rows with actual events qualify —
    an empty list means the window really had no friction. Rows for the same page
    with different tracking tails («?utm_source=…») count as one page."""
    grouped: dict[tuple[str, str], dict] = {}
    for name, (label, _hint, advice) in _FRICTION_METRICS.items():
        for row in _metric_rows(payload, name):
            events = _as_int(row.get("subTotal"))
            if events <= 0:
                continue
            url = str(row.get("Url", "") or "").strip()
            entry = grouped.setdefault(
                (name, page_path(url)),
                {"label": label, "advice": advice, "url": url, "events": 0, "sessions": 0},
            )
            entry["events"] += events
            entry["sessions"] += _as_int(row.get("sessionsCount"))
            pct = _as_float(row.get("sessionsWithMetricPercentage"))
            entry["pct"] = max(entry.get("pct", 0.0), pct)

    scored: list[tuple[int, int, ActionItemVM]] = []
    for (_name, where), entry in grouped.items():
        events, sessions, pct = entry["events"], entry["sessions"], entry["pct"]
        severity = "alta" if (pct >= _BAD_PCT or events >= _BAD_TOTAL) else "media"
        label = entry["label"]
        title = f"{label} en {where}" if where else f"{label} en tu página"
        counts = "1 vez" if events == 1 else f"{es_int(events)} veces"
        if sessions:
            counts += " en 1 visita" if sessions == 1 else f" en {es_int(sessions)} visitas"
        if pct:
            counts += f" ({es_percent(pct)} de las visitas)"
        item = ActionItemVM(
            severity=severity,
            title=title,
            detail=f"{counts}. {entry['advice']}",
            url=entry["url"],
        )
        scored.append((0 if severity == "alta" else 1, -events, item))
    scored.sort(key=lambda ranked: ranked[:2])
    return [item for _, _, item in scored[:8]]


# Below this many human sessions, percentages are noise and the note says so.
_LOW_SAMPLE_SESSIONS = 20


def _traffic_note(payload: list[dict]) -> str:
    rows = _metric_rows(payload, _HEADLINE_METRIC)
    if not rows:
        return ""
    humans = _sum_of(rows, "totalSessionCount") - _sum_of(rows, "totalBotSessionCount")
    if 0 <= humans < _LOW_SAMPLE_SESSIONS:
        label = "1 visita de una persona" if humans == 1 else f"{humans} visitas de personas"
        return (
            f"Solo hubo {label} en estos días. Son muy pocas para sacar conclusiones: "
            "vuelve a mirar cuando tengas más visitas."
        )
    return ""


def _as_int(value: object) -> int:
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def _as_float(value: object) -> float:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _sum_of(rows: list[dict], key: str) -> int:
    total = 0
    for row in rows:
        try:
            total += int(float(row.get(key, 0) or 0))
        except (TypeError, ValueError):
            continue
    return total


def _metric_table(metric: dict) -> MetricTableVM:
    """Flatten one metric into header + string rows. Column order: dimension-ish keys
    (non-numeric values) first so the breakdown label leads each row."""
    raw_name = str(metric.get("metricName", ""))
    name = _METRIC_LABELS.get(raw_name, raw_name)
    rows_in = [row for row in metric.get("information", []) if isinstance(row, dict)]
    if not rows_in:
        return MetricTableVM(name=name)

    columns: list[str] = []
    for row in rows_in:
        for key in row:
            if key not in columns:
                columns.append(key)

    def numericness(column: str) -> tuple[int, int]:
        sample = next((row[column] for row in rows_in if column in row), "")
        try:
            float(str(sample).replace(",", ""))
            return (1, columns.index(column))
        except ValueError:
            return (0, columns.index(column))

    ordered = sorted(columns, key=numericness)
    return MetricTableVM(
        name=name,
        columns=[_COLUMN_LABELS.get(column, column) for column in ordered],
        rows=[[es_number(str(row.get(column, ""))) for column in ordered] for row in rows_in],
    )
