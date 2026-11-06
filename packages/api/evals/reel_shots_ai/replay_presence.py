"""VE-05: re-resolve people/faces of an exported run with main's per-frame rule. No model call.

The v8 rows of VE-05 were written (2026-11-06 ~04:07 UTC) before the final coverage rule
(`PRESENCE_RULE_VERSION`, commit 95277026) landed, so their stored per-shot labels follow an
intermediate rule. The model's per-frame verdicts are stored (`reel_sheet.presence.frames`),
so this script applies `resolve_presence` to them again and writes a results JSON for
`score.py`. The group-level summary the model also returned is not stored: it is derived from
the group's frames («si» in any frame → observed; all «no» → not_observed; else unknown).

Reads the LOCAL dev database only (`docker exec qualify-postgres-1 psql`, one SELECT per reel,
read-only), never production. Usage:

    uv run --no-sync python packages/api/evals/reel_shots_ai/replay_presence.py \
        results/ve05-20261105-v8.json results/ve05-20261105-v8-replay.json
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from qualify_api.referentes import reel_analysis_ai as ai

_UUID = re.compile(r"^[0-9a-f-]{36}$")


def _presence_row(analysis_id: str) -> dict[str, Any]:
    if not _UUID.match(analysis_id):
        raise ValueError(f"not an analysis id: {analysis_id!r}")
    sql = (
        "select row_to_json(t) from (select reel_sheet->'presence'->'frames' f, "
        "reel_sheet->'groups'->'members' g from public_reel_analyses "
        f"where id = '{analysis_id}') t"
    )
    out = subprocess.run(
        ["docker", "exec", "qualify-postgres-1", "psql", "-U", "qualify_owner", "-d", "qualify"]
        + ["-At", "-c", sql],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.strip()
    row = json.loads(out) if out else None
    if not row or not isinstance(row.get("f"), dict) or not isinstance(row.get("g"), list):
        raise SystemExit(
            f"{analysis_id}: sin fila o sin reel_sheet.presence.frames / groups en la base "
            "local; ¿es la misma base donde se corrió el análisis?"
        )
    return row


def replay_reel(item: dict[str, Any], frames: dict[str, Any], groups: list[list[int]]) -> None:
    """Overwrite `people_presence` / `visible_faces` of each shot in `item` (in place)."""
    post_id = item.get("post_id")
    times: dict[int, list[float]] = {}
    for s in item["shots"]:
        if "frame_times_s" not in s:
            raise SystemExit(f"{post_id}: el plano {s.get('shot_index')} no trae frame_times_s")
        times[s["shot_index"]] = s["frame_times_s"]
    for shot in item["shots"]:
        index = shot["shot_index"]
        group = next((g for g in groups if index in g), None)
        if group is None or any(i not in times for i in group):
            raise SystemExit(f"{post_id}: el plano {index} no está en un grupo válido ({groups})")
        labels = [f"{i:02d}-{m}" for i in group for m in range(len(times[i]))]
        own = [label for label in labels if label.startswith(f"{index:02d}-")]
        status: dict[str, str] = {}
        for key in ("faces", "people"):
            verdicts: dict[str, str] = {}
            for label in labels:
                frame = frames.get(label, {})
                value = frame.get(key)
                if key == "people" and frame.get("faces") == "si":
                    value = "si"  # a visible face is a person
                if value:
                    verdicts[label] = value
            values = set(verdicts.values())
            summary = (
                "observed" if "si" in values else "not_observed" if values == {"no"} else "unknown"
            )
            status[key], _source = ai.resolve_presence(
                summary,
                verdicts,
                own,
                bool(labels),
                own_times=list(times[index]),
                span=(shot["start_s"], shot["end_s"]),
            )
        if status["faces"] == "observed":
            status["people"] = "observed"
        shot["people_presence"], shot["visible_faces"] = status["people"], status["faces"]


def main(argv: list[str]) -> int:
    source, target = Path(argv[0]), Path(argv[1])
    data = json.loads(source.read_text(encoding="utf-8"))
    out = copy.deepcopy(data)
    for item in out["reels"]:
        analysis = item.get("analysis") or {}
        if analysis.get("status") != "ok":
            continue
        row = _presence_row(analysis["id"])
        replay_reel(item, row["f"], row["g"])
    out["run"] = f"{data['run']}-replay"
    out["note"] = (
        f"Model output only. Same v8 model answers as {source.name}; people/faces per shot "
        f"re-resolved offline with main's resolve_presence ({ai.PRESENCE_RULE_VERSION}, commit "
        "95277026) over the per-frame verdicts stored in reel_sheet.presence. The group-level "
        "summary is not stored, so it is derived from the group's frames."
    )
    target.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
