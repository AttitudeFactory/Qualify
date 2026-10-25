"""BytePlus eval key and off-hours window (m-24852161), offline: no key value is ever
printed, the production fingerprint stops an eval, and video evals run only at night."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from qualify_api.evals import byteplus_eval_guard as g

EVAL = "eval-key-must-never-print"
APP = "app-key-must-never-print"


def test_fingerprint_is_short_stable_and_hides_the_value() -> None:
    fp = g.fingerprint(EVAL)
    assert fp.startswith("sha256:") and len(fp) == len("sha256:") + 8
    assert fp == g.fingerprint(f"  {EVAL}\n")
    assert fp != g.fingerprint(APP)
    assert EVAL not in fp


def test_fingerprint_matches_env_push_dry_run() -> None:
    """`deploy/deploy.sh` prints `printf %s "$v" | sha256sum | cut -c1-8`: same 8 chars."""
    assert g.fingerprint(APP) == "sha256:" + hashlib.sha256(APP.encode()).hexdigest()[:8]


def test_eval_key_wins_over_the_app_key() -> None:
    key = g.resolve_eval_key({g.EVAL_KEY_ENV: EVAL, g.APP_KEY_ENV: APP})
    assert key.value == EVAL and key.is_dedicated
    assert key.fingerprint == g.fingerprint(EVAL)
    assert EVAL not in repr(key) and EVAL not in key.describe()
    assert "usa la llave de la app" not in key.describe()


def test_app_key_is_an_announced_fallback() -> None:
    key = g.resolve_eval_key({g.APP_KEY_ENV: APP, g.EVAL_KEY_ENV: "  "})
    assert key.env_name == g.APP_KEY_ENV and not key.is_dedicated
    assert "usa la llave de la app" in key.describe() and APP not in key.describe()


def test_no_key_raises() -> None:
    with pytest.raises(g.EvalKeyError, match=g.EVAL_KEY_ENV):
        g.resolve_eval_key({})


@pytest.mark.parametrize("stored", ["{fp}", "{bare}", "  {upper}  "])
def test_production_fingerprint_stops_the_eval(stored: str) -> None:
    fp = g.fingerprint(APP)
    value = stored.format(fp=fp, bare=fp.removeprefix("sha256:"), upper=fp.upper())
    with pytest.raises(g.EvalKeyError) as err:
        g.resolve_eval_key({g.APP_KEY_ENV: APP, g.PROD_FINGERPRINT_ENV: value})
    assert "producción" in str(err.value) and APP not in str(err.value)


def test_a_different_production_fingerprint_lets_the_eval_key_through() -> None:
    env = {g.EVAL_KEY_ENV: EVAL, g.PROD_FINGERPRINT_ENV: g.fingerprint(APP)}
    assert g.resolve_eval_key(env).value == EVAL


@pytest.mark.parametrize(
    ("utc_hour", "utc_minute", "inside"),
    [
        (4, 0, True),  # 23:00 Bogotá: the window opens
        (7, 30, True),  # 02:30 Bogotá
        (9, 59, True),  # 04:59 Bogotá
        (10, 0, False),  # 05:00 Bogotá: closed
        (17, 0, False),  # 12:00 Bogotá: the shops' day
        (3, 59, False),  # 22:59 Bogotá
    ],
)
def test_off_hours_window_in_bogota_time(utc_hour: int, utc_minute: int, inside: bool) -> None:
    now = datetime(2026, 10, 26, utc_hour, utc_minute, tzinfo=UTC)
    assert g.in_off_hours(now) is inside
    refusal = g.off_hours_refusal(now)
    assert (refusal is None) is inside


def test_refusal_names_the_window_and_the_override() -> None:
    noon = datetime(2026, 10, 26, 17, 0, tzinfo=UTC)
    message = g.off_hours_refusal(noon)
    assert message is not None
    assert "12:00" in message and "23:00" in message and "05:00" in message
    assert "10 tareas" in message
    assert g.off_hours_refusal(noon, allow_daytime=True) is None


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError):
        g.in_off_hours(datetime(2026, 10, 26, 2, 0))


@pytest.mark.parametrize(("requested", "allowed"), [(10, 3), (3, 3), (2, 2), (0, 1), (-4, 1)])
def test_video_concurrency_is_capped(requested: int, allowed: int) -> None:
    assert g.cap_video_concurrency(requested) == allowed


def test_key_report_shows_fingerprints_and_alerts_without_values() -> None:
    env = {g.EVAL_KEY_ENV: APP, g.APP_KEY_ENV: APP, g.PROD_FINGERPRINT_ENV: g.fingerprint(APP)}
    text = "\n".join(g.key_report(env))
    assert APP not in text
    assert f"{g.EVAL_KEY_ENV}: {g.fingerprint(APP)}" in text
    assert "es la llave de producción" in text
    assert "es la misma llave que" in text


def test_key_report_clean_and_missing_prod_fingerprint() -> None:
    lines = g.key_report({g.EVAL_KEY_ENV: EVAL, g.APP_KEY_ENV: APP})
    assert not any(line.startswith("ALERTA") for line in lines)
    assert any("no se puede comprobar" in line for line in lines)


def test_cli_reads_the_env_file_and_exits_1_on_alert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in (g.EVAL_KEY_ENV, g.APP_KEY_ENV, g.PROD_FINGERPRINT_ENV):
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / ".env"
    env.write_text(f'{g.EVAL_KEY_ENV}="{EVAL}"\n{g.APP_KEY_ENV}={APP}\n', encoding="utf-8")
    assert g.main(["--env-file", str(env)]) == 0
    env.write_text(f"{g.EVAL_KEY_ENV}={APP}\n{g.APP_KEY_ENV}={APP}\n", encoding="utf-8")
    assert g.main(["--env-file", str(env)]) == 1
    out = capsys.readouterr().out
    assert EVAL not in out and APP not in out
