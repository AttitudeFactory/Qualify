"""The watched list of the eval, built by the PRODUCT code from a frozen snapshot.

`weekly_snapshot.json` holds the 25 public TikTok videos the pilot's weekly read kept
(exported read-only from production on 2026-11-15: network, post id, views, posting
date, tags and each tag's stored kind). This script replays what production will hold
after the next weekly read and asks the repository for the companions, as
`creative_state` does for «Sugerir con IA»:

1. every tag goes through `weekly.readable_tag` (what `_video_tags` keeps since
   m-25032581 — `tachira_venezuela🇻🇪` is dropped);
2. the sightings are stored in `MemoryHashtagRepository` (`record_post_sightings`);
3. the kinds the snapshot already had (topic / place / generic / noise) are applied as
   they were decided (`classified_by="ai"`: an assumption — the export does not say who
   decided; it only keeps a rule from overriding them), then
   `weekly.rule_classifications` settles what the snapshot left `unknown`;
4. `companions(rubro tags, now=2026-11-15)` with the product defaults (topic + unknown
   kinds, `hashtag_weekly` source, 90 days, 20 tags).

It writes `watched` (that list) and `watched_without_0818` (the same, minus the video of
2026-08-18 the 90-day window drops from 2026-11-16) into `cases.json`. No network, no
database:

    uv run --no-sync python packages/api/evals/hashtag_caption/build_watched.py
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from qualify_api.hashtags import weekly
from qualify_api.hashtags.repository import (
    Classification,
    MemoryHashtagRepository,
    NewPostSighting,
)

HERE = Path(__file__).resolve().parent
SNAPSHOT = HERE / "weekly_snapshot.json"
CASES = HERE / "cases.json"
TENANT = UUID(int=1)
RUBRO = ("shawarma", "comidaarabe", "sancristobaltachira", "tachira", "ensaladas")
NOW = datetime(2026, 11, 15, 23, 59, tzinfo=UTC)
DROPPED_POST = "7675191685508353287"  # posted 2026-08-18, out of the window on 2026-11-16


def build(videos: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    repo = MemoryHashtagRepository()
    sightings: list[NewPostSighting] = []
    known: list[Classification] = []
    dropped: list[str] = []
    for video in videos:
        posted = datetime.fromisoformat(video["posted_at"])
        for raw, kind in zip(video["tags"], video["kinds"], strict=True):
            tag = weekly.readable_tag(raw)
            if tag is None:
                dropped.append(raw)
                continue
            sightings.append(
                NewPostSighting(
                    tag=tag,
                    network=video["network"],
                    post_id=video["post_id"],
                    source=weekly.SOURCE,
                    source_ref=weekly.SOURCE_REF,
                    parser_version=weekly.PARSER_VERSION,
                    posted_at=posted,
                    views=video["views"],
                )
            )
            if kind != "unknown":
                known.append(Classification(tag, kind, classified_by="ai"))
    repo.record_post_sightings(TENANT, sightings)
    repo.apply_classifications(TENANT, known)
    repo.apply_classifications(TENANT, weekly.rule_classifications(sightings))
    companions = repo.companions(TENANT, RUBRO, now=NOW)
    rows = [{"tag": c.tag, "views": c.views, "posts": c.posts, "kind": c.kind} for c in companions]
    return rows, dropped


def main() -> None:
    videos = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    watched, dropped = build(videos)
    without, _ = build([v for v in videos if v["post_id"] != DROPPED_POST])
    data = json.loads(CASES.read_text(encoding="utf-8"))
    data["watched"] = watched
    data["watched_without_0818"] = without
    data.pop("watched_all", None)
    data["watched_doc"] = (
        "Built by build_watched.py through the product code (readable_tag, "
        "rule_classifications, MemoryHashtagRepository.companions) from weekly_snapshot.json, "
        "now=2026-11-15. Production's list moves every week."
    )
    CASES.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("dropped by readable_tag:", dropped)
    for name, rows in (("watched", watched), ("without 2026-08-18", without)):
        print(
            f"{name} ({len(rows)}):",
            ", ".join(f"{w['tag']}({w['posts']},{w['kind']})" for w in rows),
        )


if __name__ == "__main__":
    main()
