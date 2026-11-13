"""UI-8 (m-24921083), offline: «Me gusta así» reads «Lista» without charging or
approving anything, an expired or to-redo vista previa wins over the mark, the mark is
neither in the join's fingerprint nor in `approval_problem`, and the versions of a part
read «n de m» with each brief's own description and effective product photos. The
writes and reads under RLS are in `test_creative_part_review_db.py`."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest

from qualify_api.creative import part_review
from qualify_api.creative.fsm import APPROVED, GENERATED, REJECTED
from qualify_api.creative.part_final import approval_problem
from qualify_api.creative.part_join import join_fingerprint, part_span, ready_parts
from qualify_api.creative.part_progress import (
    PartState,
    derive_progress,
    derive_state,
    liked_mark,
    part_source,
)
from qualify_api.creative.part_review import (
    product_photos,
    version_expired,
    versions_from_rows,
)

from .test_creative_part_final import TENANT, _part, _snapshot
from .test_creative_part_progress import DAY, NOW, PARENT, facts

LIKED = {"status": "draft", "created_at": NOW - 60, "liked_at": NOW - 30}


# ---------------------------------------------------------------------------
# the row


def test_a_liked_part_to_review_reads_ready_with_no_action() -> None:
    for status in (GENERATED, REJECTED):
        row = derive_state(facts(status=status, preview=LIKED, liked=True), None, now=NOW)
        assert row.state is PartState.READY and row.liked and row.actions == ()
        assert row.has_preview


def test_without_the_mark_it_stays_to_review() -> None:
    row = derive_state(facts(status=GENERATED), None, now=NOW)
    assert row.state is PartState.TO_REVIEW and not row.liked


def test_an_approved_part_is_ready_and_liked_only_with_the_mark() -> None:
    plain = derive_state(facts(status=APPROVED), None, now=NOW)
    marked = derive_state(facts(status=APPROVED, preview=LIKED, liked=True), None, now=NOW)
    assert (plain.state, plain.liked) == (PartState.READY, False)
    assert (marked.state, marked.liked) == (PartState.READY, True)


def test_an_expired_preview_wins_over_the_mark() -> None:
    old = {"status": "draft", "created_at": NOW - 8 * DAY, "liked_at": NOW - 7.5 * DAY}
    row = derive_state(facts(status=GENERATED, preview=old, liked=True), None, now=NOW)
    assert row.state is PartState.EXPIRED and not row.liked


def test_a_part_to_redo_wins_over_the_mark() -> None:
    previous = facts(1, status=GENERATED, preview={"status": "draft", "created_at": NOW - 10})
    mine = facts(
        2,
        mode="extend",
        status=GENERATED,
        preview={"status": "draft", "created_at": NOW - 100, "liked_at": NOW - 50},
        liked=True,
    )
    row = derive_state(mine, previous, now=NOW)
    assert row.state is PartState.REDO and not row.liked


def test_a_liked_part_counts_among_the_parts_with_a_preview() -> None:
    progress = derive_progress(
        PARENT,
        [facts(1, status=GENERATED, preview=LIKED, liked=True), facts(2, status=GENERATED)],
        now=NOW,
    )
    assert [p.state for p in progress.parts] == [PartState.READY, PartState.TO_REVIEW]
    assert progress.with_preview == 2 and progress.parts[0].liked


def test_the_row_says_where_the_part_comes_from_in_the_reel() -> None:
    analysis = uuid4()
    row = derive_state(
        facts(status=GENERATED, analysis_id=analysis, shot_indexes=(2, 3)), None, now=NOW
    )
    assert (row.analysis_id, row.shot_indexes) == (analysis, (2, 3))
    assert part_source({"analysis_id": str(analysis), "shot_indexes": [2, 3]}) == {
        "analysis_id": analysis,
        "shot_indexes": (2, 3),
    }
    assert part_source({"shot_indexes": [1]}) == {"analysis_id": None, "shot_indexes": ()}
    assert part_source({"analysis_id": "nope"})["analysis_id"] is None


def test_liked_mark_reads_only_a_positive_number() -> None:
    assert liked_mark({"liked_at": 1_800_000_000})
    assert not liked_mark({"liked_at": True})
    assert not liked_mark({"liked_at": "1800000000"})
    assert not liked_mark({}) and not liked_mark(None)


# ---------------------------------------------------------------------------
# the mark never changes the join nor the approval


def _liked(part: Any) -> Any:
    params = dict(part.params)
    params["draft"] = {**dict(params["draft"]), "liked_at": int(NOW)}
    return replace(part, params=params)


def test_the_mark_is_not_in_the_joins_fingerprint() -> None:
    parts = (_part(1), _part(2))
    marked = (_liked(parts[0]), parts[1])
    spans = [part_span(p.params) for p in parts]
    assert join_fingerprint(parts, spans) == join_fingerprint(
        marked, [part_span(p.params) for p in marked]
    )
    assert ready_parts(_snapshot(*marked), TENANT) is not None


def test_the_mark_does_not_change_whether_the_video_can_be_approved() -> None:
    parts = (_part(1), _part(2), _part(3))
    snapshot = _snapshot(*parts)
    marked = _snapshot(_liked(parts[0]), parts[1], parts[2])
    assert approval_problem(snapshot, TENANT) is None
    # the same joined preview block: the fingerprint did not move
    marked = replace(
        marked,
        joined_block=snapshot.joined_block,
        joined_fingerprint=snapshot.joined_fingerprint,
    )
    assert approval_problem(marked, TENANT) is None


# ---------------------------------------------------------------------------
# the versions


def _media(description: str, keys: list[str], roles: list[str] | None = None) -> dict:
    media: dict[str, Any] = {
        "part": {"mode": "reference", "description": description},
        "clip_image_keys": keys,
    }
    if roles is not None:
        media["clip_image_roles"] = roles
    return media


def _row(revision: int, *, current: bool = False, **kw: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": uuid4(),
        "revision": revision,
        "current": current,
        "media": _media(f"Versión {revision}", [f"k{revision}.jpg"]),
        "object_key": f"t/x/generated/d/r{revision}/clip.mp4",
        "block": {"status": "draft", "created_at": NOW - 60},
        "thumbnail_key": f"t/x/generated/d/r{revision}/first-frame.jpg",
        "preview_key": "t/x/generated/d/r9/active.jpg",
        "video_seconds": "4.5",
        "purged": False,
    }
    row.update(kw)
    return row


def test_versions_read_n_of_m_with_each_briefs_description() -> None:
    rows = [
        _row(1, block={"status": "draft", "created_at": NOW - 60, "liked_at": NOW - 50}),
        _row(3, current=True, thumbnail_key=None),
    ]
    first, second = versions_from_rows(rows, NOW)
    assert (first.ordinal, first.total, first.current) == (1, 2, False)
    assert (second.ordinal, second.total, second.current) == (2, 2, True)
    assert (first.description, second.description) == ("Versión 1", "Versión 3")
    assert first.photo_keys == ("k1.jpg",) and first.liked and not second.liked
    assert first.poster_key == "t/x/generated/d/r1/first-frame.jpg"
    # only the active version falls back to the draft's picture
    assert second.poster_key == "t/x/generated/d/r9/active.jpg"
    assert first.seconds == 4.5 and first.mode == "reference"
    assert not first.expired


def test_a_version_without_a_file_or_past_its_days_is_expired() -> None:
    old = {"status": "draft", "created_at": NOW - 8 * DAY}
    gone, late, purged = versions_from_rows(
        [_row(1, object_key=None), _row(2, block=old), _row(3, purged=True)], NOW
    )
    assert gone.expired and late.expired and purged.expired
    assert not version_expired(object_key="k.mp4", block=None, purged=False, now=NOW)


def test_photos_are_the_effective_product_ones() -> None:
    assert product_photos(_media("", ["a.jpg", "b.jpg"])) == ("a.jpg", "b.jpg")
    assert product_photos(_media("", ["a.jpg", "s.jpg"], ["product", "scene"])) == ("a.jpg",)
    # roles that do not match in number: every one the product (as `parent_images`)
    assert product_photos(_media("", ["a.jpg", "b.jpg"], ["scene"])) == ("a.jpg", "b.jpg")
    assert product_photos(_media("", ["a.jpg", "a.jpg"])) == ("a.jpg",)
    assert product_photos({}) == () and product_photos(None) == ()


def test_every_photo_of_the_brief_in_its_order() -> None:
    """Review of UI-8: «Crear otra versión» keeps the place and style photos, so the
    fields carry every photo of the active brief, in order, whatever its role."""
    from qualify_api.creative.part_review import image_keys

    media = _media("", ["l.jpg", "a.jpg", "m.jpg", "a.jpg"], ["place", "product", "style"])
    assert image_keys(media) == ("l.jpg", "a.jpg", "m.jpg")
    assert image_keys({}) == () and image_keys(None) == ()


# ---------------------------------------------------------------------------
# a removed part, and `restore`'s own refusals (offline: the reads are stubbed)


class _Session:
    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _stub_child(monkeypatch: pytest.MonkeyPatch, *, removed: bool) -> None:
    monkeypatch.setattr(part_review, "tenant_session", lambda tenant: _Session())
    monkeypatch.setattr(part_review, "_child", lambda s, p, i: (uuid4(), removed))


def _use(version_id: UUID, content: object = None) -> None:
    part_review.use_part_version(
        tenant_id=TENANT,
        parent_id=PARENT,
        part_index=1,
        version_id=version_id,
        user_id=uuid4(),
        content=content,  # type: ignore[arg-type]
    )


def test_a_removed_part_has_no_versions_and_none_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_child(monkeypatch, removed=True)
    assert part_review.part_versions(tenant_id=TENANT, parent_id=PARENT, part_index=1) == ()
    with pytest.raises(part_review.PartNotReviewable) as refused:
        _use(uuid4())
    assert refused.value.reason == "not_reviewable"


class _Restore:
    def __init__(self, error: Exception | None) -> None:
        self.error = error
        self.calls = 0

    def restore_version(self, **kw: object) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error


@pytest.mark.parametrize(
    ("said", "reason"),
    [
        ("Cancela la programación antes de cambiar la versión.", "scheduled"),
        ("Espera a que termine la generación antes de usar otra versión.", "busy"),
        ("Los archivos de esta publicación ya no están disponibles.", "purged"),
        ("Esta versión no está disponible.", "unknown_version"),
    ],
)
def test_restores_own_refusals_reach_the_owner(
    monkeypatch: pytest.MonkeyPatch, said: str, reason: str
) -> None:
    """Review of UI-8: `versions.restore` refuses in the owner's words — they are kept,
    never turned into the generic failure."""
    _stub_child(monkeypatch, removed=False)
    chosen = uuid4()
    version = versions_from_rows([_row(1, id=chosen)], NOW)[0]
    monkeypatch.setattr(part_review, "part_versions", lambda **kw: (version,))
    with pytest.raises(part_review.PartNotReviewable) as refused:
        _use(chosen, _Restore(ValueError(said)))
    assert refused.value.reason == reason
    assert str(refused.value) == part_review.NOT_REVIEWABLE_TEXTS[reason]
    # anything else is not dressed up as a refusal
    with pytest.raises(ValueError, match="unknown draft status"):
        _use(chosen, _Restore(ValueError("unknown draft status 'x'")))
    content = _Restore(None)
    _use(chosen, content)
    assert content.calls == 1


def test_the_expired_text_names_the_real_button() -> None:
    assert part_review.NOT_REVIEWABLE_TEXTS["expired"] == (
        "Esta vista previa venció. Crea otra versión."
    )


def test_the_reels_account_is_read_from_public_reels(monkeypatch: pytest.MonkeyPatch) -> None:
    """m-24921083: «Video de inspiración» names the reel's account from `public_reels`
    (no vendor call), through the business's own door."""
    seen: list[dict[str, object]] = []

    class _Reels(_Session):
        def scalar(self, statement: object, params: dict[str, object]) -> str:
            seen.append(params)
            return " thegoldenbalance "

    monkeypatch.setattr(part_review, "tenant_session", lambda tenant: _Reels())
    handle = part_review.reel_account(tenant_id=TENANT, network="tiktok", post_id="77")
    assert handle == "thegoldenbalance" and seen == [{"n": "tiktok", "r": "77"}]
    assert part_review.reel_account(tenant_id=TENANT, network="", post_id="77") == ""
