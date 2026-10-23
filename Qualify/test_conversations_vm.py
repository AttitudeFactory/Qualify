"""Pure tests for the `/conversations` view-models (QUA-226, E2): accounts, the access
banner, the thread rows, the bubbles (receipts, media, day chips, the «Visto» footer),
the filters, the fresh-row detection and the composer validation.

No Reflex, no Postgres: the backend shapes come from `qualify_api.conversations` (plain
dataclasses) and every instant is a fixed value.
"""

from __future__ import annotations

import dataclasses
import typing
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from qualify_api.conversations.repository import MessageRecord, SyncStateRecord, ThreadRecord
from qualify_api.conversations.service import ThreadView, attention_state
from qualify_api.conversations.window import window_state

from .connections_vm import CapabilityVM, ConnectionVM
from .conversations_vm import (
    ACCESS_AUTH_EXPIRED,
    ACCESS_DISABLED,
    ACCESS_ERROR,
    ACCESS_NEVER_SYNCED,
    ACCESS_OK,
    ACCESS_PERMISSION_MISSING,
    ACCESS_SYNC_FAILED,
    ACCESS_UNKNOWN,
    FILTER_ALL,
    FILTER_ANSWERED,
    FILTER_PENDING,
    FILTER_READ,
    MAX_AUDIO_BYTES,
    MAX_DOCUMENT_BYTES,
    MAX_IMAGE_BYTES,
    MAX_REPLY_CHARS,
    MAX_VIDEO_BYTES,
    MEDIA_AUDIO,
    MEDIA_IMAGE,
    MEDIA_STICKER,
    MEDIA_VIDEO,
    NO_MESSAGES_YET,
    OUTBOUND_PREFIX,
    QUIET_ACCESS_KINDS,
    TAP_ICON,
    WINDOW_CLOSED_NOTICE,
    WINDOW_CLOSED_SHORT,
    AccessVM,
    AccountVM,
    AttachmentVM,
    DraftVM,
    MessageVM,
    ThreadExtra,
    ThreadRowVM,
    UnsentItem,
    avatar_hue,
    build_access_vm,
    build_account_vm,
    build_conversation,
    build_draft_vm,
    build_message_vm,
    build_thread_row,
    build_unsent_vm,
    classify_attachment,
    composer_enabled,
    counterpart_title,
    failure_label,
    filter_counts,
    filter_label,
    filter_threads,
    inbox_accounts,
    initials_of,
    media_label,
    newly_pending,
    outbox_text,
    reply_as_label,
    reply_parts_hint,
    suggestion_refusal_label,
    validate_reply,
    voice_note_name,
    window_words,
)

NOW = datetime(2026, 10, 16, 17, 0, tzinfo=UTC)
ZONE = ZoneInfo("America/Bogota")
TENANT = uuid4()
CONNECTION = uuid4()


def _thread(
    *,
    inbound: datetime | None = NOW - timedelta(hours=2),
    outbound: datetime | None = None,
    read: datetime | None = None,
    status: str = "open",
    channel: str = "dm",
    counterpart: str = "igsid-123456",
) -> ThreadRecord:
    instants = [t for t in (inbound, outbound) if t is not None]
    return ThreadRecord(
        id=uuid4(),
        tenant_id=TENANT,
        connection_id=CONNECTION,
        channel=channel,
        counterpart_external_id=counterpart,
        external_conversation_id="t_1",
        status=status,
        assigned_agent_id=None,
        last_message_at=max(instants) if instants else None,
        last_inbound_at=inbound,
        last_outbound_at=outbound,
        last_read_at=read,
        created_at=NOW - timedelta(days=1),
    )


def _view(thread: ThreadRecord) -> ThreadView:
    return ThreadView(
        thread=thread,
        attention=attention_state(thread),
        window=window_state(thread.last_inbound_at, NOW),
    )


def _message(
    *,
    direction: str = "inbound",
    text: str | None = "hola",
    at: datetime = NOW - timedelta(minutes=10),
    delivery: str | None = None,
    media: str | None = None,
    media_url: str | None = None,
    media_object_key: str | None = None,
) -> MessageRecord:
    return MessageRecord(
        id=uuid4(),
        thread_id=uuid4(),
        connection_id=CONNECTION,
        external_message_id=f"mid.{uuid4().hex[:6]}",
        direction=direction,
        author_external_id="igsid-123456" if direction == "inbound" else "ig-1",
        author_username="alice" if direction == "inbound" else None,
        text=text,
        posted_at=at,
        ingested_at=at,
        delivery_status=delivery,
        media_type=media,
        media_url=media_url,
        media_object_key=media_object_key,
    )


def _connection(
    *,
    platform: str = "instagram",
    status: str = "active",
    dms: bool = True,
    username: str = "qualifymkt.co",
) -> ConnectionVM:
    capability = CapabilityVM(
        key="manage_dms",
        label="Bandeja de mensajes directos",
        enabled=dms,
        reason="" if dms else "No concediste el permiso de mensajes directos.",
        provisional=False,
    )
    return ConnectionVM(
        id=str(uuid4()),
        platform=platform,
        brand="Bianki",
        external_username=username,
        status=status,
        last_verified_at="hoy",
        granted_scopes=[],
        enabled_capabilities=[capability] if dms else [],
        disabled_capabilities=[] if dms else [capability],
    )


def _sync(
    *,
    access: str = "ok",
    detail: str | None = None,
    sync_status: str | None = "ok",
    sync_error: str | None = None,
    finished: datetime | None = NOW - timedelta(minutes=3),
) -> SyncStateRecord:
    return SyncStateRecord(
        connection_id=CONNECTION,
        channel="dm",
        access_status=access,
        access_detail=detail,
        access_checked_at=finished,
        sync_cursor=None,
        last_sync_started_at=finished,
        last_sync_finished_at=finished,
        last_sync_status=sync_status,
        last_sync_error=sync_error,
    )


# --- accounts -----------------------------------------------------------------------------


def test_accounts_keep_instagram_only_and_drop_revoked_ones() -> None:
    accounts = inbox_accounts(
        [
            _connection(),
            _connection(platform="whatsapp"),
            _connection(status="revoked"),
            _connection(status="degraded", dms=False),
        ]
    )
    assert [a.status for a in accounts] == ["active", "degraded"]
    assert accounts[0].label == "@qualifymkt.co" and accounts[0].can_manage_dms
    assert accounts[1].is_degraded and not accounts[1].can_manage_dms
    assert "mensajes directos" in accounts[1].dm_reason


def test_account_label_never_doubles_the_at_and_names_the_channel() -> None:
    account = build_account_vm(_connection(username="@ya.con.arroba"))
    assert account.label == "@ya.con.arroba"
    assert account.channel_label == "Instagram Direct"
    assert reply_as_label(account) == "Respondes como @ya.con.arroba · Instagram Direct"
    assert reply_as_label(dataclasses.replace(account, connection_id="")) == ""


# --- identity -----------------------------------------------------------------------------


def test_initials_and_hue_are_stable_data() -> None:
    assert initials_of("@alice.compras") == "AC"
    assert initials_of("@yesii_roa") == "YR"
    assert initials_of("@maria") == "M"
    assert initials_of("", "igsid-98765") == "5"
    assert initials_of("", "") == "?"
    assert 0 <= avatar_hue("igsid-123456") < 360
    assert avatar_hue("igsid-123456") == avatar_hue("igsid-123456")
    assert avatar_hue("a") != avatar_hue("b")


# --- access banner ------------------------------------------------------------------------


def _account(**overrides) -> AccountVM:
    return dataclasses.replace(build_account_vm(_connection()), **overrides)


def test_the_matrix_verdict_comes_before_anything_the_sync_recorded() -> None:
    vm = build_access_vm(
        _sync(access="ok"),
        account=_account(can_manage_dms=False, dm_reason="Falta."),
        now=NOW,
        zone=ZONE,
    )
    assert vm.kind == ACCESS_PERMISSION_MISSING
    assert vm.show_reconnect and vm.provisional and vm.tone == "warn"
    assert vm.message.startswith("Falta.")


def test_a_degraded_connection_asks_to_reconnect() -> None:
    vm = build_access_vm(_sync(), account=_account(status="degraded"), now=NOW, zone=ZONE)
    assert vm.kind == ACCESS_AUTH_EXPIRED and vm.show_reconnect


def test_never_synced_is_provisional_not_empty() -> None:
    vm = build_access_vm(None, account=_account(), now=NOW, zone=ZONE)
    assert vm.kind == ACCESS_NEVER_SYNCED
    assert vm.provisional and not vm.show_reconnect
    assert vm.last_sync_label == "Aún no revisamos los mensajes"


@pytest.mark.parametrize(
    ("access", "kind", "reconnect", "tone"),
    [
        ("unknown", ACCESS_UNKNOWN, False, "warn"),
        ("permission_missing", ACCESS_PERMISSION_MISSING, True, "warn"),
        ("auth_expired", ACCESS_AUTH_EXPIRED, True, "warn"),
        ("access_disabled", ACCESS_DISABLED, False, "info"),
        ("error", ACCESS_ERROR, False, "warn"),
    ],
)
def test_sync_access_verdicts_become_banners(
    access: str, kind: str, reconnect: bool, tone: str
) -> None:
    vm = build_access_vm(
        _sync(access=access, detail="http_403_code_10"), account=_account(), now=NOW, zone=ZONE
    )
    assert (vm.kind, vm.show_reconnect, vm.tone, vm.provisional) == (kind, reconnect, tone, True)
    # m-24842988: Instagram's code is an internal number — never in the banner.
    assert "http_403_code_10" not in vm.message
    assert "código" not in vm.message


def test_unknown_names_the_owner_toggle() -> None:
    vm = build_access_vm(_sync(access="unknown"), account=_account(), now=NOW, zone=ZONE)
    assert "Permitir acceso a los mensajes" in vm.message


def test_ok_has_no_banner_and_a_failed_sync_has_one() -> None:
    ok = build_access_vm(_sync(), account=_account(), now=NOW, zone=ZONE)
    assert ok.kind == ACCESS_OK and ok.title == ""
    assert ok.last_sync_label == "Mensajes revisados · hace 3 min"
    failed = build_access_vm(
        _sync(sync_status="failed", sync_error="InstagramDirectError"),
        account=_account(),
        now=NOW,
        zone=ZONE,
    )
    assert failed.kind == ACCESS_SYNC_FAILED and not failed.provisional
    # A failed sync is a toast, not a banner: quiet kind, keyed by the failure's instant.
    assert failed.kind in QUIET_ACCESS_KINDS and ACCESS_OK in QUIET_ACCESS_KINDS
    assert failed.failure_key == (NOW - timedelta(minutes=3)).isoformat()
    assert failed.last_sync_label == "No pudimos revisar los mensajes · hace 3 min"


def test_the_profile_the_sync_fetched_names_the_row() -> None:
    thread = dataclasses.replace(
        _thread(),
        counterpart_name="Yesika Roa",
        counterpart_username="yesii_roa",
        counterpart_avatar_url="https://cdn/pic.jpg",
    )
    row = build_thread_row(_view(thread), ThreadExtra(username="old"), now=NOW, zone=ZONE)
    assert row.title == "Yesika Roa" and row.handle == "@yesii_roa"
    assert row.initials == "YR" and row.avatar_url == "https://cdn/pic.jpg"
    only_handle = dataclasses.replace(_thread(), counterpart_username="yesii_roa")
    row = build_thread_row(_view(only_handle), None, now=NOW, zone=ZONE)
    assert row.title == "@yesii_roa" and row.handle == "" and row.initials == "YR"


def test_window_words_are_plain_spanish() -> None:
    closes = NOW + timedelta(hours=5)
    sentence, short, tone = window_words(True, closes, NOW, ZONE)
    assert sentence.startswith("Instagram solo permite responder durante las 24 h")
    assert sentence.endswith("En esta conversación, hasta las 17:00.") and (short, tone) == (
        "",
        "ok",
    )
    tomorrow = NOW + timedelta(hours=13)
    sentence, short, tone = window_words(True, tomorrow, NOW, ZONE)
    assert sentence.endswith("hasta mañana a las 01:00.") and short == "" and tone == "ok"
    sentence, short, tone = window_words(True, NOW + timedelta(minutes=42), NOW, ZONE)
    assert sentence.startswith("Te quedan 42 min para responder: Instagram")
    assert (short, tone) == ("Quedan 42 min", "warn")
    assert window_words(False, None, NOW, ZONE) == (
        WINDOW_CLOSED_NOTICE,
        WINDOW_CLOSED_SHORT,
        "neutral",
    )


# --- thread rows --------------------------------------------------------------------------


def test_row_words_attention_window_preview_and_identity() -> None:
    thread = _thread(inbound=NOW - timedelta(hours=2))
    row = build_thread_row(
        _view(thread),
        ThreadExtra(username="alice", preview="¿tienen talla M?", preview_direction="inbound"),
        now=NOW,
        zone=ZONE,
        account_label="@qualifymkt.co",
    )
    assert row.title == "@alice" and row.handle == "" and row.initials == "A"
    assert row.hue == avatar_hue("igsid-123456") and row.avatar_url == ""
    assert row.subtitle == "@qualifymkt.co · Instagram Direct"
    assert row.preview == "¿tienen talla M?" and row.preview_icon == ""
    assert (row.attention, row.attention_label, row.attention_tone) == (
        "pending",
        "Pendiente",
        "warn",
    )
    assert row.window_open and row.window_tone == "ok"
    assert row.window_short == ""
    assert row.window_label.startswith("Instagram solo permite responder")
    assert row.time_label == "hace 2 h"
    assert not row.is_closed and not row.fresh


def test_row_prefixes_our_own_last_message_and_falls_back_without_a_handle() -> None:
    thread = _thread(inbound=NOW - timedelta(hours=3), outbound=NOW - timedelta(hours=1))
    row = build_thread_row(
        _view(thread),
        ThreadExtra(preview="claro que sí", preview_direction="outbound"),
        now=NOW,
        zone=ZONE,
    )
    assert row.preview == OUTBOUND_PREFIX + "claro que sí"
    assert row.title == "Persona sin nombre" and "123456" not in row.title
    assert row.initials == "6"
    assert row.subtitle == "Instagram Direct"
    assert (row.attention, row.attention_label) == ("answered", "Respondida")


def test_row_states_read_closed_window_media_and_empty() -> None:
    read = _thread(inbound=NOW - timedelta(hours=30), read=NOW - timedelta(hours=1))
    row = build_thread_row(_view(read), ThreadExtra(preview_media_type="image"), now=NOW, zone=ZONE)
    assert row.attention == "read" and row.attention_label == "Leída"
    assert not row.window_open and row.window_short == WINDOW_CLOSED_SHORT
    assert row.window_label == WINDOW_CLOSED_NOTICE
    assert row.preview == "Foto" and row.preview_icon == "image"
    audio = build_thread_row(
        _view(read), ThreadExtra(preview_media_type="audio"), now=NOW, zone=ZONE
    )
    assert (audio.preview, audio.preview_icon) == ("Audio", "mic")
    voice = build_thread_row(
        _view(read), ThreadExtra(preview_media_type="other"), now=NOW, zone=ZONE
    )
    assert (voice.preview, voice.preview_icon) == ("Nota de voz u otro contenido", "circle-slash")
    empty = build_thread_row(_view(_thread(inbound=None)), None, now=NOW, zone=ZONE)
    assert empty.attention == "none" and empty.preview == NO_MESSAGES_YET
    closed = build_thread_row(_view(_thread(status="closed")), None, now=NOW, zone=ZONE)
    assert closed.is_closed
    fresh = build_thread_row(_view(_thread()), None, now=NOW, zone=ZONE, fresh=True)
    assert fresh.fresh


def test_counterpart_title_rules() -> None:
    assert counterpart_title("@a", "x") == "@a"
    assert counterpart_title("a", "x") == "@a"
    assert counterpart_title("", "") == "Persona sin nombre"
    assert counterpart_title("", "17841400000123456") == "Persona sin nombre"


def test_filters_are_by_attention_and_counted() -> None:
    rows = [
        build_thread_row(_view(_thread()), None, now=NOW, zone=ZONE),
        build_thread_row(_view(_thread(read=NOW - timedelta(minutes=1))), None, now=NOW, zone=ZONE),
        build_thread_row(
            _view(_thread(outbound=NOW - timedelta(minutes=1))), None, now=NOW, zone=ZONE
        ),
    ]
    assert [r.attention for r in filter_threads(rows, FILTER_PENDING)] == ["pending"]
    assert [r.attention for r in filter_threads(rows, FILTER_READ)] == ["read"]
    assert [r.attention for r in filter_threads(rows, FILTER_ANSWERED)] == ["answered"]
    assert filter_threads(rows, FILTER_ALL) == rows == filter_threads(rows, "nope")
    assert filter_counts(rows) == {
        FILTER_ALL: 3,
        FILTER_PENDING: 1,
        FILTER_READ: 1,
        FILTER_ANSWERED: 1,
    }
    assert filter_label(FILTER_PENDING, 2) == "Pendientes · 2"
    assert filter_label(FILTER_PENDING, 0) == "Pendientes"


def test_newly_pending_announces_only_what_changed_after_a_first_load() -> None:
    old_thread = _thread(inbound=NOW - timedelta(hours=2))
    old = build_thread_row(_view(old_thread), ThreadExtra(preview="hola"), now=NOW, zone=ZONE)
    assert newly_pending([], [old]) == []  # a first load announces nothing
    assert newly_pending([old], [old]) == []  # nothing moved
    newer = dataclasses.replace(old, preview="¿y la talla L?", time_label="ahora")
    assert newly_pending([old], [newer]) == [old.thread_id]
    answered = dataclasses.replace(newer, attention="answered")
    assert newly_pending([old], [answered]) == []
    brand_new = build_thread_row(
        _view(_thread(counterpart="igsid-new")), ThreadExtra(preview="hey"), now=NOW, zone=ZONE
    )
    assert newly_pending([old], [old, brand_new]) == [brand_new.thread_id]


# --- bubbles ------------------------------------------------------------------------------


def test_bubbles_word_direction_receipts_and_media() -> None:
    inbound = build_message_vm(_message(), now=NOW, zone=ZONE)
    assert not inbound.is_outbound and inbound.tick == "" and inbound.time_label == "11:50"
    sent = build_message_vm(_message(direction="outbound", delivery="sent"), now=NOW, zone=ZONE)
    assert sent.is_outbound and (sent.tick, sent.tick_label) == ("sent", "Enviado")
    seen = build_message_vm(_message(direction="outbound", delivery="read"), now=NOW, zone=ZONE)
    assert (seen.tick, seen.tick_label) == ("read", "Visto")
    photo = build_message_vm(
        _message(text=None, media="image", media_url="https://cdn/x.jpg"),
        now=NOW,
        zone=ZONE,
        media_src="https://cdn/x.jpg",
    )
    assert photo.media_control == MEDIA_IMAGE and photo.media_label == "Foto"
    assert photo.media_src == "https://cdn/x.jpg" and photo.text == ""
    gone = build_message_vm(_message(text=None, media="audio"), now=NOW, zone=ZONE)
    assert gone.media_control == MEDIA_AUDIO and gone.media_src == "" and gone.text == ""
    quick = build_message_vm(_message(text=None, media="interactive"), now=NOW, zone=ZONE)
    assert quick.media_control == "" and quick.text == "Respuesta rápida"
    # Meta's `is_unsupported` (every audio, verified live): worded, never "[mensaje]".
    voice = build_message_vm(_message(text=None, media="other"), now=NOW, zone=ZONE)
    assert voice.media_control == "" and "nota de voz" in voice.text
    bare = build_message_vm(_message(text=None, media=None), now=NOW, zone=ZONE)
    assert bare.text == "Mensaje"
    assert media_label(None) == ("", "", "")


def test_unsent_bubbles_say_sending_or_why_not() -> None:
    queued = build_unsent_vm(
        UnsentItem(id="o1", status="pending", text="en cola", created_at=NOW), now=NOW, zone=ZONE
    )
    assert queued.message_id == "outbox-o1"
    assert (queued.tick, queued.tick_label) == ("queued", "Pendiente de envío")
    failed = build_unsent_vm(
        UnsentItem(id="o2", status="failed", text="x", created_at=NOW, error_code="window_closed"),
        now=NOW,
        zone=ZONE,
    )
    assert failed.tick == "failed" and "24 h" in failed.error_label
    media = build_unsent_vm(
        UnsentItem(
            id="o3",
            status="sending",
            text="",
            created_at=NOW,
            media_type="image",
            media_src="/r2media/t",
        ),
        now=NOW,
        zone=ZONE,
    )
    assert media.media_control == MEDIA_IMAGE and media.media_src == "/r2media/t"
    assert media.text == ""  # the media view is the message; no label under it


def test_failure_labels_cover_the_sender_codes() -> None:
    assert "canal" in failure_label("no_sender")
    assert "caducó" in failure_label("auth_error")
    assert "adjuntos" in failure_label("no_media_linker")
    assert "varios intentos" in failure_label("max_attempts:http_503_code_2")
    assert "Puede haber salido" in failure_label("send_ambiguous")
    assert failure_label("http_400_code_10") == "No se envió."  # no internal code
    assert failure_label(None) == "No se envió."


def test_conversation_is_chronological_with_day_chips_and_one_seen_footer() -> None:
    yesterday = _message(at=NOW - timedelta(days=1, minutes=30))
    first = _message(at=NOW - timedelta(minutes=30))
    ours_seen = _message(direction="outbound", delivery="read", at=NOW - timedelta(minutes=20))
    last = _message(direction="outbound", delivery="read", at=NOW - timedelta(minutes=5))
    queued = UnsentItem(
        id="q", status="sending", text="saliendo", created_at=NOW - timedelta(minutes=10)
    )
    vms = build_conversation([last, first, yesterday, ours_seen], [queued], now=NOW, zone=ZONE)
    assert [vm.message_id for vm in vms] == [
        str(yesterday.id),
        str(first.id),
        str(ours_seen.id),
        "outbox-q",
        str(last.id),
    ]
    assert [vm.day_label for vm in vms] == ["Ayer", "Hoy", "", "", ""]
    assert [vm.seen_footer for vm in vms] == ["", "", "", "", "Visto"]


def test_the_seen_footer_waits_while_a_newer_outbound_is_unread() -> None:
    seen = _message(direction="outbound", delivery="read", at=NOW - timedelta(minutes=20))
    unseen = _message(direction="outbound", delivery="sent", at=NOW - timedelta(minutes=5))
    vms = build_conversation([seen, unseen], [], now=NOW, zone=ZONE)
    assert [vm.seen_footer for vm in vms] == ["", ""]
    assert [vm.tick for vm in vms] == ["read", "sent"]


def test_media_sources_feed_the_bubbles() -> None:
    inbound = _message(text=None, media="image", media_url="https://cdn/in.jpg")
    outbound = _message(direction="outbound", text=None, media="audio", media_object_key="t/x/a")
    vms = build_conversation(
        [inbound, outbound],
        [],
        now=NOW,
        zone=ZONE,
        media_sources={str(inbound.id): "https://cdn/in.jpg", str(outbound.id): "/r2media/tok"},
    )
    assert [vm.media_src for vm in vms] == ["https://cdn/in.jpg", "/r2media/tok"]


def test_outbox_text_reads_the_messenger_platform_body() -> None:
    assert outbox_text({"recipient": {"id": "x"}, "message": {"text": " hola "}}) == "hola"
    assert outbox_text({"message": {"attachment": {"type": "image", "payload": {}}}}) == ""
    assert outbox_text({"message": {}}) == "Mensaje"
    assert outbox_text({}) == "Mensaje"


# --- composer -----------------------------------------------------------------------------


def test_reply_validation_and_the_parts_hint() -> None:
    assert validate_reply("   ") == "Escribe una respuesta."
    assert validate_reply("a" * MAX_REPLY_CHARS) == ""
    # Length is no longer a refusal: a long text is sent in consecutive messages.
    assert validate_reply("a" * (MAX_REPLY_CHARS + 1)) == ""
    assert reply_parts_hint("a" * MAX_REPLY_CHARS) == ""
    hint = reply_parts_hint("palabra " * 200)  # 1600 chars → two messages
    assert hint.startswith("Se enviará en 2 mensajes") and "1000" in hint
    assert composer_enabled(True, True, True)
    assert not composer_enabled(False, True, True)
    assert not composer_enabled(True, False, True)
    assert not composer_enabled(True, True, False)


def test_attachments_are_classified_within_metas_limits() -> None:
    assert classify_attachment("image/jpeg", 10) == (MEDIA_IMAGE, "")
    assert classify_attachment("image/png; charset=binary", 10) == (MEDIA_IMAGE, "")
    assert classify_attachment("audio/mpeg", 10) == (MEDIA_AUDIO, "")
    assert classify_attachment("image/jpeg", MAX_IMAGE_BYTES + 1)[0] == ""
    assert classify_attachment("audio/mp4", MAX_AUDIO_BYTES + 1)[0] == ""
    assert classify_attachment("video/mp4", 10) == (MEDIA_VIDEO, "")
    assert classify_attachment("video/quicktime", MAX_VIDEO_BYTES + 1)[0] == ""
    assert classify_attachment("application/pdf", 10) == ("document", "")
    assert classify_attachment("application/pdf", MAX_DOCUMENT_BYTES + 1)[0] == ""
    kind, error = classify_attachment("text/plain", 10)
    assert kind == "" and "PDF" in error
    docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert classify_attachment(docx, 10) == (
        "",
        "Instagram solo admite PDF como archivo (hasta 25 MB).",
    )
    kind, error = classify_attachment("image/gif", 10)
    assert kind == "" and "fotos" in error
    # Browsers record WAV through qualify-voice.js; webm is not something Instagram takes.
    assert classify_attachment("audio/wav", 10) == (MEDIA_AUDIO, "")
    assert classify_attachment("audio/webm", 10)[0] == ""


def test_stickers_hearts_and_voice_names() -> None:
    assert media_label("sticker") == ("Me gusta", "heart", MEDIA_STICKER)
    vm = build_message_vm(
        _message(direction="outbound", text=None, media="sticker", delivery="sent"),
        now=NOW,
        zone=ZONE,
    )
    assert vm.media_control == MEDIA_STICKER and vm.media_src == "" and vm.text == ""
    assert outbox_text({"message": {"attachment": {"type": "like_heart"}}}) == ""
    assert voice_note_name(42, NOW, ZONE) == "Nota de voz 0:42 · 12:00"
    assert voice_note_name(125, NOW, ZONE).startswith("Nota de voz 2:05")


# --- drafts (E4) ---------------------------------------------------------------------------


class _Draft:
    def __init__(self, needs_review: bool, claims: list[str] | None = None) -> None:
        self.id = uuid4()
        self.generated_text = "¡Hola! Sí, hay talla M."
        self.needs_review = needs_review
        self.grounding = {"business_name": "Bianki", "unsupported_claims": claims or []}


def test_draft_vm_words_the_review_verdict() -> None:
    plain = build_draft_vm(_Draft(False))
    assert plain.text == "¡Hola! Sí, hay talla M." and not plain.needs_review
    assert plain.note.startswith("Sugerencia de IA") and plain.claims == ""
    review = build_draft_vm(_Draft(True, ["envíos", "precio"]))
    assert review.needs_review and "requiere revisión" in review.note
    assert review.claims == "envíos · precio"
    assert suggestion_refusal_label("last_message_outbound").startswith("Ya respondiste")
    assert suggestion_refusal_label("inbound_without_text").startswith("El último mensaje")
    assert suggestion_refusal_label("window_closed").startswith("Ya no se puede")
    assert suggestion_refusal_label("whatever").startswith("No se pudo sugerir")


# --- security boundary --------------------------------------------------------------------


@pytest.mark.parametrize(
    "vm", [AccountVM, AccessVM, ThreadRowVM, MessageVM, UnsentItem, AttachmentVM, DraftVM]
)
def test_conversations_vm_has_no_credential_fields(vm: type) -> None:
    forbidden = ("token", "secret", "ciphertext", "credential", "password", "key_id")
    for field in dataclasses.fields(vm):
        assert not any(word in field.name for word in forbidden), field.name
        assert typing.get_origin(field.type) is not dict or field.name == ""


# --- replies to stories (m-24789646, B5) ------------------------------------------------


def test_an_inbound_story_reply_says_so_with_the_storys_link() -> None:
    story = dataclasses.replace(
        _message(), story_reply_id="17900000000000001", story_reply_url="https://cdn/story"
    )
    vm = build_message_vm(story, now=NOW, zone=ZONE)
    assert (vm.story_reply_label, vm.story_reply_href) == (
        "Respondió a tu historia",
        "https://cdn/story",
    )
    expired = dataclasses.replace(story, story_reply_url=None)
    assert build_message_vm(expired, now=NOW, zone=ZONE).story_reply_href == ""
    plain = build_message_vm(_message(), now=NOW, zone=ZONE)
    assert (plain.story_reply_label, plain.story_reply_href) == ("", "")


def test_the_bubble_renders_the_story_context_only_when_there_is_one() -> None:
    from .conversations_page import _story_reply
    from .conversations_state import ConversationsState

    rendered = str(_story_reply(ConversationsState.messages[0]).render())
    assert "story_reply_label" in rendered and "story_reply_href" in rendered


# --- taps: ice breakers, quick replies, buttons, menu (m-24789472) ---------------------


@pytest.mark.parametrize(
    ("kind", "payload", "text", "label"),
    [
        ("ice_breaker", "QF_PRECIO", "¿Cuánto cuesta?", "Pregunta inicial: Precio"),
        ("ice_breaker", "QF_OTRA", "¿Hacen envíos?", "Pregunta inicial: ¿Hacen envíos?"),
        ("quick_reply", "SI", "Sí", "Respuesta rápida: Sí"),
        ("button", "QFB_VER_CATALOGO", "Ver catálogo", "Botón: Ver catálogo"),
        ("menu", "QFM_HORARIO", "Horario", "Menú: Horario"),
        ("menu", "QFM_X", None, "Menú"),
    ],
)
def test_a_tapped_message_says_where_it_came_from(
    kind: str, payload: str, text: str | None, label: str
) -> None:
    tapped = dataclasses.replace(_message(text=text), choice_kind=kind, choice_payload=payload)
    vm = build_message_vm(tapped, now=NOW, zone=ZONE)
    assert vm.choice_label == label
    assert payload not in vm.choice_label  # the payload is an internal key, never shown


def test_a_typed_or_outbound_message_has_no_tap_origin() -> None:
    assert build_message_vm(_message(), now=NOW, zone=ZONE).choice_label == ""
    ours = dataclasses.replace(
        _message(direction="outbound"), choice_kind="quick_reply", choice_payload="SI"
    )
    assert build_message_vm(ours, now=NOW, zone=ZONE).choice_label == ""


def test_a_tapped_last_message_previews_as_its_origin() -> None:
    view = _view(_thread(inbound=NOW - timedelta(minutes=5)))
    row = build_thread_row(
        view,
        ThreadExtra(
            preview="¿Cuánto cuesta?",
            preview_direction="inbound",
            preview_choice_kind="ice_breaker",
            preview_choice_payload="QF_PRECIO",
        ),
        now=NOW,
        zone=ZONE,
    )
    assert (row.preview, row.preview_icon) == ("Pregunta inicial: Precio", TAP_ICON)
    typed = build_thread_row(
        view, ThreadExtra(preview="hola", preview_direction="inbound"), now=NOW, zone=ZONE
    )
    assert (typed.preview, typed.preview_icon) == ("hola", "")


def test_the_bubble_renders_the_tap_origin_only_when_there_is_one() -> None:
    from .conversations_page import _choice_origin, _message
    from .conversations_state import ConversationsState

    m = ConversationsState.messages[0]
    rendered = str(_choice_origin(m).render())
    assert "choice_label" in rendered and "LucidePointer" in rendered  # TAP_ICON
    # The bubble stacks it above the text, like a story reply.
    bubble = str(_message(m).render())
    assert "choice_label" in bubble and "q-conv-msg--story" in bubble


# --- message templates (m-24789472) ----------------------------------------------------


def test_the_template_limits_mirror_the_service() -> None:
    from qualify_api.conversations import templates as backend

    from .conversations_vm import (
        MAX_TEMPLATE_BODY_CHARS,
        MAX_TEMPLATE_TITLE_CHARS,
        MAX_TEMPLATES_PER_ACCOUNT,
    )

    assert MAX_TEMPLATE_TITLE_CHARS == backend.MAX_TITLE_CHARS
    assert MAX_TEMPLATE_BODY_CHARS == backend.MAX_BODY_CHARS
    assert MAX_TEMPLATES_PER_ACCOUNT == backend.MAX_TEMPLATES_PER_CONNECTION


def test_template_rows_keep_the_order_and_mark_the_ends() -> None:
    from qualify_api.conversations.templates import DEFAULT_TEMPLATES, ReplyTemplate

    from .conversations_vm import build_template_rows

    now = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
    records = [
        ReplyTemplate(
            id=uuid4(),
            tenant_id=uuid4(),
            connection_id=uuid4(),
            title=d.title,
            body=d.body,
            position=i,
            default_key=d.key if i < 2 else None,
            created_by_user_id=None,
            updated_by_user_id=None,
            created_at=now,
            updated_at=now,
        )
        for i, d in enumerate(DEFAULT_TEMPLATES)
    ]
    rows = build_template_rows(records)
    assert [r.title for r in rows] == ["Saludo", "Precio", "Horario", "Catálogo"]
    assert [(r.is_first, r.is_last) for r in rows] == [
        (True, False),
        (False, False),
        (False, False),
        (False, True),
    ]
    assert [r.is_default for r in rows] == [True, True, False, False]
    assert rows[0].template_id == str(records[0].id)
    assert build_template_rows([]) == []


def test_the_picker_preview_is_one_line_cut_at_a_word() -> None:
    from .conversations_vm import template_preview

    assert template_preview("Hola,\n  ¿cómo estás?") == "Hola, ¿cómo estás?"
    cut = template_preview("palabra " * 30, limit=20)
    assert cut.endswith("…") and len(cut) <= 21 and "palab…" not in cut


def test_the_counters_say_used_over_allowed() -> None:
    from .conversations_vm import char_counter, template_counter

    assert template_counter(12) == "12/50"
    assert char_counter("Saludo", 60) == "6/60"


def test_moving_a_template_returns_the_whole_new_order_or_nothing() -> None:
    from .conversations_vm import moved_order

    ids = ["a", "b", "c"]
    assert moved_order(ids, "b", -1) == ["b", "a", "c"]
    assert moved_order(ids, "b", 1) == ["a", "c", "b"]
    assert moved_order(ids, "a", -1) is None
    assert moved_order(ids, "c", 1) is None
    assert moved_order(ids, "z", 1) is None
    assert moved_order(ids, "a", 2) is None
    assert ids == ["a", "b", "c"]  # the input is not mutated


def test_the_fill_notice_names_what_is_left_and_goes_away_once_filled() -> None:
    from .conversations_vm import template_notice

    text = "¡Hola, {nombre}! El precio es [precio]."
    assert template_notice(text, ["{nombre}"], ["[precio]"]) == (
        "Completa {nombre} antes de enviar: no tenemos ese dato en esta conversación. "
        "Rellena [precio] antes de enviar."
    )
    assert template_notice("¡Hola, Ana! El precio es [precio].", ["{nombre}"], ["[precio]"]) == (
        "Rellena [precio] antes de enviar."
    )
    assert template_notice("¡Hola, Ana! Cuesta 20.", ["{nombre}"], ["[precio]"]) == ""
    three = template_notice(
        "[días] de [hora de apertura] a [hora de cierre]",
        [],
        ["[días]", "[hora de apertura]", "[hora de cierre]"],
    )
    assert three == "Rellena [días], [hora de apertura] y [hora de cierre] antes de enviar."
    assert template_notice("", [], []) == ""
