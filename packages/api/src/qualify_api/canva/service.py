"""The Canva round trip, orchestrated: connect an operator's Canva, send a draft's piece
there to edit, and bring the edited result back into Qualify.

**Written against Canva's documentation, never exercised live** — no integration
credentials existed yet (§ request 2026-09-28). What a first real run must confirm is
listed in `docs/canva-integracion.md`.

Flow:

1. `start_connect` → the UI sends the user to Canva's consent page, keeping the PKCE
   verifier and the `state` server-side (they never ride in the URL together).
2. `finish_connect` → on our redirect page: the code is exchanged and the tokens stored
   encrypted (`connections.crypto.Encryptor`), per `(tenant, user)`.
3. `send` → the draft's first stored file is uploaded to the user's Canva; a custom
   design of the piece's size is created (an image is placed in it; a video stays in
   the user's Uploads — the API cannot place one) and a link row keeps the
   `correlation_state` we append to the edit URL.
4. `handle_return` → Canva's "Return" lands on our return page with a
   `correlation_jwt`. Its signature is NOT verified (the keys endpoint was preview);
   instead the `correlation_state` must match a link of THIS tenant (RLS) created by
   THIS user, and the design is re-read with this user's own token. Then `pull`.
5. `pull` → export (PNG for an image, 1080p MP4 for a video), download at once (Canva's
   URLs last 24 h) and store next to the draft's own files.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from qualify_creative.adapters.canva_connect import (
    CanvaConnectClient,
    CanvaDesign,
    CanvaError,
    CanvaTokens,
    authorize_url,
    decode_correlation_jwt,
    mp4_quality_for,
    new_correlation_state,
    new_pkce,
    with_correlation_state,
)

from qualify_api.canva.repository import (
    AccountRecord,
    CanvaRepository,
    LinkRecord,
    MediaRef,
    NewLink,
)
from qualify_api.connections.crypto import Encryptor

logger = logging.getLogger(__name__)

CLIENT_ID_ENV = "QUALIFY_CANVA_CLIENT_ID"
CLIENT_SECRET_ENV = "QUALIFY_CANVA_CLIENT_SECRET"
REDIRECT_URI_ENV = "QUALIFY_CANVA_REDIRECT_URI"
#: Canva's portal must list this exact URL. The return URL (`/canva/return`) is set in
#: the portal only — Canva does not take it per request.
DEFAULT_REDIRECT_URI = "http://127.0.0.1:3000/canva/callback"
#: Refresh this long before the access token expires, so a call never races it.
_REFRESH_MARGIN = timedelta(minutes=2)


class CanvaNotConfigured(RuntimeError):
    """`QUALIFY_CANVA_CLIENT_ID` / `QUALIFY_CANVA_CLIENT_SECRET` are not set."""


class CanvaNotConnected(RuntimeError):
    """This user has not connected their Canva (or revoked it)."""


class NothingToSend(RuntimeError):
    """The draft has no stored image or video yet."""


class UnknownReturn(RuntimeError):
    """A return navigation that matches no link of this tenant and user."""


class MediaStore(Protocol):
    def read(self, key: str) -> bytes: ...

    def write(self, key: str, data: bytes) -> None: ...


@dataclass(frozen=True)
class CanvaConfig:
    client_id: str
    client_secret: str
    redirect_uri: str

    @classmethod
    def from_env(cls) -> CanvaConfig:
        client_id = os.environ.get(CLIENT_ID_ENV, "").strip()
        client_secret = os.environ.get(CLIENT_SECRET_ENV, "").strip()
        if not client_id or not client_secret:
            raise CanvaNotConfigured(f"{CLIENT_ID_ENV} / {CLIENT_SECRET_ENV} are not set")
        redirect = os.environ.get(REDIRECT_URI_ENV, "").strip() or DEFAULT_REDIRECT_URI
        return cls(client_id=client_id, client_secret=client_secret, redirect_uri=redirect)


def canva_configured() -> bool:
    try:
        CanvaConfig.from_env()
    except CanvaNotConfigured:
        return False
    return True


@dataclass(frozen=True)
class ConnectStart:
    url: str
    state: str
    code_verifier: str


@dataclass(frozen=True)
class SentToCanva:
    link: LinkRecord
    #: The edit URL with our correlation_state — where to send the user.
    open_url: str
    #: A video is in the user's Canva Uploads, not in the design: they drag it in.
    video_needs_drag: bool


class CanvaService:
    def __init__(
        self,
        *,
        config: CanvaConfig,
        repository: CanvaRepository,
        client: CanvaConnectClient,
        encryptor: Encryptor,
        store: MediaStore,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._config = config
        self._repo = repository
        self._client = client
        self._crypto = encryptor
        self._store = store
        self._now = now

    # -- connecting -----------------------------------------------------------------------

    def start_connect(self, *, state: str) -> ConnectStart:
        """Canva's consent URL. The caller keeps `state` and `code_verifier` server-side
        (the Reflex state's backend-only vars) and checks `state` on the way back."""
        pkce = new_pkce()
        url = authorize_url(
            client_id=self._config.client_id,
            redirect_uri=self._config.redirect_uri,
            state=state,
            code_challenge=pkce.challenge,
        )
        return ConnectStart(url=url, state=state, code_verifier=pkce.verifier)

    def finish_connect(
        self, *, tenant_id: UUID, user_id: UUID, code: str, code_verifier: str
    ) -> None:
        tokens = self._client.exchange_code(
            code=code, code_verifier=code_verifier, redirect_uri=self._config.redirect_uri
        )
        self._store_tokens(tenant_id, user_id, tokens)

    def is_connected(self, *, tenant_id: UUID, user_id: UUID) -> bool:
        return self._repo.get_account(tenant_id=tenant_id, user_id=user_id) is not None

    def disconnect(self, *, tenant_id: UUID, user_id: UUID) -> None:
        """Forget the tokens here. (Revoking the grant on Canva's side is the user's own
        "Connected apps" setting; Canva's revoke endpoint is not wired.)"""
        self._repo.delete_account(tenant_id=tenant_id, user_id=user_id)

    def _store_tokens(self, tenant_id: UUID, user_id: UUID, tokens: CanvaTokens) -> None:
        self._repo.save_account(
            AccountRecord(
                tenant_id=tenant_id,
                user_id=user_id,
                access_token_ciphertext=self._crypto.encrypt(tokens.access_token),
                refresh_token_ciphertext=self._crypto.encrypt(tokens.refresh_token),
                key_id=self._crypto.key_id,
                expires_at=tokens.expires_at,
                scope=tokens.scope,
            )
        )

    def _access_token(self, tenant_id: UUID, user_id: UUID) -> str:
        account = self._repo.get_account(tenant_id=tenant_id, user_id=user_id)
        if account is None:
            raise CanvaNotConnected("connect Canva first")
        if account.expires_at - _REFRESH_MARGIN > self._now():
            return self._crypto.decrypt(account.access_token_ciphertext, key_id=account.key_id)
        refresh = self._crypto.decrypt(account.refresh_token_ciphertext, key_id=account.key_id)
        try:
            tokens = self._client.refresh(refresh_token=refresh)
        except CanvaError as exc:
            # a spent or revoked refresh token: the user must connect again
            logger.info("canva refresh failed, forgetting the account: %s", exc)
            self._repo.delete_account(tenant_id=tenant_id, user_id=user_id)
            raise CanvaNotConnected("Canva connection expired; connect again") from exc
        # the refresh token is single-use: the new pair replaces the old one at once
        self._store_tokens(tenant_id, user_id, tokens)
        return tokens.access_token

    # -- sending --------------------------------------------------------------------------

    def send(self, *, tenant_id: UUID, user_id: UUID, draft_id: UUID) -> SentToCanva:
        """Send the draft's piece (its first stored file) to the user's Canva."""
        media = self._repo.draft_media(tenant_id=tenant_id, draft_id=draft_id)
        if not media:
            raise NothingToSend("the draft has no stored image or video yet")
        piece = media[0]
        token = self._access_token(tenant_id, user_id)
        is_video = piece.media_type == "video"
        data = self._store.read(piece.object_key)
        name = piece.object_key.rsplit("/", 1)[-1]
        asset_id = self._client.upload_asset(
            access_token=token, data=data, name=f"qualify-{name}", is_video=is_video
        )
        width, height = _size(piece)
        design = self._client.create_design(
            access_token=token,
            width=width,
            height=height,
            title=f"Qualify · {draft_id.hex[:8]}",
            # only an image can be placed by the API; a video waits in Uploads
            asset_id=None if is_video else asset_id,
        )
        correlation = new_correlation_state()
        link = self._repo.add_link(
            NewLink(
                tenant_id=tenant_id,
                draft_id=draft_id,
                created_by_user_id=user_id,
                source_object_key=piece.object_key,
                media_type="video" if is_video else "image",
                canva_design_id=design.id,
                correlation_state=correlation,
                edit_url=design.edit_url,
                design_updated_at=design.updated_at,
            )
        )
        return SentToCanva(
            link=link,
            open_url=with_correlation_state(design.edit_url, correlation),
            video_needs_drag=is_video,
        )

    def links(self, *, tenant_id: UUID, draft_id: UUID) -> list[LinkRecord]:
        return self._repo.links_for_draft(tenant_id=tenant_id, draft_id=draft_id)

    # -- coming back ----------------------------------------------------------------------

    def handle_return(self, *, tenant_id: UUID, user_id: UUID, correlation_jwt: str) -> LinkRecord:
        """Canva's return navigation: find our link, then bring the edit back."""
        try:
            claims = decode_correlation_jwt(correlation_jwt)
        except CanvaError as exc:
            raise UnknownReturn("the return carried no readable correlation") from exc
        correlation = str(claims.get("correlation_state") or "")
        link = (
            self._repo.link_by_correlation(tenant_id=tenant_id, correlation_state=correlation)
            if correlation
            else None
        )
        if link is None or link.created_by_user_id != user_id:
            raise UnknownReturn("this return matches no piece you sent to Canva")
        claimed_design = claims.get("design_id")
        if claimed_design and str(claimed_design) != link.canva_design_id:
            raise UnknownReturn("the return names another design")
        return self.pull(tenant_id=tenant_id, user_id=user_id, link_id=link.id)

    def pull(self, *, tenant_id: UUID, user_id: UUID, link_id: UUID) -> LinkRecord:
        """Export the design now and store it. Always re-exports: the user may have
        edited it again since the last pull."""
        link = self._repo.get_link(tenant_id=tenant_id, link_id=link_id)
        if link is None:
            raise UnknownReturn("no such piece sent to Canva")
        token = self._access_token(tenant_id, user_id)
        try:
            # re-read with the user's own token: proves they can open this design
            design: CanvaDesign = self._client.get_design(
                access_token=token, design_id=link.canva_design_id
            )
            source = self._source_size(tenant_id, link)
            if link.media_type == "video":
                urls = self._client.export_design(
                    access_token=token,
                    design_id=design.id,
                    file_type="mp4",
                    mp4_quality=mp4_quality_for(*source),
                )
                extension = "mp4"
            else:
                urls = self._client.export_design(
                    access_token=token, design_id=design.id, file_type="png"
                )
                extension = "png"
            data = self._client.download(urls[0])
        except CanvaError as exc:
            logger.warning("canva pull failed for link %s: %s", link_id, exc)
            return self._repo.mark_failed(tenant_id=tenant_id, link_id=link_id, error=str(exc))
        stamp = self._now().strftime("%Y%m%d%H%M%S")
        key = f"generated/{tenant_id}/{link.draft_id}/canva-{link.id.hex[:8]}-{stamp}.{extension}"
        self._store.write(key, data)
        return self._repo.mark_exported(
            tenant_id=tenant_id,
            link_id=link_id,
            object_key=key,
            design_updated_at=design.updated_at,
        )

    def _source_size(self, tenant_id: UUID, link: LinkRecord) -> tuple[int, int]:
        for ref in self._repo.draft_media(tenant_id=tenant_id, draft_id=link.draft_id):
            if ref.object_key == link.source_object_key:
                return _size(ref)
        return (1080, 1920)


def _size(ref: MediaRef) -> tuple[int, int]:
    """The piece's pixel size; a video with no recorded size is taken as 9:16 1080p."""
    if ref.width and ref.height:
        return ref.width, ref.height
    return (1080, 1920) if ref.media_type == "video" else (1080, 1350)
