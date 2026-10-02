"""TEMPORAL (pruebas, docs/brand-kit-resumen-temporal.md) — Marca's read-only summary of
the finished Brand Kit. Delete with `brand_summary.py`."""

from __future__ import annotations

from .brand_summary import BrandSummaryState
from .creative_vm import KitFormVM


def test_the_summary_shows_the_saved_kit_as_it_is() -> None:
    state = BrandSummaryState()
    state._show(
        KitFormVM(
            positioning="Cafetería de especialidad",
            audience="Oficinistas del centro",
            tone_formal_casual=80,
            tone_brief_elaborate=20,
            do_examples="¡Tu primer café corre por nuestra cuenta!\n\nVen hoy",
            banned_words="barato",
            palette_rgb="#0A3D2E, #F2C94C,",
        )
    )
    assert state.positioning == "Cafetería de especialidad"
    assert state.tone[0] == {"poles": "formal ↔ coloquial", "value": "80"}
    assert state.tone[3] == {"poles": "breve ↔ elaborado", "value": "20"}
    assert state.do_examples == ["¡Tu primer café corre por nuestra cuenta!", "Ven hoy"]
    assert state.banned_words == ["barato"]
    assert state.forbidden_claims == []
    assert state.palette == ["#0A3D2E", "#F2C94C"]
