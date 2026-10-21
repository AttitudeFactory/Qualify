"""What a generation sends to each vendor and what it cost, printed for a human
(§ request 2026-10-05: "imprime en consola el prompt que va al generador y el gasto").

The `qualify_api.creative.costs` lines (`service._log_costs`) stay as they are: one
key=value line per call, for a grep or a spreadsheet. This module is the readable
counterpart, for someone watching the `reflex run` console while testing /create:

- the COPY prompt exactly as the Anthropic adapter sends it — the system block (the
  cached brand prefix) and the user message (this brief);
- what goes to the media vendors (Seedream's scene, Seed Speech's script and voice,
  OmniHuman's gestures) and to the template engine (template and the texts it will
  print) — the "prompt" of a media call;
- the spend: every vendor call with its tokens/units and cost, the total of the draft
  and what is left of the monthly budget.

On by default (the app is pre-deploy and this is how /create is tested). Set
`QUALIFY_TRACE_PROMPTS=0` to silence it. Never raises: a trace line must not break a
generation.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any
from uuid import UUID

trace_logger = logging.getLogger("qualify_api.creative.trace")

ENV_FLAG = "QUALIFY_TRACE_PROMPTS"
_RULE = "=" * 78
_THIN = "-" * 78


def enabled() -> bool:
    return os.environ.get(ENV_FLAG, "1").strip().lower() not in ("0", "false", "no", "off")


def _emit(lines: Iterable[str]) -> None:
    if not enabled():
        return
    try:
        trace_logger.info("\n%s", "\n".join(lines))
    except Exception:  # noqa: BLE001 — a trace must never break a generation
        logging.getLogger(__name__).exception("creative trace failed")


def copy_prompt(
    *,
    draft_id: UUID | None,
    kind: str,
    chain: tuple[str, ...],
    variants: int,
    system: str,
    user: str | tuple[str, ...],
) -> None:
    """The prompt the copy model receives, once per draft: the shared prefix, then each
    variant's own assignment (§ request 2026-10-08 — each one has its angle).
    With no `draft_id` it is the preview the generator prints on «¿Todo listo?», before
    Generar (§ request 2026-10-06): the same bytes, nothing sent, nothing spent."""
    head = (
        f"PROMPT → Claude (copy)  draft={draft_id}"
        if draft_id is not None
        else "VISTA PREVIA DEL PROMPT → Claude (copy)  — aún no se envió nada"
    )
    _emit(
        [
            _RULE,
            f"{head}  tipo={kind}  variantes={variants}  cadena={' → '.join(chain)}",
            _RULE,
            "[system — prefijo de marca, cacheado]",
            system,
            _THIN,
            *_assignments((user,) if isinstance(user, str) else user),
            _RULE,
        ]
    )


def _assignments(users: tuple[str, ...]) -> list[str]:
    if len(users) == 1:
        return ["[user — el encargo]", users[0]]
    lines: list[str] = []
    for number, user in enumerate(users, 1):
        if number > 1:
            lines.append(_THIN)
        lines.extend((f"[user — el encargo, variante {number}]", user))
    return lines


def prompt_unavailable(*, kind: str, missing: tuple[str, ...]) -> None:
    """The preview could not render: the brand lacks what the prompt is built from —
    the same reason Generar would refuse (`BrandNotReady`)."""
    _emit(
        [
            _RULE,
            f"VISTA PREVIA DEL PROMPT  tipo={kind}  — no se puede armar, falta: "
            + ", ".join(missing),
            _RULE,
        ]
    )


def media_request(*, draft_id: UUID, provider: str, what: str, fields: Mapping[str, Any]) -> None:
    """What a media call sends: the presenter's script and voice, a scene's prompt, the
    template engine's props. Asset ids and keys are left out."""
    lines = [_RULE, f"PROMPT → {provider} ({what})  draft={draft_id}", _RULE]
    for name, value in fields.items():
        if value in (None, "", (), [], {}):
            continue
        text = str(value)
        lines.append(f"{name}:\n{text}" if "\n" in text or len(text) > 70 else f"{name}: {text}")
    lines.append(_RULE)
    _emit(lines)


def spend(
    *,
    draft_id: UUID,
    kind: str,
    calls: Iterable[Any],
    total: Decimal,
    budget_remaining: Decimal | None,
    outcome: str,
) -> None:
    """Every vendor call of the draft with its cost, the total, and the budget left.
    `calls` are `service.UsageWrite`s (provider, model_id, unit, tokens, pieces, cost)."""
    lines = [_RULE, f"GASTO  draft={draft_id}  tipo={kind}  resultado={outcome}", _THIN]
    count = 0
    for call in calls:
        count += 1
        if call.unit == "token":
            detail = (
                f"tokens in={call.input_tokens} out={call.output_tokens} "
                f"cache_read={call.cache_read_tokens} cache_write={call.cache_creation_tokens}"
            )
        else:
            detail = f"{call.pieces} {call.unit}(s)"
        lines.append(
            f"  {count:>2}. {call.provider:<10} {call.model_id:<28} {detail:<52} "
            f"USD {call.cost_usd:.6f}"
        )
    if not count:
        lines.append("  (ninguna llamada de pago)")
    lines.append(_THIN)
    lines.append(f"  TOTAL de este borrador: USD {total:.6f}")
    if budget_remaining is not None:
        lines.append(f"  Presupuesto mensual restante: USD {budget_remaining:.2f}")
    lines.append(_RULE)
    _emit(lines)
