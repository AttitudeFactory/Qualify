"""Send an approved piece to the creator's TikTok inbox as a DRAFT (m-24921091).

**Assisted, never autonomous.** Nothing here publishes: the Content Posting API inbox upload
puts the video in the creator's TikTok drafts and the creator finishes it in the app. There
is no schedule, no worker tick and no `video.publish`; TikTok is deliberately NOT in
`planner.publishable.SCHEDULABLE_PLATFORMS` (ADR 21(d)/23(c)). The call is a one-click human
action ("Enviar a TikTok") on an approved piece.

## Same gate as Instagram

`PostReader.get_publishable` is the single approval rule (approved copy, approved revision,
files in this tenant's R2, final video confirmed). A refusal surfaces its Spanish reason from
`planner.publishable.REASON_TEXT` and nothing is sent. The destination is `reel`: TikTok takes
one video, so a single-video output is the only accepted shape.

## Write-ahead + idempotency

A `tiktok_drafts` row exists BEFORE the first TikTok call; its key is derived from
(post, output port, approved revision, attempt), so a double click or a retried request finds
the same row and never puts a second draft in the inbox. The `publish_id` is stored as soon
as `init` answers (before the bytes go up), so an interrupted upload stays reconcilable by
`refresh`. A failed row is final (settle-once trigger): trying again is a new `attempt`.

No row is left `pending` forever: ANY failure before a `publish_id` exists (a missing
credential, a network error, a bug) settles the row as failed with a generic Spanish text, and
`refresh` settles a row still without `publish_id` after `STALE_PENDING_AFTER` (a crashed or
cancelled request) the same way. Once a `publish_id` exists, TikTok's status is the truth.

## Tokens

This service never sees one: the TikTok client arrives from a factory that goes through
`TikTokCredentialResolver` (refresh included) at send time.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from qualify_shared.objects.gate import ObjectGate
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from qualify_api.connections.credential_reader import CredentialNotFound
from qualify_api.connections.read import ConnectionSummary
from qualify_api.connections.tiktok_credentials import TikTokReconnectRequired
from qualify_api.planner.post_reader import NotPublishable, PostReader
from qualify_api.planner.publishable import DESTINATION_TIKTOK, REASON_TEXT
from qualify_api.publishing.client import MEDIA_TYPE_REELS
from qualify_api.publishing.models import TikTokDraft
from qualify_api.publishing.tiktok_client import (
    RemoteStatus,
    TikTokPostClient,
    TikTokPublishError,
)

_LOGGER = logging.getLogger(__name__)

ADAPTER_VERSION = "tiktok-inbox-v1"
UPLOAD_SCOPE = "video.upload"
FILE_UPLOAD = "FILE_UPLOAD"
PULL_FROM_URL = "PULL_FROM_URL"

STATUS_PENDING = "pending"
STATUS_UPLOADING = "uploading"
STATUS_PROCESSING = "processing"
STATUS_IN_INBOX = "in_inbox"
STATUS_FAILED = "failed"
TERMINAL = frozenset({STATUS_IN_INBOX, STATUS_FAILED})

#: Our own failure codes (never TikTok's): they fall to the generic Spanish failure text.
CODE_SEND_ERROR = "send_error"
CODE_STALE_PENDING = "stale_pending"
#: A row with no `publish_id` this long after it was written is a dead request, not a slow one
#: (the init call answers in seconds; the bytes only go up after the `publish_id` is stored).
STALE_PENDING_AFTER = timedelta(minutes=15)

_RECONNECT_SCOPE_TEXT = "Hay que volver a conectar tu cuenta de TikTok y aceptar el permiso."
# Client-facing (Spanish, plain; qualify-copy-es). Keyed by TikTok error code.
_FAILURE_TEXT: dict[str, str] = {
    "spam_risk_too_many_pending_share": (
        "Tienes varios videos sin terminar en TikTok. Publica o descarta alguno en la "
        "aplicación e inténtalo de nuevo."
    ),
    "rate_limit_exceeded": "TikTok pidió esperar un momento. Inténtalo de nuevo en unos minutos.",
    "file_format_check_failed": "TikTok no aceptó el formato de este video.",
    "url_ownership_unverified": "TikTok no pudo comprobar el origen del video. Inténtalo de nuevo.",
    "access_token_invalid": "Hay que volver a conectar tu cuenta de TikTok.",
    "scope_not_authorized": _RECONNECT_SCOPE_TEXT,
    "scope_permission_missed": _RECONNECT_SCOPE_TEXT,
}
_FAILURE_DEFAULT = "TikTok no pudo recibir tu video. Inténtalo de nuevo en unos minutos."
NOT_CONNECTED_TEXT = "Conecta primero tu cuenta de TikTok."
NEEDS_RECONNECT_TEXT = "Hay que volver a conectar tu cuenta de TikTok."
NOT_A_VIDEO_TEXT = "TikTok solo recibe un video. Elige una pieza que sea un video."
#: `video.upload` lands in the creator's TikTok inbox as a NOTIFICATION, not in the profile's
#: «Borradores» folder: the owner taps it to finish and publish.
IN_INBOX_TEXT = "Listo: abre TikTok y busca la notificación para terminar tu publicación."
SENDING_TEXT = "Estamos enviando tu video a TikTok."


def failure_text(code: str | None) -> str:
    return _FAILURE_TEXT.get(code or "", _FAILURE_DEFAULT)


class DraftRefused(Exception):
    """The draft was not sent, and `message` says why in the client's language."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class DraftState:
    draft_id: UUID
    status: str
    settled: bool
    publish_id: str | None
    message: str
    caption: str | None = None
    created: bool = True


def draft_idempotency_key(
    *, post_id: UUID, output_port: str | None, approved_revision: int, attempt: int = 1
) -> str:
    """One draft per approved revision of a piece; a new `attempt` is the explicit retry."""
    return f"tiktok:{post_id}:{output_port or '-'}:rev{approved_revision}:n{attempt}"


class TikTokClientFactory(Protocol):
    async def client_for(self, *, tenant_id: UUID, connection_id: UUID) -> TikTokPostClient: ...


class PublicVideoLinker(Protocol):
    def link(self, *, tenant_id: UUID, object_key: str, content_type: str) -> str: ...


@dataclass(frozen=True)
class DraftRecord:
    id: UUID
    status: str
    publish_id: str | None
    platform_error_code: str | None
    caption: str | None
    settled: bool
    started_at: datetime | None = None


class TikTokDraftRepository(Protocol):
    def create_or_get(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        post_id: UUID,
        output_port: str | None,
        approved_revision: int,
        idempotency_key: str,
        upload_mode: str,
        media_object_key: str,
        caption: str | None,
        user_id: UUID,
    ) -> tuple[DraftRecord, bool]: ...

    def get(self, *, tenant_id: UUID, draft_id: UUID) -> DraftRecord | None: ...

    def update(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        status: str,
        publish_id: str | None = None,
        video_bytes: int | None = None,
        platform_error_code: str | None = None,
    ) -> None: ...


def _record(row: TikTokDraft) -> DraftRecord:
    return DraftRecord(
        id=row.id,
        status=row.status,
        publish_id=row.publish_id,
        platform_error_code=row.platform_error_code,
        caption=row.caption,
        settled=row.settled_at is not None,
        started_at=row.started_at,
    )


class PostgresTikTokDraftRepository:
    def create_or_get(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        post_id: UUID,
        output_port: str | None,
        approved_revision: int,
        idempotency_key: str,
        upload_mode: str,
        media_object_key: str,
        caption: str | None,
        user_id: UUID,
    ) -> tuple[DraftRecord, bool]:
        with tenant_session(tenant_id) as session:
            inserted = session.execute(
                insert(TikTokDraft)
                .values(
                    tenant_id=tenant_id,
                    connection_id=connection_id,
                    post_id=post_id,
                    output_port=output_port,
                    approved_revision=approved_revision,
                    idempotency_key=idempotency_key,
                    upload_mode=upload_mode,
                    media_object_key=media_object_key,
                    caption=caption,
                    status=STATUS_PENDING,
                    adapter_version=ADAPTER_VERSION,
                    created_by_user_id=user_id,
                )
                .on_conflict_do_nothing(constraint="uq_tiktok_draft_idem")
                .returning(TikTokDraft.id)
            ).first()
            row = session.scalar(
                select(TikTokDraft).where(
                    TikTokDraft.connection_id == connection_id,
                    TikTokDraft.idempotency_key == idempotency_key,
                )
            )
            assert row is not None  # noqa: S101 — just inserted or already there
            return _record(row), inserted is not None

    def get(self, *, tenant_id: UUID, draft_id: UUID) -> DraftRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.get(TikTokDraft, draft_id)
            return _record(row) if row is not None else None

    def update(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        status: str,
        publish_id: str | None = None,
        video_bytes: int | None = None,
        platform_error_code: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        with tenant_session(tenant_id) as session:
            row = session.scalar(
                select(TikTokDraft).where(TikTokDraft.id == draft_id).with_for_update()
            )
            if row is None or row.settled_at is not None:
                return  # terminal is final (the DB trigger says the same)
            row.status = status
            if publish_id is not None:
                row.publish_id = publish_id
            if video_bytes is not None:
                row.video_bytes = video_bytes
            if platform_error_code is not None:
                row.platform_error_code = platform_error_code
            row.updated_at = now
            if status in TERMINAL:
                row.settled_at = now
            session.flush()


class TikTokDraftService:
    def __init__(
        self,
        *,
        posts: PostReader,
        connections: Callable[[UUID], tuple[ConnectionSummary, ...]],
        repository: TikTokDraftRepository,
        gate: ObjectGate,
        client_factory: TikTokClientFactory,
        upload_mode: str = FILE_UPLOAD,
        media_linker: PublicVideoLinker | None = None,
        connection_degrader: Callable[..., object] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._posts = posts
        self._connections = connections
        self._repo = repository
        self._gate = gate
        self._clients = client_factory
        self._mode = upload_mode
        self._linker = media_linker
        self._degrader = connection_degrader
        self._clock = clock

    def _target(self, tenant_id: UUID, connection_id: UUID) -> ConnectionSummary:
        found = next(
            (c for c in self._connections(tenant_id) if c.connection_id == connection_id), None
        )
        if found is None or found.platform != "tiktok":
            raise DraftRefused("not_connected", NOT_CONNECTED_TEXT)
        if found.status != "active" or UPLOAD_SCOPE not in found.granted_scopes:
            raise DraftRefused("needs_reconnect", NEEDS_RECONNECT_TEXT)
        return found

    async def send_to_inbox(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        connection_id: UUID,
        post_id: UUID,
        output_port: str | None = None,
        attempt: int = 1,
    ) -> DraftState:
        """Gate -> write-ahead row -> init -> bytes -> one status read. Idempotent."""
        self._target(tenant_id, connection_id)
        verdict = self._posts.get_publishable(
            tenant_id=tenant_id,
            post_id=post_id,
            output_port=output_port,
            destination=DESTINATION_TIKTOK,
        )
        if isinstance(verdict, NotPublishable):
            raise DraftRefused(
                str(verdict.reason),
                REASON_TEXT.get(verdict.reason, "Esta publicación todavía no se puede enviar."),
            )
        if verdict.media_product_type != MEDIA_TYPE_REELS or len(verdict.media) != 1:
            raise DraftRefused("not_a_video", NOT_A_VIDEO_TEXT)
        media = verdict.media[0]

        record, created = self._repo.create_or_get(
            tenant_id=tenant_id,
            connection_id=connection_id,
            post_id=post_id,
            output_port=output_port,
            approved_revision=verdict.approved_revision,
            idempotency_key=draft_idempotency_key(
                post_id=post_id,
                output_port=output_port,
                approved_revision=verdict.approved_revision,
                attempt=attempt,
            ),
            upload_mode=self._mode,
            media_object_key=media.object_key,
            caption=verdict.caption,
            user_id=user_id,
        )
        if not created:
            # Same approved revision already sent (or in flight): never a second draft.
            return await self.refresh(
                tenant_id=tenant_id, connection_id=connection_id, draft_id=record.id, created=False
            )

        try:
            client = await self._clients.client_for(
                tenant_id=tenant_id, connection_id=connection_id
            )
            publish_id = await self._init_and_upload(
                client=client, tenant_id=tenant_id, draft_id=record.id, media=media
            )
        except (TikTokReconnectRequired, CredentialNotFound):
            self._fail(tenant_id, record.id, "access_token_invalid")
            raise DraftRefused("needs_reconnect", NEEDS_RECONNECT_TEXT) from None
        except TikTokPublishError as exc:
            self._on_publish_error(tenant_id, connection_id, record.id, exc)
            return self._state(tenant_id, record.id)
        except Exception as exc:  # noqa: BLE001 — never leave the write-ahead row pending
            # Type only: an httpx/driver message may carry a URL with a token in it.
            _LOGGER.warning("tiktok draft send crashed: %s", type(exc).__name__)
            current = self._repo.get(tenant_id=tenant_id, draft_id=record.id)
            if current is not None and current.publish_id is None:
                self._fail(tenant_id, record.id, CODE_SEND_ERROR)
            # With a publish_id TikTok owns the outcome: `refresh` reconciles it.
            return self._state(tenant_id, record.id)
        self._repo.update(
            tenant_id=tenant_id, draft_id=record.id, status=STATUS_PROCESSING, publish_id=publish_id
        )
        return await self.refresh(
            tenant_id=tenant_id, connection_id=connection_id, draft_id=record.id
        )

    async def _init_and_upload(self, *, client, tenant_id, draft_id, media) -> str:  # type: ignore[no-untyped-def]
        if self._mode == PULL_FROM_URL:
            if self._linker is None:
                raise TikTokPublishError("pull mode without a media linker", code="misconfigured")
            url = self._linker.link(
                tenant_id=tenant_id, object_key=media.object_key, content_type=media.content_type
            )
            init = await client.init_pull_from_url(video_url=url)
            self._repo.update(
                tenant_id=tenant_id,
                draft_id=draft_id,
                status=STATUS_PROCESSING,
                publish_id=init.publish_id,
            )
            return init.publish_id
        fileobj = self._gate.open_object(tenant_id, media.object_key)
        try:
            size = _length(fileobj)
            init = await client.init_file_upload(video_size=size)
            if init.upload_url is None:
                raise TikTokPublishError("init response carried no upload_url")
            # Write-ahead of the bytes: the publish_id is stored before they go up.
            self._repo.update(
                tenant_id=tenant_id,
                draft_id=draft_id,
                status=STATUS_UPLOADING,
                publish_id=init.publish_id,
                video_bytes=size,
            )
            await client.upload_file(upload_url=init.upload_url, fileobj=fileobj, video_size=size)
            return init.publish_id
        finally:
            fileobj.close()

    async def refresh(
        self, *, tenant_id: UUID, connection_id: UUID, draft_id: UUID, created: bool = True
    ) -> DraftState:
        """ONE status read; settles on a terminal TikTok status. Safe to call repeatedly."""
        record = self._repo.get(tenant_id=tenant_id, draft_id=draft_id)
        if record is None:
            raise DraftRefused("not_found", "No encontramos ese envío a TikTok.")
        if record.settled:
            return self._to_state(record, created=created)
        if record.publish_id is None:
            if record.started_at is not None and (
                self._clock() - record.started_at >= STALE_PENDING_AFTER
            ):
                self._fail(tenant_id, draft_id, CODE_STALE_PENDING)
                return self._state(tenant_id, draft_id, created=created)
            return self._to_state(record, created=created)
        try:
            client = await self._clients.client_for(
                tenant_id=tenant_id, connection_id=connection_id
            )
            remote = await client.fetch_status(publish_id=record.publish_id)
        except TikTokReconnectRequired:
            raise DraftRefused("needs_reconnect", NEEDS_RECONNECT_TEXT) from None
        except TikTokPublishError as exc:
            if exc.is_auth_failure:
                self._on_publish_error(tenant_id, connection_id, draft_id, exc)
            return self._to_state(record, created=created)  # transient: stay as we were
        if remote.status in (RemoteStatus.SEND_TO_USER_INBOX, RemoteStatus.PUBLISH_COMPLETE):
            self._repo.update(tenant_id=tenant_id, draft_id=draft_id, status=STATUS_IN_INBOX)
        elif remote.status is RemoteStatus.FAILED:
            self._fail(tenant_id, draft_id, remote.fail_reason or "failed")
        return self._state(tenant_id, draft_id, created=created)

    def _fail(self, tenant_id: UUID, draft_id: UUID, code: str) -> None:
        self._repo.update(
            tenant_id=tenant_id, draft_id=draft_id, status=STATUS_FAILED, platform_error_code=code
        )

    def _on_publish_error(
        self, tenant_id: UUID, connection_id: UUID, draft_id: UUID, exc: TikTokPublishError
    ) -> None:
        # Codes and statuses only — never the response body.
        _LOGGER.warning("tiktok draft failed: code=%s http=%s", exc.code, exc.http_status)
        self._fail(tenant_id, draft_id, exc.code or f"http_{exc.http_status or 'error'}")
        if exc.is_auth_failure and self._degrader is not None:
            self._degrader(tenant_id=tenant_id, connection_id=connection_id)

    def _state(self, tenant_id: UUID, draft_id: UUID, *, created: bool = True) -> DraftState:
        record = self._repo.get(tenant_id=tenant_id, draft_id=draft_id)
        assert record is not None  # noqa: S101
        return self._to_state(record, created=created)

    @staticmethod
    def _to_state(record: DraftRecord, *, created: bool) -> DraftState:
        if record.status == STATUS_IN_INBOX:
            message = IN_INBOX_TEXT
        elif record.status == STATUS_FAILED:
            message = failure_text(record.platform_error_code)
        else:
            message = SENDING_TEXT
        return DraftState(
            draft_id=record.id,
            status=record.status,
            settled=record.settled,
            publish_id=record.publish_id,
            message=message,
            caption=record.caption,
            created=created,
        )


def _length(fileobj: object) -> int:
    """Seekable length, position restored (R2 streams re-opened for publish are seekable)."""
    origin = fileobj.seek(0, 1)  # type: ignore[attr-defined]
    end = fileobj.seek(0, 2)  # type: ignore[attr-defined]
    fileobj.seek(origin, 0)  # type: ignore[attr-defined]
    return end - origin
