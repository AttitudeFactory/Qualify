"""Persistence for referentes (migration 0020): discovery phases, the accounts each one
found, and the operator's labels. Same two-implementation discipline as
`mentions/repository.py` — `MemoryReferentesRepository` is real code that mirrors the
database's invariants, and one contract suite runs against both.

Three rules the callers can rely on:

- **A result is only reused by the algorithm that computed it.** `find_phase` matches on
  `(seed_signature, algorithm_version)`; a phase computed by an older algorithm is never
  returned as a hit. `stale_phases` lists the current phases an older algorithm computed,
  which is what a recompute walks.
- **Nothing a phase stored is ever edited.** `save_phase` inserts the new phase and stamps
  the previous current one `superseded_at` in the same transaction, so there is always at
  most one current phase per (brand, phase_key) and the old answer stays comparable.
- **Labels belong to the account, not to a phase.** A recompute that drops or re-ranks an
  account never touches what the operator decided about it.

The repository validates what the database cannot express: the seed's shape (hashtags
carry their origin) and that the brand belongs to the tenant writing for it (the FK to
`brands` alone would accept another tenant's brand id).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from qualify_shared.db.session import tenant_session
from sqlalchemy import delete, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from qualify_api.referentes.models import (
    BrandAccountLabel,
    BrandDiscoveredAccount,
    BrandDiscoveryPhase,
)
from qualify_api.tenancy.models import Brand

LABELS = ("referente", "competencia", "detractor")

#: Where a seed hashtag came from: `profile` (the brand's own most-used hashtags),
#: `catalog` (the shared hashtag catalog resolved the operator's rubro to it, migration
#: 0023) or `ai` (a catalog hashtag Claude chose for this brand — stored with the
#: `model`, `fit` and `reason` it gave, the provenance a model decision must carry) or
#: `operator` (a pill the operator kept or typed on Tu rubro y ubicación — with
#: `suggested_by`/`reason` when Claude suggested it).
ORIGIN_PROFILE = "profile"
ORIGIN_CATALOG = "catalog"
ORIGIN_AI = "ai"
ORIGIN_OPERATOR = "operator"

DEFAULT_SOURCE = "scrapecreators"


def normalize_handle(handle: str) -> str:
    """The one spelling an account is stored under: trimmed, no leading "@", lowercase.
    Matches migration 0020's CHECK, so a value that passed here cannot be rejected there."""
    cleaned = handle.strip().lstrip("@").strip().lower()
    if not cleaned:
        raise ValueError("handle is empty")
    return cleaned


def _normalize_network(network: str) -> str:
    cleaned = network.strip().lower()
    if not cleaned:
        raise ValueError("network is empty")
    return cleaned


def validate_seed(seed: object) -> dict[str, Any]:
    """The seed a phase ran on must be a JSON object whose `hashtags` (when present) are
    `{"tag", "origin"}` objects — the origin is what lets a recompute tell a hashtag the
    profile gave from one a hashtag discovery gave. Returns a JSON round-tripped copy, so
    the caller's dict is never aliased into a stored row."""
    if not isinstance(seed, Mapping):
        raise ValueError("seed must be an object")
    hashtags = seed.get("hashtags", [])
    if not isinstance(hashtags, list):
        raise ValueError("seed.hashtags must be a list")
    for item in hashtags:
        if not isinstance(item, Mapping):
            raise ValueError('seed.hashtags items must be {"tag", "origin"} objects')
        for key in ("tag", "origin"):
            value = item.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"seed hashtag is missing its {key}")
    try:
        return json.loads(json.dumps(seed, ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"seed is not JSON-serializable: {exc}") from exc


def _validate_label(label: str) -> str:
    if label not in LABELS:
        raise ValueError(f"label must be one of {LABELS}, got {label!r}")
    return label


# --------------------------------------------------------------------------------------
# write inputs / read projections
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class NewDiscoveredAccount:
    network: str
    handle: str
    #: The card exactly as the wizard renders it.
    card: Mapping[str, Any]
    full_name: str = ""
    followers: int | None = None
    profile_url: str = ""
    avatar_url: str = ""
    #: Which searches surfaced the account (`Candidate.sources`).
    found_by: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "network", _normalize_network(self.network))
        object.__setattr__(self, "handle", normalize_handle(self.handle))
        object.__setattr__(self, "found_by", tuple(self.found_by))


@dataclass(frozen=True)
class NewDiscoveryPhase:
    tenant_id: UUID
    brand_id: UUID
    phase_key: str
    algorithm_version: int
    seed_signature: str
    seed: Mapping[str, Any]
    title: str = ""
    note: str = ""
    queries: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    credits: int = 0
    #: In rank order — position 0 is the first card shown.
    accounts: tuple[NewDiscoveredAccount, ...] = ()
    source: str = DEFAULT_SOURCE

    def __post_init__(self) -> None:
        if not self.phase_key.strip():
            raise ValueError("phase_key is empty")
        if self.algorithm_version <= 0:
            raise ValueError("algorithm_version must be positive")
        if self.credits < 0:
            raise ValueError("credits cannot be negative")
        object.__setattr__(self, "seed", validate_seed(self.seed))
        object.__setattr__(self, "queries", tuple(self.queries))
        object.__setattr__(self, "errors", tuple(self.errors))
        object.__setattr__(self, "accounts", tuple(self.accounts))
        keys = [(a.network, a.handle) for a in self.accounts]
        if len(keys) != len(set(keys)):
            raise ValueError("the same account appears twice in one phase")


@dataclass(frozen=True)
class StoredDiscoveredAccount:
    rank: int
    network: str
    handle: str
    full_name: str
    followers: int | None
    profile_url: str
    avatar_url: str
    card: dict[str, Any]
    found_by: tuple[str, ...]


@dataclass(frozen=True)
class StoredDiscoveryPhase:
    id: UUID
    tenant_id: UUID
    brand_id: UUID
    phase_key: str
    algorithm_version: int
    seed_signature: str
    seed: dict[str, Any]
    title: str
    note: str
    queries: tuple[str, ...]
    errors: tuple[str, ...]
    credits: int
    source: str
    computed_at: datetime
    superseded_at: datetime | None
    accounts: tuple[StoredDiscoveredAccount, ...] = field(default=())

    @property
    def is_current(self) -> bool:
        return self.superseded_at is None


@dataclass(frozen=True)
class AccountLabel:
    network: str
    handle: str
    label: str
    labeled_by: UUID | None
    labeled_at: datetime
    #: Influence order inside the label, 0 = most influential; None until ordered.
    position: int | None = None


class ReferentesRepository(Protocol):
    def save_phase(self, phase: NewDiscoveryPhase) -> StoredDiscoveryPhase:
        """Insert `phase` as the brand's current phase for its `phase_key`, superseding
        the previous current one in the same transaction. Raises `ValueError` when the
        brand does not belong to `phase.tenant_id`."""
        ...

    def find_phase(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        phase_key: str,
        seed_signature: str,
        algorithm_version: int,
        computed_after: datetime | None = None,
    ) -> StoredDiscoveryPhase | None:
        """The newest phase computed for exactly this seed by exactly this algorithm
        version, current or superseded, optionally no older than `computed_after`. A
        superseded hit is what `promote_phase` turns back into the current one."""
        ...

    def promote_phase(self, *, tenant_id: UUID, phase_id: UUID) -> StoredDiscoveryPhase:
        """Make a stored phase the current one again (the operator went back to a city
        already searched). No-op for a phase that is already current."""
        ...

    def current_phases(
        self, *, tenant_id: UUID, brand_id: UUID
    ) -> tuple[StoredDiscoveryPhase, ...]:
        """The brand's current phase per `phase_key`, whatever version computed them."""
        ...

    def stale_phases(
        self, *, tenant_id: UUID, algorithm_version: int
    ) -> tuple[StoredDiscoveryPhase, ...]:
        """Every current phase of the tenant computed by a version older than
        `algorithm_version` — what a recompute has to redo."""
        ...

    def latest_accounts(
        self, *, tenant_id: UUID, brand_id: UUID, identities: Iterable[tuple[str, str]]
    ) -> dict[tuple[str, str], StoredDiscoveredAccount]:
        """For each `(network, handle)`, the account as the brand's most recent phase that
        found it stored it — current or superseded. How an account the operator labeled
        stays visible after a recompute stopped finding it."""
        ...

    def set_label(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        network: str,
        handle: str,
        label: str,
        labeled_by: UUID | None = None,
    ) -> AccountLabel: ...

    def clear_label(self, *, tenant_id: UUID, brand_id: UUID, network: str, handle: str) -> bool:
        """`True` when a label was removed, `False` when there was none."""
        ...

    def labels(self, *, tenant_id: UUID, brand_id: UUID) -> tuple[AccountLabel, ...]: ...

    def set_positions(
        self, *, tenant_id: UUID, brand_id: UUID, positions: Mapping[tuple[str, str], int]
    ) -> None:
        """Store each labeled `(network, handle)`'s influence position. An account with no
        label is skipped — a position only means something inside a label. Raises
        `ValueError` for a negative position."""
        ...


def _validate_positions(positions: Mapping[tuple[str, str], int]) -> dict[tuple[str, str], int]:
    out: dict[tuple[str, str], int] = {}
    for (network, handle), position in positions.items():
        if position < 0:
            raise ValueError("position must be >= 0")
        out[(_normalize_network(network), normalize_handle(handle))] = position
    return out


# --------------------------------------------------------------------------------------
# in-memory
# --------------------------------------------------------------------------------------


class MemoryReferentesRepository:
    """Mirrors migration 0020's invariants without a database. Brands must be registered
    with `add_brand` — the stand-in for the `brands` table and its tenant."""

    def __init__(self) -> None:
        self._brand_tenant: dict[UUID, UUID] = {}
        self._phases: dict[UUID, StoredDiscoveryPhase] = {}
        self._order: dict[UUID, int] = {}
        self._labels: dict[tuple[UUID, str, str], tuple[UUID, AccountLabel]] = {}
        self._seq = 0
        self._last_computed_at: datetime | None = None

    def _now(self) -> datetime:
        # Strictly increasing, like `now()` across Postgres transactions: two saves in
        # the same clock tick (common on Windows) must still order newest-last.
        now = datetime.now(UTC)
        if self._last_computed_at is not None and now <= self._last_computed_at:
            now = self._last_computed_at + timedelta(microseconds=1)
        self._last_computed_at = now
        return now

    def add_brand(self, *, tenant_id: UUID, brand_id: UUID) -> None:
        self._brand_tenant[brand_id] = tenant_id

    def _check_brand(self, tenant_id: UUID, brand_id: UUID) -> None:
        if self._brand_tenant.get(brand_id) != tenant_id:
            raise ValueError("brand not found for this tenant")

    def _visible(self, tenant_id: UUID) -> list[StoredDiscoveryPhase]:
        rows = [p for p in self._phases.values() if p.tenant_id == tenant_id]
        return sorted(rows, key=lambda p: self._order[p.id])

    def _supersede_current(self, brand_id: UUID, phase_key: str, now: datetime) -> None:
        for phase in list(self._phases.values()):
            if phase.brand_id == brand_id and phase.phase_key == phase_key and phase.is_current:
                self._phases[phase.id] = replace(phase, superseded_at=now)

    def save_phase(self, phase: NewDiscoveryPhase) -> StoredDiscoveryPhase:
        self._check_brand(phase.tenant_id, phase.brand_id)
        now = self._now()
        self._supersede_current(phase.brand_id, phase.phase_key, now)
        stored = StoredDiscoveryPhase(
            id=uuid4(),
            tenant_id=phase.tenant_id,
            brand_id=phase.brand_id,
            phase_key=phase.phase_key,
            algorithm_version=phase.algorithm_version,
            seed_signature=phase.seed_signature,
            seed=validate_seed(phase.seed),
            title=phase.title,
            note=phase.note,
            queries=phase.queries,
            errors=phase.errors,
            credits=phase.credits,
            source=phase.source,
            computed_at=now,
            superseded_at=None,
            accounts=tuple(
                StoredDiscoveredAccount(
                    rank=rank,
                    network=a.network,
                    handle=a.handle,
                    full_name=a.full_name,
                    followers=a.followers,
                    profile_url=a.profile_url,
                    avatar_url=a.avatar_url,
                    card=json.loads(json.dumps(dict(a.card), ensure_ascii=False)),
                    found_by=a.found_by,
                )
                for rank, a in enumerate(phase.accounts)
            ),
        )
        self._seq += 1
        self._phases[stored.id] = stored
        self._order[stored.id] = self._seq
        return stored

    def find_phase(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        phase_key: str,
        seed_signature: str,
        algorithm_version: int,
        computed_after: datetime | None = None,
    ) -> StoredDiscoveryPhase | None:
        hits = [
            p
            for p in self._visible(tenant_id)
            if p.brand_id == brand_id
            and p.phase_key == phase_key
            and p.seed_signature == seed_signature
            and p.algorithm_version == algorithm_version
            and (computed_after is None or p.computed_at >= computed_after)
        ]
        return hits[-1] if hits else None

    def promote_phase(self, *, tenant_id: UUID, phase_id: UUID) -> StoredDiscoveryPhase:
        phase = self._phases.get(phase_id)
        if phase is None or phase.tenant_id != tenant_id:
            raise ValueError("phase not found for this tenant")
        if phase.is_current:
            return phase
        self._supersede_current(phase.brand_id, phase.phase_key, datetime.now(UTC))
        promoted = replace(phase, superseded_at=None)
        self._phases[phase_id] = promoted
        return promoted

    def current_phases(
        self, *, tenant_id: UUID, brand_id: UUID
    ) -> tuple[StoredDiscoveryPhase, ...]:
        return tuple(p for p in self._visible(tenant_id) if p.brand_id == brand_id and p.is_current)

    def stale_phases(
        self, *, tenant_id: UUID, algorithm_version: int
    ) -> tuple[StoredDiscoveryPhase, ...]:
        return tuple(
            p
            for p in self._visible(tenant_id)
            if p.is_current and p.algorithm_version < algorithm_version
        )

    def latest_accounts(
        self, *, tenant_id: UUID, brand_id: UUID, identities: Iterable[tuple[str, str]]
    ) -> dict[tuple[str, str], StoredDiscoveredAccount]:
        wanted = set(identities)
        out: dict[tuple[str, str], StoredDiscoveredAccount] = {}
        for phase in self._visible(tenant_id):  # oldest first: newer phases overwrite
            if phase.brand_id != brand_id:
                continue
            for account in phase.accounts:
                identity = (account.network, account.handle)
                if identity in wanted:
                    out[identity] = account
        return out

    def set_label(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        network: str,
        handle: str,
        label: str,
        labeled_by: UUID | None = None,
    ) -> AccountLabel:
        self._check_brand(tenant_id, brand_id)
        key = (brand_id, _normalize_network(network), normalize_handle(handle))
        previous = self._labels.get(key)
        stored = AccountLabel(
            network=key[1],
            handle=key[2],
            label=_validate_label(label),
            labeled_by=labeled_by,
            labeled_at=datetime.now(UTC),
            # Re-labeling keeps the position, as Postgres' upsert does.
            position=previous[1].position if previous is not None else None,
        )
        self._labels[key] = (tenant_id, stored)
        return stored

    def clear_label(self, *, tenant_id: UUID, brand_id: UUID, network: str, handle: str) -> bool:
        key = (brand_id, _normalize_network(network), normalize_handle(handle))
        entry = self._labels.get(key)
        if entry is None or entry[0] != tenant_id:
            return False
        del self._labels[key]
        return True

    def labels(self, *, tenant_id: UUID, brand_id: UUID) -> tuple[AccountLabel, ...]:
        return tuple(
            label
            for (b, _n, _h), (t, label) in self._labels.items()
            if b == brand_id and t == tenant_id
        )

    def set_positions(
        self, *, tenant_id: UUID, brand_id: UUID, positions: Mapping[tuple[str, str], int]
    ) -> None:
        self._check_brand(tenant_id, brand_id)
        for (network, handle), position in _validate_positions(positions).items():
            entry = self._labels.get((brand_id, network, handle))
            if entry is None or entry[0] != tenant_id:
                continue
            self._labels[(brand_id, network, handle)] = (
                tenant_id,
                replace(entry[1], position=position),
            )


# --------------------------------------------------------------------------------------
# Postgres
# --------------------------------------------------------------------------------------


def _brand_visible(session: Session, tenant_id: UUID, brand_id: UUID) -> bool:
    # `brands` is RLS-scoped too, so under `tenant_session` another tenant's brand is
    # simply not there.
    return (
        session.scalar(select(Brand.id).where(Brand.id == brand_id, Brand.tenant_id == tenant_id))
        is not None
    )


def _load(session: Session, rows: list[BrandDiscoveryPhase]) -> tuple[StoredDiscoveryPhase, ...]:
    if not rows:
        return ()
    accounts: dict[UUID, list[StoredDiscoveredAccount]] = {row.id: [] for row in rows}
    for account in session.scalars(
        select(BrandDiscoveredAccount)
        .where(BrandDiscoveredAccount.phase_id.in_(list(accounts)))
        .order_by(BrandDiscoveredAccount.phase_id, BrandDiscoveredAccount.rank)
    ):
        accounts[account.phase_id].append(
            StoredDiscoveredAccount(
                rank=account.rank,
                network=account.network,
                handle=account.handle,
                full_name=account.full_name,
                followers=account.followers,
                profile_url=account.profile_url,
                avatar_url=account.avatar_url,
                card=dict(account.card),
                found_by=tuple(account.found_by),
            )
        )
    return tuple(
        StoredDiscoveryPhase(
            id=row.id,
            tenant_id=row.tenant_id,
            brand_id=row.brand_id,
            phase_key=row.phase_key,
            algorithm_version=row.algorithm_version,
            seed_signature=row.seed_signature,
            seed=dict(row.seed),
            title=row.title,
            note=row.note,
            queries=tuple(row.queries),
            errors=tuple(row.errors),
            credits=row.credits,
            source=row.source,
            computed_at=row.computed_at,
            superseded_at=row.superseded_at,
            accounts=tuple(accounts[row.id]),
        )
        for row in rows
    )


def _supersede_current(session: Session, brand_id: UUID, phase_key: str) -> None:
    session.execute(
        update(BrandDiscoveryPhase)
        .where(
            BrandDiscoveryPhase.brand_id == brand_id,
            BrandDiscoveryPhase.phase_key == phase_key,
            BrandDiscoveryPhase.superseded_at.is_(None),
        )
        .values(superseded_at=func.now())
    )


class PostgresReferentesRepository:
    """All access through `tenant_session`: RLS scopes every statement."""

    #: A concurrent save of the same (brand, phase_key) trips `uq_discovery_phase_current`
    #: in the losing transaction; one retry supersedes the winner and lands.
    _SAVE_ATTEMPTS = 2

    def save_phase(self, phase: NewDiscoveryPhase) -> StoredDiscoveryPhase:
        for attempt in range(self._SAVE_ATTEMPTS):
            try:
                return self._save_phase_once(phase)
            except IntegrityError:
                if attempt == self._SAVE_ATTEMPTS - 1:
                    raise
        raise AssertionError("unreachable")

    def _save_phase_once(self, phase: NewDiscoveryPhase) -> StoredDiscoveryPhase:
        with tenant_session(phase.tenant_id) as session:
            if not _brand_visible(session, phase.tenant_id, phase.brand_id):
                raise ValueError("brand not found for this tenant")
            _supersede_current(session, phase.brand_id, phase.phase_key)
            row = BrandDiscoveryPhase(
                tenant_id=phase.tenant_id,
                brand_id=phase.brand_id,
                phase_key=phase.phase_key,
                algorithm_version=phase.algorithm_version,
                seed_signature=phase.seed_signature,
                seed=dict(phase.seed),
                title=phase.title,
                note=phase.note,
                queries=list(phase.queries),
                errors=list(phase.errors),
                credits=phase.credits,
                source=phase.source,
            )
            session.add(row)
            session.flush()
            for rank, account in enumerate(phase.accounts):
                session.add(
                    BrandDiscoveredAccount(
                        tenant_id=phase.tenant_id,
                        phase_id=row.id,
                        rank=rank,
                        network=account.network,
                        handle=account.handle,
                        full_name=account.full_name,
                        followers=account.followers,
                        profile_url=account.profile_url,
                        avatar_url=account.avatar_url,
                        card=dict(account.card),
                        found_by=list(account.found_by),
                    )
                )
            session.flush()
            session.refresh(row)
            return _load(session, [row])[0]

    def find_phase(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        phase_key: str,
        seed_signature: str,
        algorithm_version: int,
        computed_after: datetime | None = None,
    ) -> StoredDiscoveryPhase | None:
        with tenant_session(tenant_id) as session:
            stmt = (
                select(BrandDiscoveryPhase)
                .where(
                    BrandDiscoveryPhase.tenant_id == tenant_id,
                    BrandDiscoveryPhase.brand_id == brand_id,
                    BrandDiscoveryPhase.phase_key == phase_key,
                    BrandDiscoveryPhase.seed_signature == seed_signature,
                    BrandDiscoveryPhase.algorithm_version == algorithm_version,
                )
                .order_by(BrandDiscoveryPhase.computed_at.desc(), BrandDiscoveryPhase.id.desc())
                .limit(1)
            )
            if computed_after is not None:
                stmt = stmt.where(BrandDiscoveryPhase.computed_at >= computed_after)
            row = session.scalar(stmt)
            return _load(session, [row])[0] if row is not None else None

    def promote_phase(self, *, tenant_id: UUID, phase_id: UUID) -> StoredDiscoveryPhase:
        with tenant_session(tenant_id) as session:
            row = session.scalar(
                select(BrandDiscoveryPhase).where(
                    BrandDiscoveryPhase.id == phase_id, BrandDiscoveryPhase.tenant_id == tenant_id
                )
            )
            if row is None:
                raise ValueError("phase not found for this tenant")
            if row.superseded_at is not None:
                # Order matters for the partial unique index: retire the current one
                # first, then bring this one back.
                _supersede_current(session, row.brand_id, row.phase_key)
                row.superseded_at = None
                session.flush()
            return _load(session, [row])[0]

    def current_phases(
        self, *, tenant_id: UUID, brand_id: UUID
    ) -> tuple[StoredDiscoveryPhase, ...]:
        with tenant_session(tenant_id) as session:
            rows = list(
                session.scalars(
                    select(BrandDiscoveryPhase)
                    .where(
                        BrandDiscoveryPhase.tenant_id == tenant_id,
                        BrandDiscoveryPhase.brand_id == brand_id,
                        BrandDiscoveryPhase.superseded_at.is_(None),
                    )
                    .order_by(BrandDiscoveryPhase.computed_at, BrandDiscoveryPhase.id)
                )
            )
            return _load(session, rows)

    def stale_phases(
        self, *, tenant_id: UUID, algorithm_version: int
    ) -> tuple[StoredDiscoveryPhase, ...]:
        with tenant_session(tenant_id) as session:
            rows = list(
                session.scalars(
                    select(BrandDiscoveryPhase)
                    .where(
                        BrandDiscoveryPhase.tenant_id == tenant_id,
                        BrandDiscoveryPhase.superseded_at.is_(None),
                        BrandDiscoveryPhase.algorithm_version < algorithm_version,
                    )
                    .order_by(BrandDiscoveryPhase.computed_at, BrandDiscoveryPhase.id)
                )
            )
            return _load(session, rows)

    def latest_accounts(
        self, *, tenant_id: UUID, brand_id: UUID, identities: Iterable[tuple[str, str]]
    ) -> dict[tuple[str, str], StoredDiscoveredAccount]:
        wanted = sorted(set(identities))
        if not wanted:
            return {}
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                select(BrandDiscoveredAccount)
                .join(
                    BrandDiscoveryPhase,
                    BrandDiscoveryPhase.id == BrandDiscoveredAccount.phase_id,
                )
                .where(
                    BrandDiscoveryPhase.tenant_id == tenant_id,
                    BrandDiscoveryPhase.brand_id == brand_id,
                    tuple_(BrandDiscoveredAccount.network, BrandDiscoveredAccount.handle).in_(
                        wanted
                    ),
                )
                .order_by(BrandDiscoveryPhase.computed_at.desc(), BrandDiscoveryPhase.id.desc())
            ).scalars()
            out: dict[tuple[str, str], StoredDiscoveredAccount] = {}
            for account in rows:
                identity = (account.network, account.handle)
                if identity in out:
                    continue  # newest first: the first sighting wins
                out[identity] = StoredDiscoveredAccount(
                    rank=account.rank,
                    network=account.network,
                    handle=account.handle,
                    full_name=account.full_name,
                    followers=account.followers,
                    profile_url=account.profile_url,
                    avatar_url=account.avatar_url,
                    card=dict(account.card),
                    found_by=tuple(account.found_by),
                )
            return out

    def set_label(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        network: str,
        handle: str,
        label: str,
        labeled_by: UUID | None = None,
    ) -> AccountLabel:
        values = {
            "tenant_id": tenant_id,
            "brand_id": brand_id,
            "network": _normalize_network(network),
            "handle": normalize_handle(handle),
            "label": _validate_label(label),
            "labeled_by": labeled_by,
        }
        with tenant_session(tenant_id) as session:
            if not _brand_visible(session, tenant_id, brand_id):
                raise ValueError("brand not found for this tenant")
            stmt = insert(BrandAccountLabel).values(**values)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_account_label",
                set_={
                    "label": stmt.excluded.label,
                    "labeled_by": stmt.excluded.labeled_by,
                    "labeled_at": func.now(),
                },
            ).returning(BrandAccountLabel.labeled_at)
            labeled_at = session.execute(stmt).scalar_one()
        return AccountLabel(
            network=values["network"],
            handle=values["handle"],
            label=values["label"],
            labeled_by=labeled_by,
            labeled_at=labeled_at,
        )

    def clear_label(self, *, tenant_id: UUID, brand_id: UUID, network: str, handle: str) -> bool:
        with tenant_session(tenant_id) as session:
            result = session.execute(
                delete(BrandAccountLabel).where(
                    BrandAccountLabel.tenant_id == tenant_id,
                    BrandAccountLabel.brand_id == brand_id,
                    BrandAccountLabel.network == _normalize_network(network),
                    BrandAccountLabel.handle == normalize_handle(handle),
                )
            )
            return result.rowcount > 0

    def labels(self, *, tenant_id: UUID, brand_id: UUID) -> tuple[AccountLabel, ...]:
        with tenant_session(tenant_id) as session:
            rows = session.scalars(
                select(BrandAccountLabel)
                .where(
                    BrandAccountLabel.tenant_id == tenant_id,
                    BrandAccountLabel.brand_id == brand_id,
                )
                .order_by(BrandAccountLabel.labeled_at, BrandAccountLabel.id)
            )
            return tuple(
                AccountLabel(
                    network=row.network,
                    handle=row.handle,
                    label=row.label,
                    labeled_by=row.labeled_by,
                    labeled_at=row.labeled_at,
                    position=row.position,
                )
                for row in rows
            )

    def set_positions(
        self, *, tenant_id: UUID, brand_id: UUID, positions: Mapping[tuple[str, str], int]
    ) -> None:
        wanted = _validate_positions(positions)
        with tenant_session(tenant_id) as session:
            if not _brand_visible(session, tenant_id, brand_id):
                raise ValueError("brand not found for this tenant")
            for (network, handle), position in wanted.items():
                session.execute(
                    update(BrandAccountLabel)
                    .where(
                        BrandAccountLabel.tenant_id == tenant_id,
                        BrandAccountLabel.brand_id == brand_id,
                        BrandAccountLabel.network == network,
                        BrandAccountLabel.handle == handle,
                    )
                    .values(position=position)
                )
