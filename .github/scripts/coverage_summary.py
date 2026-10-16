"""Per-package coverage table (Markdown) from a `coverage json` report.

Used by `.github/workflows/ci.yml` to feed `$GITHUB_STEP_SUMMARY` and the sticky PR
comment. Pure stdlib, no exit code other than 0: coverage informs, it does not block.

    uv run coverage json -o coverage.json
    uv run python .github/scripts/coverage_summary.py coverage.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Display name -> path prefix (relative to the repo root, as `coverage json` writes them).
# Order matters only for the table; a file matches the first prefix it starts with.
PACKAGES: dict[str, str] = {
    "qualify_api": "packages/api/src/",
    "qualify_shared": "packages/shared/src/",
    "qualify_scraper": "packages/scraper/src/",
    "qualify_creative": "packages/creative/src/",
    "Qualify (Reflex app)": "Qualify/",
}


def _pct(covered: int, statements: int) -> str:
    if statements == 0:
        return "n/a"
    return f"{100.0 * covered / statements:.1f}%"


def _row(label: str, files: int, statements: int, covered: int) -> str:
    return f"| {label} | {files} | {statements} | {covered} | {_pct(covered, statements)} |"


def summarize(report: dict) -> str:
    """Return the Markdown table for one `coverage json` payload."""
    totals: dict[str, list[int]] = {name: [0, 0, 0] for name in PACKAGES}
    other = [0, 0, 0]
    for filename, data in report.get("files", {}).items():
        summary = data.get("summary", {})
        row = [
            int(summary.get("covered_lines", 0)),
            int(summary.get("num_statements", 0)),
            1,
        ]
        for name, prefix in PACKAGES.items():
            if filename.startswith(prefix):
                bucket = totals[name]
                break
        else:
            bucket = other
        for i, value in enumerate(row):
            bucket[i] += value

    lines = [
        "## Coverage (offline tests, `-m 'not integration and not db and not slow'`)",
        "",
        "| Package | Files | Statements | Covered | Coverage |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, (covered, statements, files) in totals.items():
        lines.append(_row(f"`{name}`", files, statements, covered))
    if other[2]:
        lines.append(_row("other", other[2], other[1], other[0]))
    grand = report.get("totals", {})
    g_cov = int(grand.get("covered_lines", 0))
    g_stm = int(grand.get("num_statements", 0))
    lines.append(f"| **total** | | {g_stm} | {g_cov} | **{_pct(g_cov, g_stm)}** |")
    lines.append("")
    lines.append(
        "_`db` tests run later in the same `test` job, without coverage; `integration` "
        "tests never run in CI._"
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="path to coverage.json")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        sys.stdout.write(f"## Coverage\n\n_No coverage report available ({exc})._\n")
        return 0
    sys.stdout.write(summarize(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
