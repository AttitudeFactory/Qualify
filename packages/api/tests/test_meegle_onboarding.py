"""`qualify_api.meegle.onboarding.OnboardingEngine` with a fake Meegle and the invite
functions stubbed — offline. What each use-case writes back, and the failure paths."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from qualify_api.auth.invites import CreatedInvite, SignupNotAllowed
from qualify_api.mail import FakeMailer, MailError, MailNotConfigured
from qualify_api.meegle import onboarding
from qualify_api.meegle.client import FieldMeta, MeegleApiError, WorkflowNode, WorkItem
from qualify_api.meegle.onboarding import (
    INVITED_BY_PREFIX,
    OnboardingEngine,
    WorkItemNotFound,
    text_value,
)
from qualify_api.meegle.schema import SchemaResolver
from qualify_api.meegle.settings import MeegleNames

NOW = datetime(2026, 10, 16, 15, 0, tzinfo=UTC)
TENANT = UUID("77777777-7777-4777-8777-777777777777")
ITEM = 5390584662

KEYS = {
    "Correo": "f_mail",
    "Nombre de la persona": "f_name",
    "Nota personal": "f_note",
    "Estado Qualify": "f_status",
    "Enlace de invitación": "f_link",
    "Vence": "f_expires",
    "Registrada el": "f_registered",
    "Tenant": "f_tenant",
    "Qualify ref": "f_ref",
}
STATUS_OPTIONS = tuple(
    (label, f"opt_{label}")
    for label in ("pendiente", "invitada", "entregada", "registrada", "vencida", "error")
)


class FakeMeegle:
    """The slice of `MeegleClient` the engine uses, recording every write."""

    def __init__(self) -> None:
        self.items: dict[int, WorkItem] = {}
        self.updates: list[tuple[int, dict[str, Any]]] = []
        self.comments: list[tuple[int, str]] = []
        self.operations: list[tuple[int, str, str, str]] = []
        self.refuse_operate: Exception | None = None

    def query(self, ids: list[int]) -> list[WorkItem]:
        return [self.items[i] for i in ids if i in self.items]

    def update_fields(self, work_item_id: int, pairs: dict[str, Any]) -> None:
        self.updates.append((work_item_id, dict(pairs)))

    def operate_node(
        self, work_item_id: int, node_id: str, *, action: str = "confirm", rollback_reason: str = ""
    ) -> None:
        if self.refuse_operate is not None:
            raise self.refuse_operate
        self.operations.append((work_item_id, node_id, action, rollback_reason))

    def comment(self, work_item_id: int, markdown: str) -> int | None:
        self.comments.append((work_item_id, markdown))
        return len(self.comments)

    def fields_meta(self) -> list[FieldMeta]:
        return [
            FieldMeta(
                key,
                name,
                "select" if name == "Estado Qualify" else "text",
                STATUS_OPTIONS if name == "Estado Qualify" else (),
            )
            for name, key in KEYS.items()
        ]

    def workflow(self, work_item_id: int) -> list[WorkflowNode]:
        return [
            WorkflowNode("started", "started", "Datos"),
            WorkflowNode("state_0", "state_0", "Invitada"),
            WorkflowNode("state_1", "state_1", "Registrada"),
        ]


class Invites:
    """Stubs for `create_invite` / `send_invite_email` / `expire_invites_for_work_item`."""

    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.sent: list[tuple[CreatedInvite, str, str]] = []
        self.expired: list[int] = []
        self.create_raises: Exception | None = None
        self.send_raises: Exception | None = None
        self.expire_returns = 1

    def create_invite(self, email: str, **kwargs: Any) -> CreatedInvite:
        if self.create_raises is not None:
            raise self.create_raises
        self.created.append({"email": email, **kwargs})
        return CreatedInvite(
            email=email,
            token="tok123",
            expires_at=NOW + timedelta(days=7),
            recipient_name=kwargs.get("recipient_name", ""),
            business_name=kwargs.get("business_name", ""),
            note=kwargs.get("note", ""),
            id=UUID("12345678-1234-4123-8123-123456789abc"),
        )

    def send_invite_email(self, mailer, invite, base_url, *, signer="", can_reply=False):  # noqa: ANN001, ANN201
        if self.send_raises is not None:
            raise self.send_raises
        self.sent.append((invite, base_url, signer))
        return mailer.send.__self__.__class__.__name__ and "re_123"

    def expire_invites_for_work_item(self, work_item_id: int) -> int:
        self.expired.append(work_item_id)
        return self.expire_returns


@pytest.fixture
def meegle() -> FakeMeegle:
    fake = FakeMeegle()
    fake.items[ITEM] = WorkItem(
        id=ITEM,
        name="Arepera La Nona",
        fields={
            "f_mail": "  maria@arepera.com ",
            "f_name": "María",
            "f_note": {"doc_text": "Como hablamos hoy.", "doc": "{...}"},
        },
    )
    return fake


@pytest.fixture
def invites(monkeypatch: pytest.MonkeyPatch) -> Invites:
    stubs = Invites()
    monkeypatch.setattr(onboarding, "create_invite", stubs.create_invite)
    monkeypatch.setattr(onboarding, "send_invite_email", stubs.send_invite_email)
    monkeypatch.setattr(
        onboarding, "expire_invites_for_work_item", stubs.expire_invites_for_work_item
    )
    monkeypatch.setattr(onboarding, "mail_reply_to", lambda: "")
    return stubs


@pytest.fixture
def engine(meegle: FakeMeegle, invites: Invites) -> OnboardingEngine:
    mailer = FakeMailer()
    return OnboardingEngine(
        meegle,  # type: ignore[arg-type]
        SchemaResolver(meegle, MeegleNames()),
        mailer=lambda: mailer,
        base_url="https://app.qualify.la",
        signer="Herwin Rey",
        clock=lambda: NOW,
    )


# --------------------------------------------------------------------------------------
# Datos completed → invitation
# --------------------------------------------------------------------------------------


def test_datos_creates_the_invite_mails_it_and_writes_back(
    engine: OnboardingEngine, meegle: FakeMeegle, invites: Invites
) -> None:
    result = engine.start_invitation(ITEM)
    assert result.ok and result.invite_id is not None

    (created,) = invites.created
    assert created == {
        "email": "maria@arepera.com",
        "invited_by": f"{INVITED_BY_PREFIX}{ITEM}",
        "recipient_name": "María",
        "business_name": "Arepera La Nona",
        "note": "Como hablamos hoy.",
        "meegle_work_item_id": ITEM,
    }
    ((invite, base_url, signer),) = invites.sent
    assert base_url == "https://app.qualify.la" and signer == "Herwin Rey"

    ((item_id, pairs),) = meegle.updates
    assert item_id == ITEM
    assert pairs == {
        "f_status": "opt_invitada",
        "f_link": "https://app.qualify.la/registro?invitacion=tok123",
        "f_expires": int((NOW + timedelta(days=7)).timestamp() * 1000),
        "f_ref": "12345678-1234-4123-8123-123456789abc",
    }
    ((_, comment),) = meegle.comments
    assert comment.startswith("Invitación enviada a maria@arepera.com. Vence el 23 de octubre")
    assert meegle.operations == []  # nothing rolled back, nothing confirmed


def test_an_invalid_email_marks_error_comments_and_rolls_datos_back(
    engine: OnboardingEngine, meegle: FakeMeegle, invites: Invites
) -> None:
    invites.create_raises = SignupNotAllowed("El email no es válido.")
    result = engine.start_invitation(ITEM)
    assert not result.ok and result.reason == "invalid_input" and result.invite_id is None
    assert invites.sent == []
    ((_, pairs),) = meegle.updates
    assert pairs == {"f_status": "opt_error"}  # no link: no invite exists
    ((_, comment),) = meegle.comments
    assert "El email no es válido." in comment and "«Datos»" in comment
    assert meegle.operations == [(ITEM, "started", "rollback", "El email no es válido.")]


@pytest.mark.parametrize(
    ("exc", "reason"),
    [
        (MailError("mail provider answered 403"), "mail_failed"),
        (
            MailNotConfigured("QUALIFY_RESEND_API_KEY / QUALIFY_MAIL_FROM are not set"),
            "mail_not_configured",
        ),
    ],
)
def test_a_mail_failure_keeps_the_invite_and_hands_over_the_link(
    engine: OnboardingEngine, meegle: FakeMeegle, invites: Invites, exc: Exception, reason: str
) -> None:
    invites.send_raises = exc
    result = engine.start_invitation(ITEM)
    assert not result.ok and result.reason == reason
    assert result.invite_id is not None  # the invite exists; only the mail failed
    ((_, pairs),) = meegle.updates
    assert pairs["f_status"] == "opt_error"
    assert pairs["f_link"] == "https://app.qualify.la/registro?invitacion=tok123"
    assert pairs["f_ref"] == "12345678-1234-4123-8123-123456789abc"
    ((_, comment),) = meegle.comments
    assert "sí quedó creada" in comment and "mandarlo a mano" in comment
    assert meegle.operations[0][2] == "rollback"


def test_a_refused_rollback_does_not_hide_the_error(
    engine: OnboardingEngine, meegle: FakeMeegle, invites: Invites
) -> None:
    invites.create_raises = SignupNotAllowed("El email no es válido.")
    meegle.refuse_operate = MeegleApiError("Meegle refused (1): already rolled back", code=1)
    result = engine.start_invitation(ITEM)
    assert not result.ok
    assert meegle.updates and meegle.comments  # status + comment still written


def test_a_missing_item_is_work_item_not_found(engine: OnboardingEngine) -> None:
    with pytest.raises(WorkItemNotFound):
        engine.start_invitation(999)


# --------------------------------------------------------------------------------------
# Terminated / registered
# --------------------------------------------------------------------------------------


def test_terminated_expires_the_invites_and_marks_vencida(
    engine: OnboardingEngine, meegle: FakeMeegle, invites: Invites
) -> None:
    assert engine.expire_for_terminated(ITEM) == 1
    assert invites.expired == [ITEM]
    assert meegle.updates == [(ITEM, {"f_status": "opt_vencida"})]
    invites.expire_returns = 0
    assert engine.expire_for_terminated(ITEM) == 0
    assert len(meegle.updates) == 1  # nothing to mark when nothing expired


def test_registered_confirms_the_node_and_writes_tenant_and_date(
    engine: OnboardingEngine, meegle: FakeMeegle
) -> None:
    engine.mark_registered(ITEM, TENANT)
    assert meegle.updates == [
        (
            ITEM,
            {
                "f_status": "opt_registrada",
                "f_tenant": str(TENANT),
                "f_registered": int(NOW.timestamp() * 1000),
            },
        )
    ]
    assert meegle.operations == [(ITEM, "state_1", "confirm", "")]


def test_registered_tolerates_a_node_already_completed(
    engine: OnboardingEngine, meegle: FakeMeegle
) -> None:
    meegle.refuse_operate = MeegleApiError("Meegle refused (2): node finished", code=2)
    engine.mark_registered(ITEM, TENANT)  # no raise: the fields are the record
    assert meegle.updates and meegle.operations == []


# --------------------------------------------------------------------------------------
# Field value shapes
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        ("  texto ", "texto"),
        ({"doc_text": " hola \n", "doc": "x"}, "hola"),
        ('{"doc_text": "desde json", "doc": "{}"}', "desde json"),
        ("{not json", "{not json"),
        ({"label": "P0", "value": "option_1"}, "option_1"),
        (["a", {"doc_text": "b"}], "a b"),
        (42, "42"),
    ],
)
def test_text_value_tolerates_every_shape_meegle_uses(value: Any, expected: str) -> None:
    assert text_value(value) == expected


def test_uuid_ids_are_fresh_per_invite() -> None:
    assert uuid4() != uuid4()
