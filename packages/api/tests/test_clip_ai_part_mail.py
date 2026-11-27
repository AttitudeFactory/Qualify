"""m-25142979: the email of a Clip whose «parte con IA» failed — one per Clip and pass,
idempotent, staged in the pass's own fenced write and sent after it, never for a Clip that
failed or ran out of time, nothing with `QUALIFY_CLIP_AI_PARTS` off.

Offline only: the Clip, its parts and the outbox live in memory (the AI parts world of
`test_clip_ai_parts`), the mailer is a double that records (no Resend call), the identity
check is injected and the clock is fixed. Postgres (migration 0193) is in
`test_clip_ai_part_mail_db.py`."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from qualify_api.creative import clip_ai_parts as cap
from qualify_api.creative import clip_avatar as ca
from qualify_api.creative import clip_avatar_mail as cm
from qualify_api.creative.fsm import FAILED
from qualify_api.creative.part_extend import EXTEND_SWITCH
from qualify_api.creative.video_pipeline.ai_parts import CLIP_AI_PARTS_SWITCH
from qualify_api.mail import OutgoingMail
from qualify_api.mail import clip_ai_part as template

from .test_clip_ai_part_actions import (
    _actions,
    _edit_analysis,
    _edit_clip,
    _fail,
    _made_clip,
    _split_clip,
    _split_cuts_checked,
)
from .test_clip_ai_parts import (
    World,
    _block,
    _brief_of,
    _clip,
    _create,
    _entry,
    _made,
    _switches,
    _world,
    assemble_at_the_sources_size,
    assembly_files,
    no_normalize_jobs,
    queue_on,
)
from .test_content_service import TENANT_ID, USER_ID

__all__ = [  # fixtures used by name, or autouse
    "_switches",
    "assemble_at_the_sources_size",
    "assembly_files",
    "no_normalize_jobs",
    "queue_on",
]

BASE = "https://app.qualify.test"
BUSINESS = "Arepas Doña Clotilde"
EMAIL = "clotilde.owner@example.org"
AUTH_USER = uuid4()
CHANGE = f"«Cambiar» {template.CHANGE_HINT}"


class RecordingMailer:
    """The Resend double: records each mail and answers like Resend (an id)."""

    def __init__(self) -> None:
        self.sent: list[OutgoingMail] = []

    def send(self, mail: OutgoingMail) -> str | None:
        self.sent.append(mail)
        return f"resend-{len(self.sent)}"


class WorldOutbox(cm.MemoryAvatarFailureOutbox):
    """The in-memory outbox reading the Clip and its parts live from the test's world."""

    world: World

    def clip_view(self, tenant_id: UUID, clip_id: UUID) -> cm.ClipView | None:
        draft = self.world.repo.drafts.get(clip_id)
        if draft is None:
            return None
        return cm.ClipView(
            status=draft.status,
            business=BUSINESS,
            timezone="America/Bogota",
            plan=(),
            blocks=(),
            ai_parts=self.world.store.parts_of(tenant_id=tenant_id, clip_id=clip_id),
            brief=_brief_of(self.world, clip_id),
        )


class Mailing:
    """An AI parts world whose Clip stages its failure emails, and the sender's pass."""

    def __init__(self, brief: Any = None, *, create: bool = True) -> None:
        self.world = _world()
        self.outbox = WorldOutbox()
        self.outbox.world = self.world
        self.outbox.recipients[(TENANT_ID, UUID(int=0))] = cm.Recipient(EMAIL, AUTH_USER)
        self.world.content._clip_failure_outbox = self.outbox  # noqa: SLF001
        self.mailer = RecordingMailer()
        if create:
            self.made = _create(self.world, brief)

    def verify(self, auth_user_id: UUID, email: str) -> str | None:
        return email if auth_user_id == AUTH_USER else None

    def run(self) -> None:
        """One pass of the Clip's run while it waits for its parts."""
        with pytest.raises(ca.ClipBlocksWait):
            self.world.content.run_generation(tenant_id=TENANT_ID, draft_id=self.made.clip_id)

    def fail(self, index: int = 0, reason: str = "provider_error") -> None:
        _fail(self.world, self.made.part_ids[index], reason)

    def send(self) -> int:
        return cm.send_pending(
            self.outbox,
            TENANT_ID,
            now=self.world.clock[0],
            mailer=self.mailer,
            base_url=BASE,
            verify=self.verify,
        )

    def reasons(self) -> list[str | None]:
        return [r.closed_reason for r in self.outbox.rows]


# ---------------------------------------------------------------------------
# one email per Clip and pass


def test_a_failed_part_stages_one_email_and_sends_it() -> None:
    m = Mailing()
    m.fail(0)
    _made(m.world, m.made.part_ids[1])
    m.run()
    (row,) = m.outbox.rows
    part = m.made.part_ids[0]
    assert (row.kind, row.slots, row.block_ids, row.revisions) == (
        template.AI_PART_FAILED,
        (1,),
        (part,),
        (m.world.repo.drafts[part].revision,),
    )
    assert row.codes == ("provider_error",) and row.failed_at == m.world.clock[0]
    assert row.source_version == template.AI_PART_TEMPLATE_VERSION
    assert row.sent_at is None  # staged with the pass; the sender sends it afterwards
    assert m.send() == 1
    (mail,) = m.mailer.sent
    assert mail.to == EMAIL
    assert mail.subject == f"{BUSINESS}: una parte con IA de tu video no salió"
    assert "La parte con IA 1 de tu video no salió" in mail.text
    assert "La Parte con IA 1 no se pudo crear y no se descontó su vista previa." in mail.text
    assert f"Elige «Intentar de nuevo», {CHANGE} o «Quitar»." in mail.text
    assert template.COST in mail.text and template.FOOTER.format(business=BUSINESS) in mail.text
    url = f"{BASE}/drafts/{m.made.clip_id}"
    assert url in mail.text and f'href="{url}"' in mail.html
    # the owner's 72 h from the failure (12:00 UTC) in Bogotá: 7 a. m. three days on
    assert "lunes 30 de noviembre, 7 a. m." in mail.text
    assert mail.idempotency_key == cm.failure_key(
        TENANT_ID, m.made.clip_id, template.AI_PART_FAILED, row.failed_at
    )


def test_every_later_pass_or_a_restarted_worker_never_sends_a_second_email() -> None:
    m = Mailing()
    m.fail(0)
    m.run()
    for _ in range(3):  # the Clip waits: every pass reads the same failed part again
        m.world.clock[0] += timedelta(minutes=5)
        m.run()
    assert len(m.outbox.rows) == 1
    assert m.send() == 1 and m.send() == 0
    restarted = cm.failure_mail_chore(
        [TENANT_ID],
        outbox=m.outbox,
        mailer=lambda: m.mailer,
        verify=m.verify,
        clock=lambda: m.world.clock[0] + timedelta(hours=1),
    )
    assert restarted() == 0
    assert len(m.mailer.sent) == 1


def test_two_parts_failed_in_one_pass_are_one_email() -> None:
    m = Mailing()
    m.fail(0)
    m.fail(1)
    m.run()
    (row,) = m.outbox.rows
    assert row.slots == (1, 2)
    assert m.send() == 1
    (mail,) = m.mailer.sent
    assert mail.subject == f"{BUSINESS}: algunas partes con IA de tu video no salieron"
    assert "Las Partes con IA 1 y 2 no se pudieron crear" in mail.text
    assert f"cada una: «Intentar de nuevo», {CHANGE} o «Quitar»." in mail.text
    assert "no se descontaron sus vistas previas" in mail.text
    assert template.COST_MANY in mail.text


def test_a_part_failing_on_a_later_pass_is_its_own_email_once() -> None:
    m = Mailing()
    m.fail(0)
    m.run()
    assert m.send() == 1
    m.world.clock[0] += timedelta(minutes=10)
    m.fail(1)
    m.run()
    m.run()
    assert [r.slots for r in m.outbox.rows] == [(1,), (2,)]
    assert m.send() == 1 and m.send() == 0
    assert "La parte con IA 2 de tu video no salió" in m.mailer.sent[1].text


def test_a_part_made_again_that_fails_again_is_one_more_email() -> None:
    m = Mailing()
    part = m.made.part_ids[0]
    m.fail(0)
    m.run()
    assert m.send() == 1
    m.world.clock[0] += timedelta(hours=5)
    _actions(m.world).retry_part(
        tenant_id=TENANT_ID, user_id=USER_ID, clip_id=m.made.clip_id, part_id=part
    )
    m.run()  # being made again: nothing to say
    assert len(m.outbox.rows) == 1
    m.fail(0)
    m.run()
    first, second = m.outbox.rows
    assert second.revisions is not None and first.revisions is not None
    assert second.revisions[0] == first.revisions[0] + 1
    assert m.send() == 1
    a, b = m.mailer.sent
    assert a.idempotency_key != b.idempotency_key
    # its own 72 h, from the new failure (17:00 UTC)
    assert "lunes 30 de noviembre, 12 p. m." in b.text


def test_a_retry_or_a_removal_before_the_email_left_closes_it_unsent() -> None:
    m = Mailing()
    m.fail(0)
    m.run()
    _actions(m.world).retry_part(
        tenant_id=TENANT_ID, user_id=USER_ID, clip_id=m.made.clip_id, part_id=m.made.part_ids[0]
    )
    assert m.send() == 0 and m.mailer.sent == [] and m.reasons() == ["resolved"]
    other = Mailing()
    other.fail(0)
    other.run()
    assert _actions(other.world).remove_part(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        clip_id=other.made.clip_id,
        part_id=other.made.part_ids[0],
    )
    assert other.send() == 0 and other.reasons() == ["resolved"]


def test_a_clip_that_ran_out_of_time_is_never_mailed() -> None:
    """`ai_part_expired`: the Clip is no longer waiting — a row staged before it is closed
    unsent, and the expired pass stages nothing."""
    m = Mailing()
    m.fail(0)
    m.run()
    m.world.clock[0] += cap.CLIP_AI_PART_OWNER_WAIT
    m.world.content.run_generation(tenant_id=TENANT_ID, draft_id=m.made.clip_id)
    assert m.world.repo.drafts[m.made.clip_id].failure_reason == cap.AI_PART_EXPIRED
    assert len(m.outbox.rows) == 1
    assert m.send() == 0 and m.reasons() == ["resolved"]


def test_a_clip_that_failed_at_once_stages_nothing() -> None:
    """`ai_part_failed` (a part never created): no choice to offer, no email."""
    m = Mailing()
    del m.world.repo.parents[m.made.part_ids[1]]  # the part's row is gone: a broken Clip
    m.world.content.run_generation(tenant_id=TENANT_ID, draft_id=m.made.clip_id)
    clip = m.world.repo.drafts[m.made.clip_id]
    assert clip.status == FAILED and clip.failure_reason == cap.AI_PART_FAILED
    assert m.outbox.rows == []


def test_due_closes_a_row_of_a_clip_that_is_not_waiting() -> None:
    m = Mailing()
    m.fail(0)
    m.run()
    mail = m.outbox.claim(TENANT_ID, now=m.world.clock[0], include_new=True)
    assert mail is not None
    view = m.outbox.clip_view(TENANT_ID, m.made.clip_id)
    assert view is not None
    env = {CLIP_AI_PARTS_SWITCH: "on"}
    for status in ("failed", "generated"):
        reason, due = cm._ai_part_due(mail, replace(view, status=status), env)  # noqa: SLF001
        assert (reason, due) == ("resolved", None)
    reason, due = cm._ai_part_due(mail, view, env)  # noqa: SLF001
    assert reason is None and due is not None and due.slots == (1,)


# ---------------------------------------------------------------------------
# the switch


def test_with_the_switch_off_nothing_is_staged_nor_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    m = Mailing()
    m.fail(0)
    monkeypatch.setenv(CLIP_AI_PARTS_SWITCH, "off")
    m.world.content._stage_ai_part_mail(  # noqa: SLF001
        TENANT_ID,
        m.world.repo.drafts[m.made.clip_id],
        m.world.store.parts_of(tenant_id=TENANT_ID, clip_id=m.made.clip_id),
    )
    assert m.outbox.rows == []
    rows = m.world.store.parts_of(tenant_id=TENANT_ID, clip_id=m.made.clip_id)
    assert cm.mailable_ai_part_failures(rows, frozenset(), m.world.clock[0]) == ()
    # a row staged while it was on is closed, never sent, once it is off
    monkeypatch.setenv(CLIP_AI_PARTS_SWITCH, "on")
    m.run()
    assert len(m.outbox.rows) == 1
    monkeypatch.setenv(CLIP_AI_PARTS_SWITCH, "off")
    assert m.send() == 0 and m.reasons() == ["switched_off"]
    chore = cm.failure_mail_chore(
        [TENANT_ID], outbox=m.outbox, mailer=lambda: m.mailer, verify=m.verify
    )
    monkeypatch.delenv("QUALIFY_CLIP_AVATAR_PRESENTER", raising=False)
    monkeypatch.delenv("QUALIFY_CLIP_AVATAR_ANIMATED", raising=False)
    monkeypatch.delenv("QUALIFY_CLIP_CHARACTER_SCENE", raising=False)
    assert chore() == 0 and m.mailer.sent == []


# ---------------------------------------------------------------------------
# what the owner can do, in the screen's words


def test_an_igual_al_original_part_refused_offers_hacerla_nueva() -> None:
    m = Mailing(_edit_clip(_edit_analysis()))
    m.fail(0, reason="refused_face")
    m.run()
    assert m.send() == 1
    (mail,) = m.mailer.sent
    assert "Elige «Hacerla nueva» o «Quitar»." in mail.text


def test_the_only_block_left_offers_no_quitar() -> None:
    m = Mailing(_clip((_block(0),), (_entry(5),)))
    m.fail(0)
    m.run()
    assert m.send() == 1
    (mail,) = m.mailer.sent
    assert "Elige «Intentar de nuevo» o «Cambiar» (su descripción o sus fotos)." in mail.text
    assert "Quitar" not in mail.text and template.COST_NO_REMOVE in mail.text


def test_no_quitar_while_the_sigue_a_la_anterior_after_it_is_being_made(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """As the screen (`parts_view`): «Quitar» is refused while the «Sigue a la anterior»
    right after the failed part is still being made."""
    monkeypatch.setenv(EXTEND_SWITCH, "draft")
    _split_cuts_checked(monkeypatch)
    m = Mailing(_split_clip())
    m.fail(0)
    m.run()
    assert m.send() == 1
    (mail,) = m.mailer.sent
    assert "«Quitar»" not in mail.text


def test_a_failed_part_added_to_a_made_clip_says_the_video_stays_as_it_was() -> None:
    """m-25142982: a part added to a made Clip waits 72 h too, but the Clip never fails for
    it — the email says the video stays as it was, and names it as the part added."""
    m = Mailing(create=False)
    m.made, _ = _made_clip(m.world)
    new = _actions(m.world).add_part(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        clip_id=m.made.clip_id,
        entry=_entry(5, description="La arepa servida en la mesa"),
        position=len(_brief_of(m.world, m.made.clip_id).media.segments),
    )
    _fail(m.world, new)
    m.run()
    m.run()
    (row,) = m.outbox.rows
    assert row.block_ids == (new,) and row.slots == (3,)
    assert m.send() == 1
    (mail,) = m.mailer.sent
    assert mail.subject == f"{BUSINESS}: la parte con IA que agregaste a tu video no salió"
    assert template.HEADING_ADDED in mail.text
    assert f"Elige «Intentar de nuevo», {CHANGE}" in mail.text
    assert template.COST_ADDED in mail.text
    assert "tu video queda como estaba, sin esa parte" in mail.text
    assert "se descarta" not in mail.text and "se descarta" not in mail.html
    # once the owner's time ran out the Clip keeps its video: a later row is never sent
    other = Mailing(create=False)
    other.made, _ = _made_clip(other.world)
    late = _actions(other.world).add_part(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        clip_id=other.made.clip_id,
        entry=_entry(5, description="La arepa servida en la mesa"),
        position=1,
    )
    _fail(other.world, late)
    other.run()
    other.world.clock[0] += cap.CLIP_AI_PART_OWNER_WAIT + timedelta(minutes=1)
    other.world.content.run_generation(tenant_id=TENANT_ID, draft_id=other.made.clip_id)
    assert other.send() == 0 and other.reasons() == ["resolved"]


def test_a_row_closed_while_the_switch_was_off_is_mailed_again_once_it_is_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m = Mailing()
    m.fail(0)
    m.run()
    monkeypatch.setenv(CLIP_AI_PARTS_SWITCH, "off")
    assert m.send() == 0 and m.reasons() == ["switched_off"]
    monkeypatch.setenv(CLIP_AI_PARTS_SWITCH, "on")
    m.world.clock[0] += timedelta(minutes=5)
    m.run()
    m.run()
    assert m.reasons() == ["switched_off", None]
    assert m.send() == 1


def test_the_template_words() -> None:
    assert template.spanish_list(["1"]) == "1"
    assert template.spanish_list(["1", "2", "4"]) == "1, 2 y 4"
    assert template.spanish_choice(["«a»", "«b»"]) == "«a» o «b»"
    assert template.action_words(["remove", "retry", "change_mode"]) == [
        "«Intentar de nuevo»",
        "«Quitar»",
    ]
    assert template.action_words(["change"]) == ["«Cambiar» (su descripción o sus fotos)"]
    with pytest.raises(ValueError):
        template.ai_part_failure_mail(
            to=EMAIL,
            business=BUSINESS,
            clip_id=uuid4(),
            wait_until=cap.datetime.now(cap.UTC),
            timezone="America/Bogota",
            base_url=BASE,
            idempotency_key="k",
            slots=(1,),
            actions=(),
        )
    for words in template.TEXTS:
        for english in ("post", "inbox", "clip", "draft", "retry", "email"):
            assert english not in words.casefold(), words


# ---------------------------------------------------------------------------
# privacy


def test_logs_carry_ids_only(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    m = Mailing()
    m.fail(0)
    m.run()
    m.send()

    class Broken(WorldOutbox):
        def mailed_ai_parts(self, session: Any, **_: Any) -> frozenset[tuple[UUID, int]]:
            raise RuntimeError(f"boom {EMAIL} {BUSINESS}")

    broken = Mailing()
    box = Broken()
    box.world = broken.world
    broken.world.content._clip_failure_outbox = box  # noqa: SLF001
    broken.fail(0)
    broken.run()  # the wait goes on: the email is tried again on the next pass
    assert box.rows == []
    assert any("error_type=RuntimeError" in r.getMessage() for r in caplog.records)
    for record in caplog.records:
        text = record.getMessage() + " " + repr(record.args)
        for secret in (EMAIL, BUSINESS, "clotilde"):
            assert secret.casefold() not in text.casefold(), record.getMessage()
