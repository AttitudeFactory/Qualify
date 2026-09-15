"""`PublicMediaTokenRedactionFilter` (QUA-68) — the actual fix for the leak `logger.
info(token)` avoidance inside a route handler cannot touch: uvicorn's OWN access-log call,
made by its protocol layer, entirely outside the ASGI app.

Each `logging.LogRecord` here is constructed with the EXACT `args` shape uvicorn's real
`access_logger.info(...)` call uses (verified against
`.venv/Lib/site-packages/uvicorn/protocols/http/h11_impl.py`, quoted in `access_log.py`'s
own docstring) — a 5-tuple `(client_addr, method, path_with_query_string, http_version,
status_code)` — so this test exercises the filter against the real shape it targets, not an
approximation of it.
"""

from __future__ import annotations

import logging

from qualify_api.http.access_log import (
    ACCESS_LOGGER_NAME,
    PublicMediaTokenRedactionFilter,
    configure_access_log_redaction,
)


def _uvicorn_access_record(path: str) -> logging.LogRecord:
    """Builds a `LogRecord` shaped exactly like uvicorn's real access-log call — same
    message template, same 5-tuple `args`, same logger name."""
    return logging.LogRecord(
        name=ACCESS_LOGGER_NAME,
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:54321", "GET", path, "1.1", 200),
        exc_info=None,
    )


def test_the_token_is_stripped_from_the_formatted_message() -> None:
    record = _uvicorn_access_record("/public/media/SUPER_SECRET_TOKEN_ABC123")

    PublicMediaTokenRedactionFilter().filter(record)

    formatted = record.getMessage()
    assert "SUPER_SECRET_TOKEN_ABC123" not in formatted
    assert "/public/media/<redacted>" in formatted


def test_the_token_is_stripped_even_with_a_query_string() -> None:
    """`get_path_with_query_string` (uvicorn) includes the query string in the same arg —
    this route never adds one, but a future caller appending `?x=y` must not defeat the
    redaction by moving the token out of the pattern's match."""
    record = _uvicorn_access_record("/public/media/SUPER_SECRET_TOKEN_ABC123?x=y")

    PublicMediaTokenRedactionFilter().filter(record)

    assert "SUPER_SECRET_TOKEN_ABC123" not in record.getMessage()


def test_an_unrelated_path_is_left_completely_untouched() -> None:
    """The actual proof this is surgical, not a blanket suppression: a DIFFERENT route's
    access-log record must come out byte-for-byte identical."""
    record = _uvicorn_access_record("/api/publishing/attempts/11111111-1111-1111-1111-111111111111")
    original_args = record.args

    result = PublicMediaTokenRedactionFilter().filter(record)

    assert result is True  # never drops the record
    assert record.args == original_args


def test_the_record_is_never_dropped_only_rewritten() -> None:
    """A `Filter` returning `False` would SUPPRESS the log line entirely — the requirement
    is redaction, not suppression, so every record must still get through."""
    for path in ("/public/media/tok", "/api/leads/intake", "/"):
        record = _uvicorn_access_record(path)
        assert PublicMediaTokenRedactionFilter().filter(record) is True


def test_a_record_with_an_unexpected_shape_passes_through_unchanged() -> None:
    """A defensive branch: if a future uvicorn release changes the access-log call's
    argument shape, this filter must not raise, and must not guess at a different
    position — it degrades to a no-op rather than risk redacting (or leaking) the wrong
    field on a record it was never built for."""
    record = logging.LogRecord(
        name=ACCESS_LOGGER_NAME,
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="a plain string message with no args",
        args=(),
        exc_info=None,
    )

    result = PublicMediaTokenRedactionFilter().filter(record)

    assert result is True
    assert record.args == ()


def test_configure_access_log_redaction_attaches_to_the_uvicorn_access_logger() -> None:
    logger = logging.getLogger(ACCESS_LOGGER_NAME)
    logger.filters = [
        f for f in logger.filters if not isinstance(f, PublicMediaTokenRedactionFilter)
    ]

    configure_access_log_redaction()

    assert any(isinstance(f, PublicMediaTokenRedactionFilter) for f in logger.filters)


def test_configure_access_log_redaction_is_idempotent() -> None:
    """`create_app()` may run more than once in a process (every test file that builds an
    app does) — calling this twice must not attach the filter twice, which would redact
    correctly but leave a growing, wasteful filter list."""
    logger = logging.getLogger(ACCESS_LOGGER_NAME)
    logger.filters = [
        f for f in logger.filters if not isinstance(f, PublicMediaTokenRedactionFilter)
    ]

    configure_access_log_redaction()
    configure_access_log_redaction()
    configure_access_log_redaction()

    count = sum(1 for f in logger.filters if isinstance(f, PublicMediaTokenRedactionFilter))
    assert count == 1


def test_end_to_end_through_a_real_handler_emits_no_token() -> None:
    """The closest thing to a full-stack proof available offline: attach the filter, wire
    a real logging.Handler with an in-memory stream, emit a record shaped like uvicorn's
    real call, and assert the captured OUTPUT — not just record.args — never contains the
    token. This is what actually ends up wherever this process's stdout/log file goes."""
    import io

    logger = logging.getLogger(ACCESS_LOGGER_NAME)
    logger.filters = [
        f for f in logger.filters if not isinstance(f, PublicMediaTokenRedactionFilter)
    ]
    configure_access_log_redaction()

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:1234",
            "GET",
            "/public/media/THE_REAL_TOKEN_VALUE",
            "1.1",
            200,
        )
    finally:
        logger.removeHandler(handler)

    output = stream.getvalue()
    assert "THE_REAL_TOKEN_VALUE" not in output
    assert "/public/media/<redacted>" in output
