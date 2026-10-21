"""m-24828908: a piece downloaded whole — its files and its words, never the prompt."""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from qualify_api.creative.piece_export import (
    TEXT_NAME,
    archive_name,
    build_archive,
    piece_copy,
    piece_files,
    piece_text,
    slug,
)
from qualify_api.creative.service import DraftDetail, ImageRecord, VariantRecord

COPY = {
    "hook": "La smash doble que no esperabas",
    "caption": "Dos carnes prensadas, queso fundido y pan brioche.",
    "hashtags": ["smash", "#burger"],
    "cta": "Pide por WhatsApp",
}


def _variant(ordinal: int, copy: dict[str, Any], edited: dict[str, Any] | None = None) -> Any:
    return VariantRecord(
        id=uuid4(),
        draft_id=uuid4(),
        ordinal=ordinal,
        copy=copy,
        edited_copy=edited,
        fidelity={"passed": True},
        model_id="m",
        model_revision=None,
    )


def _media(key: str, media_type: str = "image", position: int = 0, **params: Any) -> Any:
    return ImageRecord(
        id=uuid4(),
        media_url=key,
        width=None,
        height=None,
        aspect_ratio=None,
        media_type=media_type,
        position=position,
        params=params or None,
        object_key=key,
    )


def _detail(
    variants: tuple[Any, ...] = (),
    media: tuple[Any, ...] = (),
    *,
    selected: UUID | None = None,
    title: str = "Smash doble",
    kind: str = "static_flyer",
) -> DraftDetail:
    return DraftDetail(
        id=uuid4(),
        brand_id=uuid4(),
        brief_id=uuid4(),
        status="generated",
        failure_reason=None,
        selected_variant_id=selected,
        voice_profile_version=1,
        pipeline_version="v1",
        requires_ai_disclosure=False,
        approved_by=None,
        approved_at=None,
        created_at=datetime.now(UTC),
        variants=variants,
        image=None,
        media=media,
        kind=kind,
        title=title,
    )


def test_the_text_has_every_word_of_the_piece_and_no_prompt() -> None:
    text = piece_text(
        title="Smash doble", kind_label="Flyer", copy=piece_copy(_detail((_variant(0, COPY),)))
    )
    for expected in (
        "Smash doble",
        "Tipo: Flyer",
        "GANCHO\nLa smash doble que no esperabas",
        "DESCRIPCIÓN\nDos carnes prensadas",
        "LLAMADO A LA ACCIÓN\nPide por WhatsApp",
        "HASHTAGS\n#smash #burger",
        "TEXTO LISTO PARA PEGAR\nLa smash doble que no esperabas\n\nDos carnes",
    ):
        assert expected in text, expected
    for internal in ("prompt", "Prompt", "modelo", "USD", "costo"):
        assert internal not in text
    assert "GUION" not in text and "TOMAS" not in text  # a flyer has neither


def test_a_script_brings_its_lines_and_shots() -> None:
    script = {
        **COPY,
        "script": "Hola, hoy te traigo la smash doble.",
        "shots": [
            {"visual": "Plano de la burger cayendo", "line": "Mira esto", "seconds": 3},
            {"visual": "Primer plano del queso", "seconds": 4},
        ],
    }
    text = piece_text(
        title="", kind_label="Guion", copy=piece_copy(_detail((_variant(0, script),)))
    )
    assert text.startswith("Pieza\nTipo: Guion")
    assert "GUION\nHola, hoy te traigo la smash doble." in text
    assert "TOMAS\n1. (3 s) Plano de la burger cayendo\n   Dice: Mira esto\n2. (4 s) Primer" in text


def test_the_selected_variant_and_the_operators_edit_are_what_is_downloaded() -> None:
    first, second = _variant(0, COPY), _variant(1, {**COPY, "hook": "Otro gancho"})
    assert piece_copy(_detail((second, first))).hook == COPY["hook"]  # the first by ordinal
    assert piece_copy(_detail((first, second), selected=second.id)).hook == "Otro gancho"
    edited = _variant(0, COPY, edited={**COPY, "hook": "Editado a mano"})
    assert piece_copy(_detail((edited,))).hook == "Editado a mano"
    assert piece_copy(_detail()) is None


def test_the_files_come_in_order_with_a_videos_thumbnail_and_a_missing_one_is_named() -> None:
    stored = {
        "t/x/generated/d/r1/clip.mp4": b"mp4",
        "t/x/generated/d/r1/first-frame.jpg": b"jpg",
        "t/x/generated/d/r1/slide-2.jpeg": b"jpeg",
    }
    detail = _detail(
        media=(
            _media("t/x/generated/d/r1/slide-2.jpeg", position=1),
            _media(
                "t/x/generated/d/r1/clip.mp4",
                "video",
                0,
                thumbnail_key="t/x/generated/d/r1/first-frame.jpg",
            ),
            _media("t/x/generated/d/r1/gone.png", position=2),
        )
    )
    files, missing = piece_files(detail, stored.__getitem__, stem="smash-doble")
    assert [(f.name, f.data) for f in files] == [
        ("smash-doble-1.mp4", b"mp4"),
        ("smash-doble-1-miniatura.jpg", b"jpg"),
        ("smash-doble-2.jpg", b"jpeg"),
    ]
    assert missing == ["smash-doble-3.png"]


def test_the_archive_holds_the_text_and_the_files() -> None:
    files, _ = piece_files(_detail(media=(_media("k/a.jpg"),)), {"k/a.jpg": b"img"}.__getitem__)
    data = build_archive(files, "Smash\n", missing=["pieza-2.mp4"])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert sorted(archive.namelist()) == ["pieza-1.jpg", TEXT_NAME]
        assert archive.read("pieza-1.jpg") == b"img"
        text = archive.read(TEXT_NAME).decode("utf-8")
    assert text.startswith("Smash") and "No se pudieron incluir: pieza-2.mp4" in text


def test_names_are_plain_file_names() -> None:
    assert slug("  Smash   Doble ¡Ñandú! ") == "smash-doble-nandu"
    assert archive_name("nibbles burger", "Smash doble") == "nibbles-burger-smash-doble.zip"
    assert archive_name("", "") == "pieza.zip"
    assert len(slug("x" * 200)) == 60
