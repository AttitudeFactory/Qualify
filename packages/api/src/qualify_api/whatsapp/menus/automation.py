"""`conversational_automation` body derived from a `MenuDefinition` (WA-14).

Meta's conversational components (welcome message, ice breakers, commands) are
configured per business phone number with
`POST /{PHONE_NUMBER_ID}/conversational_automation`. WA-16 publishes a menu version
by calling that endpoint with exactly this body, so the prompts a customer sees in
WhatsApp and the entries the engine routes are **the same datum** (plan §5.3).

Shape (conversational-components page, verified 2026-10-14):

    {
      "enable_welcome_message": bool,
      "prompts": ["Ver menú", ...],                       # ice breakers, at most 4
      "commands": [{"command_name": "menu",
                    "command_description": "Ver el menú y pedir"}, ...]   # at most 30
    }

All three keys are always present: publishing a menu without commands must CLEAR the
commands of the previous version, and Meta treats an omitted key as "leave as is".
`enable_welcome_message` is true when the menu greets first messages — Meta then
delivers a `request_welcome` message when a user opens the chat, which the engine
answers with `entry.welcome` + the start node. The welcome TEXT is never sent to Meta;
it is ours to render. Pure: no HTTP here (the Graph client is WA-06).
"""

from __future__ import annotations

from typing import Any

from qualify_api.whatsapp.menus.schema import MenuDefinition


def to_conversational_automation(definition: MenuDefinition) -> dict[str, Any]:
    entry = definition.entry
    return {
        "enable_welcome_message": bool(entry.on_first_message and entry.welcome),
        "prompts": [ib.text for ib in entry.ice_breakers],
        "commands": [
            {"command_name": cmd.name, "command_description": cmd.hint} for cmd in entry.commands
        ],
    }


__all__ = ["to_conversational_automation"]
