"""Persistence for the Brand Kit's referentes search (migration 0018).

Stores what `Qualify/creator_discovery.py`'s phased search found for a brand (one row per
phase, stamped with the algorithm version and the seed it ran on) and the operator's
referente/competencia/detractor sort over it. This package knows nothing about the
vendor or the algorithm — it stores what it is given and answers "is there a result
computed by THIS algorithm version for THIS seed?", which is what lets an improved
algorithm recompute stored results (`stale_phases`).
"""

from qualify_api.referentes.repository import (
    LABELS,
    ORIGIN_PROFILE,
    AccountLabel,
    MemoryReferentesRepository,
    NewDiscoveredAccount,
    NewDiscoveryPhase,
    PostgresReferentesRepository,
    ReferentesRepository,
    StoredDiscoveredAccount,
    StoredDiscoveryPhase,
    normalize_handle,
    validate_seed,
)

__all__ = [
    "LABELS",
    "ORIGIN_PROFILE",
    "AccountLabel",
    "MemoryReferentesRepository",
    "NewDiscoveredAccount",
    "NewDiscoveryPhase",
    "PostgresReferentesRepository",
    "ReferentesRepository",
    "StoredDiscoveredAccount",
    "StoredDiscoveryPhase",
    "normalize_handle",
    "validate_seed",
]
