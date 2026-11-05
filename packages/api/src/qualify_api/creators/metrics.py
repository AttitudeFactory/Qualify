"""The creator's figures — ONE versioned formula (`cm-1`, m-24946127;
`docs/diseno-modulo-creadores.md` §9).

Pure: no database, no network. The input is the reels of one read (`ReelRead`: the
counters of `public_reel_reads` plus what does not change, from `public_reels`) and the
profile figures of that read (`SnapshotFacts`); the output is the sheet (`build_sheet`)
or the side-by-side comparison of 2-4 creators (`compare`). Neither is stored: they are
recomputed from the read, so `(snapshot_id, metrics_version)` is their whole provenance.

What `cm-1` decides:

- **«Interacción» is the median, reel by reel, of (likes + comments) / views** over the
  measurable reels. Over views, not followers (a reel reaches non-followers; dividing by
  followers punishes the small creator with a reel that travels). Likes and comments
  only: the two Instagram gives of someone else's reel, so the figure will mean the same
  on TikTok. A median of ratios, so one viral reel does not drag the account's figure.
- **A measurable reel** has views > 0, counts the account did not hide, and was at least
  `MATURITY_DAYS` old when it was read (younger ones are still gaining views: the
  maturity curve is not calibrated, gate G-EDAD of ADR 34).
- **Fewer than `MIN_SAMPLE` measurable reels = `insufficient`**, never zero. Unknown is
  never zero either: hidden counts are counted apart, a missing follower count is
  `unknown`, «0 paid partnerships» reads «none declared».

Changing a definition, a threshold or a window = a new `CREATOR_METRICS_VERSION`.
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from qualify_api.referentes.reels import LIFT_HIGHLIGHT, embed_url

CREATOR_METRICS_VERSION = "cm-1"
#: A reel younger than this at read time is still gaining views: out of the medians.
MATURITY_DAYS = 3
#: Fewer measurable reels than this = `insufficient`.
MIN_SAMPLE = 3
#: A read this many days old is stale («Datos de hace N días»).
STALE_DAYS = 7
#: A comparison measures each creator over his own latest this-many measurable reels
#: (fewer when one of them has fewer, never under `MIN_SAMPLE`).
COMPARE_REELS = 12
TOP_REELS = 3
TOP_COLLABORATORS = 5
TOP_AUDIOS = 5
#: `(label, upper bound in seconds or None)`, in order.
DURATION_BUCKETS: tuple[tuple[str, float | None], ...] = (
    ("≤15 s", 15.0),
    ("16–30 s", 30.0),
    ("31–60 s", 60.0),
    ("61–90 s", 90.0),
    (">90 s", None),
)

MetricStatus = Literal["ok", "insufficient", "unknown"]

# MetricValue.note codes
NOTE_HIDDEN_COUNTS = "hidden_counts"
NOTE_YOUNG_REELS = "young_reels"
NOTE_NO_FOLLOWERS = "no_followers"
NOTE_NO_LIKES = "no_likes"
NOTE_SAME_DAY = "same_day"

# Comparison.warnings codes
WARN_STALE = "stale"  # "stale:<tracked_id>"
WARN_READS_APART = "reads_apart"
WARN_FEW_REELS = "few_reels"  # "few_reels:<tracked_id>"

#: Comparison rows, in order; the ones where more is better are highlighted.
COMPARE_ROWS = (
    "followers",
    "median_views",
    "views_per_follower",
    "engagement_rate",
    "reels_per_week",
    "standout_share",
    "paid_partnerships",
    "best_duration",
)
HIGHLIGHTED_ROWS = frozenset(
    {"median_views", "views_per_follower", "engagement_rate", "reels_per_week", "standout_share"}
)


@dataclass(frozen=True)
class MetricValue:
    key: str  # a key of §9.2
    value: float | None  # None when status != "ok"
    status: MetricStatus
    sample: int  # reels that went in
    note: str = ""  # a code: "hidden_counts", "young_reels", "no_followers"…


@dataclass(frozen=True)
class ReelRead:
    """One reel of one read — the input of every function here."""

    reel_id: str
    url: str
    taken_at: datetime
    duration_s: float | None
    views: int | None
    likes: int | None
    comments: int | None
    counts_hidden: bool
    is_paid_partnership: bool
    coauthors: tuple[str, ...] | None
    sound_id: str | None
    sound_title: str
    sound_is_original: bool | None


@dataclass(frozen=True)
class SnapshotFacts:
    """The profile side of one read (`creator_snapshots`), as the sheet needs it."""

    snapshot_id: UUID
    network: str
    handle: str
    read_at: datetime
    status: str
    followers: int | None
    full_name: str = ""
    bio: str = ""
    avatar_url: str = ""
    is_verified: bool = False
    reels_read: int = 0


@dataclass(frozen=True)
class ReelCard:
    reel_id: str
    url: str  # instagram.com/reel/<code>/ — to open
    embed_url: str  # the network's own player (referentes.reels.embed_url)
    taken_at: datetime
    duration_s: float | None
    views: int | None
    likes: int | None
    comments: int | None
    lift: float | None  # views / its own median
    is_young: bool  # < MATURITY_DAYS: «todavía sumando vistas»
    is_paid_partnership: bool
    coauthors: tuple[str, ...]
    sound_title: str


@dataclass(frozen=True)
class DurationBucket:
    label: str  # "16–30 s"
    reels: int
    median_views: MetricValue
    lift_vs_overall: float | None


@dataclass(frozen=True)
class AudioUse:
    title: str
    reels: int
    is_original: bool | None


@dataclass(frozen=True)
class CreatorSheet:
    tracked_id: UUID
    network: str
    handle: str
    full_name: str
    bio: str
    avatar_url: str  # a CDN URL; it expires: the view falls back to initials
    is_verified: bool
    snapshot_id: UUID
    snapshot_status: str  # ok | partial | private | missing | error
    read_at: datetime
    freshness_days: int
    stale: bool  # freshness_days >= STALE_DAYS
    metrics_version: str  # "cm-1"
    reels_read: int
    measurable_reels: int
    hidden_counts_reels: int
    covered_from: datetime | None
    covered_to: datetime | None
    followers: MetricValue
    median_views: MetricValue
    mean_views: MetricValue
    views_per_follower: MetricValue
    engagement_rate: MetricValue
    reels_per_week: MetricValue
    median_gap_days: MetricValue
    standout_share: MetricValue
    top_reels: tuple[ReelCard, ...]
    standout_reels: tuple[ReelCard, ...]
    best_duration: DurationBucket | None
    duration_buckets: tuple[DurationBucket, ...]
    paid_partnerships: int
    collabs: int
    collaborators: tuple[str, ...]
    top_audios: tuple[AudioUse, ...]
    #: False when no reel of the read says who it was made with (a parser-1 read): then
    #: `collabs` 0 means «unknown», not «none». Added to §10.3 (deviation, see the PR).
    collabs_known: bool = True


@dataclass(frozen=True)
class ComparedCreator:
    tracked_id: UUID
    handle: str
    read_at: datetime
    stale: bool
    #: Kept for the first UI build: the same number as `reels_used`.
    measurable_in_window: int
    #: The creator's own latest measurable reels the rows were computed on, and the dates
    #: they span (design §9.3, review 2026-11-04).
    reels_used: int = 0
    used_from: datetime | None = None
    used_to: datetime | None = None
    #: Fewer than `MIN_SAMPLE` measurable reels: his rows are «sin dato», never zero.
    few_reels: bool = False


@dataclass(frozen=True)
class ComparisonRow:
    key: str
    values: tuple[MetricValue, ...]  # same order as Comparison.creators
    best: tuple[int, ...]  # highlighted indexes; () when the row does not highlight
    highlights: bool


@dataclass(frozen=True)
class Comparison:
    creators: tuple[ComparedCreator, ...]
    window_from: datetime | None
    window_to: datetime | None
    metrics_version: str
    rows: tuple[ComparisonRow, ...]
    warnings: tuple[str, ...]  # codes: "stale:<tracked_id>", "reads_apart", "few_reels:<id>"
    #: N: how many latest measurable reels each creator is measured on. `window_from` /
    #: `window_to` are the whole span those reels cover (each creator's own span is on
    #: `ComparedCreator.used_from` / `used_to`).
    reels_per_creator: int = 0


# ---------------------------------------------------------------------------------------
# The definitions of §9.2


def _days(delta: timedelta) -> float:
    return delta.total_seconds() / 86400.0


def is_young(reel: ReelRead, read_at: datetime) -> bool:
    return _days(read_at - reel.taken_at) < MATURITY_DAYS


def is_measurable(reel: ReelRead, read_at: datetime) -> bool:
    return (
        not reel.counts_hidden
        and reel.views is not None
        and reel.views > 0
        and not is_young(reel, read_at)
    )


def measurable(reels: Sequence[ReelRead], read_at: datetime) -> list[ReelRead]:
    return [r for r in reels if is_measurable(r, read_at)]


def _note(reels: Sequence[ReelRead], read_at: datetime) -> str:
    """Why the sample is short, when the read says why: hidden counts, then young reels."""
    if any(r.counts_hidden for r in reels):
        return NOTE_HIDDEN_COUNTS
    if any(is_young(r, read_at) for r in reels):
        return NOTE_YOUNG_REELS
    return ""


def _ok(key: str, value: float, sample: int, note: str = "") -> MetricValue:
    return MetricValue(key, float(value), "ok", sample, note)


def _insufficient(key: str, sample: int, note: str = "") -> MetricValue:
    return MetricValue(key, None, "insufficient", sample, note)


def _unknown(key: str, note: str = "", sample: int = 0) -> MetricValue:
    return MetricValue(key, None, "unknown", sample, note)


def followers_metric(followers: int | None) -> MetricValue:
    if followers is None:
        return _unknown("followers")
    return _ok("followers", followers, 0)


def median_views(reels: Sequence[ReelRead], read_at: datetime) -> MetricValue:
    sample = measurable(reels, read_at)
    if len(sample) < MIN_SAMPLE:
        return _insufficient("median_views", len(sample), _note(reels, read_at))
    return _ok("median_views", statistics.median(r.views or 0 for r in sample), len(sample))


def mean_views(reels: Sequence[ReelRead], read_at: datetime) -> MetricValue:
    sample = measurable(reels, read_at)
    if len(sample) < MIN_SAMPLE:
        return _insufficient("mean_views", len(sample), _note(reels, read_at))
    return _ok("mean_views", statistics.fmean(r.views or 0 for r in sample), len(sample))


def views_per_follower(median: MetricValue, followers: int | None) -> MetricValue:
    if not followers:
        return _unknown("views_per_follower", NOTE_NO_FOLLOWERS)
    if median.status != "ok" or median.value is None:
        return MetricValue("views_per_follower", None, median.status, median.sample, median.note)
    return _ok("views_per_follower", median.value / followers, median.sample)


def engagement_rate(reels: Sequence[ReelRead], read_at: datetime) -> MetricValue:
    """Median of (likes + comments) / views over the measurable reels whose likes are
    known. A missing comment count adds nothing (Instagram sends it even when likes are
    hidden, so in practice it is always there)."""
    sample = [r for r in measurable(reels, read_at) if r.likes is not None]
    if len(sample) < MIN_SAMPLE:
        note = _note(reels, read_at) or NOTE_NO_LIKES
        return _insufficient("engagement_rate", len(sample), note)
    ratios = [((r.likes or 0) + (r.comments or 0)) / (r.views or 1) for r in sample]
    return _ok("engagement_rate", statistics.median(ratios), len(sample))


def median_gap_days(reels: Sequence[ReelRead]) -> MetricValue:
    """Median of the days between consecutive reels, by date (sorting by date shrugs off
    pinned reels leading the list)."""
    stamps = sorted(r.taken_at for r in reels)
    if len(stamps) < MIN_SAMPLE:
        return _insufficient("median_gap_days", len(stamps))
    gaps = [_days(b - a) for a, b in zip(stamps, stamps[1:], strict=False)]
    return _ok("median_gap_days", statistics.median(gaps), len(stamps))


def reels_per_week(gap: MetricValue) -> MetricValue:
    if gap.status != "ok" or gap.value is None:
        return MetricValue("reels_per_week", None, gap.status, gap.sample, gap.note)
    if gap.value <= 0:
        return _unknown("reels_per_week", NOTE_SAME_DAY, gap.sample)
    return _ok("reels_per_week", 7.0 / gap.value, gap.sample)


def _lift(reel: ReelRead, median: MetricValue) -> float | None:
    if median.status != "ok" or not median.value or reel.views is None:
        return None
    return reel.views / median.value


def standout(
    reels: Sequence[ReelRead], read_at: datetime, median: MetricValue
) -> tuple[list[ReelRead], MetricValue]:
    """`(the measurable reels with views >= LIFT_HIGHLIGHT × median, their share)`."""
    sample = measurable(reels, read_at)
    if median.status != "ok" or not median.value:
        return [], MetricValue("standout_share", None, median.status, median.sample, median.note)
    out = [r for r in sample if (r.views or 0) >= LIFT_HIGHLIGHT * median.value]
    out.sort(key=lambda r: r.views or 0, reverse=True)
    return out, _ok("standout_share", len(out) / len(sample), len(sample))


def _bucket_of(duration: float) -> str:
    for label, bound in DURATION_BUCKETS:
        if bound is None or duration <= bound:
            return label
    return DURATION_BUCKETS[-1][0]


def duration_buckets(
    reels: Sequence[ReelRead], read_at: datetime, overall: MetricValue
) -> tuple[DurationBucket, ...]:
    """The duration bands with at least one measurable reel, in band order."""
    grouped: dict[str, list[ReelRead]] = {}
    for reel in measurable(reels, read_at):
        if reel.duration_s is not None:
            grouped.setdefault(_bucket_of(reel.duration_s), []).append(reel)
    out: list[DurationBucket] = []
    for label, _ in DURATION_BUCKETS:
        members = grouped.get(label)
        if not members:
            continue
        median = median_views(members, read_at)
        lift = (
            median.value / overall.value
            if median.status == "ok" and median.value and overall.status == "ok" and overall.value
            else None
        )
        out.append(DurationBucket(label, len(members), median, lift))
    return tuple(out)


def best_duration(buckets: Sequence[DurationBucket]) -> DurationBucket | None:
    """The band with the highest median views among those with `MIN_SAMPLE` measurable
    reels; None when no band has enough."""
    usable = [b for b in buckets if b.median_views.status == "ok"]
    if not usable:
        return None
    return max(usable, key=lambda b: b.median_views.value or 0.0)


def collaborators(reels: Sequence[ReelRead], handle: str) -> tuple[int, tuple[str, ...], bool]:
    """`(reels made with another account, the most frequent ones, known)`; `known` is
    False when no reel of the read carries co-authors at all (parser 1)."""
    known = [r for r in reels if r.coauthors is not None]
    if not known:
        return 0, (), False
    counts: Counter[str] = Counter()
    made_with = 0
    for reel in known:
        others = [c for c in reel.coauthors or () if c and c != handle]
        if others:
            made_with += 1
            counts.update(dict.fromkeys(others, 1))
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return made_with, tuple(name for name, _ in ranked[:TOP_COLLABORATORS]), True


def _title_key(title: str) -> str:
    return " ".join(title.casefold().split())


def top_audios(reels: Sequence[ReelRead]) -> tuple[AudioUse, ...]:
    """Sounds used in 2 or more reels, by id (by normalized title when the id is
    missing), most used first."""
    groups: dict[str, list[ReelRead]] = {}
    for reel in reels:
        key = reel.sound_id or (f"title:{_title_key(reel.sound_title)}" if reel.sound_title else "")
        if key:
            groups.setdefault(key, []).append(reel)
    uses = [
        AudioUse(
            title=next((r.sound_title for r in members if r.sound_title), ""),
            reels=len(members),
            is_original=next(
                (r.sound_is_original for r in members if r.sound_is_original is not None), None
            ),
        )
        for members in groups.values()
        if len(members) >= 2
    ]
    uses.sort(key=lambda a: (-a.reels, a.title))
    return tuple(uses[:TOP_AUDIOS])


def freshness_days(read_at: datetime, now: datetime) -> int:
    return max(int((now - read_at).total_seconds() // 86400), 0)


def _embed_url(reel: ReelRead, network: str) -> str:
    return embed_url({"id": reel.reel_id, "network": network})


def _card(
    reel: ReelRead, network: str, handle: str, read_at: datetime, median: MetricValue
) -> ReelCard:
    return ReelCard(
        reel_id=reel.reel_id,
        url=reel.url,
        embed_url=_embed_url(reel, network),
        taken_at=reel.taken_at,
        duration_s=reel.duration_s,
        views=reel.views,
        likes=reel.likes,
        comments=reel.comments,
        lift=_lift(reel, median),
        is_young=is_young(reel, read_at),
        is_paid_partnership=reel.is_paid_partnership,
        # the other accounts on the reel (the stored list names every account on it)
        coauthors=tuple(c for c in reel.coauthors or () if c != handle),
        sound_title=reel.sound_title,
    )


def build_sheet(
    tracked_id: UUID, snapshot: SnapshotFacts, reels: Sequence[ReelRead], *, now: datetime
) -> CreatorSheet:
    """The creator's sheet from one read (`cm-1`)."""
    read_at = snapshot.read_at
    sample = measurable(reels, read_at)
    median = median_views(reels, read_at)
    gap = median_gap_days(reels)
    standouts, share = standout(reels, read_at, median)
    buckets = duration_buckets(reels, read_at, median)
    collabs, names, collabs_known = collaborators(reels, snapshot.handle)
    with_views = sorted(
        (r for r in reels if r.views is not None and not r.counts_hidden),
        key=lambda r: r.views or 0,
        reverse=True,
    )
    days = freshness_days(read_at, now)
    stamps = [r.taken_at for r in reels]
    return CreatorSheet(
        tracked_id=tracked_id,
        network=snapshot.network,
        handle=snapshot.handle,
        full_name=snapshot.full_name,
        bio=snapshot.bio,
        avatar_url=snapshot.avatar_url,
        is_verified=snapshot.is_verified,
        snapshot_id=snapshot.snapshot_id,
        snapshot_status=snapshot.status,
        read_at=read_at,
        freshness_days=days,
        stale=days >= STALE_DAYS,
        metrics_version=CREATOR_METRICS_VERSION,
        reels_read=snapshot.reels_read or len(reels),
        measurable_reels=len(sample),
        hidden_counts_reels=sum(1 for r in reels if r.counts_hidden),
        covered_from=min(stamps) if stamps else None,
        covered_to=max(stamps) if stamps else None,
        followers=followers_metric(snapshot.followers),
        median_views=median,
        mean_views=mean_views(reels, read_at),
        views_per_follower=views_per_follower(median, snapshot.followers),
        engagement_rate=engagement_rate(reels, read_at),
        reels_per_week=reels_per_week(gap),
        median_gap_days=gap,
        standout_share=share,
        top_reels=tuple(
            _card(r, snapshot.network, snapshot.handle, read_at, median)
            for r in with_views[:TOP_REELS]
        ),
        standout_reels=tuple(
            _card(r, snapshot.network, snapshot.handle, read_at, median) for r in standouts
        ),
        best_duration=best_duration(buckets),
        duration_buckets=buckets,
        paid_partnerships=sum(1 for r in reels if r.is_paid_partnership),
        collabs=collabs,
        collaborators=names,
        top_audios=top_audios(reels),
        collabs_known=collabs_known,
    )


# ---------------------------------------------------------------------------------------
# Comparing 2-4 creators (§9.3)


@dataclass(frozen=True)
class CompareEntry:
    tracked_id: UUID
    snapshot: SnapshotFacts
    reels: Sequence[ReelRead]


def reels_per_creator(entries: Sequence[CompareEntry]) -> int:
    """N = min(`COMPARE_REELS`, the fewest measurable reels among the creators that have
    at least `MIN_SAMPLE`). A creator under `MIN_SAMPLE` does not shrink N for the others:
    he is flagged `few_reels` and his rows are «sin dato» (review 2026-11-04)."""
    if not entries:
        return 0
    counts = [len(measurable(e.reels, e.snapshot.read_at)) for e in entries]
    enough = [c for c in counts if c >= MIN_SAMPLE]
    if not enough:
        return MIN_SAMPLE
    return min(COMPARE_REELS, min(enough))


def latest_measurable(entry: CompareEntry, count: int) -> list[ReelRead]:
    """The creator's own latest `count` measurable reels, newest first."""
    sample = measurable(entry.reels, entry.snapshot.read_at)
    sample.sort(key=lambda r: r.taken_at, reverse=True)
    return sample[:count]


def _best(values: Sequence[MetricValue]) -> tuple[int, ...]:
    """The indexes of the highest `ok` value (all of them on a tie); () when fewer than
    two values are comparable — an unknown never wins."""
    ok = [(i, v.value) for i, v in enumerate(values) if v.status == "ok" and v.value is not None]
    if len(ok) < 2:
        return ()
    top = max(value for _, value in ok)
    return tuple(i for i, value in ok if value == top)


def _pace_reels(entry: CompareEntry, reels: Sequence[ReelRead]) -> list[ReelRead]:
    """Every reel of the read from the oldest one compared on — hidden counts and reels
    younger than `MATURITY_DAYS` included: they count for how often he posts."""
    if not reels:
        return list(entry.reels)
    start = min(r.taken_at for r in reels)
    return [r for r in entry.reels if r.taken_at >= start]


def _row_values(entry: CompareEntry, reels: Sequence[ReelRead]) -> dict[str, MetricValue]:
    read_at = entry.snapshot.read_at
    paid = (
        _ok("paid_partnerships", sum(1 for r in reels if r.is_paid_partnership), len(reels))
        if len(reels) >= MIN_SAMPLE
        else _insufficient("paid_partnerships", len(reels))
    )
    median = median_views(reels, read_at)
    _, share = standout(reels, read_at, median)
    best = best_duration(duration_buckets(reels, read_at, median))
    return {
        "followers": followers_metric(entry.snapshot.followers),
        "median_views": median,
        "views_per_follower": views_per_follower(median, entry.snapshot.followers),
        "engagement_rate": engagement_rate(reels, read_at),
        "reels_per_week": reels_per_week(median_gap_days(_pace_reels(entry, reels))),
        "standout_share": share,
        "paid_partnerships": paid,
        # value = its lift over the creator's own median; note = the band's label
        "best_duration": MetricValue(
            "best_duration",
            best.lift_vs_overall if best is not None else None,
            "ok" if best is not None and best.lift_vs_overall is not None else "insufficient",
            best.reels if best is not None else 0,
            best.label if best is not None else "",
        ),
    }


def compare(entries: Sequence[CompareEntry], *, now: datetime) -> Comparison:
    """2-4 creators side by side, each measured over his OWN latest N measurable reels
    (the same N for all, `reels_per_creator`) — so a creator who posts little is not
    squeezed into a date window that holds one or two of his reels. Row by row; the best
    `ok` value of the rows where more is better is highlighted (ties: all). No summed
    score, no ranking; unknown is never zero."""
    count = reels_per_creator(entries)
    per_creator: list[dict[str, MetricValue]] = []
    creators: list[ComparedCreator] = []
    warnings: list[str] = []
    spans: list[datetime] = []
    for entry in entries:
        reels = latest_measurable(entry, count)
        per_creator.append(_row_values(entry, reels))
        stale = freshness_days(entry.snapshot.read_at, now) >= STALE_DAYS
        if stale:
            warnings.append(f"{WARN_STALE}:{entry.tracked_id}")
        few = len(reels) < MIN_SAMPLE
        if few:
            warnings.append(f"{WARN_FEW_REELS}:{entry.tracked_id}")
        stamps = [r.taken_at for r in reels]
        spans += stamps
        creators.append(
            ComparedCreator(
                tracked_id=entry.tracked_id,
                handle=entry.snapshot.handle,
                read_at=entry.snapshot.read_at,
                stale=stale,
                measurable_in_window=len(reels),
                reels_used=len(reels),
                used_from=min(stamps) if stamps else None,
                used_to=max(stamps) if stamps else None,
                few_reels=few,
            )
        )
    reads = [e.snapshot.read_at for e in entries]
    if reads and max(reads) - min(reads) > timedelta(days=STALE_DAYS):
        warnings.append(WARN_READS_APART)
    rows: list[ComparisonRow] = []
    for key in COMPARE_ROWS:
        values = tuple(values[key] for values in per_creator)
        highlights = key in HIGHLIGHTED_ROWS
        rows.append(ComparisonRow(key, values, _best(values) if highlights else (), highlights))
    return Comparison(
        creators=tuple(creators),
        window_from=min(spans) if spans else None,
        window_to=max(spans) if spans else None,
        metrics_version=CREATOR_METRICS_VERSION,
        rows=tuple(rows),
        warnings=tuple(warnings),
        reels_per_creator=count,
    )


__all__ = [
    "COMPARE_REELS",
    "CREATOR_METRICS_VERSION",
    "MATURITY_DAYS",
    "MIN_SAMPLE",
    "STALE_DAYS",
    "AudioUse",
    "CompareEntry",
    "Comparison",
    "ComparedCreator",
    "ComparisonRow",
    "CreatorSheet",
    "DurationBucket",
    "MetricStatus",
    "MetricValue",
    "ReelCard",
    "ReelRead",
    "SnapshotFacts",
    "build_sheet",
    "compare",
    "latest_measurable",
    "reels_per_creator",
]
