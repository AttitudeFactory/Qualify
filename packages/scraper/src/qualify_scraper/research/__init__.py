"""Research-only tooling. NOT part of the Parte 2 production ingestion path.

Nothing under `qualify_scraper.research` may be imported by production code, and
nothing here may be imported by `qualify_scraper.client`, `.parsers` or `.extract`.
The namespace is the enforcement: modules here depend on `yt-dlp`, an external tool
that tracks an adversarial, undocumented target and will break without warning.

`yt-dlp` is invoked as a **binary via subprocess**, never imported, so it does not
need to be in the workspace venv and **no `uv sync` is required to run this package**
— see `harvest.py`'s "Running it" note for why a group sync must not be used here.
"""

from qualify_scraper.research.harvest import (
    AccountProfile,
    FetchFailure,
    HarvestedPost,
    HarvestReport,
    PostRef,
    VideoFetcher,
    YtDlpFetcher,
    harvest_corpus,
)

__all__ = [
    "AccountProfile",
    "FetchFailure",
    "HarvestReport",
    "HarvestedPost",
    "PostRef",
    "VideoFetcher",
    "YtDlpFetcher",
    "harvest_corpus",
]
