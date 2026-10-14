"""WA-06 manual smoke: send a text (and optionally three buttons) from the test number.

    python -m qualify_api.whatsapp.smoke --to +57300... --text "hola" [--buttons] [--phone-number]

DEV ONLY. Reads `QUALIFY_WA_SYSTEM_USER_TOKEN` and `QUALIFY_WA_PHONE_NUMBER_ID` from the
environment — this is the one process in which the token is read from a variable at
all; WA-05 moves it into `oauth_credentials`, after which every caller goes through
`CredentialResolver.client_for(connection_id, scheme="Bearer")` and this script keeps
working only for the person who already holds the token. It prints the `wamid` and
nothing else: never the token, never the response body.

Sends for real and costs a conversation — run it against your own number.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.resolver import _InjectedAuthClient
from qualify_api.whatsapp.client import ButtonSpec, HttpWhatsAppClient, WhatsAppApiError

_TOKEN_ENV = "QUALIFY_WA_SYSTEM_USER_TOKEN"
_PHONE_ENV = "QUALIFY_WA_PHONE_NUMBER_ID"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="qualify_api.whatsapp.smoke", description=__doc__)
    parser.add_argument("--to", required=True, help="recipient, E.164 with the plus sign")
    parser.add_argument("--text", default="hola desde Qualify", help="text body to send")
    parser.add_argument(
        "--buttons", action="store_true", help="also send a 3-button interactive message"
    )
    parser.add_argument(
        "--phone-number",
        action="store_true",
        help="also print the number's verified_name/quality/status (no send involved)",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    token = os.environ.get(_TOKEN_ENV)
    phone_number_id = os.environ.get(_PHONE_ENV)
    if not token or not phone_number_id:
        print(f"set {_TOKEN_ENV} and {_PHONE_ENV} in the environment", file=sys.stderr)
        return 2

    graph = _InjectedAuthClient(token, scheme="Bearer")
    del token
    client = HttpWhatsAppClient(
        graph_client=graph,
        graph_url=MetaOAuthSettings.from_env().graph_url,
        phone_number_id=phone_number_id,
    )
    try:
        if args.phone_number:
            info = await client.get_phone_number()
            print(
                f"phone_number verified_name={info.verified_name!r} "
                f"quality={info.quality_rating} status={info.status} "
                f"tier={info.messaging_limit_tier} name_status={info.name_status}"
            )
        wamid = await client.send_text(args.to, args.text)
        print(f"text wamid={wamid}")
        if args.buttons:
            wamid = await client.send_interactive_buttons(
                args.to,
                "Smoke WA-06: elige una opcion",
                [
                    ButtonSpec(id="smoke_menu", title="Ver menu"),
                    ButtonSpec(id="smoke_order", title="Hacer pedido"),
                    ButtonSpec(id="smoke_human", title="Hablar con alguien"),
                ],
                footer="Qualify",
            )
            print(f"buttons wamid={wamid}")
    except WhatsAppApiError as exc:
        print(
            f"whatsapp api error: status={exc.status} code={exc.code} subcode={exc.subcode} "
            f"auth={exc.is_auth_error} transport={exc.is_transport}",
            file=sys.stderr,
        )
        return 1
    finally:
        await graph.aclose()
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(_parse_args(sys.argv[1:] if argv is None else argv)))


if __name__ == "__main__":
    raise SystemExit(main())
