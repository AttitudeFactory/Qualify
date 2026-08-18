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
from uuid import UUID

from qualify_api.clarity import production_clarity_service
from qualify_api.clarity.repository import SnapshotRow

# Metrics whose information rows are single aggregate objects worth headline cards.
_HEADLINE_METRIC = "Traffic"
_ENGAGEMENT_METRIC = "EngagementTime"

# The Data Export friction metrics, in the order the health row renders them. Each maps
# to (label, what it means for the site owner, what to do about it) — the raw metric
# names mean nothing to a tenant, so the translation IS the feature.
_FRICTION_METRICS: dict[str, tuple[str, str, str]] = {
    "RageClickCount": (
        "Rage clicks",
        "Clics repetidos y frustrados sobre un mismo elemento.",
        "Un botón o enlace parece no responder. Revisa la grabación en Clarity y "
        "arregla (o quita) el elemento que la gente golpea sin resultado.",
    ),
    "DeadClickCount": (
        "Clics muertos",
        "Clics sobre cosas que no hacen nada.",
        "Algo parece clicable sin serlo (texto subrayado, imagen, tarjeta). "
        "Conviértelo en enlace real o cambia su estilo para que no invite al clic.",
    ),
    "ErrorClickCount": (
        "Clics con error",
        "Clics que dispararon un error de JavaScript.",
        "Una acción del usuario está rompiendo el sitio. Abre la sesión en Clarity "
        "para ver qué clic lo provoca y pásalo a quien mantenga el sitio.",
    ),
    "ScriptErrorCount": (
        "Errores de JavaScript",
        "Errores del código del sitio durante la sesión.",
        "El sitio está fallando aunque el usuario no haga nada raro. "
        "Prioridad alta para el desarrollador del sitio.",
    ),
    "QuickbackClick": (
        "Rebotes rápidos",
        "Entraron a una página y volvieron atrás de inmediato.",
        "La página no era lo que esperaban: revisa el título/enlace que los trajo "
        "o el primer pantallazo de esa página.",
    ),
    "ExcessiveScroll": (
        "Scroll excesivo",
        "Desplazamiento de más buscando algo que no aparece.",
        "Lo que buscan está muy abajo o no está. Sube el contenido clave "
        "o añade accesos directos.",
    ),
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
    affected: str  # "8% de sesiones" or "" when zero
    status: str  # "ok" | "warn" | "bad"
    hint: str  # one-liner: what this signal means


@dataclass(frozen=True)
class ActionItemVM:
    """One concrete recommendation derived from the snapshot, ranked for the
    'qué atender ahora' list. Plain strings only — this reaches the browser."""

    severity: str  # "alta" | "media"
    title: str  # "Rage clicks en /reservas"
    detail: str  # counts + the recommended action, in Spanish


@dataclass(frozen=True)
class SnapshotVM:
    fetched_at: str  # "2026-08-15 14:03 UTC"; "" when no snapshot exists
    window: str  # "últimas 72 h"
    dimensions: str  # "URL · Device" or ""
    stats: list[list[str]] = field(default_factory=list)  # [label, value] pairs
    friction: list[FrictionCardVM] = field(default_factory=list)
    actions: list[ActionItemVM] = field(default_factory=list)
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


def latest_snapshot_for(tenant_id: UUID) -> SnapshotVM | None:
    snapshot = production_clarity_service().latest(tenant_id=tenant_id)
    return _to_vm(snapshot) if snapshot else None


def refresh_snapshot(tenant_id: UUID, *, num_of_days: int, dimension: str) -> SnapshotVM:
    """Spend one live Data Export request. Raises the service/client error family."""
    snapshot = production_clarity_service().refresh(
        tenant_id=tenant_id,
        num_of_days=num_of_days,
        dimensions=[dimension] if dimension else [],
    )
    return _to_vm(snapshot)


_WINDOW_LABEL = {1: "últimas 24 h", 2: "últimas 48 h", 3: "últimas 72 h"}


def _to_vm(snapshot: SnapshotRow) -> SnapshotVM:
    return SnapshotVM(
        fetched_at=snapshot.fetched_at.strftime("%Y-%m-%d %H:%M UTC"),
        window=_WINDOW_LABEL.get(snapshot.num_of_days, f"{snapshot.num_of_days} días"),
        dimensions=" · ".join(snapshot.dimensions),
        stats=_headline_stats(snapshot.payload),
        friction=_friction_cards(snapshot.payload),
        actions=_action_items(snapshot.payload),
        traffic_note=_traffic_note(snapshot.payload),
        tables=[table for table in map(_metric_table, snapshot.payload) if table.rows],
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
        ["Sesiones", f"{sessions:,}"],
        ["Sesiones bot", f"{bots:,}"],
        ["Usuarios únicos", f"{users:,}"],
    ]
    engagement = _metric_rows(payload, _ENGAGEMENT_METRIC)
    if engagement:
        stats.append(["Tiempo activo", _format_seconds(_sum_of(engagement, "activeTime"))])
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
            affected = f"{pct:g}% de sesiones" if pct else ""
        cards.append(
            FrictionCardVM(
                label=label, total=f"{total:,}", affected=affected, status=status, hint=hint
            )
        )
    return cards


def _action_items(payload: list[dict]) -> list[ActionItemVM]:
    """Per-URL recommendations, worst first. Only rows with actual events qualify —
    an empty list means the window really had no friction."""
    scored: list[tuple[int, int, ActionItemVM]] = []
    for name, (label, _hint, advice) in _FRICTION_METRICS.items():
        for row in _metric_rows(payload, name):
            events = _as_int(row.get("subTotal"))
            if events <= 0:
                continue
            pct = _as_float(row.get("sessionsWithMetricPercentage"))
            sessions = _as_int(row.get("sessionsCount"))
            where = str(row.get("Url", "") or "").strip()
            severity = "alta" if (pct >= _BAD_PCT or events >= _BAD_TOTAL) else "media"
            title = f"{label} en {where}" if where else f"{label} en el sitio"
            counts = f"{events:,} eventos"
            if sessions:
                counts += f" en {sessions:,} sesiones"
            if pct:
                counts += f" ({pct:g}% afectadas)"
            item = ActionItemVM(severity=severity, title=title, detail=f"{counts}. {advice}")
            scored.append((0 if severity == "alta" else 1, -events, item))
    scored.sort(key=lambda entry: entry[:2])
    return [item for _, _, item in scored[:8]]


# Below this many human sessions, percentages are noise and the note says so.
_LOW_SAMPLE_SESSIONS = 20


def _traffic_note(payload: list[dict]) -> str:
    rows = _metric_rows(payload, _HEADLINE_METRIC)
    if not rows:
        return ""
    humans = _sum_of(rows, "totalSessionCount") - _sum_of(rows, "totalBotSessionCount")
    if 0 <= humans < _LOW_SAMPLE_SESSIONS:
        label = "1 sesión real" if humans == 1 else f"{humans} sesiones reales"
        return (
            f"Solo {label} en la ventana — con tan poco tráfico, "
            "los porcentajes no son concluyentes todavía."
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
    name = str(metric.get("metricName", ""))
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
        columns=ordered,
        rows=[[str(row.get(column, "")) for column in ordered] for row in rows_in],
    )
