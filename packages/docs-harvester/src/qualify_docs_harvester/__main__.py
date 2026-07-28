"""CLI: run the harvest.

    uv run python -m qualify_docs_harvester --output ../../reference/meta-instagram-platform

Safe to re-run: the journal in the output directory is the resume point, so an
interrupted harvest continues rather than re-fetching. Scraping Meta costs them
bandwidth and us time, so resume is the default behaviour, not a flag.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from qualify_docs_harvester.crawl import DEFAULT_SEEDS, crawl
from qualify_docs_harvester.fetch import HttpFetcher


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qualify-docs-harvester")
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="corpus root; the manifest journal lives here and drives resume",
    )
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--max-pages", type=int, default=1200)
    parser.add_argument(
        "--min-interval",
        type=float,
        default=1.1,
        help="minimum seconds between requests (politeness floor, >= 1.0)",
    )
    parser.add_argument(
        "--seed",
        action="append",
        default=None,
        help="override the default seed set (repeatable)",
    )
    args = parser.parse_args(argv)

    if args.min_interval < 1.0:
        parser.error("--min-interval must be >= 1.0; we do not hammer Meta's servers")

    fetcher = HttpFetcher(min_interval=args.min_interval)
    try:
        stats = crawl(
            fetcher=fetcher,
            output_root=args.output,
            seeds=tuple(args.seed) if args.seed else DEFAULT_SEEDS,
            max_depth=args.max_depth,
            max_pages=args.max_pages,
        )
    finally:
        fetcher.close()

    print(f"harvested:            {stats.harvested}")
    print(f"duplicates (aliases): {stats.duplicate}")
    print(f"skipped out of scope: {stats.skipped_out_of_scope}")
    print(f"soft 404s:            {stats.soft_404}")
    print(f"http errors:          {stats.http_error}")
    print(f"fetch errors:         {stats.fetch_error}")
    print(f"resumed with:         {stats.resumed_from} URLs already decided")
    if stats.failures:
        print("\nfailures (not silently dropped):")
        for failure in stats.failures:
            print(f"  {failure}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
