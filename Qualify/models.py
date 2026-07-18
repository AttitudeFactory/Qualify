"""Persisted data model for the mentions dashboard MVP.

Field names mirror the planned ClickHouse `ingestion.posts` / `search.content_index`
schema (see docs/plan-ingesta-social.md) so this local SQLite mock stays close to
the real shape once the ingestion pipeline lands.
"""

from datetime import datetime

from sqlmodel import Field, SQLModel


class Mention(SQLModel, table=True):
    """A single scraped TikTok/IG mention of a brand."""

    id: int | None = Field(default=None, primary_key=True)
    brand: str
    platform: str  # "tiktok" | "instagram"
    post_id: str
    creator_handle: str
    post_url: str
    caption: str
    posted_at: datetime
    views: int = 0
    likes: int = 0
    comments_count: int = 0
    shares: int = 0
    sentiment: str  # "positive" | "neutral" | "negative"
