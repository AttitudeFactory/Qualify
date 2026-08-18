"""CLI over the registration service — recovery tool and seeded-tenant onboarding.

Not a separate code path: both subcommands call exactly the functions the `/signup`
page uses. Typical uses:

    # Register a brand-new business (assigns a tenant_id automatically):
    uv run python -m qualify_api.auth.provision register \
        --name "Polet Bubble Tea" --email hlrd1993+polet@gmail.com \
        --country VE --timezone America/Caracas --currency USD

    # Give one of the seeded tenants a login:
    uv run python -m qualify_api.auth.provision link \
        --tenant a0000000-0000-4000-8000-000000000001 \
        --email hlrd1993+puntoservis@gmail.com

Passwords are prompted (never argv — argv leaks into shell history and `ps`).
"""

from __future__ import annotations

import argparse
import getpass
from uuid import UUID

from qualify_api.auth.registry import default_auth_provider
from qualify_api.auth.service import (
    RegistrationInvalid,
    link_login_to_tenant,
    register_business,
)


def _prompt_password() -> str:
    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        raise SystemExit("passwords do not match")
    return password


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="qualify-auth-provision", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    register = sub.add_parser("register", help="register a new business (new tenant)")
    register.add_argument("--name", required=True, help="business name (becomes tenant + brand)")
    register.add_argument("--email", required=True)
    register.add_argument("--country", required=True, help="ISO country, e.g. VE")
    register.add_argument("--timezone", required=True, help="IANA tz, e.g. America/Caracas")
    register.add_argument("--currency", required=True, help="ISO-4217, e.g. USD")

    link = sub.add_parser("link", help="attach a login to an existing tenant")
    link.add_argument("--tenant", required=True, help="existing tenant uuid")
    link.add_argument("--email", required=True)

    args = parser.parse_args(argv)
    provider = default_auth_provider()
    password = _prompt_password()

    try:
        if args.command == "register":
            result = register_business(
                provider,
                business_name=args.name,
                email=args.email,
                password=password,
                country=args.country,
                timezone=args.timezone,
                currency=args.currency,
            )
        else:
            result = link_login_to_tenant(
                provider,
                tenant_id=UUID(args.tenant),
                email=args.email,
                password=password,
            )
    except RegistrationInvalid as exc:
        raise SystemExit(f"refused: {exc.message}") from None

    print(f"ok: tenant_id={result.tenant_id} auth_user_id={result.auth_user_id}")
    print(f"    business={result.business_name!r} email={result.email}")


if __name__ == "__main__":
    main()
