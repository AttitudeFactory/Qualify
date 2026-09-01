"""The seam between the Dashboard de Menciones and the real `mentions` backend (QUA-49).

Same split `inbox_provider.py`/`publishing_provider.py` establish: a thin, in-process
projection over `qualify_api.mentions.composition`'s published read seam
(`list_mentions_for_tenant`) — no HTTP hop, same posture `http/app.py`'s own module
docstring documents for the Reflex CRM in general. This module owns exactly one thing:
turning a `MentionRecord` (a service shape) into a `MentionVM` (a display-ready
projection) — same division `inbox_provider.CandidateMedia`/`inbox_vm.py` already draw
between what a service returns and what a component renders.

**`brand` is the CONNECTED account's own username, not a third-party brand name.** The
Mentions dashboard's original synthetic data modeled multi-brand *competitive* listening
(scraped mentions of several brands); a real Instagram `mentions` webhook event is
intrinsically single-account — it fires because someone mentioned OUR connected account.
Reusing the same column lets the existing filter UI keep working (a tenant with more than
one connected Instagram account still gets a meaningful filter), but the semantics are
different, and only this module's own docstring is the place that says so.

**`views` is always "—".** Not a placeholder pending implementation — Meta's
`mentioned_media`/`mentioned_comment` nodes carry no view/play-count field for content the
connected account does not own, for any media type (`qualify_shared.social.ig_shapes.
MENTIONED_MEDIA_NO_VIEWS_CITATION`). Inventing a number here would be exactly the
fabrication QUA-49's audit ruled out. `likes` degrades the same way, per-row, whenever
`MentionRecord.like_count` is `None` (enrichment failed, or Meta itself omitted the field
— `mentioned_media.md`'s own note that owners who hide like counts get an omitted field).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from qualify_api.mentions.composition import list_mentions_for_tenant

from .inbox_provider import instagram_connections

NO_DATA = "—"


@dataclass(frozen=True)
class MentionVM:
    """Display-ready projection of one real mention — exactly the fields
    `components.mention_row` renders, nothing else. `sentiment` is the raw pipeline
    label (`"POS"`/`"NEG"`/`"NEU"`/`""`) — `ui.primitives.sentiment_badge` already
    matches this exact vocabulary (QUA-92), so no further translation belongs here.
    """

    id: str
    posted_at: str
    platform: str
    brand: str
    creator_handle: str
    caption: str
    sentiment: str
    views: str
    likes: str


def list_mentions(tenant_id: UUID) -> list[MentionVM]:
    """Blocking DB call (via `list_mentions_for_tenant`/`instagram_connections`) —
    callers on the event loop must run it off-thread, same convention every other
    provider function in this file's siblings (`inbox_provider.instagram_connections`)
    already establishes.
    """
    # A tenant can have more than one connected Instagram account; label each mention
    # with the one it actually belongs to rather than assuming a single connection.
    account_labels = {
        connection.id: connection.external_username or str(connection.id)
        for connection in instagram_connections(tenant_id)
    }

    rows: list[MentionVM] = []
    for record in list_mentions_for_tenant(tenant_id=tenant_id):
        content_text = record.caption or record.text
        posted_at = record.content_posted_at or record.received_at
        rows.append(
            MentionVM(
                id=str(record.id),
                posted_at=posted_at.strftime("%d %b %Y"),
                platform=record.platform,
                brand=account_labels.get(record.connection_id, record.external_account_id),
                creator_handle=(
                    f"@{record.author_username}" if record.author_username else NO_DATA
                ),
                caption=content_text if content_text else NO_DATA,
                sentiment=record.sentiment_label or "",
                views=NO_DATA,
                likes=str(record.like_count) if record.like_count is not None else NO_DATA,
            )
        )
    return rows
