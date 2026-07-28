# qualify-docs-harvester

Resumable, rate-limited harvester for Meta developer documentation into a local
markdown corpus. See module docstrings for the two non-obvious behaviours:
`urls.py` (why `/docs/` and `/documentation/` must not be rewritten into each
other) and `soft404.py` (why HTTP 200 is not evidence a page exists).

```bash
uv run pytest                                     # offline, no network
uv run python -m qualify_docs_harvester --output ../../reference/meta-instagram-platform
```
