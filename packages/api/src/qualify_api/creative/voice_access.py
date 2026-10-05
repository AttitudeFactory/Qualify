"""Which HeyGen voices a brand may render with (§ request 2026-10-05: "cierra esa
vulnerabilidad porque otro usuario / marca pueda usar la voz clonada de otro
usuario/marca").

Every brand's voice clone lives in the ONE HeyGen account Qualify renders with
(`QUALIFY_HEYGEN_API_KEY`), so HeyGen itself would happily render brand A's script in
brand B's cloned voice: the isolation between tenants is Qualify's to enforce, and until
this module the `voice_id` a render asked for travelled to HeyGen unchecked — the /create
picker only ever offers the right voices, but a picker is not a boundary.

The rule, applied where the render is built (`MediaProducer._video`):

- the brand's OWN clone (`brand_voice_clones`, read through the tenant's RLS session) is
  allowed, and
- so is any voice of HeyGen's PUBLIC catalog as the picker lists it — Spanish, both
  genders, `type="public"` (the same `list_voices` calls `build_heygen_catalog` makes, so
  nothing the picker offers is ever refused);
- anything else — another brand's clone above all, but also a voice id made up by hand —
  is refused BEFORE anything is uploaded or rendered, as a policy failure
  (`FailureReason.ROUTE_BLOCKED_BY_POLICY`), so nothing is spent on it.

The public catalog is cached in-process for `PUBLIC_TTL_SECONDS`; the clone is read per
render (it changes when the operator re-clones, and the read is one indexed row).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol
from uuid import UUID

logger = logging.getLogger(__name__)

#: HeyGen's language name for the voices the scripts are written in.
PUBLIC_LANGUAGE = "Spanish"
PUBLIC_GENDERS = ("female", "male")
#: Per gender — the same page size the /create picker reads (`creative_provider.
#: _CATALOG_LIMIT`), so the allowed set and the offered set are the same set.
PUBLIC_LIMIT = 50
PUBLIC_TTL_SECONDS = 3600


class VoiceGuard(Protocol):
    """`True` when `voice_id` may be rendered for this brand with this HeyGen key."""

    def __call__(self, *, tenant_id: UUID, brand_id: UUID, voice_id: str, api_key: str) -> bool: ...


CloneLookup = Callable[[UUID, UUID], str | None]
"""(tenant_id, brand_id) → the brand's own clone's HeyGen voice id, or None."""


def _db_clone_lookup(tenant_id: UUID, brand_id: UUID) -> str | None:
    from .voice_clone import VoiceCloneService  # noqa: PLC0415 — keeps the DB out of tests

    clone = VoiceCloneService().current(tenant_id=tenant_id, brand_id=brand_id)
    return None if clone is None else clone.heygen_voice_id


def public_voice_ids(adapter: Any, api_key: str) -> frozenset[str]:
    """The ids of HeyGen's public Spanish voices, as the picker lists them."""
    ids: set[str] = set()
    for gender in PUBLIC_GENDERS:
        for voice in adapter.list_voices(
            api_key=api_key,
            voice_type="public",
            language=PUBLIC_LANGUAGE,
            gender=gender,
            limit=PUBLIC_LIMIT,
        ):
            voice_id = voice.get("voice_id") if isinstance(voice, dict) else None
            if voice_id:
                ids.add(str(voice_id))
    return frozenset(ids)


class BrandVoiceGuard:
    """The production `VoiceGuard`: the brand's own clone, or a public voice."""

    def __init__(
        self,
        adapter: Any,
        *,
        clone_lookup: CloneLookup = _db_clone_lookup,
        ttl_seconds: float = PUBLIC_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._adapter = adapter
        self._clone_lookup = clone_lookup
        self._ttl = ttl_seconds
        self._clock = clock
        self._public: tuple[float, frozenset[str]] | None = None
        self._lock = threading.Lock()

    def _public_ids(self, api_key: str) -> frozenset[str]:
        with self._lock:
            cached = self._public
            if cached is not None and self._clock() - cached[0] < self._ttl:
                return cached[1]
        ids = public_voice_ids(self._adapter, api_key)
        with self._lock:
            self._public = (self._clock(), ids)
        return ids

    def __call__(self, *, tenant_id: UUID, brand_id: UUID, voice_id: str, api_key: str) -> bool:
        if not voice_id:
            return False
        own = self._clone_lookup(tenant_id, brand_id)
        if own is not None and voice_id == own:
            return True
        allowed = voice_id in self._public_ids(api_key)
        if not allowed:
            # the id, not the brand: enough to find the attempt, nothing to leak
            logger.warning(
                "voice %s refused for brand %s: not public, not its clone", voice_id, brand_id
            )
        return allowed
