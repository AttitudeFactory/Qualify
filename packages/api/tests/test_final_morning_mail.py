from datetime import UTC, date, datetime
from uuid import uuid4

import httpx
import pytest

from qualify_api.mail import OutgoingMail, ResendMailer
from qualify_api.mail.final_summary import batch_cut
from qualify_api.mail.final_template import FinalVideo, build_summary

DAY = date(2026, 10, 26)
NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)


def build(videos, **kwargs):
    return build_summary(
        to="a@example.invalid",
        name="Ana",
        business="Bianki",
        videos=tuple(videos),
        day=DAY,
        timezone="America/Bogota",
        base_url="https://app.example.invalid",
        preference_url="https://app.example.invalid/preferences/capability",
        idempotency_key="test/1",
        **kwargs,
    )


@pytest.mark.parametrize("count", [1, 2, 6])
def test_ready_subject_plural_rows_and_protected_review_links(count):
    videos = [FinalVideo(uuid4(), f"Pieza {n}") for n in range(count)]
    mail = build(videos)
    assert mail.subject == (
        "Bianki: tu video está listo para revisar"
        if count == 1
        else f"Bianki: tus {count} videos están listos para revisar"
    )
    assert mail.sender_name == "Qualify"
    assert mail.headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert "Sin tu confirmación, no se publica" in mail.html
    assert "revisar=videos" in mail.text and "pieza=" in mail.text
    assert "confirm=" not in mail.html
    assert mail.html.count('alt="Video:') == min(count, 4)
    if count > 4:
        assert "y 2 más en Tu semana" in mail.text
    assert "Todavía sin fecha" in mail.text


def test_today_wins_over_ready_and_failures_and_named_input_is_escaped():
    today = FinalVideo(uuid4(), '<script>"x"</script>', scheduled_at=NOW)
    mail = build([FinalVideo(uuid4(), "Falló", failed=True), today])
    assert mail.subject == "Bianki: 1 video sale hoy y espera tu confirmación"
    assert "Sale hoy a las 7:00 a. m. · Instagram, reel" in mail.text
    assert "<script>" not in mail.html and "&lt;script&gt;" in mail.html
    assert "No pudimos preparar el video final. Ábrelo" in mail.text


@pytest.mark.parametrize("count", [1, 2])
def test_only_failures_exact_copy(count):
    mail = build([FinalVideo(uuid4(), "Pieza", failed=True) for _ in range(count)])
    assert (
        mail.subject == f"Bianki: no pudimos preparar {count} {'video' if count == 1 else 'videos'}"
    )
    assert (
        "Ábrelo para intentarlo de nuevo; no usa otro video."
        if count == 1
        else "Ábrelos para intentarlo de nuevo; no usan otro video."
    ) in mail.html
    assert f"Anoche no pudimos preparar el video final de {count}" in mail.text


def test_fixed_clock_seven_in_two_business_zones():
    assert batch_cut(NOW, "America/Bogota")[0] == DAY
    assert batch_cut(NOW, "America/Caracas") is None
    assert batch_cut(datetime(2026, 10, 26, 11, tzinfo=UTC), "America/Caracas")[0] == DAY
    assert batch_cut(datetime(2026, 10, 26, 13, tzinfo=UTC), "America/Bogota") is None


def test_existing_sender_unchanged_and_summary_uses_same_verified_address(monkeypatch):
    captured = []

    def post(url, **kwargs):
        captured.append(kwargs)
        return httpx.Response(200, json={"id": "sent"})

    monkeypatch.setattr("qualify_api.mail.httpx.post", post)
    sender = ResendMailer("not-a-real-key", "Herwin de Qualify <hello@send.example.invalid>")
    sender.send(OutgoingMail("a@example.invalid", "Invitación", "hi", "hi"))
    sender.send(build([FinalVideo(uuid4(), "Pieza")]))
    assert captured[0]["json"]["from"] == "Herwin de Qualify <hello@send.example.invalid>"
    assert "Idempotency-Key" not in captured[0]["headers"]
    assert captured[1]["json"]["from"] == "Qualify <hello@send.example.invalid>"
    assert captured[1]["headers"]["Idempotency-Key"] == "test/1"
    assert captured[1]["json"]["headers"]["List-Unsubscribe"].startswith("<https://")


def test_mail_outage_does_not_stop_worker_recovery(monkeypatch):
    from qualify_api.creative.worker import __main__ as cli

    recovered = []

    def broken_mail():
        raise RuntimeError("mail not configured")

    monkeypatch.setattr(cli, "_load_dotenv", lambda: None)
    monkeypatch.setattr(cli, "production_executors", lambda: {})
    monkeypatch.setattr(
        "qualify_api.creative.composition.production_content_service", lambda: object()
    )
    monkeypatch.setattr(
        "qualify_api.creative.worker.pipeline.PipelinePreparation", lambda *args: lambda: None
    )
    monkeypatch.setattr("qualify_api.mail.final_summary.morning_chore", lambda scope: broken_mail)
    monkeypatch.setattr(
        "qualify_api.creative.worker.operations.production_monitor", lambda ids: None
    )

    def loop(worker, **kwargs):
        kwargs["sidecar"]()
        return 0

    monkeypatch.setattr(cli, "run_loop", loop)
    assert (
        cli.main(
            ["--tenant", str(uuid4()), "--once"],
            recovery=lambda: recovered.append(True),
            install_signals=False,
        )
        == 0
    )
    assert recovered == [True]


def test_nightly_failure_does_not_stop_pipeline_preparation(monkeypatch):
    from qualify_api.creative.worker import __main__ as cli

    prepared = []
    recovered = []

    def broken_night(scope):
        raise RuntimeError("night policy temporarily unavailable")

    monkeypatch.setattr(cli, "_load_dotenv", lambda: None)
    monkeypatch.setattr(cli, "production_executors", lambda: {})
    monkeypatch.setattr(
        "qualify_api.creative.composition.production_content_service", lambda: object()
    )
    monkeypatch.setattr(
        "qualify_api.creative.worker.pipeline.PipelinePreparation",
        lambda *args: lambda: prepared.append(True),
    )
    monkeypatch.setattr("qualify_api.creative.final_review.nightly_maintenance", broken_night)

    def loop(worker, **kwargs):
        kwargs["preparation"]()
        kwargs["sidecar"]()
        return 0

    monkeypatch.setattr(cli, "run_loop", loop)
    assert (
        cli.main(
            ["--tenant", str(uuid4()), "--once"],
            store=object(),
            recovery=lambda: recovered.append(True),
            install_signals=False,
        )
        == 0
    )
    assert prepared == [True] and recovered == [True]


def test_public_load_failure_does_not_silence_queue_monitor(monkeypatch):
    from qualify_api.creative.worker import __main__ as cli
    from qualify_api.creative.worker.operations import Snapshot

    calls = []

    class Monitor:
        clock = staticmethod(lambda: NOW)
        beat = staticmethod(lambda: None)

        def check(self, snapshot):
            calls.append("monitor")

    def failed_load():
        calls.append("load")
        raise RuntimeError("Redis unavailable")

    monkeypatch.setattr(cli, "_load_dotenv", lambda: None)
    monkeypatch.setattr(
        "qualify_api.creative.worker.operations.production_monitor", lambda ids: Monitor()
    )
    monkeypatch.setattr(
        "qualify_api.creative.worker.operations.read_snapshot", lambda **kwargs: Snapshot()
    )
    monkeypatch.setattr(
        "qualify_api.creative.worker.queue_load.production_load_chore", lambda **kwargs: failed_load
    )

    def loop(worker, **kwargs):
        kwargs["sidecar"]()
        return 0

    monkeypatch.setattr(cli, "run_loop", loop)
    assert (
        cli.main(
            ["--all-tenants", "--once"],
            executors={},
            recovery=lambda: calls.append("recover"),
            install_signals=False,
        )
        == 0
    )
    assert calls == ["recover", "load", "monitor"]


def test_only_failures_main_button_opens_the_first_displayed_piece():
    from html import escape

    from qualify_api.mail.final_template import review_url

    failed = FinalVideo(uuid4(), "Falló", failed=True)
    mail = build([failed])
    target = review_url("https://app.example.invalid", failed.piece_id)
    assert target in mail.text
    assert f'class="mail-cta" href="{escape(target, quote=True)}"' in mail.html
