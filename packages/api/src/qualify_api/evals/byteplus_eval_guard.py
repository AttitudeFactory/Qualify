"""Which BytePlus key an eval spends with, and when a video eval may run (m-24852161).

BytePlus counts Seedance's 10 tasks at a time **per model and per primary account, adding
every sub-account** (`docs/escalar-generacion-concurrencia.md` §1.1). A separate key or
sub-account for evals does NOT give more room: it only separates the spend, makes the
tasks visible under their own key (`arkcli`, read-only) and lets one key be revoked
without touching production. So two rules live here:

1. **Its own key.** An eval spends with `QUALIFY_BYTEPLUS_ARK_EVAL_API_KEY`; the app's
   `QUALIFY_BYTEPLUS_ARK_API_KEY` is only a fallback that is announced. Keys are compared
   by fingerprint (a short sha256 prefix), never printed: when
   `QUALIFY_BYTEPLUS_ARK_PROD_KEY_FINGERPRINT` is set and the resolved key matches it, the
   eval refuses to start.
2. **Video evals run outside business hours, few at a time.** Until the own queue
   (ADR 41, m-24852163) exists, an eval that creates Seedance/OmniHuman tasks runs only in
   `WINDOW_START`–`WINDOW_END` Bogotá time — 23:00–05:00 Bogotá is 00:00–06:00 Caracas and
   01:00–07:00 Montevideo, outside the shops' day in the three markets — and with at most
   `MAX_VIDEO_TASKS_AT_ONCE` tasks in flight. Once the queue exists, evals enqueue in its
   `scheduled` lane instead. Image evals (Seedream, 500 images per minute) are not bound
   by the window.

Pure functions plus a tiny CLI (`just byteplus-llaves`) that prints the fingerprints of
the keys in an env file. Nothing here calls BytePlus.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

EVAL_KEY_ENV = "QUALIFY_BYTEPLUS_ARK_EVAL_API_KEY"
APP_KEY_ENV = "QUALIFY_BYTEPLUS_ARK_API_KEY"
#: The production key's fingerprint (`fingerprint()` of the value in `.env.prod`), so a
#: local eval can tell it is about to spend with it. A fingerprint is not a secret.
PROD_FINGERPRINT_ENV = "QUALIFY_BYTEPLUS_ARK_PROD_KEY_FINGERPRINT"

#: The off-hours window for video evals, in Bogotá time (UTC-5, no daylight saving).
WINDOW_TZ = ZoneInfo("America/Bogota")
WINDOW_START = time(23, 0)
WINDOW_END = time(5, 0)
#: Seedance tasks an eval may keep in flight: 3 of the account's 10, so a night client
#: still has 7.
MAX_VIDEO_TASKS_AT_ONCE = 3

#: The same 8 hex characters `just env-push --dry-run` prints (`deploy/deploy.sh`, `fp`), so
#: production's fingerprint can be copied from its `change <old> -> <new>` line.
_FINGERPRINT_CHARS = 8


def fingerprint(key: str) -> str:
    """`sha256:<first 8 hex>` of a key: enough to tell two keys apart, useless to use one."""
    digest = hashlib.sha256(key.strip().encode("utf-8")).hexdigest()
    return f"sha256:{digest[:_FINGERPRINT_CHARS]}"


def _normalize_fingerprint(value: str) -> str:
    value = value.strip().lower()
    return value if value.startswith("sha256:") else f"sha256:{value}"


class EvalKeyError(RuntimeError):
    """No usable key for an eval: missing, or the production one."""


@dataclass(frozen=True)
class EvalKey:
    """The key an eval will spend with. `repr` never shows the value."""

    value: str = field(repr=False)
    env_name: str
    fingerprint: str

    @property
    def is_dedicated(self) -> bool:
        return self.env_name == EVAL_KEY_ENV

    def describe(self) -> str:
        """One line for the console, without the value."""
        note = "" if self.is_dedicated else f" (sin {EVAL_KEY_ENV}: usa la llave de la app)"
        return f"Llave de BytePlus: {self.env_name} · huella {self.fingerprint}{note}"


def resolve_eval_key(env: Mapping[str, str] | None = None) -> EvalKey:
    """The eval key, else the app key (announced by `EvalKey.describe`). Raises
    `EvalKeyError` when there is none or when it matches the production fingerprint."""
    env = os.environ if env is None else env
    for name in (EVAL_KEY_ENV, APP_KEY_ENV):
        value = (env.get(name) or "").strip()
        if value:
            key = EvalKey(value=value, env_name=name, fingerprint=fingerprint(value))
            break
    else:
        raise EvalKeyError(f"{EVAL_KEY_ENV} is not set (nor {APP_KEY_ENV})")
    prod = (env.get(PROD_FINGERPRINT_ENV) or "").strip()
    if prod and _normalize_fingerprint(prod) == key.fingerprint:
        raise EvalKeyError(
            f"{key.env_name} es la llave de producción (huella {key.fingerprint}): "
            f"pon una llave propia de evaluaciones en {EVAL_KEY_ENV}"
        )
    return key


def in_off_hours(now: datetime) -> bool:
    """Whether `now` (timezone-aware) falls in the video-eval window, Bogotá time."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local = now.astimezone(WINDOW_TZ).time()
    if WINDOW_START <= WINDOW_END:
        return WINDOW_START <= local < WINDOW_END
    return local >= WINDOW_START or local < WINDOW_END


def off_hours_refusal(now: datetime | None = None, *, allow_daytime: bool = False) -> str | None:
    """None when a video eval may start now; otherwise the message to print. A video eval
    calls this before its first task; `allow_daytime` is the founder-approved override
    (a CLI flag, never a default)."""
    now = now or datetime.now(UTC)
    if allow_daytime or in_off_hours(now):
        return None
    local = now.astimezone(WINDOW_TZ).strftime("%H:%M")
    return (
        f"Son las {local} en Bogotá. Las evaluaciones con video comparten con los clientes "
        f"las 10 tareas a la vez de BytePlus y corren entre las "
        f"{WINDOW_START:%H:%M} y las {WINDOW_END:%H:%M} (hora de Bogotá). "
        "Para correrla ahora hace falta el visto bueno del fundador."
    )


def cap_video_concurrency(requested: int) -> int:
    """At most `MAX_VIDEO_TASKS_AT_ONCE` video tasks in flight, at least 1."""
    return max(1, min(requested, MAX_VIDEO_TASKS_AT_ONCE))


def _env_file_pairs(path: str | None) -> dict[str, str]:
    pairs: dict[str, str] = {}
    if not path or not Path(path).is_file():
        return pairs
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        name = name.strip()
        if sep and name and not name.startswith("#"):
            pairs[name] = value.strip().strip('"').strip("'")
    return pairs


def key_report(env: Mapping[str, str]) -> list[str]:
    """The fingerprint of each BytePlus key in `env`, and whether the eval key is apart
    from the app's and from production. Values are never in the output."""
    lines: list[str] = []
    prints: dict[str, str] = {}
    for name in (EVAL_KEY_ENV, APP_KEY_ENV):
        value = (env.get(name) or "").strip()
        if value:
            prints[name] = fingerprint(value)
        lines.append(f"{name}: {prints.get(name, 'ausente')}")
    prod = (env.get(PROD_FINGERPRINT_ENV) or "").strip()
    prod_print = _normalize_fingerprint(prod) if prod else None
    lines.append(f"{PROD_FINGERPRINT_ENV}: {prod_print or 'ausente'}")
    if prod_print and prod_print in prints.values():
        clash = ", ".join(name for name, fp in prints.items() if fp == prod_print)
        lines.append(f"ALERTA: {clash} es la llave de producción.")
    if EVAL_KEY_ENV in prints and prints[EVAL_KEY_ENV] == prints.get(APP_KEY_ENV):
        lines.append(f"ALERTA: {EVAL_KEY_ENV} es la misma llave que {APP_KEY_ENV}.")
    if not prod_print:
        lines.append(
            f"Sin {PROD_FINGERPRINT_ENV} no se puede comprobar que ninguna sea la de producción."
        )
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Huellas de las llaves de BytePlus (m-24852161).")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(argv)
    env = {**_env_file_pairs(args.env_file), **os.environ}
    lines = key_report(env)
    print("\n".join(lines))
    return 1 if any(line.startswith("ALERTA") for line in lines) else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
