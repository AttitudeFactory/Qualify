"""View-models for the Stories screens (QUA-106). Same custody rules as
`publishing_vm.py`/`replies_provider.py`'s `DraftVM`: every Reflex var serializes to
the client, and `StoryProposalService` never sees or returns a token to begin with, so
there is nothing credential-bearing to keep off these dataclasses in the first place.

Kept free of Reflex and network imports so a whitelist-style test can assert this
stays true as the module grows, same convention `publishing_vm.py`/`creative_vm.py`
already follow.
"""

from __future__ import annotations

from dataclasses import dataclass

#: `story_proposals.status` value -> operator-facing label. Every value the CHECK
#: constraint (migration 0021) allows has an entry.
STATUS_LABELS: dict[str, str] = {
    "proposed": "Pendiente de revisión",
    "approved": "Aprobada",
    "edited": "Aprobada (editada)",
    "rejected": "Rechazada",
    "publishing": "Publicando",
    "published": "Publicada",
    "publish_failed": "Falló la publicación",
}

#: Radix color scheme for the badge. Never color alone — the label above always ships
#: with it (docs/design-system.md §5).
STATUS_TONES: dict[str, str] = {
    "proposed": "amber",
    "approved": "grass",
    "edited": "grass",
    "rejected": "gray",
    "publishing": "blue",
    "published": "grass",
    "publish_failed": "tomato",
}

_UNKNOWN_TONE = "gray"


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def status_tone(status: str) -> str:
    return STATUS_TONES.get(status, _UNKNOWN_TONE)


def _duration_label(duration_ms: int | None) -> str:
    if not duration_ms or duration_ms <= 0:
        return ""
    total_seconds = duration_ms // 1000
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}"


@dataclass(frozen=True)
class TrendAudioOptionVM:
    """One audio Meta suggests as 'trending' — a REFERENCE for the human, never a
    value sent to Meta's publish call in this slice (QUA-106 decision). `display_label`
    is computed once in `build_trend_audio_vm`, same "no property on a VM" convention
    `StoryProposalVM` documents."""

    audio_id: str
    title: str
    artist_or_creator: str
    duration_label: str
    rank: int
    display_label: str = ""


@dataclass(frozen=True)
class StoryProposalVM:
    """Display-ready projection of a `ProposalRecord` — used by BOTH the `/stories`
    list rows and the `/stories/[proposal_id]` detail screen.

    The boolean fields below are computed ONCE, in `build_proposal_vm`, never as a
    `@property` — same convention `creative_vm.DraftVM` (`can_approve`, `is_drafting`,
    `is_failed`) already establishes, because a Reflex Var wraps concrete field values,
    not a Python property getter evaluated per access."""

    id: str
    connection_id: str
    caption: str
    trend_audio_id: str
    trend_audio_title: str
    status: str
    status_label: str
    status_tone: str
    publish_error_code: str
    created_label: str
    can_decide: bool = False
    can_publish: bool = False
    is_publishing: bool = False
    is_terminal: bool = False
    has_trend_audio: bool = False


def build_trend_audio_vm(
    *,
    audio_id: str,
    title: str,
    artist_or_creator: str,
    duration_ms: int | None,
    rank: int,
) -> TrendAudioOptionVM:
    duration_label = _duration_label(duration_ms)
    parts = [title]
    if artist_or_creator:
        parts.append(f"· {artist_or_creator}")
    if duration_label:
        parts.append(f"({duration_label})")
    return TrendAudioOptionVM(
        audio_id=audio_id,
        title=title,
        artist_or_creator=artist_or_creator,
        duration_label=duration_label,
        rank=rank,
        display_label=" ".join(parts),
    )


def build_proposal_vm(
    *,
    id: str,  # noqa: A002 — matches the record's own field name, not shadowing a call site
    connection_id: str,
    caption: str,
    trend_audio_id: str,
    trend_audio_title: str,
    status: str,
    publish_error_code: str,
    created_label: str,
) -> StoryProposalVM:
    return StoryProposalVM(
        id=id,
        connection_id=connection_id,
        caption=caption,
        trend_audio_id=trend_audio_id,
        trend_audio_title=trend_audio_title,
        status=status,
        status_label=status_label(status),
        status_tone=status_tone(status),
        publish_error_code=publish_error_code,
        created_label=created_label,
        can_decide=status == "proposed",
        can_publish=status in ("approved", "edited"),
        is_publishing=status == "publishing",
        is_terminal=status in ("rejected", "published", "publish_failed"),
        has_trend_audio=bool(trend_audio_id),
    )
