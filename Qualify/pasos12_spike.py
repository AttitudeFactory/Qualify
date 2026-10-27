"""Synthetic PASOS12 export fixture; never merge this prototype."""
import reflex as rx

_source = rx.asset("pasos12_cards.jsx", shared=True)
_features = rx.asset("pasos12_features.js", shared=True)
_style = rx.asset("pasos12_style.css", shared=True)

class MotionCardList(rx.NoSSRComponent):
    library = f"$/public{_source}"
    tag = "MotionCardList"
    lib_dependencies = ["motion@14.6.0"]

    def add_imports(self):
        return {"": f"$/public{_style}"}

spike_cards = MotionCardList.create
