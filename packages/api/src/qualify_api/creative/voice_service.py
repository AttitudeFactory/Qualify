"""Voice profile lifecycle, S1 scope: manual kit only (MC-05 reduced; design §4.4).

S1 builds the PROPOSED profile **deterministically from the brand kit** — no model call,
no network. LLM distillation from owned media / public web (design §4.4 `distill`, the
`InsufficientEvidence` path, `paid_by=PLATFORM` spend) is a later story; when it lands
it becomes another producer of PROPOSED rows and everything below it (approve, the
single-ACTIVE invariant, `active_profile`) stays exactly as written here.

Lifecycle (`VoiceProfileStatus`): PROPOSED → ACTIVE → SUPERSEDED. The invariant this
module owns is **at most one ACTIVE profile per brand**, enforced inside a single
transaction in `approve` — the supersede of the old ACTIVE and the promotion of the new
one either both happen or neither does.

The JSONB `profile` column stores only the distilled voice fields (`tone_axes`,
`lexicon`, `avoid_lexicon`, `sentence_rhythm`, `signature_moves`); identity, version,
status and provenance live in real columns so the DB can enforce and index them.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import UUID

from qualify_creative.enums import VoiceProfileStatus, VoiceSourceKind
from qualify_creative.schemas import BrandKit, BrandVoiceProfile, ToneAxes, VoiceSource
from qualify_shared.db.session import tenant_session
from sqlalchemy import func, select

from qualify_api.creative.brand_service import kit_from_row
from qualify_api.creative.models import BrandKit as BrandKitRow
from qualify_api.creative.models import BrandVoiceProfile as VoiceProfileRow


class UnknownBrandKit(Exception):
    """The brand has no kit row, so there is nothing to propose a voice from."""


class UnknownVersion(Exception):
    """No profile row exists for this (brand, version)."""


class NotProposed(Exception):
    """The version exists but is not in PROPOSED — approving it again (or approving a
    superseded one) would rewrite history instead of advancing it."""


# Words worth carrying from the do-examples into the lexicon: 4+ letters, so the
# articles and prepositions of a Spanish caption fall out without a stopword list.
_TOKEN = re.compile(r"\w{4,}", re.UNICODE)


def _lexicon_from_kit(kit: BrandKit) -> tuple[str, ...]:
    """Deterministic lexicon: the CTA patterns verbatim (the whole phrase is the brand
    move), then tokens mined from the do-examples, lowercased, deduplicated in first-
    appearance order. Same kit → same tuple, always."""
    lexicon: list[str] = []
    seen: set[str] = set()
    for pattern in kit.cta_patterns:
        key = pattern.casefold()
        if key not in seen:
            seen.add(key)
            lexicon.append(pattern)
    for example in kit.do_examples:
        for token in _TOKEN.findall(example):
            word = token.casefold()
            if not word.isdigit() and word not in seen:
                seen.add(word)
                lexicon.append(word)
    return tuple(lexicon)


def _profile_from_row(row: VoiceProfileRow) -> BrandVoiceProfile:
    profile = row.profile or {}
    return BrandVoiceProfile(
        brand_id=row.brand_id,
        version=row.version,
        status=VoiceProfileStatus(row.status),
        tone_axes=ToneAxes.model_validate(profile["tone_axes"]),
        lexicon=tuple(profile.get("lexicon", ())),
        avoid_lexicon=tuple(profile.get("avoid_lexicon", ())),
        sentence_rhythm=profile.get("sentence_rhythm", ""),
        signature_moves=tuple(profile.get("signature_moves", ())),
        sources=tuple(VoiceSource.model_validate(source) for source in row.sources or ()),
        distilled_by_model=row.distilled_by_model or "",
        distilled_at=row.distilled_at,
    )


def _kit_profile(kit: BrandKit) -> dict:
    """The distilled voice fields S1 derives from the kit — the JSONB `profile`."""
    return {
        "tone_axes": kit.tone_axes.model_dump(),
        "lexicon": list(_lexicon_from_kit(kit)),
        "avoid_lexicon": list(kit.banned_words),
        "sentence_rhythm": "",
        "signature_moves": [],
    }


def _kit_sources(kit: BrandKit) -> list[dict]:
    """Provenance (§4.4): S1 reads exactly one source — the manual kit."""
    return [
        {
            "kind": VoiceSourceKind.MANUAL_KIT.value,
            "ref": "brand_kit",
            "excerpt": kit.positioning,
        }
    ]


def _kit_only(sources: object) -> bool:
    """Whether a stored profile came from the kit alone (so a kit save may replace it)."""
    items = list(sources or ()) if isinstance(sources, list | tuple) else []
    return all(
        isinstance(item, dict) and item.get("kind") == VoiceSourceKind.MANUAL_KIT.value
        for item in items
    )


class VoiceProfileService:
    def propose_from_kit(self, *, tenant_id: UUID, brand_id: UUID, user_id: UUID) -> int:
        """Create the next PROPOSED profile from the brand kit; returns its version.

        Raises `UnknownBrandKit` when the brand has no kit. `user_id` is the §4.4
        contract (mutations name their actor); the row records authorship only at
        approval, because a proposal is machine output — S1's "model" is the kit copy.
        """
        with tenant_session(tenant_id) as session:
            kit_row = session.scalar(select(BrandKitRow).where(BrandKitRow.brand_id == brand_id))
            if kit_row is None:
                raise UnknownBrandKit(f"brand {brand_id} has no brand kit")
            kit = kit_from_row(kit_row)
            latest = session.scalar(
                select(func.max(VoiceProfileRow.version)).where(
                    VoiceProfileRow.brand_id == brand_id
                )
            )
            version = (latest or 0) + 1
            session.add(
                VoiceProfileRow(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    version=version,
                    status=VoiceProfileStatus.PROPOSED.value,
                    profile=_kit_profile(kit),
                    sources=_kit_sources(kit),
                )
            )
            session.flush()
            return version

    def adopt_from_kit(self, *, tenant_id: UUID, brand_id: UUID, user_id: UUID) -> int:
        """Saving the kit IS the approval (founder, 2026-09-30: "no quiero aprobación").

        While the voice is a deterministic function of the kit (S1: one `MANUAL_KIT`
        source, no model), the person saving the kit wrote every field it is made of and
        reviewed them on ¿Todo correcto? — a second "Aprobar" click adds nothing, and a
        voice left behind by a later kit edit puts two different tone targets in every
        prompt. So: when the kit's voice fields changed, the next version is created
        straight as ACTIVE, the previous one SUPERSEDED, and whoever saved is recorded as
        approver. Same kit → nothing is written; the current version comes back.

        Never replaces a voice distilled from other sources (owned media, public web —
        a model's inference a person approved through `approve`): that one stays ACTIVE
        and its version comes back. The single-ACTIVE invariant is also a database fact
        (0032's partial unique index), so two racing saves cannot both win.
        Raises `UnknownBrandKit` when the brand has no kit."""
        now = datetime.now(UTC)
        with tenant_session(tenant_id) as session:
            kit_row = session.scalar(select(BrandKitRow).where(BrandKitRow.brand_id == brand_id))
            if kit_row is None:
                raise UnknownBrandKit(f"brand {brand_id} has no brand kit")
            kit = kit_from_row(kit_row)
            profile, sources = _kit_profile(kit), _kit_sources(kit)
            actives = session.scalars(
                select(VoiceProfileRow)
                .where(
                    VoiceProfileRow.brand_id == brand_id,
                    VoiceProfileRow.status == VoiceProfileStatus.ACTIVE.value,
                )
                .with_for_update()
            ).all()
            for current in actives:
                if not _kit_only(current.sources):
                    return current.version
                if current.profile == profile and list(current.sources or ()) == sources:
                    return current.version
            latest = session.scalar(
                select(func.max(VoiceProfileRow.version)).where(
                    VoiceProfileRow.brand_id == brand_id
                )
            )
            for previous in actives:
                previous.status = VoiceProfileStatus.SUPERSEDED.value
                previous.updated_at = now
            # the old ACTIVE must be gone before the new one exists (partial unique index)
            session.flush()
            version = (latest or 0) + 1
            session.add(
                VoiceProfileRow(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    version=version,
                    status=VoiceProfileStatus.ACTIVE.value,
                    profile=profile,
                    sources=sources,
                    approved_by=user_id,
                    approved_at=now,
                )
            )
            session.flush()
            return version

    def approve(self, *, tenant_id: UUID, brand_id: UUID, version: int, user_id: UUID) -> None:
        """Promote a PROPOSED version to ACTIVE; any previous ACTIVE becomes SUPERSEDED.

        One transaction: the single-ACTIVE invariant is never observable as violated,
        even by a concurrent reader between the two writes.
        """
        now = datetime.now(UTC)
        with tenant_session(tenant_id) as session:
            row = session.scalar(
                select(VoiceProfileRow).where(
                    VoiceProfileRow.brand_id == brand_id,
                    VoiceProfileRow.version == version,
                )
            )
            if row is None:
                raise UnknownVersion(f"brand {brand_id} has no voice profile v{version}")
            if row.status != VoiceProfileStatus.PROPOSED.value:
                raise NotProposed(f"voice profile v{version} is {row.status}, not proposed")
            previous_actives = session.scalars(
                select(VoiceProfileRow).where(
                    VoiceProfileRow.brand_id == brand_id,
                    VoiceProfileRow.status == VoiceProfileStatus.ACTIVE.value,
                )
            ).all()
            for previous in previous_actives:
                previous.status = VoiceProfileStatus.SUPERSEDED.value
                previous.updated_at = now
            # the old ACTIVE must be gone before the new one is promoted: 0032's partial
            # unique index checks each UPDATE, and one flush may order them either way
            session.flush()
            row.status = VoiceProfileStatus.ACTIVE.value
            row.approved_by = user_id
            row.approved_at = now
            row.updated_at = now
            session.flush()

    def active_profile(self, *, tenant_id: UUID, brand_id: UUID) -> BrandVoiceProfile | None:
        """The brand's ACTIVE profile rehydrated, or None when nothing is approved yet."""
        with tenant_session(tenant_id) as session:
            row = session.scalar(
                select(VoiceProfileRow).where(
                    VoiceProfileRow.brand_id == brand_id,
                    VoiceProfileRow.status == VoiceProfileStatus.ACTIVE.value,
                )
            )
            if row is None:
                return None
            return _profile_from_row(row)
