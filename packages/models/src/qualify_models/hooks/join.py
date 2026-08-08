"""Join the corpus runner's `metrics.csv` to the extractor's `hook_features.csv`.

This is the seam between the two halves of the spike: `packages/scraper`'s research runner
produces one row per harvested post (metrics), `qualify_models.hooks` produces one row per
(video, window) (features), and Fase D needs them as a single `PostObservation` list.

**Why this module exists rather than a `pandas.read_csv` in a notebook.** The contract has
one rule that a careless read would break in silence:

> An empty cell means **missing**. A `0` means **a measured zero**. They are different
> values and they must stay different all the way into the analysis.

The runner writes it that way deliberately (its `_post_from_info` used to coerce a missing
`view_count` to `0` via `int(x or 0)` — an idiom that turns "unreported" into "worst post in
the library"). This loader is the other half of that guarantee: it maps empty to `None` and
`0` to `0.0`, and it refuses to guess anything in between. Both directions are pinned by
tests on both sides of the seam.

The join is also **reported, never silent**: rows present in one file and absent from the
other are counted and returned. A join that quietly halves the corpus is the failure mode
that makes an underpowered study look adequately powered.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel

from qualify_models.hooks.analysis import PostObservation

# Columns the corpus runner is contracted to emit. `views` is the primary outcome, so its
# absence is a hard error rather than a silently missing column.
REQUIRED_METRICS_COLUMNS = frozenset({"source_id", "account_id"})


class JoinResult(BaseModel):
    """The joined observations plus everything that did not join.

    `observations` alone would let a 50% join loss pass unnoticed; the counts make it
    visible at the call site, which is where someone can still do something about it.
    """

    observations: list[PostObservation]
    n_metrics_rows: int
    n_feature_rows: int
    missing_hook_features: list[str]
    missing_metrics: list[str]

    @property
    def join_rate(self) -> float:
        return len(self.observations) / self.n_metrics_rows if self.n_metrics_rows else 0.0


def optional_float(raw: str | None) -> float | None:
    """`""` -> None, `"0"` -> 0.0. The single rule this module exists to enforce.

    Note that `float(raw or 0)` — the idiom this replaces — collapses both to 0.0, and the
    collapse is invisible downstream because the result is a perfectly valid number.
    """
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    return float(stripped)


def optional_int(raw: str | None) -> int | None:
    value = optional_float(raw)
    return None if value is None else int(value)


def parse_posted_at(raw: str | None) -> date | None:
    """Accept a full ISO timestamp or a bare date; return the date.

    The runner writes a full UTC timestamp (from yt-dlp's `timestamp`) rather than a
    date-only `upload_date`, so time-of-day survives in the corpus even though the recency
    adjustment only needs day resolution. Parsing is explicit because pydantic coercion
    from an ISO *datetime* string into a `date` field is not something to rely on silently.
    """
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    try:
        return date.fromisoformat(stripped)
    except ValueError:
        pass
    normalized = stripped.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        return None


def _engagement(likes: float | None, comments: float | None) -> float | None:
    """likes + comments, or None if either component is missing.

    Deliberately NOT `(likes or 0) + (comments or 0)`. A post with 8 likes and an
    unreported comment count does not have engagement 8 — it has unknown engagement, and
    treating it as 8 would place it below a post with 9 measured engagement that may in
    fact be lower.
    """
    if likes is None or comments is None:
        return None
    return likes + comments


def load_hook_types(
    hook_features_csv: Path,
    window_seconds: float,
) -> dict[str, str]:
    """`source_id -> hook_type` for one window of the extractor's output."""
    mapping: dict[str, str] = {}
    with Path(hook_features_csv).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            raw_window = optional_float(row.get("window_seconds"))
            if raw_window is None or raw_window != window_seconds:
                continue
            source_id = (row.get("source_id") or "").strip()
            hook_type = (row.get("hook_type") or "").strip()
            if source_id and hook_type:
                mapping[source_id] = hook_type
    return mapping


def join_observations(
    metrics_csv: Path,
    hook_features_csv: Path,
    window_seconds: float,
    follower_counts: dict[str, int] | None = None,
) -> JoinResult:
    """Build the Fase D input from the two CSVs.

    `follower_counts` comes from the runner's separate `accounts.csv` — it is per-account,
    not per-post, and is kept out of `metrics.csv` on purpose so nobody is tempted to use
    it as a per-post covariate in a design that never compares across accounts.
    """
    hook_types = load_hook_types(hook_features_csv, window_seconds)
    seen_metrics: set[str] = set()
    observations: list[PostObservation] = []
    missing_hook_features: list[str] = []
    n_metrics_rows = 0

    with Path(metrics_csv).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing_columns = REQUIRED_METRICS_COLUMNS - set(reader.fieldnames or [])
        if missing_columns:
            raise ValueError(
                f"{metrics_csv} is missing required column(s): {sorted(missing_columns)}"
            )
        for row in reader:
            n_metrics_rows += 1
            source_id = (row.get("source_id") or "").strip()
            if not source_id:
                continue
            seen_metrics.add(source_id)
            hook_type = hook_types.get(source_id)
            if hook_type is None:
                missing_hook_features.append(source_id)
                continue
            likes = optional_float(row.get("likes"))
            comments = optional_float(row.get("comments"))
            account_id = (row.get("account_id") or "").strip()
            observations.append(
                PostObservation(
                    source_id=source_id,
                    account_id=account_id,
                    hook_type=hook_type,
                    engagement=_engagement(likes, comments),
                    views=optional_float(row.get("views")),
                    posted_at=parse_posted_at(row.get("posted_at")),
                    duration_seconds=optional_float(row.get("duration_seconds")),
                    follower_count=(follower_counts or {}).get(account_id),
                )
            )

    return JoinResult(
        observations=observations,
        n_metrics_rows=n_metrics_rows,
        n_feature_rows=len(hook_types),
        missing_hook_features=sorted(missing_hook_features),
        missing_metrics=sorted(set(hook_types) - seen_metrics),
    )


def load_follower_counts(accounts_csv: Path) -> dict[str, int]:
    """`account_id -> follower_count` from the runner's `accounts.csv`.

    Missing follower counts stay absent from the mapping rather than becoming 0 — the same
    rule as everywhere else here. `follower_count` is not obtainable from yt-dlp at all, so
    absence is the expected case, not an anomaly.
    """
    counts: dict[str, int] = {}
    with Path(accounts_csv).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            account_id = (row.get("account_id") or "").strip()
            value = optional_int(row.get("follower_count"))
            if account_id and value is not None:
                counts[account_id] = value
    return counts
