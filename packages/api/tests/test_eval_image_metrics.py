"""Offline checks of `qualify_api.evals.image_metrics` (m-24849234 PR 2): the flat finish
and its stroke checks, the Lab palette and background metrics of a color transfer, and
the local part of the legibility check. Synthetic images only; no vendor, no network."""

from __future__ import annotations

import hashlib
import io
import math
import unicodedata
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from qualify_api.evals import image_metrics as im

FIXTURES = Path(__file__).resolve().parents[1] / "evals" / "plantillas_ai" / "fixtures"
MINT, CORAL, COPPER = (62, 180, 137), (255, 127, 80), (184, 115, 51)


def _bytes(image: Image.Image, fmt: str = "PNG") -> bytes:
    out = io.BytesIO()
    image.save(out, format=fmt)
    return out.getvalue()


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _lab(rgb: tuple[int, int, int]) -> np.ndarray:
    return im.to_lab(Image.new("RGB", (1, 1), rgb)).reshape(3)


# ---------------------------------------------------------------------------
# Flat finish


@pytest.fixture(scope="module")
def luma() -> im.FlatResult:
    return im.flat_texture_fill(_fixture("luma-wordmark.png"), _fixture("textura-rayas-cobre.png"))


def test_flat_finish_of_the_luma_wordmark_keeps_every_stroke(luma: im.FlatResult) -> None:
    assert luma.size == (1080, 351) and max(luma.size) == im.FLAT_LONG_SIDE
    assert luma.mask_source == "alpha"
    assert luma.mask_iou >= im.MIN_MASK_IOU
    assert luma.mask_diff_fraction < im.MAX_MASK_DIFF_FRACTION
    assert luma.components_before == luma.components_after == 4  # L, U, M, A
    assert luma.min_stroke_px >= im.MIN_STROKE_PX
    assert not luma.stroke_lost and luma.passed
    out = Image.open(io.BytesIO(luma.png))
    assert out.mode == "RGBA" and out.size == luma.size
    assert out.getpixel((0, 0))[3] == 0  # transparent background


def test_the_texture_covers_the_whole_silhouette(luma: im.FlatResult) -> None:
    out = np.asarray(Image.open(io.BytesIO(luma.png)))
    logo = Image.open(io.BytesIO(_fixture("luma-wordmark.png")))
    alpha = np.asarray(logo.getchannel("A").resize(luma.size, Image.LANCZOS))
    assert np.array_equal(out[..., 3], alpha)  # the alpha is the silhouette itself
    box = Image.fromarray(alpha).point(lambda v: 255 if v >= 128 else 0).getbbox()
    assert box is not None
    texture = Image.open(io.BytesIO(_fixture("textura-rayas-cobre.png")))
    tiled = np.asarray(im.tile_texture(texture, luma.size, (box[1], box[3])))
    inside = alpha > 0
    assert np.array_equal(out[..., :3][inside], tiled[inside])  # texture RGB everywhere


def test_an_opaque_logo_gets_its_silhouette_from_the_corner_color() -> None:
    logo = Image.new("RGB", (540, 200), (255, 255, 255))
    ImageDraw.Draw(logo).rectangle((40, 40, 500, 160), fill=(255, 230, 0))  # yellow on white
    result = im.flat_texture_fill(_bytes(logo), _fixture("textura-rayas-cobre.png"))
    assert result.mask_source == "corner" and result.size == (1080, 400)
    assert result.passed and result.components_before == result.components_after == 1


def test_the_soft_silhouette_ramps_around_the_threshold() -> None:
    logo = Image.new("RGB", (3, 1))
    logo.putpixel((1, 0), (32, 32, 32))  # difference 32: still background
    logo.putpixel((2, 0), (64, 64, 64))  # difference 64: fully mark
    mask, source = im.silhouette(logo)
    assert source == "corner"
    assert [mask.getpixel((x, 0)) for x in range(3)] == [0, 0, 255]


def test_a_thin_stroke_lost_at_1080_is_detected() -> None:
    logo = Image.new("RGBA", (4320, 1080), (0, 0, 0, 0))
    draw = ImageDraw.Draw(logo)
    draw.rectangle((200, 200, 1800, 880), fill=(10, 10, 10, 255))
    draw.rectangle((3000, 200, 3001, 880), fill=(10, 10, 10, 255))  # 2 px: 0.5 px at 1080
    result = im.flat_texture_fill(_bytes(logo), _fixture("textura-rayas-cobre.png"))
    assert result.size == (1080, 270)
    assert result.components_before == 2
    assert result.stroke_lost and not result.passed


def test_stroke_width_and_components_on_known_shapes() -> None:
    shape = np.zeros((40, 60), dtype=bool)
    shape[5:12, 5:50] = True  # 7 px thick bar
    assert im.min_stroke_width(shape) == 7
    shape[20:35, 30] = True  # a separate 1 px line
    assert im.min_stroke_width(shape) == 1
    assert im.count_components(shape) == 2
    diagonal = np.eye(8, dtype=bool)  # touching only at corners: one 8-connected stroke
    assert im.count_components(diagonal) == 1
    assert im.count_components(np.zeros((5, 5), dtype=bool)) == 0
    speck = np.zeros((10, 10), dtype=bool)
    speck[2, 2] = True
    assert im.count_components(speck) == 0  # below MIN_COMPONENT_AREA
    thick = np.ones((200, 200), dtype=bool)
    assert im.min_stroke_width(thick) == im.STROKE_PROBE_CAP  # «at least the cap»


@pytest.mark.parametrize("width", [1, 2, 3, 4, 6, 9])
def test_stroke_widths_are_exact(width: int) -> None:
    shape = np.zeros((40, 60), dtype=bool)
    shape[10 : 10 + width, 5:55] = True  # horizontal bar
    assert im.min_stroke_width(shape) == width
    vertical = shape.T.copy()
    assert im.min_stroke_width(vertical) == width


def test_a_two_px_stroke_is_not_lost() -> None:
    shape = np.zeros((30, 30), dtype=bool)
    shape[5:25, 10:12] = True
    assert im.min_stroke_width(shape) == 2 == im.MIN_STROKE_PX
    diagonal = np.eye(20, dtype=bool)  # an 8-connected 1 px diagonal
    assert im.min_stroke_width(diagonal) == 1


def _luma_at(width: int) -> bytes:
    logo = Image.open(io.BytesIO(_fixture("luma-wordmark.png")))
    return _bytes(logo.resize((width, round(logo.height * width / logo.width)), Image.LANCZOS))


@pytest.mark.parametrize("width", [400, 250])
def test_a_small_native_logo_passes_the_silhouette_check(width: int) -> None:
    result = im.flat_texture_fill(_luma_at(width), _fixture("textura-rayas-cobre.png"))
    assert max(result.size) == im.FLAT_LONG_SIDE
    assert result.mask_iou >= im.MIN_MASK_IOU
    assert result.mask_diff_fraction < im.MAX_MASK_DIFF_FRACTION
    assert result.components_before == result.components_after == 4 and result.passed


def test_a_genuinely_eroded_output_fails_the_silhouette_check() -> None:
    logo = Image.open(io.BytesIO(_fixture("luma-wordmark.png")))
    native = im.binary(logo.getchannel("A"))
    alpha = logo.getchannel("A").resize(im.fit_long_side(logo.size), Image.LANCZOS)
    eroded = im.binary(alpha)
    for _ in range(4):
        eroded = im.erode_2x2(eroded)
    iou, diff, _ = im.silhouette_match(native, Image.fromarray(eroded.astype(np.uint8) * 255))
    assert iou < im.MIN_MASK_IOU and diff >= im.MAX_MASK_DIFF_FRACTION
    iou_ok, diff_ok, _ = im.silhouette_match(native, alpha)
    assert iou_ok >= im.MIN_MASK_IOU and diff_ok < im.MAX_MASK_DIFF_FRACTION


def test_a_speck_below_the_output_area_is_not_a_lost_stroke() -> None:
    logo = Image.new("RGBA", (4320, 1080), (0, 0, 0, 0))
    draw = ImageDraw.Draw(logo)
    draw.rectangle((200, 200, 1800, 880), fill=(10, 10, 10, 255))
    draw.rectangle((3000, 500, 3002, 502), fill=(10, 10, 10, 255))  # 3x3: < 1 px at 1080
    result = im.flat_texture_fill(_bytes(logo), _fixture("textura-rayas-cobre.png"))
    assert result.components_before == result.components_after == 1
    assert not result.stroke_lost and result.passed
    draw.rectangle((3500, 500, 3523, 523), fill=(10, 10, 10, 255))  # 24x24: 6x6 at 1080
    bigger = im.flat_texture_fill(_bytes(logo), _fixture("textura-rayas-cobre.png"))
    assert bigger.components_before == bigger.components_after == 2


def test_a_dark_background_logo_gets_its_silhouette_from_the_corner() -> None:
    logo = Image.new("RGB", (540, 200), (0, 0, 0))
    ImageDraw.Draw(logo).rectangle((40, 40, 500, 160), fill=(0, 0, 200))  # blue on black
    mask, source = im.silhouette(logo)
    assert source == "corner"
    assert mask.getpixel((0, 0)) == 0 and mask.getpixel((270, 100)) == 255
    result = im.flat_texture_fill(_bytes(logo), _fixture("textura-rayas-cobre.png"))
    assert result.mask_source == "corner" and result.passed


# ---------------------------------------------------------------------------
# Color transfer


def test_kmeans_recovers_the_three_bands_of_the_palette() -> None:
    bands = Image.open(io.BytesIO(_fixture("paleta-menta-coral-cobre.png")))
    palette = im.kmeans_palette(im.to_lab(bands).reshape(-1, 3), 3)
    assert len(palette) == 3
    for color in (MINT, CORAL, COPPER):
        assert np.sqrt(((palette - _lab(color)) ** 2).sum(axis=1)).min() < 1.0
    again = im.kmeans_palette(im.to_lab(bands).reshape(-1, 3), 3)
    assert np.array_equal(palette, again)  # fixed seed: same palette


def test_lab_of_srgb_red_is_close_to_the_reference_value() -> None:
    lab = _lab((255, 0, 0))  # D50 Lab of sRGB red ≈ (54.3, 80.8, 69.9)
    assert abs(lab[0] - 54.3) < 1.5 and abs(lab[1] - 80.8) < 2 and abs(lab[2] - 69.9) < 2


def test_palette_delta_e_is_zero_for_identical_and_large_for_disjoint() -> None:
    reference = np.array([_lab(MINT), _lab(CORAL), _lab(COPPER)])
    assert im.palette_delta_e(reference, reference) == pytest.approx(0.0)
    blues = np.array([_lab((0, 0, 255)), _lab((20, 20, 120))])
    assert im.palette_delta_e(blues, reference) > 50


def _recolored_disc(background_noise: int = 0) -> bytes:
    """The disc fixture with the disc painted in the palette's three colors and,
    optionally, noise on the background (a model that drifted)."""
    image = Image.open(io.BytesIO(_fixture("objeto-disco.png"))).convert("RGB")
    mask = Image.open(io.BytesIO(_fixture("objeto-disco-mascara.png")))
    arr = np.asarray(image).copy()
    inside = np.asarray(mask) > 0
    columns = np.nonzero(inside.any(axis=0))[0]
    thirds = np.array_split(columns, 3)
    for color, cols in zip((MINT, CORAL, COPPER), thirds, strict=True):
        region = np.zeros_like(inside)
        region[:, cols] = True
        arr[inside & region] = color
    if background_noise:
        rng = np.random.default_rng(7)
        noise = rng.integers(-background_noise, background_noise + 1, arr.shape)
        noisy = np.clip(arr.astype(int) + noise, 0, 255).astype(np.uint8)
        arr[~inside] = noisy[~inside]
    return _bytes(Image.fromarray(arr))


def test_identical_background_gives_infinite_psnr_and_a_close_palette() -> None:
    metrics = im.color_transfer_metrics(
        _fixture("objeto-disco.png"),
        _recolored_disc(),
        _fixture("paleta-menta-coral-cobre.png"),
        _fixture("objeto-disco-mascara.png"),
    )
    assert metrics.mask_source == "mask"
    assert metrics.background_psnr_db == math.inf
    assert metrics.edge_psnr_db is None  # a hard mask has no soft edge
    assert metrics.palette_delta_e < 1.0 and metrics.palette_ok
    record = metrics.as_record()
    assert record["psnr_fondo_db"] == "inf" and record["metricas_version"] == im.METRICS_VERSION
    assert "fondo_identico_tras_recomponer" not in record


def test_a_drifted_background_is_measured_and_recomposition_restores_it() -> None:
    original = _fixture("objeto-disco.png")
    mask = _fixture("objeto-disco-mascara.png")
    metrics = im.color_transfer_metrics(
        original,
        _recolored_disc(background_noise=12),
        _fixture("paleta-menta-coral-cobre.png"),
        mask,
    )
    assert metrics.background_psnr_db is not None
    assert math.isfinite(metrics.background_psnr_db) and 20 < metrics.background_psnr_db < 40
    assert metrics.recomposed_png is not None
    recomposed = np.asarray(Image.open(io.BytesIO(metrics.recomposed_png)).convert("RGB"))
    outside = np.asarray(Image.open(io.BytesIO(mask))) == 0
    source = np.asarray(Image.open(io.BytesIO(original)).convert("RGB"))
    assert np.array_equal(recomposed[outside], source[outside])


def test_a_soft_mask_edge_is_measured_on_the_recomposed_image() -> None:
    from PIL import ImageFilter

    soft = Image.open(io.BytesIO(_fixture("objeto-disco-mascara.png"))).filter(
        ImageFilter.GaussianBlur(3)
    )
    metrics = im.color_transfer_metrics(
        _fixture("objeto-disco.png"),
        _recolored_disc(),
        _fixture("paleta-menta-coral-cobre.png"),
        _bytes(soft),
    )
    assert metrics.edge_psnr_db is not None and math.isfinite(metrics.edge_psnr_db)
    assert isinstance(metrics.as_record()["borde_recompuesto_psnr_db"], float)


def test_a_result_in_a_single_reference_color_fails_the_palette() -> None:
    image = Image.open(io.BytesIO(_fixture("objeto-disco.png"))).convert("RGB")
    mask = Image.open(io.BytesIO(_fixture("objeto-disco-mascara.png")))
    image.paste(MINT, (0, 0), mask)  # the whole object in mint only
    metrics = im.color_transfer_metrics(
        _fixture("objeto-disco.png"),
        _bytes(image),
        _fixture("paleta-menta-coral-cobre.png"),
        _fixture("objeto-disco-mascara.png"),
    )
    assert metrics.result_to_reference_delta_e < 1.0  # one way it looks perfect
    assert metrics.reference_to_result_delta_e > im.PALETTE_DELTA_E_MAX
    assert not metrics.palette_ok


def test_the_palette_samples_a_large_image() -> None:
    big = Image.new("RGB", (400, 300), MINT)
    ImageDraw.Draw(big).rectangle((200, 0, 399, 299), fill=CORAL)
    palette = im._palette(big, None, 3)  # 120 000 px > PALETTE_SAMPLE
    assert len(palette) == 2
    for color in (MINT, CORAL):
        assert np.sqrt(((palette - _lab(color)) ** 2).sum(axis=1)).min() < 1.0


def test_an_unchanged_object_is_far_from_the_reference_palette() -> None:
    metrics = im.color_transfer_metrics(
        _fixture("objeto-disco.png"),
        _fixture("objeto-disco.png"),
        _fixture("paleta-menta-coral-cobre.png"),
        _fixture("objeto-disco-mascara.png"),
    )
    assert metrics.palette_delta_e > im.PALETTE_DELTA_E_MAX and not metrics.palette_ok


def test_mask_fallbacks_alpha_then_none() -> None:
    reference = _fixture("paleta-menta-coral-cobre.png")
    rgba = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(rgba).rectangle((16, 16, 47, 47), fill=(40, 80, 200, 255))
    alpha = im.color_transfer_metrics(_bytes(rgba), _bytes(rgba), reference)
    assert alpha.mask_source == "alpha" and alpha.recomposed_png is not None
    opaque = _bytes(Image.new("RGB", (64, 64), (40, 80, 200)))
    none = im.color_transfer_metrics(opaque, opaque, reference)
    assert none.mask_source == "none"
    assert none.background_psnr_db is None and none.edge_psnr_db is None
    assert none.recomposed_png is None and none.as_record()["psnr_fondo_db"] is None


def test_a_result_of_another_size_is_resized_and_a_wrong_mask_refused() -> None:
    original = _fixture("objeto-disco.png")
    small = Image.open(io.BytesIO(_recolored_disc())).resize((256, 192))
    metrics = im.color_transfer_metrics(
        original,
        _bytes(small),
        _fixture("paleta-menta-coral-cobre.png"),
        _fixture("objeto-disco-mascara.png"),
    )
    assert metrics.result_resized and metrics.as_record()["resultado_redimensionado"] is True
    with pytest.raises(ValueError, match="mask"):
        im.color_transfer_metrics(
            original, original, original, _bytes(Image.new("L", (10, 10), 255))
        )


# ---------------------------------------------------------------------------
# Legibility (local part)


@pytest.mark.parametrize(
    ("expected", "read", "match"),
    [
        ("Mar y Sal", "  MAR   y\nsal ", True),  # case and whitespace do not count
        ("ÑAPA", unicodedata.normalize("NFD", "ÑAPA"), True),  # composed == decomposed
        ("ÑAPA", "NAPA", False),  # the tilde is part of the word
        ("La Ceiba", "La Céiba", False),  # accents count
        ("¡Gran apertura!", "Gran apertura", False),  # punctuation counts
        ("LUMA", "LUMA", True),
        ("LUMA", "", False),
    ],
)
def test_exact_match_rules(expected: str, read: str, match: bool) -> None:
    assert im.exact_match(expected, read) is match


def test_fake_reader_and_the_pending_record() -> None:
    image = _fixture("luma-wordmark.png")
    assert im.legibility_record(None, image, "LUMA") == {
        "metricas_version": im.METRICS_VERSION,
        "estado": "pendiente",
    }
    reader = im.FakeReader(default="?", by_digest={hashlib.sha256(image).hexdigest(): "luma"})
    reader_type: im.LegibilityReader = reader
    assert im.legibility_record(reader_type, image, "LUMA") == {
        "metricas_version": im.METRICS_VERSION,
        "estado": "leido",
        "leido": "luma",
        "coincide": True,
    }
    assert im.legibility_record(reader, b"other", "LUMA")["coincide"] is False
    assert len(reader.calls) == 2
