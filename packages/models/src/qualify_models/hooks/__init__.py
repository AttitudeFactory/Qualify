"""Hook-pattern extraction: structured, comparable features of a short video's opening.

A spike, not Parte 3. It writes JSON/CSV to disk and stops there — no Celery, no R2, no
`ingestion`/`search`/`signals` schemas.

Read `NOTES_hook_pattern_spike.md` (Spanish) next to this package for the definition of
"hook" this implements, what it can and cannot conclude, and the corpus it needs.

Imports are lazy for the same reason as the package root: `spec`, `schema`, `lexical` and
`visual` carry no torch/transformers dependency and must stay importable in a CI job
without the `ml` group installed. `extract` pulls the cascade (and therefore transformers)
only when it is actually touched.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from qualify_models.hooks.extract import DETECTOR_VERSION, extract_hook_features
    from qualify_models.hooks.schema import HookFeatures, HookWindowFeatures
    from qualify_models.hooks.spec import (
        HOOK_SPEC_VERSION,
        PRIMARY_WINDOW_SECONDS,
        WINDOW_SECONDS,
        HookType,
        Setting,
        TextDensity,
    )

_LAZY_EXPORTS = {
    "DETECTOR_VERSION": "qualify_models.hooks.extract",
    "extract_hook_features": "qualify_models.hooks.extract",
    "HookFeatures": "qualify_models.hooks.schema",
    "HookWindowFeatures": "qualify_models.hooks.schema",
    "HOOK_SPEC_VERSION": "qualify_models.hooks.spec",
    "PRIMARY_WINDOW_SECONDS": "qualify_models.hooks.spec",
    "WINDOW_SECONDS": "qualify_models.hooks.spec",
    "HookType": "qualify_models.hooks.spec",
    "Setting": "qualify_models.hooks.spec",
    "TextDensity": "qualify_models.hooks.spec",
}

__all__ = [
    "DETECTOR_VERSION",
    "HOOK_SPEC_VERSION",
    "PRIMARY_WINDOW_SECONDS",
    "WINDOW_SECONDS",
    "HookFeatures",
    "HookType",
    "HookWindowFeatures",
    "Setting",
    "TextDensity",
    "extract_hook_features",
]


def __getattr__(name: str) -> Any:
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(module_path), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted([*globals(), *_LAZY_EXPORTS])
