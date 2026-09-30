"""Canva round trip: send a generated piece to the operator's Canva to edit it there, and
bring the edited result back (§ request 2026-09-28). Written against Canva's Connect API
documentation and not yet run live — see `docs/canva-integracion.md`.

- `models` / `repository` — the operator's encrypted Canva tokens and one row per piece
  sent (`canva_accounts`, `canva_design_links`, migration 0030).
- `service` — connect (OAuth + PKCE), send, handle Canva's return, pull the export.
- `composition` — production wiring.
"""

from qualify_api.canva.service import (
    CanvaConfig,
    CanvaNotConfigured,
    CanvaNotConnected,
    CanvaService,
    ConnectStart,
    NothingToSend,
    SentToCanva,
    UnknownReturn,
    canva_configured,
)

__all__ = [
    "CanvaConfig",
    "CanvaNotConfigured",
    "CanvaNotConnected",
    "CanvaService",
    "ConnectStart",
    "NothingToSend",
    "SentToCanva",
    "UnknownReturn",
    "canva_configured",
]
