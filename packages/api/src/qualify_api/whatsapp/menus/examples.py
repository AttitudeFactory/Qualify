"""Reference menus (WA-14).

`BIANKI_DEMO_MENU` is a realistic Spanish fast-food menu for the dogfooding number
(Bianki, plan §1): greeting, the four shortcuts WhatsApp shows as ice breakers
("Ver menú / Hacer pedido / Horario / Ubicación"), the catalog list, the order summary
with address collection, and "hablar con una persona". It passes validation and the
engine tests walk it end to end; WA-16 can also seed a new number with it. Its
`productos` node is `source: 'catalog'`: in production the rows come from the number's
brand catalog (`whatsapp.catalog.load_catalog_for_phone`, WA-15).

Texts are product copy (Spanish) on purpose — they are what a customer reads.
"""

from __future__ import annotations

from qualify_api.whatsapp.menus.schema import MenuDefinition

BIANKI_DEMO_MENU: MenuDefinition = MenuDefinition.model_validate(
    {
        "version": 1,
        "start_node": "inicio",
        "entry": {
            "on_first_message": True,
            "welcome": (
                "¡Hola! Soy el asistente de Bianki. Te ayudo a ver el menú y hacer tu pedido."
            ),
            "keywords": {
                "hola": "inicio",
                "menú": "productos",
                "pedido": "productos",
                "pedir": "productos",
                "horario": "horario",
                "ubicacion": "ubicacion",
                "persona": "persona",
                "ayuda": "persona",
            },
            "ice_breakers": [
                {"text": "Ver menú", "node": "productos"},
                {"text": "Hacer pedido", "node": "productos"},
                {"text": "Horario", "node": "horario"},
                {"text": "Ubicación", "node": "ubicacion"},
            ],
            "commands": [
                {"name": "menu", "hint": "Ver el menú y hacer un pedido", "node": "productos"},
                {"name": "horario", "hint": "Horario de atención", "node": "horario"},
                {"name": "ubicacion", "hint": "Dónde estamos", "node": "ubicacion"},
                {"name": "persona", "hint": "Hablar con una persona del equipo", "node": "persona"},
            ],
            "fallback_node": "persona",
        },
        "nodes": {
            "inicio": {
                "kind": "buttons",
                "body": "¿Qué quieres hacer?",
                "options": [
                    {"id": "ver_menu", "label": "Ver menú y pedir", "next": "productos"},
                    {"id": "info", "label": "Horario y ubicación", "next": "info"},
                    {"id": "persona", "label": "Hablar con alguien", "next": "persona"},
                ],
            },
            "info": {
                "kind": "buttons",
                "body": "¿Qué necesitas saber?",
                "options": [
                    {"id": "horario", "label": "Horario", "next": "horario"},
                    {"id": "ubicacion", "label": "Ubicación", "next": "ubicacion"},
                    {"id": "volver", "label": "Volver", "next": "inicio"},
                ],
            },
            "horario": {
                "kind": "text",
                "body": (
                    "Abrimos de lunes a domingo de 12:00 a 22:00.\n"
                    "Cuando quieras pedir, escribe *menú*."
                ),
            },
            "ubicacion": {
                "kind": "text",
                "body": (
                    "Estamos en la Calle 10 # 5-20, barrio Centro.\n"
                    "Cuando quieras pedir, escribe *menú*."
                ),
            },
            "productos": {
                "kind": "products",
                "source": "catalog",
                "body": "Elige un producto para agregarlo a tu pedido.",
                "button_label": "Ver productos",
                "more_label": "Ver más",
                "page_size": 10,
                "next_after_pick": "agregado",
                "empty_body": "Por ahora no tenemos productos cargados. Escríbenos y te atendemos.",
            },
            "agregado": {
                "kind": "buttons",
                "body": "Listo, lo agregué a tu pedido. ¿Qué sigue?",
                "options": [
                    {"id": "agregar_mas", "label": "Agregar más", "next": "productos"},
                    {"id": "ver_pedido", "label": "Ver mi pedido", "next": "resumen"},
                    {"id": "cancelar", "label": "Cancelar pedido", "next": "cancelado"},
                ],
            },
            "resumen": {
                "kind": "order_summary",
                "body": "Total: {total}\n¿Confirmas tu pedido?",
                "confirm_next": "direccion",
                "add_more_next": "productos",
                "cancel_next": "cancelado",
            },
            "direccion": {
                "kind": "collect",
                "prompt": "¿A qué dirección te lo llevamos? Escríbela completa, con barrio.",
                "field": "direccion",
                "validation": "text",
                "error_message": "Necesito la dirección escrita para poder tomar el pedido.",
                "next": "pedido_confirmado",
            },
            "pedido_confirmado": {
                "kind": "handoff",
                "message": (
                    "¡Gracias! Una persona del equipo confirma tu pedido y el tiempo de "
                    "entrega en un momento."
                ),
                "reason": "order_confirmed",
            },
            "cancelado": {
                "kind": "text",
                "body": (
                    "Listo, cancelé el pedido. Cuando quieras volver a empezar, escribe *menú*."
                ),
            },
            "persona": {
                "kind": "handoff",
                "message": "Te paso con una persona del equipo; en un momento te responden.",
                "reason": "customer_request",
            },
        },
    }
)

__all__ = ["BIANKI_DEMO_MENU"]
