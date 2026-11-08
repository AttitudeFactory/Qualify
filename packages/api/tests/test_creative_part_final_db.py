"""VE-10b (m-24921068) against Postgres: a video by parts approved ONCE, each part's
1080p kept as it came (`part_final`), and the local 1080p final join.

- Criterion 1: 3 parts and seconds for only 2 → approving charges nothing and approves
  nothing; with enough → the 3 parts charged in ONE transaction and 3 finals queued in
  the night lane (ADR 41). Approving twice charges and queues once.
- Criterion 2: a part in `part_final` never shows — «Tu semana», the morning mail, the
  gallery's files, the Planificador.
- Criterion 3: the final join ends `final_ready` (logo once, 1080×1920) and the
  unchanged `confirm_final` makes it publishable; «Pedir otra versión» afterwards
  charges only the part made again.
- A stale joined preview is refused; the plain `approve` refuses a parent and a part; a
  part final that fails gives its seconds back (D9) and «Reintentar» does not charge
  them again; a final join that fails charges nothing and its retry pays no vendor.

The real `ContentService`, `PostgresCreationsLedger`, `QueueDispatcher`,
`PipelinePreparation`, `DbPartJoins` and RLS; the producer is a fake (no vendor) and
the encoder a recording stand-in (the real PyAV join is covered offline)."""

from __future__ import annotations

import hashlib
import io
import time
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from typing import Any
from uuid import UUID, uuid4

import pytest
from PIL import Image
from qualify_creative.video.join import JoinedVideo, JoinError, JoinSegment
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creative import part_final
from qualify_api.creative.creations import NotEnoughCreations, PostgresCreationsLedger
from qualify_api.creative.draft_mode import draft_pending
from qualify_api.creative.final_review import FinalIdentity, confirm_final
from qualify_api.creative.fsm import APPROVED, GENERATED
from qualify_api.creative.media import FinalOutcome
from qualify_api.creative.part_final import (
    JOIN_FINAL_PENDING,
    JOIN_FINAL_SIZE,
    ApproveWholeVideo,
    PartFailed,
    StaleJoinedPreview,
)
from qualify_api.creative.part_join import PART_FINAL
from qualify_api.creative.parts import (
    PART_FINAL_IN_FLIGHT_TEXT,
    PART_SCHEDULED_TEXT,
    PartChangeRefused,
    PartChanges,
    open_parent_join,
)
from qualify_api.creative.pieces import DbPieceFiles
from qualify_api.creative.pipeline import PipelineStore
from qualify_api.creative.service import DraftExpired
from qualify_api.creative.worker.pipeline import PipelinePreparation
from qualify_api.home.summary import read_home_counts
from qualify_api.mail.final_summary import _new_videos
from qualify_api.planner.draft_post_reader import DraftPostReader
from qualify_api.tenancy.models import TenantMember

from . import test_creative_parts_db as parts_db
from .test_creative_part_join import Joiner, Store
from .test_creative_part_join_db import THREE_PARTS, JoinMedia
from .test_creative_parts import parent_brief

pytestmark = pytest.mark.db

SECONDS = (5, 4, 6)  # THREE_PARTS: what each part asks Seedance for (D29)


class ReadingJoiner(Joiner):
    """The recording encoder, keeping what each join read (its folder is gone after)."""

    def __init__(self) -> None:
        super().__init__()
        self.inputs: list[list[bytes]] = []

    def __call__(self, clips, *, out, size, overlay=None):  # noqa: ANN001, ANN204
        self.inputs.append([c.path.read_bytes() for c in clips])
        self.sizes = [*getattr(self, "sizes", []), size]
        return super().__call__(clips, out=out, size=size, overlay=overlay)


class Segments:
    """The final join's encoder doubles (`segmenter`, `concat`): each part's segment is
    a stand-in file naming the raw bytes it read; `concat` lays them end to end. Records
    what each final read (`inputs`), its overlay and size, and how many segments were
    ENCODED (a resumed pass fetches the kept ones instead). `error` fails a segment;
    `crash` runs the real child with a command that dies like an OOM kill; `delay` makes
    every segment take that long (a join longer than the lease)."""

    def __init__(self) -> None:
        self.calls: list[list[bytes]] = []  # one entry per concat (= per final made)
        self.inputs: list[list[bytes]] = []
        self.overlays: list[bytes | None] = []
        self.sizes: list[tuple[int, int]] = []
        self.encoded = 0
        self.error: Exception | None = None
        self.crash = False
        self.delay = 0.0
        self.fail_after: int | None = None  # raise a lease loss after this many segments

    def segment(self, clip, *, out, pcm_out, size, overlay=None, poster=False, **_):  # noqa: ANN001, ANN003, ANN201
        if self.crash:
            import sys

            from qualify_creative.video.join_child import segment_in_child

            return segment_in_child(
                clip, out=out, pcm_out=pcm_out, size=size,
                command=(sys.executable, "-c", "import os; os._exit(137)"),
            )  # fmt: skip
        if self.error is not None:
            raise self.error
        if self.delay:
            time.sleep(self.delay)
        self.encoded += 1
        self.overlays.append(overlay)
        self.sizes.append(size)
        out.write_bytes(b"segment:" + clip.path.read_bytes())
        pcm_out.write_bytes(b"\0" * 8 * 2000)
        return JoinSegment(out, pcm_out, 1, 2000, b"\xff\xd8poster" if poster else None)

    def concat(self, segments, *, out):  # noqa: ANN001, ANN201
        read = [seg.path.read_bytes().removeprefix(b"segment:") for seg in segments]
        self.calls.append(read)
        self.inputs.append(read)
        out.write_bytes(b"final:" + b"|".join(read))
        return JoinedVideo(
            path=out, width=1080, height=1920, fps=Fraction(24), frames=len(segments),
            duration_sec=len(segments) / 24, poster=segments[0].poster,
        )  # fmt: skip


class FinalMedia(JoinMedia):
    """`JoinMedia` with the parts' finals: the vendor's raw 1080p is a file put in the
    store, kept as it came (`part_final_media`, the production branch), and the final
    join over the database with the recording encoder."""

    def __init__(self, store: Store, joiner: Joiner) -> None:
        super().__init__(store, joiner)
        self._part_joins = self.joins
        self.segments = Segments()
        self.finals: list[UUID] = []
        self.fail: set[UUID] = set()

    def finalize(self, *, tenant_id: UUID, draft_id: UUID, asset: Any, revision: int, **_: Any):  # noqa: ANN201
        self.finals.append(draft_id)
        if draft_id in self.fail:
            return FinalOutcome(failure="provider_error", detail="Seedance falló")
        key = f"t/{tenant_id}/generated/{draft_id}/r{revision}/clip-final-raw.mp4"
        self.store.files[key] = f"raw 1080p {draft_id} r{revision}".encode()
        raw = {
            "key": key,
            "task_id": f"task-{draft_id}",
            "model_id": "seedance-2-5",
            "resolution": "1080p",
            "cost_usd": "1.17",
        }
        block = dict(asset.params["draft"])
        return FinalOutcome(media=part_final.part_final_media(asset, block, raw, revision))

    def join_final(self, tenant_id: UUID, parent_id: UUID):  # noqa: ANN201
        return part_final.join_final(
            self.store,
            self.joins,
            tenant_id,
            parent_id,
            segmenter=self.segments.segment,
            concat=self.segments.concat,
        )

    def save_join_final(self, tenant_id: UUID, parent_id: UUID, write) -> bool:  # noqa: ANN001
        return self.joins.save_final(tenant_id=tenant_id, parent_id=parent_id, write=write)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    tenant, brand, user = parts_db._business(monkeypatch)
    service, parts, _ = parts_db._service()
    store, joiner = Store(), ReadingJoiner()
    media = FinalMedia(store, joiner)
    service._media = media  # type: ignore[assignment]
    brief = parent_brief(*THREE_PARTS).model_copy(update={"brand_id": brand})
    parent = service.create_draft(tenant_id=tenant, brand_id=brand, brief=brief, user_id=user)
    service.run_generation(tenant_id=tenant, draft_id=parent)
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    for child in ids:
        service.run_generation(tenant_id=tenant, draft_id=child)
    _worker_pass(service, tenant)  # the joined preview
    assert _join_row(tenant, parent).params["draft"]["status"] == "join_preview"
    return service, parts, media, tenant, brand, user, parent, ids


def _scalar(tenant: UUID, sql: str, **params: object) -> Any:
    with tenant_session(tenant) as session:
        return session.execute(text(sql), params).scalar()


def _worker_pass(service, tenant: UUID) -> None:  # noqa: ANN001
    with tenant_session(tenant) as session:
        # the parts' own generations ran inline here
        session.execute(
            text(
                "UPDATE creative_pipeline_runs SET prepared_version=dirty_version "
                "WHERE phase='generation'"
            )
        )
        # the vendor's side of ADR 41 (`PipelineExecutor._stamp_started`): the queued
        # finals have started
        session.execute(
            text("""
            UPDATE image_assets SET params = jsonb_set(params, '{draft,status}', '"rendering"')
            WHERE params->'draft'->>'status' = 'final_scheduled'
            """)
        )
    PipelinePreparation(service, PipelineStore(), (tenant,))()


def _join_row(tenant: UUID, parent: UUID) -> Any:
    with tenant_session(tenant) as session:
        return session.execute(
            text("""
            SELECT a.id, a.object_key, a.params FROM image_assets a
            JOIN content_drafts d ON d.id = a.draft_id
            WHERE a.draft_id=:p AND a.params->'draft'->>'finish'='join'
              AND a.version_id IS NOT DISTINCT FROM d.active_version_id
            """),
            {"p": parent},
        ).one()


def _variant(service, tenant: UUID, parent: UUID) -> UUID:  # noqa: ANN001
    return service.repository.variants_for(tenant_id=tenant, draft_id=parent)[0].id


def _approve(world) -> Any:  # noqa: ANN001
    service, _, _, tenant, _, user, parent, _ = world
    return service.approve_parts(
        tenant_id=tenant,
        parent_id=parent,
        variant_id=_variant(service, tenant, parent),
        user_id=user,
    )


def _charges(tenant: UUID, ids: list[UUID]) -> list[tuple[UUID, int, int, int]]:
    with tenant_session(tenant) as session:
        return [
            tuple(row)
            for row in session.execute(
                text("""
                SELECT draft_id, revision, videos, video_seconds FROM creation_charges
                WHERE draft_id = ANY(:i) AND videos > 0 ORDER BY draft_id, revision
                """),
                {"i": ids},
            ).all()
        ]


def _final_jobs(tenant: UUID, ids: list[UUID]) -> list[Any]:
    with tenant_session(tenant) as session:
        return list(
            session.execute(
                text(
                    "SELECT draft_id, lane, revision FROM creative_jobs "
                    "WHERE kind='final' AND draft_id = ANY(:i)"
                ),
                {"i": ids},
            ).all()
        )


def _status(tenant: UUID, draft: UUID) -> str:
    return _scalar(tenant, "SELECT status FROM content_drafts WHERE id=:d", d=draft)


def _seconds_left(brand: UUID, tenant: UUID) -> int:
    return PostgresCreationsLedger().balance(tenant_id=tenant, brand_id=brand).videos_left


def _part_blocks(tenant: UUID, ids: list[UUID]) -> list[dict[str, Any]]:
    with tenant_session(tenant) as session:
        return [
            session.execute(
                text("""
                SELECT a.params->'draft' FROM image_assets a JOIN content_drafts d
                  ON d.id = a.draft_id AND a.version_id = d.active_version_id
                WHERE a.draft_id = :d
                """),
                {"d": child},
            ).scalar()
            for child in ids
        ]


def _finals_and_join(world) -> None:  # noqa: ANN001
    """Two worker passes: the parts' finals (their `final:` runs), then the join."""
    service, _, _, tenant, *_ = world
    _worker_pass(service, tenant)
    _worker_pass(service, tenant)


# ---------------------------------------------------------------------------
# criterion 1 — all or nothing, one transaction, the night lane; twice = once


def test_criterion_1_seconds_for_two_of_three_parts_charge_and_approve_nothing_db(world) -> None:  # noqa: ANN001
    service, _, _, tenant, brand, user, parent, ids = world
    ledger = PostgresCreationsLedger()
    filler = uuid4()
    left = _seconds_left(brand, tenant)
    # leave 14 s: parts 1 and 2 (5 + 4 s) would fit, all three (15 s) do not
    ledger.charge_videos(
        tenant_id=tenant, brand_id=brand, draft_id=filler, revision=1, videos=1, seconds=left - 14
    )
    assert _seconds_left(brand, tenant) == 14
    with pytest.raises(NotEnoughCreations):
        _approve(world)
    assert _status(tenant, parent) == GENERATED
    assert [_status(tenant, c) for c in ids] == [GENERATED] * 3
    assert _charges(tenant, ids) == [] and _final_jobs(tenant, ids) == []
    assert _join_row(tenant, parent).params["draft"]["status"] == "join_preview"
    assert _seconds_left(brand, tenant) == 14

    ledger.uncharge_videos(tenant_id=tenant, draft_id=filler, revision=1)
    _approve(world)
    assert _status(tenant, parent) == APPROVED
    assert [_status(tenant, c) for c in ids] == [APPROVED] * 3
    assert sorted(_charges(tenant, ids)) == sorted(
        (child, 1, 1, seconds) for child, seconds in zip(ids, SECONDS, strict=True)
    )
    assert _seconds_left(brand, tenant) == left - sum(SECONDS)
    jobs = _final_jobs(tenant, ids)
    assert sorted(j.draft_id for j in jobs) == sorted(ids)
    assert {j.lane for j in jobs} == {"nightly"}
    assert all(b["status"] == "final_scheduled" for b in _part_blocks(tenant, ids))
    block = _join_row(tenant, parent).params["draft"]
    assert block["status"] == JOIN_FINAL_PENDING
    assert block["approved_fingerprint"] == block["fingerprint"]
    # each part approved with its one inherited text
    for child in ids:
        (variant,) = service.repository.variants_for(tenant_id=tenant, draft_id=child)
        assert (
            service.repository.get_draft(tenant_id=tenant, draft_id=child).selected_variant_id
            == variant.id
        )

    # approving twice charges and queues once
    _approve(world)
    assert len(_charges(tenant, ids)) == 3 and len(_final_jobs(tenant, ids)) == 3
    assert _seconds_left(brand, tenant) == left - sum(SECONDS)
    del user


def test_the_plain_approve_refuses_a_parent_and_a_part_db(world) -> None:  # noqa: ANN001
    service, _, _, tenant, _, user, parent, ids = world
    with pytest.raises(ApproveWholeVideo):
        service.approve(
            tenant_id=tenant,
            draft_id=parent,
            variant_id=_variant(service, tenant, parent),
            user_id=user,
        )
    (variant,) = service.repository.variants_for(tenant_id=tenant, draft_id=ids[0])
    with pytest.raises(ApproveWholeVideo):
        service.approve(tenant_id=tenant, draft_id=ids[0], variant_id=variant.id, user_id=user)
    assert _status(tenant, parent) == GENERATED and _charges(tenant, ids) == []


def test_a_stale_joined_preview_is_refused_and_charges_nothing_db(world) -> None:  # noqa: ANN001
    service, parts, _, tenant, brand, user, parent, ids = world
    parts.regenerate_part(
        tenant_id=tenant,
        parent_id=parent,
        part_index=2,
        changes=PartChanges(description="Manos que sirven papas fritas."),
        user_id=user,
    )
    service.run_generation(tenant_id=tenant, draft_id=ids[1])  # its new version, not joined
    left = _seconds_left(brand, tenant)
    with pytest.raises(StaleJoinedPreview):
        _approve(world)
    assert _status(tenant, parent) == GENERATED and _charges(tenant, ids) == []
    assert _seconds_left(brand, tenant) == left
    _worker_pass(service, tenant)  # the new joined preview
    _approve(world)
    assert _status(tenant, parent) == APPROVED


# ---------------------------------------------------------------------------
# criteria 2 and 3 — the parts' finals stay hidden; the join is the final


def test_criteria_2_and_3_part_finals_hidden_join_final_ready_and_confirmed_db(world) -> None:  # noqa: ANN001
    service, _, media, tenant, brand, user, parent, ids = world
    logo = f"t/{tenant}/brand/logo.png"
    picture = io.BytesIO()
    Image.new("RGBA", (64, 64), (200, 30, 30, 255)).save(picture, "PNG")
    media.store.files[logo] = picture.getvalue()
    with tenant_session(tenant) as session:  # the owner chose the logo for this video
        session.execute(
            text("""
            UPDATE content_briefs b SET media = jsonb_set(b.media, '{brand_logo_key}',
                to_jsonb(CAST(:k AS text)))
            FROM content_drafts d WHERE d.brief_id = b.id AND d.id = :p
            """),
            {"k": logo, "p": parent},
        )
        open_parent_join(session, parent)
    _worker_pass(service, tenant)  # its joined preview now carries the logo
    assert _join_row(tenant, parent).params["draft"]["logo"]["key"] == logo
    joins_before = len(media.segments.calls)
    _approve(world)
    _worker_pass(service, tenant)  # the parts' finals
    blocks = _part_blocks(tenant, ids)
    assert [b["status"] for b in blocks] == [PART_FINAL] * 3
    assert all(b["raw_final"]["key"].endswith("clip-final-raw.mp4") for b in blocks)
    assert all("final_sha256" not in b for b in blocks)

    # criterion 2: nothing lists a part — not even a part with its final
    with tenant_session(tenant) as session:
        session.execute(
            text(
                "UPDATE creative_jobs SET status='succeeded', finished_at=:t "
                "WHERE kind='final' AND draft_id = ANY(:i)"
            ),
            {"i": ids, "t": datetime.now(UTC)},
        )
    counts = read_home_counts(tenant)
    assert counts.videos_to_confirm == 0 and counts.finals_failed == 0
    with tenant_session(tenant) as session:
        mailed = _new_videos(session, datetime.now(UTC) + timedelta(minutes=1))
    assert all(video[0] not in ids for video in mailed)
    assert DbPieceFiles().files(tenant_id=tenant, brand_id=brand) == []
    reader = DraftPostReader()
    assert [p.post_id for p in reader.list_for_brand(tenant_id=tenant, brand_id=brand)] == [parent]
    assert set(reader.get_many(tenant_id=tenant, post_ids=[parent, *ids])) == {parent}
    assert [d.id for d in service.list_drafts(tenant_id=tenant, brand_id=brand)] == [parent]
    # the parent itself is not publishable while its final join is pending
    assert draft_pending(_join_row(tenant, parent).params)

    # criterion 3: the final join
    _worker_pass(service, tenant)
    assert len(media.segments.calls) == joins_before + 1
    row = _join_row(tenant, parent)
    block = row.params["draft"]
    assert block["status"] == "final_ready"
    assert row.object_key == block["final_object_key"]
    assert row.object_key.startswith(f"t/{tenant}/generated/{parent}/join-final-")
    assert block["final_sha256"] == hashlib.sha256(media.store.files[row.object_key]).hexdigest()
    assert block["final_revision"] == _scalar(
        tenant, "SELECT revision FROM content_drafts WHERE id=:p", p=parent
    )
    # joined from the raw finals at 1080×1920, the logo laid ONCE over the whole video
    assert media.segments.inputs[-1] == [f"raw 1080p {child} r1".encode() for child in ids]
    assert all(o is not None for o in media.segments.overlays[-3:])  # the same layer
    assert len({o for o in media.segments.overlays[-3:]}) == 1  # on every part
    assert media.segments.sizes[-1] == JOIN_FINAL_SIZE
    joined = row.params["join_final"]
    assert joined["size"] == list(JOIN_FINAL_SIZE) and joined["cost_usd"] == "0"
    assert joined["logo"]["key"] == logo
    assert [p["raw_final_key"] for p in joined["parts"]] == [b["raw_final"]["key"] for b in blocks]
    assert _scalar(tenant, "SELECT count(*) FROM creation_charges WHERE draft_id=:p", p=parent) <= 1
    # «Tu semana» now asks to look at it; the unchanged confirm makes it publishable
    assert read_home_counts(tenant).videos_to_confirm == 1
    assert draft_pending(row.params)
    revision = block["final_revision"]
    with admin_session() as session:  # who may confirm a final: the business's owner
        session.add(TenantMember(tenant_id=tenant, user_id=user, role="owner"))
    confirm_final(
        tenant_id=tenant,
        draft_id=parent,
        user_id=user,
        expected=(FinalIdentity(row.id, row.object_key, block["final_sha256"], revision),),
    )
    confirmed = _join_row(tenant, parent)
    assert confirmed.params["draft"]["status"] == "final"
    assert not draft_pending(confirmed.params)
    assert read_home_counts(tenant).videos_to_confirm == 0
    # another pass does nothing more
    _worker_pass(service, tenant)
    assert len(media.segments.calls) == joins_before + 1


def test_criterion_3_another_version_after_the_final_charges_only_that_part_db(world) -> None:  # noqa: ANN001
    service, parts, media, tenant, brand, user, parent, ids = world
    _approve(world)
    _finals_and_join(world)
    first = _join_row(tenant, parent)
    assert first.params["draft"]["status"] == "final_ready"
    left = _seconds_left(brand, tenant)

    parts.regenerate_part(
        tenant_id=tenant,
        parent_id=parent,
        part_index=2,
        changes=PartChanges(description="Manos que sirven papas fritas."),
        user_id=user,
    )
    assert _status(tenant, parent) == GENERATED  # back to the gate
    service.run_generation(tenant_id=tenant, draft_id=ids[1])
    _worker_pass(service, tenant)  # the new joined preview, from the kept parts 1 and 3
    preview = _join_row(tenant, parent)
    assert preview.params["draft"]["status"] == "join_preview"
    assert preview.params["draft"]["fingerprint"] != first.params["draft"]["fingerprint"]
    assert first.object_key in media.store.files  # the earlier final stays in R2

    finals_before = list(media.finals)
    _approve(world)
    # only part 2's new generation is charged; parts 1 and 3 keep their charge
    charges = _charges(tenant, ids)
    assert sorted(charges) == sorted(
        [(ids[0], 1, 1, 5), (ids[1], 1, 1, 4), (ids[1], 2, 1, 4), (ids[2], 1, 1, 6)]
    )
    assert _seconds_left(brand, tenant) == left - 4
    assert [j.draft_id for j in _final_jobs(tenant, ids) if j.revision == 2] == [ids[1]]
    _finals_and_join(world)
    assert media.finals[len(finals_before) :] == [ids[1]]  # no other part paid again
    final = _join_row(tenant, parent)
    assert final.params["draft"]["status"] == "final_ready"
    assert final.object_key != first.object_key
    assert media.segments.inputs[-1] == [
        f"raw 1080p {ids[0]} r1".encode(),
        f"raw 1080p {ids[1]} r2".encode(),
        f"raw 1080p {ids[2]} r1".encode(),
    ]


# ---------------------------------------------------------------------------
# failures keep what was paid for


def test_a_failed_part_final_gives_its_seconds_back_and_the_retry_charges_nothing_db(world) -> None:  # noqa: ANN001
    service, _, media, tenant, brand, _, parent, ids = world
    media.fail.add(ids[1])
    left = _seconds_left(brand, tenant)
    _approve(world)
    _finals_and_join(world)
    blocks = _part_blocks(tenant, ids)
    assert [b["status"] for b in blocks] == [PART_FINAL, "failed", PART_FINAL]
    assert _join_row(tenant, parent).params["draft"]["status"] == JOIN_FINAL_PENDING
    # D9: part 2's 4 s come back; the others stay used
    assert _seconds_left(brand, tenant) == left - 5 - 6
    paid = list(media.finals)

    media.fail.clear()
    with tenant_session(tenant) as session:  # the executor's side: that job failed
        session.execute(
            text(
                "UPDATE creative_jobs SET status='failed', finished_at=now(), "
                "vendor_task_id='task-failed', last_error='failed' "
                "WHERE kind='final' AND draft_id=:d"
            ),
            {"d": ids[1]},
        )
    service.retry_final(tenant_id=tenant, draft_id=parent)
    assert _seconds_left(brand, tenant) == left - 5 - 6  # «Reintentar» counts nothing
    _finals_and_join(world)
    assert media.finals[len(paid) :] == [ids[1]]
    assert _join_row(tenant, parent).params["draft"]["status"] == "final_ready"


def test_a_failed_final_join_charges_nothing_and_its_retry_pays_no_vendor_db(world) -> None:  # noqa: ANN001
    service, _, media, tenant, brand, _, parent, ids = world
    _approve(world)
    left = _seconds_left(brand, tenant)
    media.segments.error = JoinError("the raw part cannot be decoded")
    _finals_and_join(world)
    row = _join_row(tenant, parent)
    assert row.params["draft"]["status"] == "failed"
    assert row.params["draft"]["error"] == part_final.JOIN_FINAL_FAILED_TEXT
    assert read_home_counts(tenant).finals_failed == 1
    assert _seconds_left(brand, tenant) == left  # nothing charged, nothing given back
    paid = list(media.finals)
    assert sorted(paid) == sorted(ids)

    media.segments.error = None
    service.retry_final(tenant_id=tenant, draft_id=parent)
    assert _join_row(tenant, parent).params["draft"]["status"] == JOIN_FINAL_PENDING
    _worker_pass(service, tenant)
    assert _join_row(tenant, parent).params["draft"]["status"] == "final_ready"
    assert media.finals == paid  # the raw finals were joined again, never paid again
    assert _seconds_left(brand, tenant) == left


def test_an_io_failure_in_the_final_join_is_retried_by_the_next_pass_db(world) -> None:  # noqa: ANN001
    service, _, media, tenant, _, _, parent, _ = world
    _approve(world)
    _worker_pass(service, tenant)  # the parts' finals
    error = JoinError("disk full")
    error.__cause__ = OSError(28, "No space left on device")
    media.segments.error = error
    _worker_pass(service, tenant)
    assert _join_row(tenant, parent).params["draft"]["status"] == JOIN_FINAL_PENDING
    run = _scalar(
        tenant,
        "SELECT dirty_version > prepared_version FROM creative_pipeline_runs "
        "WHERE draft_id=:p AND phase='join_final'",
        p=parent,
    )
    assert run is True  # not marked done: retried
    media.segments.error = None
    _worker_pass(service, tenant)
    assert _join_row(tenant, parent).params["draft"]["status"] == "final_ready"


def test_another_version_of_a_part_whose_final_is_not_made_gives_its_seconds_back_db(world) -> None:  # noqa: ANN001
    service, parts, media, tenant, brand, user, parent, ids = world
    left = _seconds_left(brand, tenant)
    _approve(world)  # the finals wait for tonight
    assert _seconds_left(brand, tenant) == left - sum(SECONDS)
    parts.regenerate_part(
        tenant_id=tenant,
        parent_id=parent,
        part_index=2,
        changes=PartChanges(description="Manos que sirven papas fritas."),
        user_id=user,
    )
    # part 2's final will never be the video's: its 4 s come back; 1 and 3 stay counted
    assert _seconds_left(brand, tenant) == left - 5 - 6
    assert _status(tenant, parent) == GENERATED
    service.run_generation(tenant_id=tenant, draft_id=ids[1])
    # parts 1 and 3 get their finals; the new preview joins once they are kept (each
    # kept final dirties the preview join: the next pass joins it)
    _worker_pass(service, tenant)
    _worker_pass(service, tenant)
    assert _join_row(tenant, parent).params["draft"]["status"] == "join_preview"
    _approve(world)
    assert _seconds_left(brand, tenant) == left - 5 - 6 - 4
    _finals_and_join(world)
    assert _join_row(tenant, parent).params["draft"]["status"] == "final_ready"
    assert sorted(media.finals) == sorted(ids)  # one paid final per part, none twice


def test_a_crashed_join_child_is_retried_charges_nothing_and_the_row_stays_pending_db(
    world,  # noqa: ANN001
) -> None:
    service, _, media, tenant, brand, _, parent, _ = world
    _approve(world)
    left = _seconds_left(brand, tenant)
    _worker_pass(service, tenant)  # the parts' finals
    media.segments.crash = True
    _worker_pass(service, tenant)
    assert _join_row(tenant, parent).params["draft"]["status"] == JOIN_FINAL_PENDING
    assert _scalar(
        tenant,
        "SELECT dirty_version > prepared_version FROM creative_pipeline_runs "
        "WHERE draft_id=:p AND phase='join_final'",
        p=parent,
    )
    assert _seconds_left(brand, tenant) == left
    media.segments.crash = False
    _worker_pass(service, tenant)
    assert _join_row(tenant, parent).params["draft"]["status"] == "final_ready"
    assert _seconds_left(brand, tenant) == left


def test_a_final_join_longer_than_the_lease_saves_in_one_pass_db(world, monkeypatch) -> None:  # noqa: ANN001
    from qualify_api.creative import pipeline

    service, _, media, tenant, _, _, parent, _ = world
    _approve(world)
    _worker_pass(service, tenant)  # the parts' finals
    monkeypatch.setattr(pipeline, "LEASE", timedelta(seconds=3))
    media.segments.delay = 2.5  # 3 parts: 7.5 s, more than two leases
    _worker_pass(service, tenant)
    assert _join_row(tenant, parent).params["draft"]["status"] == "final_ready"
    assert media.segments.encoded == 3 and len(media.segments.calls) == 1


def test_a_lease_lost_mid_join_resumes_without_encoding_the_kept_segments_db(
    world,  # noqa: ANN001
    monkeypatch,  # noqa: ANN001
) -> None:
    from qualify_api.creative.pipeline import CheckpointError

    service, _, media, tenant, _, _, parent, _ = world
    _approve(world)
    _worker_pass(service, tenant)  # the parts' finals
    calls = {"n": 0}
    real = part_final._keep_lease

    def lost_after_two() -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise CheckpointError("preparation lease lost between the parts of a final join")
        real()

    monkeypatch.setattr(part_final, "_keep_lease", lost_after_two)
    _worker_pass(service, tenant)
    assert _join_row(tenant, parent).params["draft"]["status"] == JOIN_FINAL_PENDING
    assert media.segments.encoded == 2 and media.segments.calls == []
    kept = [k for k in media.store.files if "/join-segment-" in k and k.endswith(".mp4")]
    assert len(kept) == 2  # in R2 under their fingerprints
    _worker_pass(service, tenant)  # resumes: only part 3 is encoded
    assert media.segments.encoded == 3
    assert _join_row(tenant, parent).params["draft"]["status"] == "final_ready"
    assert len(media.segments.calls) == 1


# ---------------------------------------------------------------------------
# review of 2026-11-08: changing a part of an approved video, retries, restore


def _final_jobs_status(tenant: UUID, child: UUID) -> list[str]:
    with tenant_session(tenant) as session:
        return list(
            session.execute(
                text("SELECT status FROM creative_jobs WHERE kind='final' AND draft_id=:d"),
                {"d": child},
            ).scalars()
        )


def _redo(parts, tenant: UUID, parent: UUID, user: UUID, index: int = 2) -> None:  # noqa: ANN001
    parts.regenerate_part(
        tenant_id=tenant,
        parent_id=parent,
        part_index=index,
        changes=PartChanges(description="Manos que sirven papas fritas."),
        user_id=user,
    )


def test_another_version_cancels_the_parts_queued_final_and_its_run_db(world) -> None:  # noqa: ANN001
    _, parts, _, tenant, brand, user, parent, ids = world
    left = _seconds_left(brand, tenant)
    _approve(world)
    _redo(parts, tenant, parent, user)
    assert _final_jobs_status(tenant, ids[1]) == ["cancelled"]
    assert _final_jobs_status(tenant, ids[0]) == ["queued"]  # the others keep theirs
    pending = _scalar(
        tenant,
        "SELECT count(*) FROM creative_pipeline_runs WHERE draft_id=:d "
        "AND phase LIKE 'final:%' AND dirty_version > prepared_version",
        d=ids[1],
    )
    assert pending == 0
    assert _seconds_left(brand, tenant) == left - 5 - 6  # part 2's 4 s back


def test_another_version_is_refused_while_the_parts_final_is_being_made_db(world) -> None:  # noqa: ANN001
    _, parts, _, tenant, brand, user, parent, ids = world
    _approve(world)
    left = _seconds_left(brand, tenant)
    from qualify_shared.db.creative_worker import creative_worker_session

    from qualify_api.creative import job_queue as q

    job = _scalar(
        tenant, "SELECT id FROM creative_jobs WHERE kind='final' AND draft_id=:d", d=ids[1]
    )
    with creative_worker_session() as session:  # the executor took it: paid, in flight
        claimed = q.claim_job(
            session,
            job_id=job,
            vendor_model=q.SEEDANCE_POOL,
            size=10,
            worker_id="ve10b",
            lease=timedelta(minutes=5),
            now=datetime(9999, 1, 2, tzinfo=UTC),  # past its unprepared night slot
        )
    assert claimed is not None
    with pytest.raises(PartChangeRefused) as refused:
        _redo(parts, tenant, parent, user)
    assert str(refused.value) == PART_FINAL_IN_FLIGHT_TEXT
    assert _status(tenant, parent) == APPROVED and _status(tenant, ids[1]) == APPROVED
    assert _seconds_left(brand, tenant) == left
    assert _final_jobs_status(tenant, ids[1]) == ["claimed"]


def test_an_old_finals_failure_never_refunds_the_new_revision_db(world) -> None:  # noqa: ANN001
    service, parts, _, tenant, brand, user, parent, ids = world
    _approve(world)
    with tenant_session(tenant) as session:
        old_asset = session.execute(
            text("SELECT id FROM image_assets WHERE draft_id=:d AND params ? 'draft'"),
            {"d": ids[1]},
        ).scalar()
    _redo(parts, tenant, parent, user)  # rev 1's 4 s come back here
    service.run_generation(tenant_id=tenant, draft_id=ids[1])
    _worker_pass(service, tenant)
    _worker_pass(service, tenant)
    _approve(world)  # charges rev 2
    after = _seconds_left(brand, tenant)
    # the old (rev 1) final reported failed late: it may only touch rev 1's charge
    service._refund_final_part(tenant, ids[1], "final_failed", (old_asset,))
    assert _seconds_left(brand, tenant) == after
    # the new final failing gives back rev 2's 4 s, once
    with tenant_session(tenant) as session:
        new_asset = session.execute(
            text("""
            SELECT a.id FROM image_assets a JOIN content_drafts d ON d.id=a.draft_id
            WHERE a.draft_id=:d AND a.version_id=d.active_version_id AND a.params ? 'draft'
            """),
            {"d": ids[1]},
        ).scalar()
    service._refund_final_part(tenant, ids[1], "final_failed", (new_asset,))
    service._refund_final_part(tenant, ids[1], "final_failed", (new_asset,))
    assert _seconds_left(brand, tenant) == after + 4


def test_a_scheduled_video_refuses_a_part_change_in_spanish_db(world) -> None:  # noqa: ANN001
    from qualify_api.connections.models import PlatformApp, SocialConnection
    from qualify_api.planner.models import CalendarEvent

    _, parts, _, tenant, brand, user, parent, _ = world
    _approve(world)
    with admin_session() as session:
        app = PlatformApp(app_id=f"ve10b-{uuid4()}", secret_ref="test", api_version="v21.0")
        session.add(app)
        session.flush()
        app_id = app.id
    with tenant_session(tenant) as session:
        connection = SocialConnection(
            tenant_id=tenant, platform_app_id=app_id, platform="instagram",
            account_type="business", external_account_id=str(uuid4()), linked_page_id="t",
            granted_scopes=[], status="active", access_posture="development",
            current_credential_version=0, connected_by_user_id=user,
        )  # fmt: skip
        session.add(connection)
        session.flush()
        session.add(
            CalendarEvent(
                tenant_id=tenant, brand_id=brand, post_id=parent, connection_id=connection.id,
                scheduled_at=datetime.now(UTC) + timedelta(days=1), scheduled_tz="UTC",
                status="scheduled", created_by_user_id=user,
            )
        )  # fmt: skip
    with pytest.raises(PartChangeRefused) as refused:
        _redo(parts, tenant, parent, user)
    assert str(refused.value) == PART_SCHEDULED_TEXT
    assert _status(tenant, parent) == APPROVED


def test_a_published_video_refuses_a_part_change_in_spanish_db(world) -> None:  # noqa: ANN001
    _, parts, _, tenant, _, user, parent, _ = world
    _approve(world)
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE content_drafts SET status='published' WHERE id=:p"), {"p": parent}
        )
    with pytest.raises(PartChangeRefused) as refused:
        _redo(parts, tenant, parent, user)
    assert str(refused.value) == PART_SCHEDULED_TEXT


def test_restoring_a_parts_version_of_an_approved_video_never_dead_ends_db(world) -> None:  # noqa: ANN001
    service, parts, _, tenant, brand, user, parent, ids = world
    with tenant_session(tenant) as session:
        first = session.execute(
            text("SELECT active_version_id FROM content_drafts WHERE id=:d"), {"d": ids[1]}
        ).scalar()
    _redo(parts, tenant, parent, user)
    service.run_generation(tenant_id=tenant, draft_id=ids[1])
    _worker_pass(service, tenant)
    _approve(world)  # parts 1, 2 (rev 2), 3 charged; finals queued
    left = _seconds_left(brand, tenant)
    service.restore_version(tenant_id=tenant, draft_id=ids[1], version_id=first)
    assert _status(tenant, parent) == GENERATED  # back to the gate, not a dead end
    assert _seconds_left(brand, tenant) == left + 4  # the unmade rev 2 final's seconds
    assert "queued" not in _final_jobs_status(tenant, ids[1])
    _worker_pass(service, tenant)
    _worker_pass(service, tenant)
    assert _join_row(tenant, parent).params["draft"]["status"] == "join_preview"
    _approve(world)
    assert _status(tenant, parent) == APPROVED


def test_a_part_that_always_kills_its_child_fails_the_join_after_three_tries_db(world) -> None:  # noqa: ANN001
    service, _, media, tenant, brand, _, parent, _ = world
    _approve(world)
    _worker_pass(service, tenant)  # the parts' finals
    left = _seconds_left(brand, tenant)
    from qualify_creative.video.join_child import WORKER_STOPPING

    WORKER_STOPPING.clear()  # a worker that is not stopping
    media.segments.crash = True  # an OOM kill every time
    for expected in (JOIN_FINAL_PENDING, JOIN_FINAL_PENDING, "failed"):
        _worker_pass(service, tenant)
        assert _join_row(tenant, parent).params["draft"]["status"] == expected
    block = _join_row(tenant, parent).params["draft"]
    assert block["child_losses"] == 3 and block["error"] == part_final.JOIN_FINAL_FAILED_TEXT
    # the run is done: no fourth try in the next pass, other work is not held up
    assert not _scalar(
        tenant,
        "SELECT dirty_version > prepared_version FROM creative_pipeline_runs "
        "WHERE draft_id=:p AND phase='join_final'",
        p=parent,
    )
    _worker_pass(service, tenant)
    assert _join_row(tenant, parent).params["draft"]["child_losses"] == 3
    assert _seconds_left(brand, tenant) == left
    # «Reintentar» starts again from zero
    media.segments.crash = False
    service.retry_final(tenant_id=tenant, draft_id=parent)
    assert _join_row(tenant, parent).params["draft"]["child_losses"] == 0
    _worker_pass(service, tenant)
    assert _join_row(tenant, parent).params["draft"]["status"] == "final_ready"


def test_a_failed_part_and_an_expired_part_say_so_in_spanish_db(world) -> None:  # noqa: ANN001
    _, _, _, tenant, _, _, parent, ids = world
    with tenant_session(tenant) as session:
        session.execute(
            text(
                "UPDATE content_drafts SET status='failed', failure_reason='provider_error' "
                "WHERE id=:d"
            ),
            {"d": ids[2]},
        )
    with pytest.raises(PartFailed) as failed:
        _approve(world)
    assert str(failed.value) == (
        "Una parte de tu video no salió. Pide otra versión de esa parte para poder aprobarlo."
    )
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE content_drafts SET status='generated' WHERE id=:d"), {"d": ids[2]}
        )
        session.execute(
            text("""
            UPDATE image_assets SET params = jsonb_set(params, '{draft,created_at}', '1000')
            WHERE draft_id=:d
            """),
            {"d": ids[0]},
        )
    with pytest.raises(DraftExpired) as expired:
        _approve(world)
    assert str(expired.value) == part_final.PART_EXPIRED_TEXT


def test_a_parts_final_rendering_inline_refuses_a_part_change_db(world) -> None:  # noqa: ANN001
    _, parts, _, tenant, brand, user, parent, ids = world
    _approve(world)
    left = _seconds_left(brand, tenant)
    with tenant_session(tenant) as session:  # inline/thread mode: no job, the block says it
        session.execute(
            text("""
            UPDATE image_assets SET params = jsonb_set(params, '{draft,status}', '"rendering"')
            WHERE draft_id = :d AND params ? 'draft'
            """),
            {"d": ids[1]},
        )
    with pytest.raises(PartChangeRefused) as refused:
        _redo(parts, tenant, parent, user)
    assert str(refused.value) == (
        "La versión final de esta parte se está preparando ahora. Cuando termine, podrás cambiarla."
    )
    assert _status(tenant, parent) == APPROVED and _seconds_left(brand, tenant) == left
    assert _final_jobs_status(tenant, ids[1]) == ["queued"]
