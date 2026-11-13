"""m-24820842 (UX review 2026-11-04, C1/C2): the owner-facing errors this PR added speak of
«imágenes de tu marca», never «recursos», and name only options the screen shows."""

from pathlib import Path

import qualify_api.creative.brand_references as brand_references
import qualify_api.creative.media as media
from qualify_api.creative.media import GENERATED_AD_IMAGES_OFF

_UI = Path(__file__).resolve().parents[3] / "Qualify"


def _source(module: object) -> str:
    return Path(module.__file__).read_text(encoding="utf-8")  # type: ignore[attr-defined]


def test_the_brand_image_errors_say_imagenes_not_recursos() -> None:
    assert brand_references.INVALID_IMAGE == (
        "Una de las imágenes de tu marca no se puede abrir. Elige otra."
    )
    refs = _source(brand_references)
    assert "No pudimos abrir las imágenes de tu marca. Toca «Crear» otra vez." in refs
    code = _source(media)
    for new in (
        "No pudimos guardar tus imágenes. Toca «Crear» otra vez.",
        "quita alguna de las imágenes de tu ",
        "cuándo usar tus otras imágenes (en Tu marca)",
        "Usaremos todas las imágenes que elegiste.",
    ):
        assert new in code
    for old in (
        "No pudimos guardar tus recursos",
        "quita alguno de los recursos",
        "tus otros recursos",
        "Conservaremos todos los recursos",
        "No pudimos leer tus recursos",
        "Uno de los recursos de tu marca",
    ):
        assert old not in code and old not in refs


def test_the_template_error_does_not_offer_the_corner_choice_it_never_shows() -> None:
    code = _source(media)
    assert "Las plantillas solo llevan tu logo, no otras imágenes de tu marca. " in code
    assert "Esta plantilla no pone tu logo dentro de la foto" not in code


def test_the_ad_image_error_names_what_its_screen_shows() -> None:
    assert "elige «Imagen»" not in _source(media)
    screen = (_UI / "content_generator.py").read_text(encoding="utf-8")
    summary = (_UI / "generator_summary_vm.py").read_text(encoding="utf-8")
    # every option the message names is a label of the «Imagen publicitaria» form
    assert 'BRAND_LOGO_PLACE_TITLE = "¿Dónde lo ponemos?"' in screen
    assert 'LOGO_SIGNATURE_TEXT = "En una esquina, como firma"' in summary
    assert 'BRAND_OTHER_IMAGES_TITLE = "Otras imágenes de tu marca (opcional)"' in screen
    for label in (
        "«¿Dónde lo ponemos?»",
        "«En una esquina, como firma»",
        "«Otras imágenes de tu marca»",
    ):
        assert label in GENERATED_AD_IMAGES_OFF
    assert "recurso" not in GENERATED_AD_IMAGES_OFF


def test_the_failed_piece_panel_title_speaks_of_the_publication() -> None:
    pages = (_UI / "creative_pages.py").read_text(encoding="utf-8")
    assert "No pudimos crear tu publicación" in pages
    assert "La generación falló" not in pages
