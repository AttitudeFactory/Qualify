"""m-24842989: `replies_provider.pending_drafts` passes the comment's author through and
takes the publication's picture from the inbox's already-loaded candidates — no query,
no Meta call of its own."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from qualify_api.replies.repository import DraftRecord

from . import replies_provider
from .inbox_vm import CandidateMediaVM

TENANT = UUID("11111111-1111-4111-8111-111111111111")
CONNECTION = UUID("22222222-2222-4222-8222-222222222222")


def _record(**overrides: object) -> DraftRecord:
    base = DraftRecord(
        id=uuid4(),
        tenant_id=TENANT,
        connection_id=CONNECTION,
        message_id=uuid4(),
        source_id="c-1",
        sentiment_result_id=uuid4(),
        sentiment_label="POS",
        gate_reason="ok",
        generator_version="v1",
        generated_text="¡Gracias!",
        final_text=None,
        status="proposed",
        comment_text="qué rico",
        created_at=datetime(2026, 10, 23, 12, 0, tzinfo=UTC),
        decided_at=None,
        decided_by_user_id=None,
        sent_at=None,
        external_reply_id=None,
        send_error_code=None,
        settled_at=None,
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def _candidate(media_id: str, *, caption: str = "", thumb: str = "") -> CandidateMediaVM:
    return CandidateMediaVM(
        external_media_id=media_id,
        posted_at="",
        is_monitored=True,
        caption=caption,
        permalink="",
        thumbnail_url=thumb,
    )


@pytest.fixture
def records(monkeypatch: pytest.MonkeyPatch) -> list[DraftRecord]:
    rows: list[DraftRecord] = []
    monkeypatch.setattr(
        replies_provider, "_list_pending_drafts", lambda **_: tuple(rows), raising=True
    )
    # Dates use the tenant's zone (m-24789645); keep the test off the database.
    monkeypatch.setattr(replies_provider, "_tenant_zone", lambda _tenant: ZoneInfo("UTC"))
    return rows


def test_author_and_thumbnail_pass_through(records: list[DraftRecord]) -> None:
    records.append(
        _record(author_username="cliente.feliz", external_media_id="m-1", media_caption="Shawarma")
    )
    (vm,) = replies_provider.pending_drafts(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        candidates=[_candidate("m-1", caption="otro", thumb="https://cdn/x.jpg")],
    )
    assert vm.author_username == "cliente.feliz"
    assert vm.media_thumbnail_url == "https://cdn/x.jpg"
    # The stored caption wins over the candidate's.
    assert vm.media_alt == "Shawarma"


def test_caption_falls_back_to_the_candidate_then_to_publicacion(
    records: list[DraftRecord],
) -> None:
    records.extend(
        [
            _record(external_media_id="m-1"),
            _record(external_media_id="m-2"),
            _record(),
        ]
    )
    vms = replies_provider.pending_drafts(
        tenant_id=TENANT, connection_id=CONNECTION, candidates=[_candidate("m-1", caption="Helado")]
    )
    assert [v.media_alt for v in vms] == ["Helado", "Publicación", "Publicación"]
    assert [v.media_thumbnail_url for v in vms] == ["", "", ""]
    assert all(v.author_username == "" for v in vms)


def test_without_candidates_nothing_breaks(records: list[DraftRecord]) -> None:
    records.append(_record(author_username="ana", external_media_id="m-9"))
    (vm,) = replies_provider.pending_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    assert (vm.author_username, vm.media_thumbnail_url, vm.media_alt) == ("ana", "", "Publicación")
