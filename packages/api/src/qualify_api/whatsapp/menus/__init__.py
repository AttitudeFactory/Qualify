"""Deterministic WhatsApp menus (WA-14, pure half).

- `schema`: the `MenuDefinition` the editor authors and `whatsapp_menu_versions`
  stores — every Meta limit validated at definition time.
- `engine`: `step()` / `render_node()`, synchronous and pure; the webhook handler
  (WA-07) persists the returned state and sends the returned actions.
- `automation`: the exact `conversational_automation` body Meta expects, derived
  from the same definition so what WhatsApp shows and what Qualify runs is one datum.
- `examples`: `BIANKI_DEMO_MENU`, the realistic Spanish fast-food menu tests run.
"""
