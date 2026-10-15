"""Deterministic WhatsApp menus (WA-14, pure half).

- `schema`: the `MenuDefinition` the editor authors and `whatsapp_menu_versions`
  stores — every Meta limit validated at definition time.
- `engine`: `step()` / `render_node()`, synchronous and pure; the webhook handler
  (WA-07) persists the returned state and sends the returned actions.
- `automation`: the exact `conversational_automation` body Meta expects, derived
  from the same definition so what WhatsApp shows and what Qualify runs is one datum.
- `examples`: `BIANKI_DEMO_MENU`, the realistic Spanish fast-food menu tests run.
- `repository` (persistence half, migration 0058): `MenuRepository` for the WA-16
  editor (`qualify_app`, `tenant_session`) and `load_published_menu_for_phone`, the
  `menu_loader` the WA-07 handler takes (`qualify_webhook_worker`, tenant-blind).
"""

from qualify_api.whatsapp.menus.repository import (
    MemoryMenuRepository,
    MenuLoader,
    MenuNotFound,
    MenuRecord,
    MenuRepository,
    MenuVersionNotFound,
    MenuVersionRecord,
    PostgresMenuRepository,
    coerce_definition,
    load_published_menu_for_phone,
)

__all__ = [
    "MemoryMenuRepository",
    "MenuLoader",
    "MenuNotFound",
    "MenuRecord",
    "MenuRepository",
    "MenuVersionNotFound",
    "MenuVersionRecord",
    "PostgresMenuRepository",
    "coerce_definition",
    "load_published_menu_for_phone",
]
