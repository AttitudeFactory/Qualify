"""photo_recipe contract tests. The segmentation model itself never runs here (that is
`integration` work); everything else is pure and runs against synthetic images."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from qualify_creative.photo import (
    SEGMENTATION_MODEL,
    FoodPreset,
    LocalBiRefNetSegmenter,
    cutout,
    enhance_subject,
    export_for_instagram,
    ground_shadow,
    load_normalized,
)


def _jpeg(image: Image.Image, exif: Image.Exif | None = None) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif or Image.Exif())
    return buffer.getvalue()


def _mask(size: tuple[int, int], box: tuple[int, int, int, int]) -> Image.Image:
    from PIL import ImageDraw

    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rectangle(box, fill=255)
    return mask


class TestNormalize:
    def test_exif_orientation_is_baked_into_pixels(self) -> None:
        """Silent failure #1: a portrait iPhone shot carries orientation=6 and viewers
        rotate it on the fly; pixel pipelines do not. After normalization the pixels
        themselves must be upright."""
        landscape = Image.new("RGB", (120, 80), "white")
        exif = Image.Exif()
        exif[274] = 6  # rotate 90 CW to display
        upright = load_normalized(_jpeg(landscape, exif))
        assert (upright.width, upright.height) == (80, 120)

    def test_output_is_always_rgb(self) -> None:
        grey = Image.new("L", (50, 50), 128)
        assert load_normalized(_jpeg(grey)).mode == "RGB"

    def test_export_resizes_and_is_deterministic(self) -> None:
        big = Image.new("RGB", (2160, 2700), "#66499A")
        a = export_for_instagram(big)
        b = export_for_instagram(big)
        assert a == b
        assert Image.open(io.BytesIO(a)).width == 1080


class TestSegmentSeam:
    def test_bria_model_is_rejected(self) -> None:
        """The license foot-gun: rembg's current default works perfectly and its weights
        require a paid commercial agreement. Constructing it must fail loudly."""
        with pytest.raises(ValueError, match="paid agreement"):
            LocalBiRefNetSegmenter("bria-rmbg")

    def test_default_model_is_the_mit_one(self) -> None:
        assert SEGMENTATION_MODEL == "birefnet-general-lite"

    def test_source_never_names_bria_as_default(self) -> None:
        """Static guard: nobody flips the pinned constant to rembg's default in a
        refactor without tripping this."""
        from pathlib import Path

        import qualify_creative.photo.segment as seg

        source = Path(seg.__file__).read_text()
        assert 'SEGMENTATION_MODEL = "birefnet-general-lite"' in source


class TestDerive:
    def test_cutout_crops_to_subject_and_is_transparent_outside(self) -> None:
        photo = Image.new("RGB", (200, 200), "#A98BD6")
        cut = cutout(photo, _mask((200, 200), (50, 40, 150, 180)))
        assert (cut.width, cut.height) == (101, 141)
        assert cut.mode == "RGBA"

    def test_shadow_matches_subject_width_band(self) -> None:
        cut = Image.new("RGBA", (100, 300), (255, 0, 0, 255))
        shadow = ground_shadow(cut)
        assert shadow.width == cut.width
        assert shadow.getbbox() is not None

    def test_enhancement_only_touches_the_subject(self) -> None:
        """The point of masking the preset: the plate pops, the table does not move."""
        photo = Image.new("RGB", (100, 100), (120, 100, 90))
        mask = _mask((100, 100), (0, 0, 49, 99))
        result = enhance_subject(photo, mask)
        assert result.getpixel((75, 50)) == (120, 100, 90)  # fondo intacto
        assert result.getpixel((25, 50)) != (120, 100, 90)  # sujeto tratado

    def test_saturation_cap_is_enforced(self) -> None:
        """Research §3: past +10% food reads as fake. The type refuses to exist."""
        with pytest.raises(ValueError, match="fake"):
            FoodPreset(saturation=1.2)
