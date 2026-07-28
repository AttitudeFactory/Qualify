#!/usr/bin/env python3
"""Append a timestamped finding to a session-state or notes file.

Append-only by construction: the target file is opened in append mode and never
read or rewritten, so any agent may record a finding into a file whose other
sections belong to someone else without risking a clobber.

Usage:
    uv run .claude/skills/durable-findings/scripts/record_finding.py \
        --file .claude/sprint-state-2026-07-26-c04-inflight.md \
        --agent pipeline \
        --title "Meta soft-404 on /documentation/graph-api/*" \
        --body "Returns HTTP 200 with a page-not-found body."
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

HEADING = "## Findings recorded by agents (append-only)"


def build_entry(agent: str, title: str, body: str, *, now: datetime) -> str:
    """Render one finding as a markdown block. Pure — easy to test."""
    stamp = now.strftime("%Y-%m-%d %H:%M")
    lines = [f"### [{stamp}] {agent} — {title}", "", body.strip(), "", ""]
    return "\n".join(lines)


def record(target: Path, agent: str, title: str, body: str, *, now: datetime) -> None:
    """Append the entry to `target`, creating the file and section heading if absent."""
    target.parent.mkdir(parents=True, exist_ok=True)
    needs_heading = not target.exists() or HEADING not in target.read_text(encoding="utf-8")
    with target.open("a", encoding="utf-8") as handle:
        if needs_heading:
            handle.write(f"\n{HEADING}\n\n")
        handle.write(build_entry(agent, title, body, now=now))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, type=Path, help="target markdown file")
    parser.add_argument("--agent", required=True, help="who discovered it")
    parser.add_argument("--title", required=True, help="one-line summary")
    parser.add_argument("--body", required=True, help="what it changes and for whom")
    args = parser.parse_args(argv)

    record(args.file, args.agent, args.title, args.body, now=datetime.now())
    print(f"recorded finding to {args.file}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
