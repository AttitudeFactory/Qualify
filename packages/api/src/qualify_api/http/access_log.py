"""Access-log redaction for the public media route (QUA-68).

**Why `logger.info(token)` avoidance inside the route is not enough.** Nothing in
`public_media_routes.py` ever logs the token — but that was never the leak. Verified against
the installed `uvicorn` (`.venv/Lib/site-packages/uvicorn/protocols/http/h11_impl.py`, the
call this module targets):

```python
self.access_logger.info(
    '%s - "%s %s HTTP/%s" %d',
    get_client_addr(self.scope), self.scope["method"],
    get_path_with_query_string(self.scope), http_version, status_code,
)
```

This call lives in uvicorn's OWN protocol implementation, entirely outside the ASGI app —
it fires whether or not our route handler logs anything, for every request, on the
`uvicorn.access` logger, with the full request path (token included) as `record.args[2]`.
There is no hook inside a FastAPI route that can suppress it; the only place to intervene is
the `uvicorn.access` logger itself.

**Why this is a `logging.Filter`, not `access_log=False`.** Disabling uvicorn's access log
outright would blind every OTHER route too — exactly the "no desactivar innecesariamente el
logging HTTP de toda la aplicación" this ticket forbids. A `Filter` runs before formatting
and can rewrite `record.args` in place; every other path keeps logging exactly as before,
untouched.
"""

from __future__ import annotations

import logging
import re

# `get_path_with_query_string` (uvicorn) includes the query string too, though this route
# never uses one — matched regardless, since a future caller appending `?x=y` to the path
# must not defeat the redaction.
_TOKEN_PATH_PATTERN = re.compile(r"^(/public/media/)[^\s?]+")
_REDACTED = r"\1<redacted>"

# The position of the path within `record.args` for uvicorn's access-log call, verified
# against the actual call above — NOT guessed from documentation. If a future uvicorn
# release changes this shape, `PublicMediaTokenRedactionFilter.filter` degrades safely
# (see its own docstring): it leaves an unrecognised record alone rather than raising.
_PATH_ARG_INDEX = 2
_EXPECTED_ARGS_LENGTH = 5

ACCESS_LOGGER_NAME = "uvicorn.access"


class PublicMediaTokenRedactionFilter(logging.Filter):
    """Rewrites `/public/media/{token}` to `/public/media/<redacted>` in uvicorn's access
    log records — and touches nothing else. Every other path's `record.args` passes through
    completely unmodified, so this is surgical, not a blanket log suppression.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) != _EXPECTED_ARGS_LENGTH:
            # Not the shape this filter targets (a different uvicorn version, a manually
            # constructed record, a plain string message) — pass it through unchanged
            # rather than guess at a different position, which risks redacting the wrong
            # field on a record this filter was never built for.
            return True
        path = args[_PATH_ARG_INDEX]
        if not isinstance(path, str):
            return True
        redacted = _TOKEN_PATH_PATTERN.sub(_REDACTED, path)
        if redacted != path:
            new_args = list(args)
            new_args[_PATH_ARG_INDEX] = redacted
            record.args = tuple(new_args)
        return True  # never drops the record — only ever rewrites one field of it


def configure_access_log_redaction() -> None:
    """Attach the filter to `uvicorn.access`, idempotently.

    **Why calling this from `create_app()` is the right place, not a fragile one.** When
    uvicorn runs `create_app` as a `--factory`, it has ALREADY called
    `Config.configure_logging()` (which applies uvicorn's own `dictConfig`) by the time the
    factory executes — verified against `uvicorn/config.py`'s `Server`/`Config` startup
    order. So this filter is attached to an already-configured `uvicorn.access` logger,
    appending to its `.filters` list; it does not race uvicorn's own logging setup, and it
    does not need a custom `log_config=` passed to `uvicorn.run()`.

    In-process callers (Reflex's `httpx.ASGITransport` calls into `create_app()` directly,
    `inbox_provider.py`) never go through uvicorn's protocol layer at all, so there is no
    access logger and nothing to leak — this function is a safe no-op there too, it just
    attaches a filter to a named logger that may never emit anything.
    """
    access_logger = logging.getLogger(ACCESS_LOGGER_NAME)
    if any(isinstance(f, PublicMediaTokenRedactionFilter) for f in access_logger.filters):
        return  # idempotent — create_app() may run more than once (e.g. per test)
    access_logger.addFilter(PublicMediaTokenRedactionFilter())
