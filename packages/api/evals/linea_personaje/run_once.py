"""«Sugerir con IA» the line of a character's scene (m-25129386): the cost of ONE suggestion,
on a FICTIONAL business written for this measurement (no client material).

Two modes, run by hand, never from CI:

    # free: Anthropic's token counter over the real prompt and tool, 5, 8 and 10 s
    PYTHONUTF8=1 uv run --no-sync python packages/api/evals/linea_personaje/run_once.py \
        --env-file .env --count-tokens

    # paid, ONCE (needs the founder's OK in session): one real call through the service,
    # with its US$0.01 DollarMeter, an 8 s scene
    PYTHONUTF8=1 uv run --no-sync python packages/api/evals/linea_personaje/run_once.py \
        --env-file .env --live-once

Only `QUALIFY_ANTHROPIC_API_KEY` is read from `--env-file` (nothing else of the file enters
the process: Langfuse stays off, and the consumption sink is an in-memory recorder, so
nothing is booked to a database). The live mode goes through `CharacterLineService` with an
in-memory ledger and the service's own client (`max_retries=0`): one call, never retried.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from qualify_creative.schemas import BrandKit, ToneAxes, character_line_max_chars

from qualify_api import claude_tools
from qualify_api.creative import character_line_ai as cl
from qualify_api.creative.character_scene import SCENE_SWITCH

#: A made-up business: nothing here comes from a client.
TENANT = UUID("e7a10000-0000-4000-8000-000025129386")
BRAND = UUID("e7a10000-0000-4000-8000-0000251293b0")
CHARACTER = cl.LineCharacter(
    name="Mango",
    style="animated",
    description="Un mango sonriente con gorra azul y delantal blanco, alegre y conversador.",
)
PRODUCT = cl.LineProduct(
    name="Copa de mango",
    category="Helados",
    description="Helado de mango hecho en casa con trozos de fruta fresca y crema.",
)
BRAND_NAME = "Heladería La Nube"


def _kit() -> BrandKit:
    return BrandKit(
        brand_id=BRAND,
        positioning="Helados artesanales de fruta, hechos cada mañana en el barrio.",
        audience="Familias y jóvenes del barrio que buscan algo fresco por la tarde.",
        tone_axes=ToneAxes(
            formal_casual=70, sober_enthusiastic=65, technical_plain=85, brief_elaborate=30
        ),
        banned_words=("barato",),
        forbidden_claims=("el mejor helado del país",),
    )


class _Reads:
    def character(self, **_kw: Any) -> cl.LineCharacter:
        return CHARACTER

    def product(self, **_kw: Any) -> cl.LineProduct:
        return PRODUCT

    def kit(self, **_kw: Any) -> BrandKit:
        return _kit()

    def brand_name(self, **_kw: Any) -> str:
        return BRAND_NAME


def _load_key(env_file: str | None) -> None:
    if env_file:
        for line in Path(env_file).read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() == claude_tools.API_KEY_ENV:
                os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))
    if not os.environ.get(claude_tools.API_KEY_ENV):
        raise SystemExit(f"{claude_tools.API_KEY_ENV} is not set (use --env-file)")


def count_tokens() -> dict[str, Any]:
    """Anthropic's free token counter over exactly what the service sends."""
    client = cl.no_retry_client(claude_tools.api_key_from_env())
    out: dict[str, Any] = {}
    for seconds in (5, 8, 10):
        target = character_line_max_chars(seconds) - cl.LINE_MARGIN_CHARS
        counted = client.messages.count_tokens(
            model=cl.LINE_MODEL.model_id,
            system=cl.SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": cl.render_request(
                        character=CHARACTER,
                        product=PRODUCT,
                        kit=_kit(),
                        brand_name=BRAND_NAME,
                        duration_s=seconds,
                        target_chars=target,
                    ),
                }
            ],
            tools=[cl.line_tool(target)],
        )
        tokens = int(counted.input_tokens)
        price_in, price_out = claude_tools.PRICES[cl.LINE_MODEL.model_id]
        out[f"{seconds}s"] = {
            "input_tokens": tokens,
            "input_usd": tokens * price_in / 1_000_000,
            "worst_usd_at_max_tokens": (tokens * price_in + cl.MAX_TOKENS * price_out) / 1_000_000,
        }
    return out


def live_once() -> dict[str, Any]:
    booked: list[claude_tools.ClaudeConsumption] = []
    claude_tools.configure_consumption_sink(booked.append)
    ledger = cl.MemoryLineLedger()
    service = cl.CharacterLineService(reads=_Reads(), ledger=ledger, env={SCENE_SWITCH: "on"})
    started = datetime.now(UTC)
    result: dict[str, Any] = {"started_at": started.isoformat(), "seconds": 8}
    try:
        got = service.suggest(
            tenant_id=TENANT,
            brand_id=BRAND,
            user_id=uuid4(),
            scene_key=uuid4(),
            request_key="eval-1",
            character_id=uuid4(),
            product_id=uuid4(),
            duration_s=8,
        )
        result.update(
            outcome="ok",
            line=got.line,
            chars=len(got.line),
            max_chars=got.max_chars,
            cost_usd=str(got.cost_usd),
        )
    except cl.CharacterLineRefused as exc:
        result.update(outcome=exc.code, detail=str(exc))
    for row in booked:
        result.setdefault("bookings", []).append(
            {
                "model_revision": row.model_revision,
                "input_tokens": row.input_tokens,
                "output_tokens": row.output_tokens,
                "cache_read_tokens": row.cache_read_tokens,
                "cache_creation_tokens": row.cache_creation_tokens,
                "cost_usd": str(row.cost_usd),
                "prompt_version": row.attribution.prompt_version,
            }
        )
    result["ledger_rows"] = [
        {"cost_usd": str(r.cost_usd), "in": r.input_tokens, "out": r.output_tokens}
        for r in ledger.rows.values()
    ]
    result["ledger_spent_usd"] = str(ledger.spent_usd)
    result["meter_limit_usd"] = str(cl.LINE_MAX_USD)
    assert Decimal(result["ledger_spent_usd"]) <= cl.LINE_MAX_USD
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--count-tokens", action="store_true")
    mode.add_argument("--live-once", action="store_true")
    args = parser.parse_args()
    _load_key(args.env_file)
    out = count_tokens() if args.count_tokens else live_once()
    out["model"] = cl.LINE_MODEL.label
    out["prompt_version"] = cl.LINE_PROMPT_VERSION
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
