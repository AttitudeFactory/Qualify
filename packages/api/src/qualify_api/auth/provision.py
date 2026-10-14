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

    # Invite someone to register their own business (emails a single-use link):
    uv run python -m qualify_api.auth.provision invite --email cliente@negocio.com \
        --name María --business "Arepera La Nona" --note "Como hablamos hoy…"

Passwords are prompted (never argv — argv leaks into shell history and `ps`). The invite
link is always printed too, so it can be shared by hand when mail is not configured.
"""

from __future__ import annotations

import argparse
import getpass
import os
from uuid import UUID

from qualify_api.auth.invites import (
    DEFAULT_INVITE_DAYS,
    SignupNotAllowed,
    create_invite,
    send_invite_email,
)
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


def _default_base_url() -> str:
    return (
        os.environ.get("QUALIFY_PUBLIC_URL")
        or os.environ.get("REFLEX_DEPLOY_URL")
        or "http://localhost:3100"
    )


def _invite(
    email: str,
    days: int,
    base_url: str,
    send: bool,
    *,
    name: str,
    business: str,
    note: str,
    signer: str,
) -> None:
    from qualify_api.mail import MailError, MailNotConfigured, default_mailer, mail_reply_to

    try:
        invite = create_invite(
            email,
            days=days,
            invited_by=signer or "cli",
            recipient_name=name,
            business_name=business,
            note=note,
        )
    except SignupNotAllowed as exc:
        raise SystemExit(f"refused: {exc.message}") from None
    print(f"ok: invite for {invite.email}, expires {invite.expires_at:%Y-%m-%d %H:%M} UTC")
    print(f"    link: {invite.link(base_url)}")
    if not send:
        return
    try:
        send_invite_email(
            default_mailer(), invite, base_url, signer=signer, can_reply=bool(mail_reply_to())
        )
    except (MailNotConfigured, MailError) as exc:
        print(f"    email NOT sent ({exc}); share the link above by hand")
        return
    print("    email sent")


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

    invite = sub.add_parser("invite", help="email a single-use signup invitation")
    invite.add_argument("--email", required=True, help="who may register (literal email)")
    invite.add_argument("--name", default="", help="their first name, for the greeting")
    invite.add_argument("--business", default="", help="the business; prefills the signup")
    invite.add_argument("--note", default="", help="a personal line from you (≤600 chars)")
    invite.add_argument(
        "--signer",
        default=os.environ.get("QUALIFY_INVITE_SIGNER", ""),
        help="who invites, e.g. 'Herwin Rey' (default: QUALIFY_INVITE_SIGNER)",
    )
    invite.add_argument("--days", type=int, default=DEFAULT_INVITE_DAYS)
    invite.add_argument("--base-url", default=None, help="public app URL for the link")
    invite.add_argument("--no-email", action="store_true", help="only print the link")

    args = parser.parse_args(argv)
    if args.command == "invite":
        _invite(
            args.email,
            args.days,
            args.base_url or _default_base_url(),
            not args.no_email,
            name=args.name,
            business=args.business,
            note=args.note,
            signer=args.signer.strip(),
        )
        return
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
