"""Offline tests for the «Publicar» backfill (m-25019220): the matching rule, the bursts it
must survive, the permalink filler's bounds, and the tick hook. No database, no R2, no
Graph — fakes only. The end-to-end runs are in `test_publish_backfill_db.py`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.objects.gate import StoredObject

from qualify_api.inbox.media_client import MediaReadError, MediaSummary
from qualify_api.planner import permalinks
from qualify_api.planner.permalinks import (
    RETRY_BANDS,
    Outcome,
    PermalinkResult,
    PermalinkTarget,
    fill_permalinks,
    instagram_permalink,
)
from qualify_api.planner.publish_backfill import (
    fits,
    is_publicar_file,
    main,
    match_single,
    sniff,
    window_for,
)
from qualify_api.planner.tick import TickRunner

TENANT = UUID("00000000-0000-0000-0000-0000000000a1")
CONN = UUID("00000000-0000-0000-0000-0000000000c1")
FOLDER = f"t/{TENANT}/media/{CONN}/"
T0 = datetime(2026, 11, 13, 15, 0, tzinfo=UTC)
JPEG = "image/jpeg"


def _obj(name: str, at: datetime, size: int = 500_000) -> StoredObject:
    return StoredObject(key=FOLDER + name, size=size, last_modified=at)


def _hex() -> str:
    return uuid4().hex


# -- bytes and names ------------------------------------------------------------------------


def test_sniff_tells_the_formats_publicar_stages() -> None:
    assert sniff(b"\xff\xd8\xff\xe0" + b"\0" * 12) == "image/jpeg"
    assert sniff(b"\0\0\0\x18ftypisom" + b"\0" * 4) == "video/mp4"
    assert sniff(b"\0\0\0\x14ftypqt  " + b"\0" * 4) == "video/quicktime"
    assert sniff(b"\x89PNG\r\n\x1a\n") == "image/png"
    assert sniff(b"RIFF\0\0\0\0WEBPVP8 ") == "image/webp"
    assert sniff(b"hello") is None


def test_only_a_32_hex_name_in_the_connection_folder_is_a_publicar_file() -> None:
    assert is_publicar_file(FOLDER + _hex(), FOLDER)
    assert not is_publicar_file(FOLDER + "dm-" + _hex(), FOLDER)  # a DM attachment
    assert not is_publicar_file(FOLDER + "ig-1789", FOLDER)  # our own Instagram copy
    assert not is_publicar_file(FOLDER + str(uuid4()), FOLDER)  # dashed: not uuid4().hex
    assert not is_publicar_file(f"t/{TENANT}/media/{uuid4()}/{_hex()}", FOLDER)


def test_fits_checks_the_type_and_the_image_cap() -> None:
    assert fits("IMAGE", JPEG, 8 * 1024 * 1024)
    assert not fits("IMAGE", JPEG, 8 * 1024 * 1024 + 1)
    assert not fits("IMAGE", "video/mp4", 10)
    assert not fits("IMAGE", "image/png", 10)
    assert fits("REELS", "video/mp4", 10**8)
    assert not fits("REELS", JPEG, 10)
    assert fits("STORIES", JPEG, 10) and fits("STORIES", "video/quicktime", 10)
    assert not fits("IMAGE", None, 10)


# -- the window -----------------------------------------------------------------------------


def test_the_window_reaches_back_120s_without_a_previous_attempt() -> None:
    assert window_for(T0, None) == (T0 - timedelta(seconds=120), T0 + timedelta(seconds=5))


def test_the_window_starts_5s_after_the_previous_attempt_started() -> None:
    previous = T0 - timedelta(seconds=30)
    assert window_for(T0, previous) == (previous + timedelta(seconds=5), T0 + timedelta(seconds=5))


def test_consecutive_windows_never_overlap() -> None:
    starts = [T0 + timedelta(seconds=s) for s in (0, 3, 40, 41, 300)]
    windows = [window_for(s, starts[i - 1] if i else None) for i, s in enumerate(starts)]
    for (_, high), (low, _) in zip(windows, windows[1:], strict=False):
        assert high <= low  # (low, high] intervals: touching is not overlapping


# -- the rule -------------------------------------------------------------------------------


def _match(  # noqa: ANN202
    objects,  # noqa: ANN001
    *,
    start=T0,  # noqa: ANN001
    previous=None,  # noqa: ANN001
    following=None,  # noqa: ANN001
    referenced=(),  # noqa: ANN001
    types=None,  # noqa: ANN001
    product="IMAGE",  # noqa: ANN001
):
    types = types if types is not None else {o.key: JPEG for o in objects}
    return match_single(
        product=product,
        started_at=start,
        previous_start=previous,
        next_start=following,
        objects=objects,
        folder=FOLDER,
        referenced=set(referenced),
        content_types=types,
    )


def _around(starts: list[datetime], i: int) -> dict[str, datetime | None]:
    return {
        "start": starts[i],
        "previous": starts[i - 1] if i else None,
        "following": starts[i + 1] if i + 1 < len(starts) else None,
    }


def test_neighbours_closer_than_30s_make_any_match_doubtful() -> None:
    staged = _obj(_hex(), T0 - timedelta(seconds=2))
    assert _match([staged], previous=T0 - timedelta(seconds=30)).clear
    assert not _match([staged], previous=T0 - timedelta(seconds=29)).clear
    assert not _match([staged], following=T0 + timedelta(seconds=10)).clear
    assert "next attempt" in _match([staged], following=T0 + timedelta(seconds=10)).reason


def test_one_unreferenced_jpeg_in_the_window_is_a_clear_match() -> None:
    staged = _obj(_hex(), T0 - timedelta(seconds=2))
    match = _match([staged, _obj(_hex(), T0 - timedelta(minutes=10))])  # second: too early
    assert match.clear and match.key == staged.key and match.content_type == JPEG


def test_two_candidates_are_doubtful_never_a_guess() -> None:
    match = _match(
        [_obj(_hex(), T0 - timedelta(seconds=2)), _obj(_hex(), T0 - timedelta(seconds=9))]
    )
    assert not match.clear and "2 unreferenced" in match.reason


def test_no_candidate_is_doubtful() -> None:
    assert not _match([]).clear


def test_a_referenced_file_is_never_matched_again() -> None:
    staged = _obj(_hex(), T0 - timedelta(seconds=2))
    assert not _match([staged], referenced=[staged.key]).clear


def test_a_dm_attachment_or_our_copy_never_counts() -> None:
    staged = _obj(_hex(), T0 - timedelta(seconds=2))
    noise = [_obj("dm-" + _hex(), T0 - timedelta(seconds=1)), _obj("ig-17", T0)]
    assert _match([staged, *noise]).key == staged.key


def test_a_file_whose_bytes_do_not_fit_the_type_is_doubtful() -> None:
    staged = _obj(_hex(), T0 - timedelta(seconds=2))
    assert not _match([staged], types={staged.key: "video/mp4"}).clear
    assert not _match([staged], types={staged.key: None}).clear
    big = _obj(_hex(), T0 - timedelta(seconds=2), size=9 * 1024 * 1024)
    assert not _match([big]).clear
    assert _match([staged], types={staged.key: "video/mp4"}, product="REELS").clear


def test_a_file_without_a_date_is_never_matched() -> None:
    assert not _match([StoredObject(key=FOLDER + _hex(), size=1, last_modified=None)]).clear


@pytest.mark.parametrize("gap_seconds", [30, 45, 180])
def test_a_burst_gives_each_attempt_its_own_file_and_none_twice(gap_seconds: int) -> None:
    """The founder's 9 images, «Una por una»: each file staged ~1-3 s before its attempt
    started, the next attempt `gap_seconds` later."""
    starts = [T0 + timedelta(seconds=gap_seconds * i) for i in range(9)]
    staged = [
        _obj(_hex(), start - timedelta(seconds=1 + (i % 3))) for i, start in enumerate(starts)
    ]
    matched: list[str] = []
    for i, start in enumerate(starts):
        match = _match(staged, **_around(starts, i))
        assert match.clear, match.reason
        matched.append(match.key or "")
    assert matched == [obj.key for obj in staged]
    assert len(set(matched)) == 9


@pytest.mark.parametrize("gap_seconds", [1, 4, 8, 12, 29])
def test_a_tight_burst_is_doubtful_where_files_crowd_but_never_wrong(gap_seconds: int) -> None:
    """Attempts under 30 s apart: the 5 s clock tolerance could put the NEXT file inside
    a window while the attempt's own file sits just before it — so none is trusted."""
    starts = [T0 + timedelta(seconds=gap_seconds * i) for i in range(9)]
    staged = [_obj(_hex(), start - timedelta(seconds=1)) for start in starts]
    seen: set[str] = set()
    for i, start in enumerate(starts):
        match = _match(staged, **_around(starts, i))
        assert not match.clear
        assert match.key is None and match.key not in seen


def test_a_burst_with_a_stray_upload_falls_back_only_where_it_landed() -> None:
    starts = [T0 + timedelta(seconds=40 * i) for i in range(3)]
    staged = [_obj(_hex(), start - timedelta(seconds=1)) for start in starts]
    stray = _obj(_hex(), starts[1] - timedelta(seconds=10))  # an upload that never started
    results = [_match([*staged, stray], **_around(starts, i)) for i, start in enumerate(starts)]
    assert [r.clear for r in results] == [True, False, True]


# -- the permalink --------------------------------------------------------------------------


def test_only_an_https_instagram_address_is_a_permalink() -> None:
    assert (
        instagram_permalink("https://www.instagram.com/p/Cx1/")
        == "https://www.instagram.com/p/Cx1/"
    )
    assert instagram_permalink("https://instagram.com/reel/x/") == "https://instagram.com/reel/x/"
    for bad in (
        "",
        None,
        "http://www.instagram.com/p/x/",
        "https://evil.example/p/x/",
        "javascript:alert(1)",
        "https://www.instagram.com.evil.example/p/",
    ):
        assert instagram_permalink(bad) is None


def test_retry_bands_end_after_a_day() -> None:
    assert RETRY_BANDS[0][0] == timedelta(0)
    assert max(end for _, end in RETRY_BANDS) <= timedelta(hours=24, minutes=3)
    total = sum((end - start).total_seconds() for start, end in RETRY_BANDS) / 60
    assert total <= 20  # at most ~19 reads at one tick per minute


class _Reader:
    def __init__(self, answers: dict[str, MediaSummary | Exception]) -> None:
        self.answers = answers
        self.reads: list[str] = []

    async def get_media(self, *, media_id: str) -> MediaSummary:
        self.reads.append(media_id)
        answer = self.answers[media_id]
        if isinstance(answer, Exception):
            raise answer
        return answer


class _Budget:
    def __init__(self, left: int) -> None:
        self.left = left
        self.spent = 0

    def remaining(self, *, tenant_id: UUID, connection_id: UUID, now: datetime) -> int:
        return self.left - self.spent

    def spend(self, *, tenant_id: UUID, connection_id: UUID, now: datetime) -> None:
        self.spent += 1


def _summary(media_id: str, permalink: str | None) -> MediaSummary:
    return MediaSummary(id=media_id, timestamp=T0, permalink=permalink)


@pytest.fixture
def stored(monkeypatch: pytest.MonkeyPatch) -> dict[UUID, str]:
    written: dict[UUID, str] = {}

    def fake_store(*, tenant_id: UUID, attempt_id: UUID, permalink: str | None) -> Outcome:
        clean = instagram_permalink(permalink)
        if clean is None:
            return Outcome.IGNORED
        if attempt_id in written:
            return Outcome.ALREADY
        written[attempt_id] = clean
        return Outcome.FILLED

    monkeypatch.setattr(permalinks, "store_permalink", fake_store)
    return written


async def test_the_filler_stores_instagram_addresses_and_ignores_the_rest(stored) -> None:  # noqa: ANN001
    targets = [PermalinkTarget(uuid4(), CONN, m) for m in ("1", "2", "3", "4")]
    reader = _Reader(
        {
            "1": _summary("1", "https://www.instagram.com/p/A/"),
            "2": _summary("2", None),
            "3": _summary("3", "https://evil.example/p/"),
            "4": MediaReadError("gone", http_status=400, platform_code=100),
        }
    )
    factory_calls: list[UUID] = []

    async def readers(tenant_id: UUID, connection_id: UUID) -> _Reader:
        factory_calls.append(connection_id)
        return reader

    results = await fill_permalinks(
        targets, tenant_id=TENANT, now=T0, readers=readers, budget=_Budget(10)
    )
    assert [r.outcome for r in results] == [
        Outcome.FILLED,
        Outcome.IGNORED,
        Outcome.IGNORED,
        Outcome.UNREADABLE,
    ]
    assert stored == {targets[0].attempt_id: "https://www.instagram.com/p/A/"}
    assert factory_calls == [CONN]  # one reader per connection


async def test_the_filler_never_reads_past_the_budget(stored) -> None:  # noqa: ANN001
    targets = [PermalinkTarget(uuid4(), CONN, str(i)) for i in range(3)]
    reader = _Reader({str(i): _summary(str(i), f"https://instagram.com/p/{i}/") for i in range(3)})

    async def readers(tenant_id: UUID, connection_id: UUID) -> _Reader:
        return reader

    budget = _Budget(2)
    results = await fill_permalinks(
        targets, tenant_id=TENANT, now=T0, readers=readers, budget=budget
    )
    assert [r.outcome for r in results] == [Outcome.FILLED, Outcome.FILLED, Outcome.NO_BUDGET]
    assert reader.reads == ["0", "1"] and budget.spent == 2


async def test_a_connection_that_cannot_be_read_costs_only_its_targets(stored) -> None:  # noqa: ANN001
    other = uuid4()
    targets = [PermalinkTarget(uuid4(), CONN, "1"), PermalinkTarget(uuid4(), other, "2")]
    reader = _Reader({"2": _summary("2", "https://instagram.com/p/B/")})

    async def readers(tenant_id: UUID, connection_id: UUID) -> _Reader:
        if connection_id == CONN:
            raise PermissionError("revoked")
        return reader

    results = await fill_permalinks(
        targets, tenant_id=TENANT, now=T0, readers=readers, budget=_Budget(5)
    )
    assert [r.outcome for r in results] == [Outcome.NO_READER, Outcome.FILLED]


# -- the tick hook --------------------------------------------------------------------------


class _NoEvents:
    def list_in_flight(self, *, tenant_id: UUID, limit: int = 100) -> list[object]:
        return []

    def list_due(self, *, tenant_id: UUID, now: datetime, limit: int = 100) -> list[object]:
        return []


class _Tenants:
    def tenants(self, *, now: datetime) -> list[UUID]:
        return [TENANT]


async def test_the_tick_fills_permalinks_per_tenant_and_survives_a_failure() -> None:
    calls: list[UUID] = []

    async def fill(*, tenant_id: UUID, now: datetime) -> list[PermalinkResult]:
        calls.append(tenant_id)
        return [PermalinkResult(uuid4(), Outcome.FILLED), PermalinkResult(uuid4(), Outcome.IGNORED)]

    runner = TickRunner(
        tenants=_Tenants(),
        repository=_NoEvents(),  # type: ignore[arg-type]
        executor=object(),  # type: ignore[arg-type]
        clock=lambda: T0,
        permalinks=fill,
    )
    report = await runner.run_once()
    assert calls == [TENANT] and report.tenants[0].operations == 1

    async def broken(*, tenant_id: UUID, now: datetime) -> list[PermalinkResult]:
        raise RuntimeError("graph down")

    runner = TickRunner(
        tenants=_Tenants(),
        repository=_NoEvents(),  # type: ignore[arg-type]
        executor=object(),  # type: ignore[arg-type]
        clock=lambda: T0,
        permalinks=broken,
    )
    report = await runner.run_once()
    assert report.tenants[0].errors == ["permalinks:RuntimeError"]


# -- the CLI --------------------------------------------------------------------------------


def test_the_cli_requires_a_tenant(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main([], deps=object())  # type: ignore[arg-type]
    assert "--tenant" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["--limit", "0"],
        ["--limit", "501"],
        ["--probe", "--execute"],
        ["--attempt", str(uuid4())],
    ],
)
def test_the_cli_refuses_contradictory_flags(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--tenant", str(TENANT), *argv], deps=object())  # type: ignore[arg-type]
