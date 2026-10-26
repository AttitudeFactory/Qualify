"""Offline warning email and daily chore regressions (m-24842840)."""

import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from qualify_api.auth.config import SupabaseSettings
from qualify_api.auth.confirmed_email import confirmed_email
from qualify_api.creative import retention_job, retention_mail
from qualify_api.creative.retention import RetentionFacts, evaluate
from qualify_api.mail import MailNotConfigured, ResendMailer
from qualify_api.mail.config import public_app_url
from qualify_api.mail.retention import ExpiringPiece, WarningStage, warning_mail

NOW = datetime(2027, 1, 10, 2, tzinfo=UTC)


def test_mail_lists_deadlines_in_tenant_timezone_and_escapes_titles() -> None:
    piece = ExpiringPiece(uuid4(), "<Oferta & regalo>", NOW, "https://example.test/a.jpg")
    mail = warning_mail(
        "client@example.test",
        uuid4(),
        "Mi marca",
        [piece],
        pieces_url="https://example.test/drafts",
        timezone="America/Caracas",
    )
    assert "09/01/2027" in mail.text
    assert "Los archivos de esta pieza se borrar\u00e1n pronto:" in mail.text
    assert "https://example.test/drafts" in mail.text
    assert "Abre cada pieza y descarga los archivos que quieras conservar." in mail.text
    assert "Si te pedimos iniciar sesi\u00f3n, entra con tu cuenta de Qualify." in mail.text
    assert "&lt;Oferta &amp; regalo&gt;" in mail.html
    assert "<img" in mail.html
    assert "<Oferta" not in mail.html


def test_provider_retries_use_same_key_but_a_renewed_deadline_gets_a_new_key(monkeypatch) -> None:
    brand, draft = uuid4(), uuid4()

    def build(deadline):
        return warning_mail(
            "client@example.test",
            brand,
            "Marca",
            [ExpiringPiece(draft, "Pieza", deadline)],
            pieces_url="https://example.test/drafts",
            timezone="UTC",
        )

    original = build(NOW)
    assert original.idempotency_key == build(NOW).idempotency_key
    assert original.idempotency_key != build(NOW + timedelta(days=1)).idempotency_key
    requests = []

    def post(*args, **kwargs):
        requests.append(kwargs)
        return httpx.Response(200, json={"id": "email-1"})

    monkeypatch.setattr("qualify_api.mail.httpx.post", post)
    assert ResendMailer("secret", "sender@example.test").send(original) == "email-1"
    assert requests[0]["headers"]["Idempotency-Key"] == original.idempotency_key


def test_daily_warning_failure_cannot_stop_purge_and_switch_is_independent(monkeypatch) -> None:
    calls = []

    def warn(*args):
        calls.append("warning")
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(retention_mail, "run_piece_warnings", warn)
    monkeypatch.setattr(retention_job, "run_piece_purge", lambda *a, **kw: calls.append("purge"))
    monkeypatch.setenv(retention_job.WARNING_ENV, "1")
    retention_job.daily_chore([uuid4()])()
    assert calls == ["warning", "purge"]
    calls.clear()
    monkeypatch.setenv(retention_job.WARNING_ENV, "off")
    retention_job.daily_chore([uuid4()])()
    assert calls == ["purge"]


def test_unconfirmed_or_changed_email_is_excluded(monkeypatch) -> None:
    uid = uuid4()
    monkeypatch.setattr(
        SupabaseSettings,
        "from_env",
        lambda: SupabaseSettings("https://auth.example.test", "public", "secret"),
    )
    body = {"id": str(uid), "email": "member@example.test"}

    def get(*args, **kwargs):
        return httpx.Response(200, json=body, request=httpx.Request("GET", args[0]))

    monkeypatch.setattr("qualify_api.auth.confirmed_email.httpx.get", get)
    assert confirmed_email(uid, "member@example.test") is None
    body["email_confirmed_at"] = NOW.isoformat()
    assert confirmed_email(uid, "other@example.test") is None
    assert confirmed_email(uid, "member@example.test") == "member@example.test"


def test_recorded_deadline_is_not_repeated_next_day_but_renewal_is_pending() -> None:
    from qualify_api.creative.retention_mail import pending_pieces

    draft = uuid4()
    original = ExpiringPiece(draft, "Pieza", NOW + timedelta(days=10))
    recorded = {(draft, original.deadline, WarningStage.WINDOW_15D.value)}
    assert pending_pieces([original], recorded) == []
    renewed = ExpiringPiece(draft, "Pieza", NOW + timedelta(days=90))
    assert pending_pieces([renewed], recorded) == [renewed]


@pytest.mark.parametrize(
    ("hours_left", "held", "expected"),
    [
        (15 * 24 + 1, False, None),
        (15 * 24, False, WarningStage.WINDOW_15D),
        (24.01, False, WarningStage.WINDOW_15D),
        (24, False, WarningStage.LAST_DAY),
        (23.99, False, WarningStage.LAST_DAY),
        (0.01, False, WarningStage.LAST_DAY),
        (0, False, None),
        (-1, False, None),
        (12, True, None),
    ],
)
def test_selection_excludes_expired_and_protected_and_uses_stage_boundaries(
    hours_left: float,
    held: bool,
    expected: WarningStage | None,
) -> None:
    facts = RetentionFacts(NOW - timedelta(days=90) + timedelta(hours=hours_left), held=held)
    assert retention_mail.warning_stage(evaluate(facts, NOW), NOW) == expected


def test_last_day_copy_and_stage_have_separate_provider_and_ledger_identity() -> None:
    draft, brand = uuid4(), uuid4()
    piece = ExpiringPiece(draft, "Pieza", NOW + timedelta(hours=12))
    kwargs = dict(pieces_url="https://example.test/drafts", timezone="America/Caracas")
    early = warning_mail("client@example.test", brand, "Marca", [piece], **kwargs)
    last = warning_mail(
        "client@example.test", brand, "Marca", [piece], stage=WarningStage.LAST_DAY, **kwargs
    )
    assert "\u00daltimo d\u00eda" in last.subject
    assert "en las pr\u00f3ximas 24 horas" in last.text
    assert "a las 10:00 (hora de tu negocio)" in last.text
    assert early.idempotency_key != last.idempotency_key
    recorded = {(draft, piece.deadline, WarningStage.WINDOW_15D.value)}
    assert retention_mail.pending_pieces([piece], recorded, WarningStage.WINDOW_15D) == []
    assert retention_mail.pending_pieces([piece], recorded, WarningStage.LAST_DAY) == [piece]


@pytest.mark.parametrize("stage", list(WarningStage))
@pytest.mark.parametrize(
    "base_url", ["https://example.test/drafts", "https://example.test/drafts/"]
)
def test_each_piece_has_its_own_authenticated_detail_link_in_both_formats(
    stage: WarningStage,
    base_url: str,
) -> None:
    pieces = [
        ExpiringPiece(uuid4(), "Primera pieza", NOW + timedelta(hours=12)),
        ExpiringPiece(uuid4(), "Segunda pieza", NOW + timedelta(hours=18)),
    ]
    mail = warning_mail(
        "client@example.test",
        uuid4(),
        "Marca",
        pieces,
        pieces_url=base_url,
        timezone="UTC",
        stage=stage,
    )
    links = re.findall(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', mail.html, re.S)
    for piece in pieces:
        url = f"https://example.test/drafts/{piece.draft_id}"
        assert (url, piece.title) in links
        assert (url, "Ver pieza y descargar") in links
        assert f"Ver pieza y descargar: {url}" in mail.text
    assert "/drafts//" not in mail.html
    assert "/drafts//" not in mail.text


def test_mail_public_url_uses_deployment_configuration_and_local_dev_port() -> None:
    production = "https://qualify.attitudefactory.co"
    assert public_app_url({}) == "http://localhost:3000"
    assert public_app_url({"REFLEX_DEPLOY_URL": production + "/"}) == production
    assert (
        public_app_url(
            {
                "QUALIFY_DEPLOY_ENV": "production",
                "QUALIFY_PUBLIC_URL": production,
                "REFLEX_DEPLOY_URL": "http://localhost:3100",
            }
        )
        == production
    )
    with pytest.raises(MailNotConfigured):
        public_app_url({"QUALIFY_DEPLOY_ENV": "production"})


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:3000",
        "https://localhost",
        "https://127.0.0.1",
        "https://[::1]",
        "http://qualify.attitudefactory.co",
    ],
)
def test_production_never_sends_local_or_insecure_email_links(url: str) -> None:
    with pytest.raises(MailNotConfigured):
        public_app_url({"QUALIFY_DEPLOY_ENV": "production", "QUALIFY_PUBLIC_URL": url})


@pytest.mark.parametrize("stage", list(WarningStage))
def test_production_template_has_direct_links_and_existing_mail_visual_style(
    stage: WarningStage,
) -> None:
    origin = public_app_url(
        {
            "QUALIFY_DEPLOY_ENV": "production",
            "QUALIFY_PUBLIC_URL": "https://qualify.attitudefactory.co/",
        }
    )
    piece = ExpiringPiece(uuid4(), "Pieza de prueba de plantilla", NOW + timedelta(hours=12))
    mail = warning_mail(
        "client@example.test",
        uuid4(),
        "Marca",
        [piece],
        pieces_url=origin + "/drafts",
        timezone="UTC",
        stage=stage,
    )
    assert origin + "/drafts/" + str(piece.draft_id) in mail.html
    assert origin + "/drafts/" + str(piece.draft_id) in mail.text
    assert "localhost" not in mail.html + mail.text
    assert "<!doctype html>" in mail.html
    assert 'role="presentation"' in mail.html
    assert "prefers-color-scheme:dark" in mail.html
    assert "qualify-icon-email.png" in mail.html
    assert mail.subject.startswith("\u00daltimo d\u00eda") == (stage is WarningStage.LAST_DAY)


def test_daily_ticks_include_the_final_warning_at_exactly_24_hours_before_expiry(
    monkeypatch,
) -> None:
    due = NOW + timedelta(days=1)
    facts = RetentionFacts(due - timedelta(days=90))
    stages = []
    ticks = []

    class Clock(datetime):
        moment = NOW

        @classmethod
        def now(cls, tz=None):
            return cls.moment

    def warn(scope, moment):
        ticks.append(moment)
        stage = retention_mail.warning_stage(evaluate(facts, moment), moment)
        if stage is not None:
            stages.append(stage)

    monkeypatch.setattr(retention_job, "datetime", Clock)
    monkeypatch.setattr(retention_mail, "run_piece_warnings", warn)
    monkeypatch.setattr(retention_job, "run_piece_purge", lambda *args, **kwargs: [])
    monkeypatch.setenv(retention_job.WARNING_ENV, "1")
    chore = retention_job.daily_chore([uuid4()])
    chore()
    Clock.moment = due
    chore()
    assert ticks == [due - timedelta(days=1), due]
    assert stages == [WarningStage.LAST_DAY]


@pytest.mark.parametrize(
    ("status", "definitive"), [(400, True), (429, True), (408, False), (500, False)]
)
def test_provider_distinguishes_rejected_from_unknown_acceptance(
    monkeypatch, status, definitive
) -> None:
    from qualify_api.mail import MailError, MailRejected, OutgoingMail

    monkeypatch.setattr(
        "qualify_api.mail.httpx.post", lambda *a, **kw: httpx.Response(status, json={})
    )
    with pytest.raises(MailError) as caught:
        ResendMailer("fake", "from@example.test").send(
            OutgoingMail("to@example.test", "Subject", "HTML", "Text")
        )
    assert isinstance(caught.value, MailRejected) is definitive


def test_warning_retry_chore_preserves_scope_and_respects_email_kill_switch(monkeypatch) -> None:
    tenant = uuid4()
    calls = []
    monkeypatch.setattr(
        retention_mail, "run_warning_retries", lambda scope, now: calls.append(scope)
    )
    monkeypatch.setattr(
        retention_mail,
        "send_tenant_warnings",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not stage new pieces")),
    )
    monkeypatch.setenv(retention_job.WARNING_ENV, "1")
    monkeypatch.setenv(retention_job.EXECUTE_ENV, "off")
    chore = retention_job.warning_retry_chore([tenant])
    chore()
    assert calls == [[tenant]]
    monkeypatch.setenv(retention_job.WARNING_ENV, "off")
    chore()
    assert calls == [[tenant]]
