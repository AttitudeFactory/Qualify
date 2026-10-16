"""`db`-marked: invitations against live Postgres (migration 0063) — stored as a hash,
looked up by the raw token, spent exactly once by the signup that creates the business."""

from __future__ import annotations

from uuid import uuid4

import pytest
from qualify_shared.db.admin import admin_session
from sqlalchemy import select

from qualify_api.auth import (
    FakeAuthProvider,
    SignupNotAllowed,
    authorize_signup,
    create_invite,
    lookup_invite,
    register_business,
)
from qualify_api.tenancy.models import SignupInvite

pytestmark = pytest.mark.db


def _email() -> str:
    return f"hlrd1993+invite-{uuid4().hex[:8]}@gmail.com"


def _register(provider: FakeAuthProvider, email: str, invite_id):
    return register_business(
        provider,
        business_name="Invitado",
        email=email,
        password="correct-horse-9",
        country="VE",
        timezone="America/Caracas",
        currency="USD",
        invite_id=invite_id,
    )


def test_only_the_hash_is_stored() -> None:
    created = create_invite(_email(), business_name="Arepera La Nona", note="Hola")
    with admin_session() as session:
        rows = session.scalars(select(SignupInvite).where(SignupInvite.email == created.email))
        stored = [row.token_hash for row in rows]
    assert stored and created.token not in stored
    view = lookup_invite(created.token)
    assert view is not None and view.email == created.email
    assert view.business_name == "Arepera La Nona"  # prefills the signup
    assert lookup_invite("not-a-token") is None


def test_an_invite_makes_one_account() -> None:
    created = create_invite(_email())
    invite_id = authorize_signup(created.email, created.token)
    assert invite_id is not None
    _register(FakeAuthProvider(), created.email, invite_id)
    assert lookup_invite(created.token) is None  # spent
    with pytest.raises(SignupNotAllowed):
        authorize_signup(created.email, created.token)
    with pytest.raises(SignupNotAllowed):  # a raced second signup fails at consume time
        _register(FakeAuthProvider(), _email().replace("invite", "race"), invite_id)
