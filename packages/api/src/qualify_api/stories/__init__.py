"""Instagram Story proposals with mandatory human approval (QUA-106, first slice).

Pipeline: operator uploads media (`stage_and_propose_story`, the ONLY media source in
this v1 — no AI generation, no third-party reuse) -> optional trending-audio reference
(`suggest_trend_audio`, Meta's `GET /ig_audio`, informational only) -> human decision
(`approved`/`edited`/`rejected`) -> `publish_proposal` (delegates to the EXISTING
`qualify_api.publishing.PublishService`, `media_product_type=STORIES`) -> `refresh_
proposal` mirrors that attempt's eventual `published`/`failed` verdict back onto the
proposal.

Explicitly out of this module (QUA-106 decision, revisit only with a new ticket):
autonomous publish, any scheduler/cron, `audio_configuration` (the suggested audio is
shown, never attached to the real Meta call), Scrape Creators, AI-generated visual
media.
"""

from qualify_api.stories.composition import (
    decide_proposal,
    get_proposal,
    list_proposals,
    production_story_proposal_service,
    publish_proposal,
    refresh_proposal,
    stage_and_propose_story,
    suggest_trend_audio,
)
from qualify_api.stories.repository import (
    DECISIONS,
    MemoryStoryProposalRepository,
    PostgresStoryProposalRepository,
    ProposalRecord,
    StoryProposalRepository,
    UnknownProposal,
)
from qualify_api.stories.service import StoryProposalService
from qualify_api.stories.trend_audio_client import (
    AUDIO_TYPE_MUSIC,
    AUDIO_TYPE_ORIGINAL_SOUND,
    TrendAudioError,
    TrendAudioOption,
)

__all__ = [
    "AUDIO_TYPE_MUSIC",
    "AUDIO_TYPE_ORIGINAL_SOUND",
    "DECISIONS",
    "MemoryStoryProposalRepository",
    "PostgresStoryProposalRepository",
    "ProposalRecord",
    "StoryProposalRepository",
    "StoryProposalService",
    "TrendAudioError",
    "TrendAudioOption",
    "UnknownProposal",
    "decide_proposal",
    "get_proposal",
    "list_proposals",
    "production_story_proposal_service",
    "publish_proposal",
    "refresh_proposal",
    "stage_and_propose_story",
    "suggest_trend_audio",
]
