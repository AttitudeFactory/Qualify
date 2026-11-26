"""m-25120319: the email of a failed avatar of a Clip («Uno de tus avatares no se pudo
crear. Entra para intentarlo de nuevo o quitarlo.»).

Offline only: the Clip, its blocks and the outbox live in memory, the mailer is a double
that records (no Resend call, no network), the identity check is injected and the clock
is fixed. The Postgres outbox (migration 0186) is in `test_clip_avatar_mail_db.py`."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from qualify_api.creative import clip_avatar as ca
from qualify_api.creative import clip_avatar_mail as cm
from qualify_api.creative.fsm import DRAFTING, FAILED
from qualify_api.mail import MailError, MailRejected, OutgoingMail
from qualify_api.mail import clip_avatar as template

from .test_clip_avatar import SCRIPT, _presenter
from .test_clip_avatar_first_create import _at, _clip_brief
from .test_clip_avatar_retry import T0, World
from .test_clip_avatar_retry import _queue as _queue  # noqa: F401 — the switches on
from .test_clip_avatar_retry import queue_on as queue_on  # noqa: F401 — its fixture
from .test_content_service import TENANT_ID

BASE = "https://app.qualify.test"
BUSINESS = "Arepas Doña Clotilde"
EMAIL = "clotilde.owner@example.org"
NAME = "Clotilde Pérez"
AUTH_USER = uuid4()


class RecordingMailer:
    """The Resend double: records each mail, answers like Resend (an id) or fails."""

    def __init__(self) -> None:
        self.sent: list[OutgoingMail] = []
        self.fail_with: Exception | None = None

    def send(self, mail: OutgoingMail) -> str | None:
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append(mail)
        return f"resend-{len(self.sent)}"


class WorldOutbox(cm.MemoryAvatarFailureOutbox):
    """The in-memory outbox reading the Clip live from the test's world."""

    world: World

    def clip_view(self, tenant_id: UUID, clip_id: UUID) -> cm.ClipView | None:
        draft = self.world.repo.drafts.get(clip_id)
        if draft is None:
            return None
        return cm.ClipView(
            status=draft.status,
            business=BUSINESS,
            timezone="America/Bogota",
            plan=_clip_brief(self.world, clip_id).media.clip_avatar_plan,
            blocks=self.world.store.blocks_of(tenant_id=tenant_id, clip_id=clip_id),
        )


class Mailing:
    """A world whose Clip stages its failure emails, and the sender's pass."""

    def __init__(self, **kw: Any) -> None:
        self.world = World(**kw)
        self.outbox = WorldOutbox()
        self.outbox.world = self.world
        self.outbox.recipients[(TENANT_ID, UUID(int=0))] = cm.Recipient(EMAIL, AUTH_USER)
        self.world.content._clip_failure_outbox = self.outbox  # noqa: SLF001
        self.mailer = RecordingMailer()
        self.verified: list[UUID] = []
        self.made = self.world.create(_at(_presenter(), 0))

    def verify(self, auth_user_id: UUID, email: str) -> str | None:
        self.verified.append(auth_user_id)
        return email if auth_user_id == AUTH_USER else None

    def fail_and_see(self, index: int = 0) -> None:
        self.world.fail(self.made.block_ids[index])
        self.world.run(self.made.clip_id)

    def send(self, *, now: datetime | None = None, base_url: str | None = BASE) -> int:
        return cm.send_pending(
            self.outbox,
            TENANT_ID,
            now=now or self.world.clock.now,
            mailer=self.mailer,
            base_url=base_url,
            verify=self.verify,
        )

    def retry(self, index: int = 0) -> None:
        self.world.retry(self.made, index)

    def plan_entry(self, slot: int = 1) -> Any:
        plan = _clip_brief(self.world, self.made.clip_id).media.clip_avatar_plan
        return next(e for e in plan if e.slot == slot)

    def reasons(self) -> list[str | None]:
        return [r.closed_reason for r in self.outbox.rows]


# ---------------------------------------------------------------------------
# one email per failed avatar


def test_a_failure_seen_stages_one_email_in_the_same_write_and_sends_it() -> None:
    m = Mailing()
    m.fail_and_see()
    (row,) = m.outbox.rows
    entry = m.plan_entry()
    assert entry.failed_at == T0 and row.failed_at == T0  # the stamp IS the identity
    assert (row.clip_id, row.block_id, row.slot) == (m.made.clip_id, m.made.block_ids[0], 1)
    assert row.code == "provider_error"
    assert m.send() == 1
    (mail,) = m.mailer.sent
    assert mail.to == EMAIL
    assert mail.subject == f"{BUSINESS}: uno de tus avatares no se pudo crear"
    assert template.LEAD.format(business=BUSINESS) in mail.text
    assert template.HEADING in mail.text
    url = f"{BASE}/drafts/{m.made.clip_id}"
    assert url in mail.text and f'href="{url}"' in mail.html
    assert template.BUTTON in mail.html
    # the 72 h in the business's hour: 15:00 UTC + 72 h = 10:00 in Bogotá three days on
    assert "domingo 29 de noviembre, 10 a. m." in mail.text
    assert mail.idempotency_key == cm.failure_key(TENANT_ID, m.made.clip_id, 1, T0)
    assert row.sent_at is not None and row.provider_id == "resend-1"


def test_reading_the_state_again_or_a_restarted_worker_never_sends_a_second_email() -> None:
    m = Mailing()
    m.fail_and_see()
    for _ in range(3):  # later passes read the same failure again
        m.world.clock.now += timedelta(minutes=1)
        m.world.run(m.made.clip_id)
    assert len(m.outbox.rows) == 1
    assert m.send() == 1
    assert m.send() == 0  # a second pass of the same sender
    restarted = cm.failure_mail_chore(
        [TENANT_ID],
        outbox=m.outbox,
        mailer=lambda: m.mailer,
        verify=m.verify,
        clock=lambda: m.world.clock.now + timedelta(hours=1),
    )
    assert restarted() == 0  # a new worker process: nothing pending, nothing sent
    assert len(m.mailer.sent) == 1


def test_staging_the_same_failure_twice_keeps_one_row() -> None:
    """Even if the same stamp were written twice, its identity conflicts."""
    m = Mailing()
    failure = cm.AvatarFailure(m.made.block_ids[0], 1, "presenter", "provider_error", T0)
    args = {"tenant_id": TENANT_ID, "clip_id": m.made.clip_id, "user_id": UUID(int=0)}
    assert m.outbox.stage(None, failures=[failure], **args) == 1
    assert m.outbox.stage(None, failures=[failure, failure], **args) == 0
    assert len(m.outbox.rows) == 1


def test_a_retry_that_fails_again_is_a_new_failure_and_one_more_email() -> None:
    m = Mailing()
    m.fail_and_see()
    assert m.send() == 1
    m.world.clock.now = T0 + timedelta(hours=5)
    m.retry()
    assert m.plan_entry().failed_at is None
    m.world.run(m.made.clip_id)  # the new attempt is being made: nothing to say
    assert len(m.outbox.rows) == 1
    m.fail_and_see()  # the second attempt fails too
    assert [r.failed_at for r in m.outbox.rows] == [T0, T0 + timedelta(hours=5)]
    assert m.send() == 1 and m.send() == 0
    first, second = m.mailer.sent
    assert first.idempotency_key != second.idempotency_key
    # its own 72 h, from the new failure
    assert "domingo 29 de noviembre, 3 p. m." in second.text


def test_a_retry_before_the_email_left_closes_it_unsent() -> None:
    m = Mailing()
    m.fail_and_see()
    m.retry()
    assert m.send() == 0 and m.mailer.sent == []
    assert m.reasons() == ["resolved"]


def test_a_removed_avatar_or_a_clip_that_moved_on_is_not_mailed() -> None:
    m = Mailing()
    m.fail_and_see()
    m.world.remove(m.made)
    assert m.send() == 0 and m.reasons() == ["resolved"]
    other = Mailing()
    other.fail_and_see()
    clip = other.made.clip_id
    other.world.repo.drafts[clip] = replace(other.world.repo.drafts[clip], status=FAILED)
    assert other.send() == 0 and other.reasons() == ["resolved"]


def test_two_avatars_failing_in_one_pass_send_one_email_each() -> None:
    """The rule today: one email per failed avatar (each has its own buttons)."""
    m = Mailing()
    m.made = m.world.create(_at(_presenter(), 0), _at(_presenter(script="Hola."), 1))
    m.world.fail(m.made.block_ids[0])
    m.world.fail(m.made.block_ids[1])
    m.world.run(m.made.clip_id)
    assert sorted(r.slot for r in m.outbox.rows) == [1, 2]
    assert m.send() == 2


def test_a_still_creating_block_or_a_made_one_stages_nothing() -> None:
    m = Mailing()
    m.world.run(m.made.clip_id)
    assert m.outbox.rows == []
    assert m.world.repo.drafts[m.made.block_ids[0]].status == DRAFTING


# ---------------------------------------------------------------------------
# the switches


def test_with_both_switches_off_nothing_is_staged(monkeypatch: pytest.MonkeyPatch) -> None:
    m = Mailing()
    for switch in (ca.PRESENTER_SWITCH, ca.ANIMATED_SWITCH):
        monkeypatch.delenv(switch, raising=False)
    m.fail_and_see()
    assert m.plan_entry().failed_at == T0  # the Clip still sees its failure
    assert m.outbox.rows == []
    assert m.send() == 0 and m.mailer.sent == []


def test_with_both_switches_off_the_worker_sends_nothing_and_reads_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m = Mailing()
    m.fail_and_see()
    assert len(m.outbox.rows) == 1
    for switch in (ca.PRESENTER_SWITCH, ca.ANIMATED_SWITCH):
        monkeypatch.setenv(switch, "off")

    class Untouchable(cm.MemoryAvatarFailureOutbox):
        def pending_tenants(self) -> list[UUID]:
            raise AssertionError("read while switched off")

        def claim(self, *a: Any, **kw: Any) -> None:
            raise AssertionError("read while switched off")

    chore = cm.failure_mail_chore(
        None, outbox=Untouchable(), mailer=lambda: m.mailer, verify=m.verify
    )
    assert chore() == 0 and m.mailer.sent == []


def test_a_kind_switched_off_after_staging_closes_its_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m = Mailing()
    m.fail_and_see()
    monkeypatch.setenv(ca.PRESENTER_SWITCH, "off")
    assert m.send() == 0 and m.reasons() == ["switched_off"]


def test_a_switched_off_kind_is_never_a_failure_to_mail() -> None:
    m = Mailing()
    row = m.world.store.blocks_of(tenant_id=TENANT_ID, clip_id=m.made.clip_id)[0]
    entry = m.plan_entry().model_copy(update={"failed_at": T0})
    planned = ca.PlannedBlock(entry, row, "failed", "switched_off")
    assert cm.mailable_failures([planned]) == ()
    assert cm.mailable_failures([ca.PlannedBlock(entry, None, "failed", "block_missing")]) == ()


# ---------------------------------------------------------------------------
# delivery: Resend's key, uncertain sends, refusals, no recipient


def test_an_uncertain_send_is_retried_verbatim_with_the_same_key() -> None:
    m = Mailing()
    m.fail_and_see()
    m.mailer.fail_with = MailError("timeout")
    assert m.send() == 0
    frozen = m.outbox.rows[0].payload
    assert frozen is not None and m.outbox.rows[0].first_attempt_at == T0
    m.mailer.fail_with = None
    # the lease runs out; meanwhile the business's name changed: the frozen mail goes
    later = T0 + cm.LEASE + timedelta(seconds=1)
    assert m.send(now=later) == 1
    assert m.mailer.sent[0] == OutgoingMail(**frozen["mail"])
    assert m.verified == [AUTH_USER, AUTH_USER]  # checked again before the retry


def test_an_uncertain_send_stops_before_resend_forgets_its_key() -> None:
    m = Mailing()
    m.fail_and_see()
    m.mailer.fail_with = MailError("timeout")
    m.send()
    m.mailer.fail_with = None
    assert m.send(now=T0 + cm.RETRY_WINDOW) == 0
    assert m.reasons() == ["uncertain"] and m.mailer.sent == []


def test_a_refused_email_is_closed() -> None:
    m = Mailing()
    m.fail_and_see()
    m.mailer.fail_with = MailRejected("422")
    assert m.send() == 0 and m.reasons() == ["rejected"]


def test_no_confirmed_recipient_closes_it_and_a_shaky_check_waits() -> None:
    m = Mailing()
    m.fail_and_see()
    m.verify = lambda auth, email: (_ for _ in ()).throw(RuntimeError("supabase down"))  # type: ignore[method-assign]
    assert m.send() == 0 and m.reasons() == [None]  # waits for a later pass
    m.verify = lambda auth, email: None  # type: ignore[method-assign]
    assert m.send(now=T0 + cm.LEASE) == 0 and m.reasons() == ["no_recipient"]
    m2 = Mailing()
    m2.outbox.recipients.clear()  # the author left the business
    m2.fail_and_see()
    assert m2.send() == 0 and m2.reasons() == ["no_recipient"]


def test_without_mail_links_configured_only_frozen_emails_leave() -> None:
    m = Mailing()
    m.fail_and_see()
    assert m.send(base_url=None) == 0
    assert m.reasons() == [None] and m.outbox.rows[0].payload is None
    assert m.send() == 1


# ---------------------------------------------------------------------------
# privacy: ids only in the logs


def test_logs_carry_ids_only_never_an_address_a_name_or_a_script(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    m = Mailing()
    m.outbox.recipients[(TENANT_ID, UUID(int=0))] = cm.Recipient(EMAIL, AUTH_USER)
    m.fail_and_see()
    m.mailer.fail_with = MailError("timeout")
    m.send()  # deferred
    m.mailer.fail_with = None
    m.send(now=T0 + cm.LEASE)  # sent
    m.world.clock.now = T0 + timedelta(hours=1)
    m.retry()
    m.fail_and_see()
    m.mailer.fail_with = MailRejected("422")
    m.send()  # rejected
    m3 = Mailing()
    m3.fail_and_see()
    m3.retry()
    m3.send()  # closed, resolved
    records = [r for r in caplog.records if r.name == cm.logger.name]
    messages = " ".join(r.getMessage() for r in records)
    for event in ("send deferred", "sent", "rejected", "reason=resolved"):
        assert event in messages  # every path of the run was logged, and checked below
    for record in caplog.records:
        text = record.getMessage() + " " + repr(record.args)
        for secret in (EMAIL, NAME, BUSINESS, SCRIPT, "clotilde"):
            assert secret.casefold() not in text.casefold(), record.getMessage()


def test_every_log_call_of_the_outbox_passes_ids_and_codes_only() -> None:
    """The explicit review, as a test: no log call is handed an address, a name, the
    business, a script or the mail itself."""
    import ast
    import inspect

    allowed = {
        "tenant_id",
        "mail.tenant_id",
        "mail.id",
        "mail.clip_id",
        "reason",
        "type(exc).__name__",
    }

    def is_logger(func: ast.expr) -> bool:
        if isinstance(func, ast.IfExp):  # `(logger.error if … else logger.info)(…)`
            return is_logger(func.body) and is_logger(func.orelse)
        return (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "logger"
            and func.attr != "exception"  # never: it would print the exception's text
        )

    tree = ast.parse(inspect.getsource(cm))
    assert "logger.exception" not in inspect.getsource(cm)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and is_logger(n.func)]
    assert len(calls) >= 7  # every log call of the module is checked
    for call in calls:
        assert isinstance(call.args[0], ast.Constant)  # a fixed message, never data
        for arg in call.args[1:]:
            assert ast.unparse(arg) in allowed, ast.unparse(call)
        assert not call.keywords, ast.unparse(call)


# ---------------------------------------------------------------------------
# the words (pending ux-designer review)


def test_the_mail_escapes_the_business_and_has_a_plain_text_twin() -> None:
    mail = template.failure_mail(
        to=EMAIL,
        business="Pan & <Queso>",
        clip_id=UUID(int=7),
        wait_until=T0,
        timezone="America/Montevideo",
        base_url=BASE + "/",
        idempotency_key="k",
    )
    assert "Pan &amp; &lt;Queso&gt;" in mail.html and "<Queso>" not in mail.html
    assert mail.subject == "Pan & <Queso>: uno de tus avatares no se pudo crear"
    assert f"{BASE}/drafts/{UUID(int=7)}" in mail.text
    assert "jueves 26 de noviembre, 12 p. m." in mail.text  # Montevideo, UTC-3
    assert template.TEMPLATE_VERSION == "clip-avatar-failed-v1"


def test_the_key_is_derived_from_the_failure_and_carries_no_client_data() -> None:
    key = cm.failure_key(TENANT_ID, UUID(int=1), 1, T0)
    assert key == cm.failure_key(TENANT_ID, UUID(int=1), 1, T0.astimezone())
    assert key != cm.failure_key(TENANT_ID, UUID(int=1), 1, T0 + timedelta(seconds=1))
    assert key.startswith("clip-avatar-failed/") and len(key) < 256
    assert str(TENANT_ID) not in key


def test_the_worker_mail_pass_runs_both_chores_even_when_one_raises() -> None:
    from qualify_api.creative.worker.__main__ import _chain

    ran: list[str] = []

    def broken() -> int:
        ran.append("morning")
        raise RuntimeError("boom")

    def avatar() -> int:
        ran.append("avatar")
        return 2

    assert _chain(broken, avatar)() == 2 and ran == ["morning", "avatar"]


# ---------------------------------------------------------------------------
# review fixes (2026-11-26)


def test_a_database_error_carrying_client_data_never_reaches_the_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SQLAlchemy puts its `[parameters: …]` — here the frozen mail — in the exception's
    text: the pass logs the ids and the error type only."""
    caplog.set_level(logging.DEBUG)
    m = Mailing()
    m.fail_and_see()

    class Leaky(RuntimeError):
        pass

    def freeze(mail: cm.PendingMail, payload: Any, *, now: datetime) -> bool:
        raise Leaky(f"[parameters: {payload!r}] {EMAIL} {BUSINESS} {SCRIPT}")

    m.outbox.freeze = freeze  # type: ignore[method-assign]
    chore = cm.failure_mail_chore(
        [TENANT_ID], outbox=m.outbox, mailer=lambda: m.mailer, verify=m.verify,
        clock=lambda: T0,
    )  # fmt: skip
    assert chore() == 0 and m.mailer.sent == []
    assert any("error_type=Leaky" in r.getMessage() for r in caplog.records)
    for record in caplog.records:
        assert record.exc_info is None
        text = record.getMessage().casefold()
        for secret in (EMAIL, BUSINESS, SCRIPT, "parameters"):
            assert secret.casefold() not in text, record.getMessage()


def test_a_frozen_mail_is_not_resent_once_the_owner_retried_or_removed_it() -> None:
    m = Mailing()
    m.fail_and_see()
    m.mailer.fail_with = MailError("timeout")
    m.send()  # frozen, uncertain
    m.mailer.fail_with = None
    m.retry()
    assert m.send(now=T0 + cm.LEASE) == 0 and m.reasons() == ["resolved"]
    removed = Mailing()
    removed.fail_and_see()
    removed.mailer.fail_with = MailError("timeout")
    removed.send()
    removed.mailer.fail_with = None
    removed.world.remove(removed.made)
    assert removed.send(now=T0 + cm.LEASE) == 0 and removed.reasons() == ["resolved"]
    assert m.mailer.sent == [] and removed.mailer.sent == []


def test_a_frozen_mail_is_not_resent_to_someone_who_left_or_changed_address() -> None:
    m = Mailing()
    m.fail_and_see()
    m.mailer.fail_with = MailError("timeout")
    m.send()
    m.mailer.fail_with = None
    m.outbox.recipients.clear()  # no longer a member
    assert m.send(now=T0 + cm.LEASE) == 0 and m.reasons() == ["no_recipient"]
    moved = Mailing()
    moved.fail_and_see()
    moved.mailer.fail_with = MailError("timeout")
    moved.send()
    moved.mailer.fail_with = None
    moved.outbox.recipients[(TENANT_ID, UUID(int=0))] = cm.Recipient("otra@example.org", AUTH_USER)
    assert moved.send(now=T0 + cm.LEASE) == 0 and moved.reasons() == ["no_recipient"]


def test_the_time_is_read_again_before_each_claim() -> None:
    m = Mailing()
    m.fail_and_see()
    m.mailer.fail_with = MailError("timeout")
    m.send()  # frozen at T0
    m.mailer.fail_with = None
    times = iter([T0 + cm.RETRY_WINDOW, T0 + cm.RETRY_WINDOW, T0 + cm.RETRY_WINDOW])
    sent = cm.send_pending(
        m.outbox, TENANT_ID, mailer=m.mailer, base_url=BASE, verify=m.verify,
        clock=lambda: next(times),
    )  # fmt: skip
    assert sent == 0 and m.reasons() == ["uncertain"]
    with pytest.raises(ValueError):
        cm.send_pending(m.outbox, TENANT_ID, mailer=m.mailer, base_url=BASE, verify=m.verify)


def test_an_invalid_business_timezone_falls_back_to_utc() -> None:
    for zone in ("Mars/Olympus", "", "../etc"):
        mail = template.failure_mail(
            to=EMAIL, business=BUSINESS, clip_id=UUID(int=7), wait_until=T0, timezone=zone,
            base_url=BASE, idempotency_key="k",
        )  # fmt: skip
        assert "jueves 26 de noviembre, 3 p. m." in mail.text


def test_the_deadline_reads_in_spanish_from_a_table() -> None:
    utc = template.business_zone("UTC")
    at = datetime(2026, 11, 12, 18, 30, tzinfo=utc)
    assert template.spanish_deadline(at, utc) == "jueves 12 de noviembre, 6:30 p. m."
    assert template.spanish_deadline(at.replace(minute=0), utc) == "jueves 12 de noviembre, 6 p. m."
    assert template.spanish_deadline(at.replace(hour=0, minute=5), utc).endswith("12:05 a. m.")
    assert template.spanish_deadline(at.replace(hour=12, minute=0), utc).endswith("12 p. m.")
    sunday = datetime(2026, 3, 1, 9, 0, tzinfo=utc)
    assert template.spanish_deadline(sunday, utc) == "domingo 1 de marzo, 9 a. m."


def test_the_preview_line_and_the_body_say_what_ux_reviewed() -> None:
    m = Mailing()
    m.fail_and_see()
    m.send()
    (mail,) = m.mailer.sent
    deadline = "domingo 29 de noviembre, 10 a. m."
    preview = mail.html.split('overflow:hidden">', 1)[1].split("</div>", 1)[0]
    assert preview == f"Elige antes del {deadline} o tu video se descarta."
    assert template.WAIT.format(business=BUSINESS, deadline=deadline) in mail.text
    assert template.BUTTON == "Revisar mi video" and "Revisar mi video" in mail.html
    assert template.FOOTER.format(business=BUSINESS) in mail.text


def test_removing_the_avatar_leaves_the_video_to_approve_never_published() -> None:
    """The email promises «armamos tu video sin él y tú lo apruebas antes de publicar»."""
    from qualify_api.creative.fsm import GENERATED

    m = Mailing()
    m.fail_and_see()
    m.world.remove(m.made)
    m.world.run(m.made.clip_id)
    assert m.world.repo.drafts[m.made.clip_id].status == GENERATED  # «Por aprobar»
