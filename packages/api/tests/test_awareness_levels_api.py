"""Awareness levels and business perks on the API side, offline: the kit's perks through
`brand_service` (written only when the caller set them, read back normalized), the
level through the `content_briefs` row and the `creative_angles` record, the brand
fingerprint (a perks change gives a cached set a new one, an empty list keeps the old
one), the video-by-parts prompt and its version, and migration 0163's place in the
chain."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from uuid import uuid4

from qualify_creative.angles import AngleBrand, AngleProduct, CreativeAngle
from qualify_creative.enums import AwarenessLevel, BriefObjective, ImageRoute
from qualify_creative.schemas import BrandKit, ContentBrief, ToneAxes

from qualify_api.creative import models as orm
from qualify_api.creative.angle_sets import _angle_record, brand_fingerprint
from qualify_api.creative.brand_service import _apply_kit, kit_from_row
from qualify_api.creative.parts_ai import (
    PROPOSE_PARTS_PROMPT_VERSION,
    PartsBrief,
    propose_user_prompt,
)
from qualify_api.creative.service import _brief_row, brief_from_row

BRAND_ID = uuid4()
PERKS = ("Parqueadero gratis", "Pet friendly", "Abierto hasta las 11 p. m.")
_VERSIONS = Path(__file__).resolve().parents[3] / "migrations/postgres/versions"


def _kit(**overrides: object) -> BrandKit:
    base: dict[str, object] = {
        "brand_id": BRAND_ID,
        "positioning": "Shawarma de patio de comidas",
        "audience": "Familias",
        "tone_axes": ToneAxes(
            formal_casual=50, sober_enthusiastic=50, technical_plain=50, brief_elaborate=50
        ),
    }
    base.update(overrides)
    return BrandKit(**base)  # type: ignore[arg-type]


# -- the kit's perks -----------------------------------------------------------------------


def test_perks_are_written_normalized_and_read_back() -> None:
    row = orm.BrandKit(tenant_id=uuid4(), brand_id=BRAND_ID, language="es")
    _apply_kit(row, _kit(business_perks=["Pet friendly ", "pet friendly", "", "Mesas"]))
    assert row.business_perks == ["Pet friendly", "Mesas"]
    assert kit_from_row(row).business_perks == ("Pet friendly", "Mesas")


def test_a_kit_that_does_not_set_the_perks_never_wipes_them() -> None:
    row = orm.BrandKit(tenant_id=uuid4(), brand_id=BRAND_ID, language="es")
    _apply_kit(row, _kit(business_perks=list(PERKS)))
    _apply_kit(row, _kit())  # an older caller that knows nothing of perks
    assert row.business_perks == list(PERKS)
    _apply_kit(row, _kit(business_perks=[]))  # an explicit empty list clears them
    assert row.business_perks == []


def test_a_row_without_perks_reads_as_none() -> None:
    row = orm.BrandKit(tenant_id=uuid4(), brand_id=BRAND_ID, language="es")
    _apply_kit(row, _kit())
    row.business_perks = None  # a row the column default has not reached yet
    assert kit_from_row(row).business_perks == ()


# -- the level through the rows ------------------------------------------------------------


def test_the_brief_row_keeps_the_level_and_an_old_one_reads_none() -> None:
    brief = ContentBrief(
        brand_id=BRAND_ID,
        objective=BriefObjective.AWARENESS,
        topic="Mesa del patio",
        image_route=ImageRoute.TEMPLATE_ONLY,
        awareness_level=AwarenessLevel.UNAWARE,
    )
    row = _brief_row(uuid4(), uuid4(), brief)
    assert row.awareness_level == "unaware"
    assert brief_from_row(row).awareness_level is AwarenessLevel.UNAWARE
    row.awareness_level = None
    assert brief_from_row(row).awareness_level is None


def _angle_row(level: str | None) -> orm.CreativeAngle:
    return orm.CreativeAngle(
        id=uuid4(),
        set_id=uuid4(),
        position=1,
        title="Mesa",
        scene="en la mesa del patio",
        composition="",
        hook="",
        cta="",
        rationale="",
        status="proposed",
        attempts=0,
        awareness_level=level,
    )


def test_the_angle_record_exposes_the_level_and_tolerates_old_or_unknown_rows() -> None:
    record = _angle_record(_angle_row("most_aware"))
    assert record.awareness_level is AwarenessLevel.MOST_AWARE
    assert record.angle.awareness_level is AwarenessLevel.MOST_AWARE
    assert _angle_record(_angle_row(None)).awareness_level is None
    assert _angle_record(_angle_row("otro")).awareness_level is None


# -- the brand fingerprint -----------------------------------------------------------------


def test_the_fingerprint_moves_with_the_perks_and_not_without_them() -> None:
    brand = AngleBrand(name="Bianki", sector="shawarma")
    # the formula before the perks: a kit without them keeps its old fingerprint
    old = hashlib.sha256("\n".join(("Bianki", "", "", "shawarma", "", "")).encode()).hexdigest()
    assert brand_fingerprint(brand) == old[:16]
    with_perks = brand_fingerprint(AngleBrand(name="Bianki", sector="shawarma", perks=PERKS))
    assert with_perks != brand_fingerprint(brand)
    other = brand_fingerprint(AngleBrand(name="Bianki", sector="shawarma", perks=PERKS[:2]))
    assert other != with_perks


# -- the video-by-parts prompt -------------------------------------------------------------


def test_the_parts_prompt_carries_perks_and_level_only_when_present() -> None:
    product = AngleProduct(product_id=uuid4(), name="Shawarma mixto")
    angle = CreativeAngle(
        position=1, title="Mesa", scene="en la mesa", awareness_level=AwarenessLevel.UNAWARE
    )
    rich = propose_user_prompt(
        PartsBrief(story="Ven", brand=AngleBrand(name="Bianki", perks=PERKS), product=product),
        angle,
    )
    for perk in PERKS:
        assert f"- {perk}\n" in rich
    assert "nunca inventes otros" in rich
    assert "Nivel de consciencia del público: unaware — " in rich
    plain = propose_user_prompt(
        PartsBrief(story="Ven", brand=AngleBrand(name="Bianki"), product=product),
        CreativeAngle(position=1, title="Mesa", scene="en la mesa"),
    )
    assert "Lo que ofrece el negocio" not in plain and "Nivel de consciencia" not in plain
    assert PROPOSE_PARTS_PROMPT_VERSION == "proponer-partes-v3.2"


# -- migration 0163 ------------------------------------------------------------------------


def test_migration_0163_follows_0162_and_is_the_only_head() -> None:
    text = (_VERSIONS / "0163_awareness_levels_business_perks.py").read_text()
    assert 'revision = "0163"' in text and 'down_revision = "0162"' in text
    parents = [
        re.search(r'^down_revision = "(\d+)"', path.read_text(), re.M)
        for path in _VERSIONS.glob("*.py")
    ]
    assert [m.group(1) for m in parents if m].count("0162") == 1
    assert "def downgrade()" in text and text.count("drop_column") >= 2
