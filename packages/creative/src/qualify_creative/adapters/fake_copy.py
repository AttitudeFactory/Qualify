"""A copy provider that writes a fixed text, for end-to-end tests (m-24955929). TEST-ONLY.

`QUALIFY_COPY_FAKE=1` makes `production_content_service()` route copy here instead of
Anthropic (`qualify_api.creative.composition`), so an E2E run creates a real piece —
draft, router, ledger, media into `generated/` — without a paid call. Off by default;
**refused when `QUALIFY_DEPLOY_ENV=production`** (`fake_copy_enabled()` raises).

Its calls are priced on the copy slot's real model id at zero tokens ($0 — the pricing
table has no fake id); the copy variant's `model_revision` says `fake-copy-e2e`. The slot
still resolves the platform key (`PlatformKeyResolver`), so the variable must exist,
though the fake never uses it.
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any

from qualify_creative.adapters.anthropic_copy import DEFAULT_MODEL_ID
from qualify_creative.enums import GenerationTask
from qualify_creative.providers import GenerationResult, Usage

FAKE_COPY_ENV = "QUALIFY_COPY_FAKE"
FAKE_MODEL_ID = "fake-copy-e2e"


class FakeCopyRefused(RuntimeError):
    """`QUALIFY_COPY_FAKE` set where it must never be (production)."""


def fake_copy_enabled() -> bool:
    if os.environ.get(FAKE_COPY_ENV, "").strip() != "1":
        return False
    if os.environ.get("QUALIFY_DEPLOY_ENV", "").strip().lower() == "production":
        raise FakeCopyRefused(f"{FAKE_COPY_ENV} is test-only and refused in production")
    return True


class FakeCopyAdapter:
    """`GenerationProvider` for copy: no SDK, no network, no cost."""

    name = "anthropic"  # the slot the router's copy chain asks for
    supports = frozenset({GenerationTask.COPY})

    def generate(self, request: Any, *, api_key: str) -> GenerationResult:
        return GenerationResult(
            payload={
                "hook": "Así es nuestro local por dentro",
                "caption": (
                    "Te mostramos nuestro local, nuestro equipo y cómo preparamos todo cada "
                    "día, con fotos y videos reales de nuestro negocio."
                ),
                "hashtags": ["comidacasera", "hechoamano"],
                "cta": "Ven a visitarnos",
            },
            # the copy slot's priced model (the ledger prices every call), at zero tokens:
            # $0; `model_revision` says the copy was never written by it
            model_id=DEFAULT_MODEL_ID,
            provider=self.name,
            usage=Usage(input_tokens=0, output_tokens=0),
            model_revision=FAKE_MODEL_ID,
        )

    def estimate_cost_usd(
        self, request: Any, pricing: Any, *, api_key: str | None = None
    ) -> Decimal:
        return Decimal("0")
