"""Offline: the business point is validated and rounded like the screen's capture."""

from __future__ import annotations

import math

import pytest

from qualify_api.ads.audience import AudienceUnavailable, MapPoint
from qualify_api.ads.business_location import business_point


def test_rounds_to_six_decimals_and_fits_map_point() -> None:
    point = business_point(7.889_123_456, -72.505_000_49)
    assert point == (7.889123, -72.505)
    MapPoint(point[0], point[1], "Tu negocio").validate()


def test_negative_zero_becomes_zero() -> None:
    assert math.copysign(1, business_point(-0.0000001, 0)[0]) == 1


@pytest.mark.parametrize(
    ("lat", "lng"),
    [(90.1, 0), (0, -180.5), (math.nan, 0), (0, math.inf), (True, 0), ("7.8", 0), (None, 0)],
)
def test_refuses_impossible_points(lat: object, lng: object) -> None:
    with pytest.raises(AudienceUnavailable):
        business_point(lat, lng)
