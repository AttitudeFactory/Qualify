"""The team's view of «creaciones del mes» (CREAR-5, m-24848531): the real dollars next
to the creations charged, per piece and per month. The owner never sees money
(decision 8); this is a terminal report for Attitude Factory, read-only.

    uv run --no-sync python -m qualify_api.creative.creations_report --tenant <uuid>
    uv run --no-sync python -m qualify_api.creative.creations_report --tenant <uuid> \
        --month 2026-10

Per piece: when it was asked, what it was, the creations and generated videos charged
(or given back), the weights and pricing versions that priced it, and the USD its vendor
calls really cost (`creative_usage_events`, every revision of the piece). Per brand and
month: creations used of the quota, videos used of theirs (founder, 2026-10-24: 4 a
month, apart from creations), USD real, and USD per creation used. With videos in the
month that USD includes them, so it is no longer comparable with the USD 0.15 a creation
covers on its own: read the pieces' lines for that.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from qualify_creative.creations import load_weights

from qualify_api.creative.creations import CHARGED


@dataclass(frozen=True)
class ChargeRow:
    brand_id: UUID
    draft_id: UUID
    revision: int
    request_kind: str
    weight: int
    status: str
    weights_version: str
    pricing_table_version: str
    period_month: date
    charged_at: datetime
    #: v2: the generated videos it used, and how many came back because a final failed.
    videos: int = 0
    videos_given_back: int = 0

    @property
    def counted(self) -> int:
        """The creations this charge still takes from the month."""
        return self.weight if self.status == CHARGED else 0

    @property
    def counted_videos(self) -> int:
        """The videos this charge still takes from the month."""
        if self.status != CHARGED:
            return 0
        return max(self.videos - self.videos_given_back, 0)


@dataclass(frozen=True)
class PieceLine:
    draft_id: UUID
    first_charged_at: datetime
    request_kind: str
    creations_charged: int
    creations_refunded: int
    usd_real: Decimal
    versions: str
    videos_charged: int = 0
    videos_refunded: int = 0


@dataclass(frozen=True)
class MonthLine:
    brand_id: UUID
    period_month: date
    creations_used: int
    quota: int
    usd_real: Decimal
    videos_used: int = 0
    video_quota: int = 0

    @property
    def usd_per_creation(self) -> Decimal | None:
        if not self.creations_used:
            return None
        return (self.usd_real / self.creations_used).quantize(Decimal("0.001"))


def build_report(
    charges: Sequence[ChargeRow],
    usd_by_draft: dict[UUID, Decimal],
    *,
    quota: int,
    video_quota: int = 0,
) -> tuple[list[PieceLine], list[MonthLine]]:
    """Fold the charges into one line per piece and one per brand and month."""
    by_draft: dict[UUID, list[ChargeRow]] = defaultdict(list)
    for row in charges:
        by_draft[row.draft_id].append(row)
    pieces: list[PieceLine] = []
    months: dict[tuple[UUID, date], list[ChargeRow]] = defaultdict(list)
    for draft_id, rows in by_draft.items():
        rows.sort(key=lambda r: r.revision)
        pieces.append(
            PieceLine(
                draft_id=draft_id,
                first_charged_at=rows[0].charged_at,
                request_kind=rows[0].request_kind,
                creations_charged=sum(r.counted for r in rows),
                creations_refunded=sum(r.weight - r.counted for r in rows),
                usd_real=usd_by_draft.get(draft_id, Decimal(0)),
                versions=", ".join(
                    sorted({f"{r.weights_version}/{r.pricing_table_version}" for r in rows})
                ),
                videos_charged=sum(r.counted_videos for r in rows),
                videos_refunded=sum(r.videos - r.counted_videos for r in rows),
            )
        )
        months[(rows[0].brand_id, rows[0].period_month)].extend(rows)
    pieces.sort(key=lambda p: p.first_charged_at)
    month_lines = [
        MonthLine(
            brand_id=brand_id,
            period_month=period,
            creations_used=sum(r.counted for r in rows),
            quota=quota,
            usd_real=sum(
                (usd_by_draft.get(d, Decimal(0)) for d in {r.draft_id for r in rows}),
                Decimal(0),
            ),
            videos_used=sum(r.counted_videos for r in rows),
            video_quota=video_quota,
        )
        for (brand_id, period), rows in sorted(months.items(), key=lambda kv: kv[0][1])
    ]
    return pieces, month_lines


def render(pieces: Iterable[PieceLine], months: Iterable[MonthLine]) -> str:
    lines = ["Piezas (creaciones cobradas / devueltas, USD real):"]
    for p in pieces:
        refunded = f" (devueltas {p.creations_refunded})" if p.creations_refunded else ""
        videos = ""
        if p.videos_charged or p.videos_refunded:
            back = f", devueltos {p.videos_refunded}" if p.videos_refunded else ""
            videos = f"  videos {p.videos_charged}{back}"
        lines.append(
            f"  {p.first_charged_at:%Y-%m-%d %H:%M}  {str(p.draft_id)[:8]}  "
            f"{p.request_kind:<16} {p.creations_charged:>3}{refunded}{videos}  "
            f"USD {p.usd_real:.4f}  [{p.versions}]"
        )
    lines.append("Meses:")
    for m in months:
        per = f"USD {m.usd_per_creation} por creación" if m.usd_per_creation else "—"
        lines.append(
            f"  {m.period_month:%Y-%m}  marca {str(m.brand_id)[:8]}  "
            f"{m.creations_used} de {m.quota} creaciones  "
            f"{m.videos_used} de {m.video_quota} videos  USD {m.usd_real:.4f}  {per}"
        )
    return "\n".join(lines)


def _fetch(tenant_id: UUID, month: date | None) -> tuple[list[ChargeRow], dict[UUID, Decimal]]:
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import func, select

    from qualify_api.creative.models import CreationCharge, CreativeUsageEvent

    with tenant_session(tenant_id) as session:
        query = select(CreationCharge)
        if month is not None:
            query = query.where(CreationCharge.period_month == month)
        charges = [
            ChargeRow(
                brand_id=c.brand_id,
                draft_id=c.draft_id,
                revision=c.revision,
                request_kind=c.request_kind,
                weight=c.weight,
                status=c.status,
                weights_version=c.weights_version,
                pricing_table_version=c.pricing_table_version,
                period_month=c.period_month,
                charged_at=c.charged_at,
                videos=c.videos,
                videos_given_back=len(c.final_refunded_assets or ()),
            )
            for c in session.scalars(query)
        ]
        drafts = {c.draft_id for c in charges}
        usd: dict[UUID, Decimal] = {}
        if drafts:
            for draft_id, total in session.execute(
                select(CreativeUsageEvent.draft_id, func.sum(CreativeUsageEvent.cost_usd))
                .where(CreativeUsageEvent.draft_id.in_(drafts))
                .group_by(CreativeUsageEvent.draft_id)
            ):
                usd[draft_id] = Decimal(total or 0)
    return charges, usd


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Creaciones del mes: USD real (equipo).")
    parser.add_argument("--tenant", required=True, type=UUID)
    parser.add_argument("--month", help="YYYY-MM (default: every month)")
    args = parser.parse_args(argv)
    month = None
    if args.month:
        parsed = datetime.strptime(args.month, "%Y-%m").replace(tzinfo=UTC)
        month = date(parsed.year, parsed.month, 1)
    charges, usd = _fetch(args.tenant, month)
    weights = load_weights()
    pieces, months = build_report(
        charges, usd, quota=weights.monthly_quota, video_quota=weights.monthly_video_quota
    )
    print(render(pieces, months))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
