"""NAV-11 (m-24849129): the brand's image policy refusal, in the owner's words."""

from __future__ import annotations

from .creative_state import route_blocked_text

_BASE = "Tu marca no permite crear la imagen de esa forma. Elige otra opción para la imagen."


def test_the_policy_fallback_is_not_said_twice() -> None:
    assert route_blocked_text("No habilitada para esta marca.") == _BASE
    assert route_blocked_text("") == _BASE


def test_a_specific_reason_follows_the_sentence() -> None:
    assert route_blocked_text("Solo fotos reales del local.") == (
        f"{_BASE} Solo fotos reales del local."
    )
