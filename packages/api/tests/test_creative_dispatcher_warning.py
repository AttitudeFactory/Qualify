"""The startup warning when generation runs inline (m-24993021).

Without `QUALIFY_CREATIVE_DISPATCHER=queue` the parts of a video by parts are never created
(only creative-worker's pipeline creates them), so the server says so once at startup.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

from qualify_api.creative.queue_dispatch import (
    SWITCH,
    queue_enabled,
    reset_inline_warning,
    warn_if_inline,
)

LOGGER = "test.creative_dispatcher"


@pytest.fixture(autouse=True)
def _fresh_process() -> Iterator[None]:
    reset_inline_warning()
    yield
    reset_inline_warning()


def _warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == LOGGER and r.levelno == logging.WARNING]


@pytest.mark.parametrize("value", [None, "inline", " INLINE "])
def test_warns_when_inline_or_unset(
    value: str | None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    if value is None:
        monkeypatch.delenv(SWITCH, raising=False)
    else:
        monkeypatch.setenv(SWITCH, value)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert warn_if_inline(logging.getLogger(LOGGER)) is True
    [record] = _warnings(caplog)
    message = record.getMessage()
    assert f"{SWITCH}=queue" in message
    assert "never created" in message


def test_silent_when_queue(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(SWITCH, "queue")
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        assert warn_if_inline(logging.getLogger(LOGGER)) is False
    assert [r for r in caplog.records if r.name == LOGGER] == []


def test_warns_only_once_per_process(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv(SWITCH, raising=False)
    log = logging.getLogger(LOGGER)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert warn_if_inline(log) is True
        assert warn_if_inline(log) is False
        assert warn_if_inline(log) is False
    assert len(_warnings(caplog)) == 1


def test_invalid_value_logs_error_and_queue_enabled_still_raises(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(SWITCH, "celery")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert warn_if_inline(logging.getLogger(LOGGER)) is False
    assert [r.levelno for r in caplog.records if r.name == LOGGER] == [logging.ERROR]
    with pytest.raises(ValueError):
        queue_enabled()
