"""`db`-marked: Brand Kit drafts prepared by a Meegle «Alta de cliente» are reserved to
that Alta's invitation (PB-0, m-24852193, migration 0091).

The three paths of the ticket — the public first view does not resume a reserved draft,
an invite of the same item adopts it, an invite of another item (or none) does not — plus
idempotency per item and tenant isolation of the draft row."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from qualify_api.auth import (
    EmailHasAccount,
    FakeAuthProvider,
    create_invite,
    register_business,
    resolve_login,
    service,
    start_alta_brand_kit_draft,
    start_brand_kit_draft,
)
from qualify_api.auth.drafts import ORIGIN_ALTA, ORIGIN_WEB
from qualify_api.tenancy.models import Brand, BrandKitDraft, User

pytestmark = pytest.mark.db

_DEFAULTS = {"country": "VE", "timezone": "America/Caracas", "currency": "USD"}


@pytest.fixture(autouse=True)
def _no_meegle_write_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """A signup with an Alta invite writes back to Meegle; offline here."""
    monkeypatch.setattr(service, "notify_meegle_registered", lambda item, tenant: None)


def _email() -> str:
    return f"hlrd1993+alta-{uuid4().hex[:8]}@gmail.com"


def _item() -> int:
    return uuid4().int % 10**12


def _register(email: str, invite_id: UUID | None, provider: FakeAuthProvider | None = None):
    return register_business(
        provider or FakeAuthProvider(),
        business_name="Bianki",
        email=email,
        password="correct-horse-9",
        country="CO",
        timezone="America/Bogota",
        currency="COP",
        invite_id=invite_id,
    )


def _row(tenant_id: UUID) -> BrandKitDraft:
    with admin_session() as session:
        row = session.scalar(select(BrandKitDraft).where(BrandKitDraft.tenant_id == tenant_id))
        assert row is not None
        session.expunge(row)
        return row


def test_an_alta_draft_carries_its_origin_and_is_idempotent_per_item() -> None:
    email, item = _email(), _item()
    first = start_alta_brand_kit_draft(email, item)
    assert first.resumed is False
    row = _row(first.tenant_id)
    assert (row.origin, row.meegle_work_item_id, row.claimed_at) == (ORIGIN_ALTA, item, None)

    again = start_alta_brand_kit_draft(email.upper(), item)
    assert again.resumed is True and again.tenant_id == first.tenant_id


def test_a_corrected_alta_email_rekeys_the_same_draft() -> None:
    item = _item()
    first = start_alta_brand_kit_draft(_email(), item)
    corrected = _email()
    again = start_alta_brand_kit_draft(corrected, item)
    assert again.tenant_id == first.tenant_id and again.email == corrected
    with admin_session() as session:
        owner = session.scalar(select(User).where(User.tenant_id == first.tenant_id))
        assert owner is not None and owner.email == corrected
    # …and the corrected email's invite adopts it.
    invite = create_invite(corrected, meegle_work_item_id=item)
    assert _register(corrected, invite.id).tenant_id == first.tenant_id


def test_the_public_first_view_does_not_resume_a_reserved_draft() -> None:
    email = _email()
    reserved = start_alta_brand_kit_draft(email, _item())

    public = start_brand_kit_draft(email, **_DEFAULTS)
    # Indistinguishable from "no draft for this email": a fresh, empty web draft.
    assert public.resumed is False
    assert public.tenant_id != reserved.tenant_id
    assert _row(public.tenant_id).origin == ORIGIN_WEB
    assert _row(reserved.tenant_id).claimed_at is None


def test_an_invite_of_the_same_item_resumes_the_reserved_draft_before_signup() -> None:
    email, item = _email(), _item()
    reserved = start_alta_brand_kit_draft(email, item)
    own = create_invite(email, meegle_work_item_id=item)
    other = create_invite(email, meegle_work_item_id=_item())

    resumed = start_brand_kit_draft(email, **_DEFAULTS, invite_token=own.token)
    assert resumed.resumed is True and resumed.tenant_id == reserved.tenant_id

    elsewhere = start_brand_kit_draft(email, **_DEFAULTS, invite_token=other.token)
    assert elsewhere.tenant_id != reserved.tenant_id
    bogus = start_brand_kit_draft(email, **_DEFAULTS, invite_token="not-a-token")
    assert bogus.tenant_id == elsewhere.tenant_id  # the email's one web draft, resumed


def test_signup_with_an_invite_of_the_same_item_adopts_the_reserved_draft() -> None:
    email, item = _email(), _item()
    reserved = start_alta_brand_kit_draft(email, item)
    start_brand_kit_draft(email, **_DEFAULTS)  # a public visitor also typed the email
    invite = create_invite(email, meegle_work_item_id=item)
    provider = FakeAuthProvider()

    registered = _register(email, invite.id, provider)
    assert registered.tenant_id == reserved.tenant_id

    assert _row(reserved.tenant_id).claimed_at is not None
    with admin_session() as session:
        users = session.scalars(select(User).where(User.tenant_id == reserved.tenant_id)).all()
        assert len(users) == 1 and users[0].auth_user_id == registered.auth_user_id
        brands = session.scalars(select(Brand).where(Brand.tenant_id == reserved.tenant_id))
        assert [b.name for b in brands] == ["Bianki"]
    assert resolve_login(provider, email, "correct-horse-9").tenant_id == reserved.tenant_id
    with pytest.raises(EmailHasAccount):  # adopted: the item's draft is an account now
        start_alta_brand_kit_draft(email, item)


def test_signup_with_an_invite_of_another_item_does_not_adopt_it() -> None:
    email = _email()
    reserved = start_alta_brand_kit_draft(email, _item())
    invite = create_invite(email, meegle_work_item_id=_item())

    registered = _register(email, invite.id)
    assert registered.tenant_id != reserved.tenant_id
    assert _row(reserved.tenant_id).claimed_at is None


def test_signup_without_an_invite_does_not_adopt_it() -> None:
    email = _email()
    reserved = start_alta_brand_kit_draft(email, _item())

    registered = _register(email, None)
    assert registered.tenant_id != reserved.tenant_id
    assert _row(reserved.tenant_id).claimed_at is None


def test_web_drafts_keep_their_behaviour_with_any_invite() -> None:
    """An invite not made from Meegle (`just invite`), or one whose item has no reserved
    draft, adopts the web draft typed with that email, as before 0091."""
    email = _email()
    web = start_brand_kit_draft(email, **_DEFAULTS)
    invite = create_invite(email, meegle_work_item_id=_item())
    assert _register(email, invite.id).tenant_id == web.tenant_id

    plain_email = _email()
    plain_web = start_brand_kit_draft(plain_email, **_DEFAULTS)
    plain = create_invite(plain_email)
    assert _register(plain_email, plain.id).tenant_id == plain_web.tenant_id


def test_an_email_with_an_account_gets_no_alta_draft() -> None:
    email = _email()
    _register(email, None)
    with pytest.raises(EmailHasAccount):
        start_alta_brand_kit_draft(email, _item())


def test_one_alta_draft_per_item_is_enforced_by_the_schema() -> None:
    item = _item()
    first = start_alta_brand_kit_draft(_email(), item)
    other = start_brand_kit_draft(_email(), **_DEFAULTS)  # some other tenant
    with pytest.raises(IntegrityError), admin_session() as session:
        session.execute(
            text(
                "UPDATE brand_kit_drafts SET origin = 'alta', meegle_work_item_id = :i "
                "WHERE tenant_id = :t"
            ),
            {"i": item, "t": other.tenant_id},
        )
    assert _row(first.tenant_id).meegle_work_item_id == item


def test_an_alta_draft_is_invisible_to_other_tenants() -> None:
    reserved = start_alta_brand_kit_draft(_email(), _item())
    stranger = start_brand_kit_draft(_email(), **_DEFAULTS)

    with tenant_session(stranger.tenant_id) as session:
        seen = session.scalars(select(BrandKitDraft.tenant_id)).all()
    assert seen == [stranger.tenant_id]

    with tenant_session(reserved.tenant_id) as session:
        seen = session.scalars(select(BrandKitDraft.tenant_id)).all()
    assert seen == [reserved.tenant_id]
