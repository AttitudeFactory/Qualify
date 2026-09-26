"""The shared hashtag catalog (migration 0023): what hashtags mean each rubro, learned
from the referentes searches themselves. Public data, shared across tenants on purpose —
see the migration's docstring. The search algorithm (`Qualify/creator_discovery.py`) knows
nothing about this package; `Qualify/hashtag_catalog.py` is the bridge."""

from qualify_api.hashtags.repository import (
    CLASSIFIERS,
    DEFAULT_KINDS,
    DEFAULT_MIN_SIMILARITY,
    KINDS,
    MATCH_FUZZY_TAG,
    MATCH_FUZZY_TERM,
    MATCH_TERM,
    MIN_TERM_LENGTH,
    SOURCES,
    Classification,
    HashtagRepository,
    MemoryHashtagRepository,
    NewHashtag,
    NewTermLink,
    PostgresHashtagRepository,
    ResolvedHashtag,
    StoredHashtag,
    fold,
    normalize_tag,
)

__all__ = [
    "CLASSIFIERS",
    "DEFAULT_KINDS",
    "DEFAULT_MIN_SIMILARITY",
    "KINDS",
    "MATCH_FUZZY_TAG",
    "MATCH_FUZZY_TERM",
    "MATCH_TERM",
    "MIN_TERM_LENGTH",
    "SOURCES",
    "Classification",
    "HashtagRepository",
    "MemoryHashtagRepository",
    "NewHashtag",
    "NewTermLink",
    "PostgresHashtagRepository",
    "ResolvedHashtag",
    "StoredHashtag",
    "fold",
    "normalize_tag",
]
