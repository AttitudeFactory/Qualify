"""«Fotos y videos de tu negocio» (CM-2, m-24955919): the texts and states of the
section, from the plain records the service returns. Pure — no Reflex, no database.

Pins (`docs/epica-galeria-medios-negocio.md` §5 CM-2):
1. The copy is the epic's, verbatim; the service's refusals are its own sentences.
2. A video being prepared (or that failed) is a tile of its own, read from the job, and
   can be neither chosen (CM-5) nor cut (CM-4); a failed one offers «Quitar».
3. Leaving mid-upload leaves nothing behind; leaving while «Preparando…» keeps the tile
   (it comes from the job), and the video replaces it once the job is done.
4. Every medium shows its thumbnail, a video its length («0:42») and a spoken label.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from qualify_api.catalog.business_media import (
    GALLERY_FULL_TEXT,
    PHOTO_TOO_HEAVY_TEXT,
    VIDEO_TOO_HEAVY_TEXT,
    VIDEOS_WAITING_TEXT,
)

from .catalog_gallery_vm import (
    ADD_LABEL,
    CUTTING_TEXT,
    FAILED_TEXT,
    GALLERY_DESCRIPTION,
    GALLERY_EMPTY,
    GALLERY_TITLE,
    PREPARING_TEXT,
    REMOVE_DESCRIPTION,
    TRIMMED_TEXT,
    UPLOAD_CUT_TEXT,
    OutcomeRow,
    build_gallery_items,
    count_videos,
    duration_label,
    duration_spoken,
    outcome_messages,
    rejection_text,
    remove_title,
    trimmed_job_ids,
    upload_text,
    videos_waiting,
)

_T0 = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class _Media:
    id: UUID
    media_type: str
    object_key: str
    poster_key: str | None = None
    duration_ms: int | None = None
    created_at: datetime = _T0


@dataclass(frozen=True)
class _Job:
    id: UUID
    kind: str = "ingest"
    status: str = "queued"
    source_media_id: UUID | None = None
    media_id: UUID | None = None
    trimmed: bool = False


def _url(key: str, kind: str) -> str:
    return f"/r2media/{kind}:{key}"


_PHOTO = _Media(UUID(int=1), "image", "t/x/gallery/1/photo.jpg")
_VIDEO = _Media(UUID(int=2), "video", "t/x/gallery/2/video.mp4", "t/x/gallery/2/poster.jpg", 42_000)


def test_the_copy_is_the_epics() -> None:
    assert GALLERY_TITLE == "Fotos y videos de tu negocio"
    assert GALLERY_DESCRIPTION == (
        "Muestra tu local, tu equipo y cómo trabajas. Úsalas en tus publicaciones."
    )
    assert ADD_LABEL == "Agregar fotos o videos"
    assert UPLOAD_CUT_TEXT == "Se cortó la subida. Revisa tu conexión y vuelve a intentarlo."
    assert PREPARING_TEXT == (
        "Preparando tu video… Puedes salir; aparecerá aquí cuando esté listo."
    )
    assert FAILED_TEXT == "No pudimos preparar este video. Súbelo otra vez."
    assert VIDEO_TOO_HEAVY_TEXT == "Ese video es muy pesado. Prueba con uno más corto."
    assert VIDEOS_WAITING_TEXT == (
        "Ya estamos preparando 3 videos. Cuando termine uno, podrás subir el siguiente."
    )
    assert TRIMMED_TEXT == (
        "Tu video dura más de un minuto y guardamos solo el primero. Si quieres otra "
        "parte, recórtala en tu teléfono antes de subirla."
    )
    assert GALLERY_EMPTY == (
        "Todavía no tienes fotos ni videos de tu negocio. Sube algunas de tu local, tu "
        "equipo o tu trabajo."
    )
    assert remove_title("video") + " " + REMOVE_DESCRIPTION == (
        "¿Quitar este video de tu Galería? Las publicaciones que ya hiciste no cambian."
    )
    assert remove_title("image") == "¿Quitar esta foto de tu Galería?"


def test_the_upload_says_its_real_percentage() -> None:
    assert upload_text(45, videos=1, photos=0) == (
        "Subiendo tu video (45 %). Deja esta pantalla abierta hasta que termine."
    )
    assert upload_text(7, videos=0, photos=1).startswith("Subiendo tu foto (7 %).")
    assert upload_text(10, videos=0, photos=3).startswith("Subiendo tus fotos (10 %).")
    assert upload_text(10, videos=2, photos=0).startswith("Subiendo tus videos (10 %).")
    assert upload_text(150, videos=1, photos=2).startswith("Subiendo tus fotos y videos (100 %).")


def test_media_show_their_thumbnail_length_and_a_spoken_label() -> None:
    photo, video = build_gallery_items([_PHOTO, _VIDEO], [], _url)
    assert photo.state == "ready" and photo.media_type == "image"
    assert photo.thumb_url == "/r2media/image:t/x/gallery/1/photo.jpg"
    assert photo.video_url == "" and photo.duration == ""
    assert photo.label == "Foto de tu negocio"
    assert video.thumb_url == "/r2media/image:t/x/gallery/2/poster.jpg"
    assert video.video_url == "/r2media/video:t/x/gallery/2/video.mp4"
    assert video.duration == "0:42" and video.label == "Video de 42 segundos"
    assert all(i.can_remove and i.selectable for i in (photo, video))
    assert video.cuttable and not photo.cuttable


def test_a_preparing_or_failed_video_can_neither_be_chosen_nor_cut() -> None:
    preparing = _Job(UUID(int=10), status="running")
    failed = _Job(UUID(int=11), status="failed")
    items = build_gallery_items([_PHOTO], [preparing, failed], _url)
    first, second, last = items
    # what is pending sits first, right under the button
    assert (first.state, first.note, first.note_tone) == ("preparing", PREPARING_TEXT, "info")
    assert (second.state, second.note, second.note_tone) == ("failed", FAILED_TEXT, "error")
    for tile in (first, second):
        assert not tile.selectable and not tile.cuttable
        assert tile.media_type == "video" and tile.thumb_url == ""
    assert not first.can_remove  # nothing to take away while media-worker works
    assert second.can_remove and second.job_id == str(failed.id)  # «Quitar» on a failure
    assert last.media_id == str(_PHOTO.id)


def test_a_video_being_cut_cannot_be_removed_or_chosen() -> None:
    cut = _Job(UUID(int=12), kind="cut", status="running", source_media_id=_VIDEO.id)
    (video,) = build_gallery_items([_VIDEO], [cut], _url)
    assert video.state == "cutting" and video.note == CUTTING_TEXT
    assert not video.can_remove and not video.selectable and not video.cuttable


def test_leaving_mid_upload_leaves_nothing_and_preparing_survives_a_reload() -> None:
    # «Subiendo…» cut short: the service kept no job and no medium, so a fresh read after
    # coming back shows the Galería as it was — the owner simply uploads it again.
    before = build_gallery_items([_PHOTO], [], _url)
    after_leaving = build_gallery_items([_PHOTO], [], _url)
    assert after_leaving == before
    # «Preparando…»: the tile comes from the job, so a reload (or a deploy) shows it again
    job = _Job(UUID(int=20), status="queued")
    reloaded = build_gallery_items([_PHOTO], [job], _url)
    assert reloaded[0].state == "preparing" and reloaded[0].key == f"job-{job.id}"
    # …and once media-worker is done the video replaces the tile
    done = _Job(UUID(int=20), status="done", media_id=_VIDEO.id)
    finished = build_gallery_items([_PHOTO, _VIDEO], [done], _url)
    assert [i.state for i in finished] == ["ready", "ready"]
    assert finished[1].media_id == str(_VIDEO.id)


def test_videos_waiting_counts_only_active_uploads() -> None:
    jobs = [
        _Job(UUID(int=1), status="queued"),
        _Job(UUID(int=2), status="running"),
        _Job(UUID(int=3), status="failed"),
        _Job(UUID(int=4), status="done", media_id=UUID(int=9)),
        _Job(UUID(int=5), kind="cut", status="running", source_media_id=UUID(int=9)),
    ]
    assert videos_waiting(jobs) == 2


def test_the_over_a_minute_notice_follows_finished_trimmed_uploads() -> None:
    jobs = [
        _Job(UUID(int=1), status="done", media_id=UUID(int=9), trimmed=True),
        _Job(UUID(int=2), status="done", media_id=UUID(int=8), trimmed=False),
        _Job(UUID(int=3), status="running", trimmed=True),
    ]
    assert trimmed_job_ids(jobs) == [str(UUID(int=1))]


def test_durations_read_and_sound_like_minutes_and_seconds() -> None:
    assert duration_label(42_000) == "0:42"
    assert duration_label(60_000) == "1:00"
    assert duration_label(None) == ""
    assert duration_spoken(1_000) == "1 segundo"
    assert duration_spoken(60_000) == "1 minuto"
    assert duration_spoken(65_400) == "1 minuto y 5 segundos"


def test_videos_are_counted_by_name_like_the_service_stages_them() -> None:
    picked = [{"name": "IMG_1.MOV"}, {"name": "clip.mp4"}, {"name": "foto.heic"}, {"path": "a.m4v"}]
    assert count_videos(picked) == 3


def test_refused_picks_say_why_in_the_owners_words() -> None:
    too_big_video = {"file": {"path": "IMG_9.MOV"}, "errors": [{"code": "file-too-large"}]}
    too_big_photo = {"file": {"path": "foto.jpg"}, "errors": [{"code": "file-too-large"}]}
    wrong = {"file": {"path": "menu.pdf"}, "errors": [{"code": "file-invalid-type"}]}
    assert rejection_text([too_big_video]) == VIDEO_TOO_HEAVY_TEXT
    assert rejection_text([too_big_photo]) == PHOTO_TOO_HEAVY_TEXT
    assert "no es una foto ni un video" in rejection_text([wrong])
    assert rejection_text([]) == ""


def test_upload_outcomes_name_each_file_only_when_there_are_several() -> None:
    one = [OutcomeRow("IMG_1.MOV", error_text=VIDEO_TOO_HEAVY_TEXT, is_video=True)]
    assert outcome_messages(one) == (VIDEO_TOO_HEAVY_TEXT, "")
    many = [
        OutcomeRow("a.jpg"),
        OutcomeRow("b.mov", error_text=GALLERY_FULL_TEXT, is_video=True),
        OutcomeRow("c.mov", error_text=GALLERY_FULL_TEXT, is_video=True),
    ]
    error, info = outcome_messages(many)
    assert error == f"b.mov: {GALLERY_FULL_TEXT} · c.mov: {GALLERY_FULL_TEXT}"
    assert info == ""
    dup = [OutcomeRow("a.jpg", duplicate=True)]
    assert outcome_messages(dup) == ("", "Esa foto ya estaba en tu Galería.")
    assert outcome_messages([OutcomeRow("v.mp4", duplicate=True, is_video=True)])[1] == (
        "Ese video ya estaba en tu Galería."
    )


def test_no_english_and_no_codes_in_what_the_owner_reads() -> None:
    texts = [
        GALLERY_TITLE,
        GALLERY_DESCRIPTION,
        ADD_LABEL,
        UPLOAD_CUT_TEXT,
        PREPARING_TEXT,
        FAILED_TEXT,
        TRIMMED_TEXT,
        GALLERY_EMPTY,
        REMOVE_DESCRIPTION,
        upload_text(45, videos=1, photos=0),
    ]
    banned = re.compile(r"\b(upload|post|error|click|clic|arrastra|MB|HTTP)\b", re.IGNORECASE)
    for text in texts:
        assert banned.search(text) is None, text
