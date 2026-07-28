from dataclasses import dataclass

import reflex as rx
from sqlmodel import select

from .db import get_session
from .models import Mention
from .seed_data import seed_if_empty


@dataclass
class MentionRow:
    """Display-ready projection of a Mention row for the frontend."""

    id: int
    brand: str
    platform: str
    creator_handle: str
    caption: str
    post_url: str
    posted_at: str
    views: int
    likes: int
    comments_count: int
    shares: int
    sentiment: str


class DashboardState(rx.State):
    """State for the mentions dashboard."""

    mentions: list[MentionRow] = []

    brand_filter: str = "Todas"
    platform_filter: str = "Todas"
    sentiment_filter: str = "Todos"
    search_query: str = ""

    @rx.event
    def load_mentions(self) -> None:
        seed_if_empty()
        with get_session() as session:
            rows = session.exec(select(Mention).order_by(Mention.posted_at.desc())).all()
        self.mentions = [
            MentionRow(
                id=m.id,
                brand=m.brand,
                platform=m.platform,
                creator_handle=m.creator_handle,
                caption=m.caption,
                post_url=m.post_url,
                posted_at=m.posted_at.strftime("%d %b %Y"),
                views=m.views,
                likes=m.likes,
                comments_count=m.comments_count,
                shares=m.shares,
                sentiment=m.sentiment,
            )
            for m in rows
        ]

    @rx.var
    def brand_options(self) -> list[str]:
        return ["Todas"] + sorted({m.brand for m in self.mentions})

    @rx.var
    def platform_options(self) -> list[str]:
        return ["Todas"] + sorted({m.platform for m in self.mentions})

    @rx.var
    def filtered_mentions(self) -> list[MentionRow]:
        rows = self.mentions
        if self.brand_filter != "Todas":
            rows = [r for r in rows if r.brand == self.brand_filter]
        if self.platform_filter != "Todas":
            rows = [r for r in rows if r.platform == self.platform_filter]
        if self.sentiment_filter != "Todos":
            rows = [r for r in rows if r.sentiment == self.sentiment_filter]
        if self.search_query:
            query = self.search_query.lower()
            rows = [
                r for r in rows if query in r.caption.lower() or query in r.creator_handle.lower()
            ]
        return rows

    @rx.var
    def total_mentions(self) -> int:
        return len(self.filtered_mentions)

    @rx.var
    def positive_count(self) -> int:
        return sum(1 for r in self.filtered_mentions if r.sentiment == "positive")

    @rx.var
    def neutral_count(self) -> int:
        return sum(1 for r in self.filtered_mentions if r.sentiment == "neutral")

    @rx.var
    def negative_count(self) -> int:
        return sum(1 for r in self.filtered_mentions if r.sentiment == "negative")

    @rx.event
    def set_brand_filter(self, value: str) -> None:
        self.brand_filter = value

    @rx.event
    def set_platform_filter(self, value: str) -> None:
        self.platform_filter = value

    @rx.event
    def set_sentiment_filter(self, value: str) -> None:
        self.sentiment_filter = value

    @rx.event
    def set_search_query(self, value: str) -> None:
        self.search_query = value
