"""`DashboardState`'s computed vars (QUA-49) — constructed directly with `.mentions`
pre-populated, same technique `test_inbox_state.py` uses for vars reachable without
`self.get_state(AuthState)` (which needs a live `EventContext` `load_mentions` itself
cannot get here — see that file's module docstring for the same pre-existing gap).
"""

from __future__ import annotations

from .mentions_provider import MentionVM
from .state import DashboardState, MentionRow

assert MentionRow is MentionVM  # the alias `state.py` documents, pinned structurally


def _row(
    *,
    brand: str = "qualifymkt.co",
    platform: str = "instagram",
    sentiment: str = "",
    caption: str = "hola @qualifymkt.co",
    creator_handle: str = "@someone",
) -> MentionRow:
    return MentionRow(
        id="1",
        posted_at="01 Ago 2026",
        platform=platform,
        brand=brand,
        creator_handle=creator_handle,
        caption=caption,
        sentiment=sentiment,
        views="—",
        likes="5",
    )


def test_total_mentions_counts_the_filtered_list() -> None:
    state = DashboardState()
    state.mentions = [_row(), _row()]

    assert state.total_mentions == 2


def test_positive_negative_neutral_counts_use_the_real_pipeline_labels() -> None:
    """Real mentions carry `"POS"`/`"NEG"`/`"NEU"` (or `""` for unanalyzed) — never the
    old synthetic `"positive"`/`"neutral"`/`"negative"` strings."""
    state = DashboardState()
    state.mentions = [
        _row(sentiment="POS"),
        _row(sentiment="POS"),
        _row(sentiment="NEU"),
        _row(sentiment="NEG"),
        _row(sentiment=""),  # not yet analyzed
    ]

    assert state.positive_count == 2
    assert state.neutral_count == 1
    assert state.negative_count == 1
    # An unanalyzed mention counts toward the total but no sentiment bucket — it must
    # never be silently folded into "neutral".
    assert state.total_mentions == 5
    assert state.positive_count + state.neutral_count + state.negative_count == 4


def test_brand_filter_scopes_to_one_connected_account() -> None:
    state = DashboardState()
    state.mentions = [_row(brand="qualifymkt.co"), _row(brand="other-brand.co")]
    state.brand_filter = "qualifymkt.co"

    assert [r.brand for r in state.filtered_mentions] == ["qualifymkt.co"]


def test_sentiment_filter_matches_the_raw_label() -> None:
    state = DashboardState()
    state.mentions = [_row(sentiment="POS"), _row(sentiment="NEG")]
    state.sentiment_filter = "NEG"

    assert len(state.filtered_mentions) == 1
    assert state.filtered_mentions[0].sentiment == "NEG"

    state.sentiment_filter = "Todos"
    assert len(state.filtered_mentions) == 2


def test_search_query_matches_caption_or_creator() -> None:
    state = DashboardState()
    state.mentions = [
        _row(caption="excelente servicio", creator_handle="@ana"),
        _row(caption="no me gustó", creator_handle="@bruno"),
    ]
    state.search_query = "ana"

    assert [r.creator_handle for r in state.filtered_mentions] == ["@ana"]


def test_brand_options_are_derived_from_the_loaded_mentions() -> None:
    state = DashboardState()
    state.mentions = [_row(brand="b1"), _row(brand="b2")]

    assert state.brand_options == ["Todas", "b1", "b2"]


def test_show_empty_state_is_true_only_once_loaded_clean_with_zero_rows() -> None:
    """The three-way split `mentions_body` renders on: loading and an error both
    suppress the empty state even with zero rows, so a load-in-progress or a failed load
    never flashes "Aún no hay menciones" before the real reason is known."""
    state = DashboardState()

    # Default/initial state: not loading, no error, no rows yet.
    assert state.show_empty_state is True

    state.is_loading_mentions = True
    assert state.show_empty_state is False

    state.is_loading_mentions = False
    state.mentions_error = "No se pudieron cargar las menciones."
    assert state.show_empty_state is False

    state.mentions_error = ""
    state.mentions = [_row()]
    assert state.show_empty_state is False

    state.mentions = []
    assert state.show_empty_state is True
