"""Public surface of `qualify-models`.

The re-exports below are **lazy on purpose** (PEP 562).

`permission_capability` (C-05) is a pure scope->capability lookup table with no ML
dependency at all, and it is imported by the Reflex CRM's `capabilities.py` (C-06),
whose tests run in CI — where the `ml` group (torch, transformers) is deliberately
NOT installed, per the root `pyproject.toml`'s `default-groups`.

With eager re-exports, `import qualify_models.permission_capability` ran this module
first and transitively pulled `cascade` -> `filter` -> `transformers`, so a lookup
table could not be read without the whole GPU stack present. That is what broke CI
collection on 2026-08-03: four `Qualify/` test modules failed to import, and the
failure looked like a missing dependency rather than an over-eager `__init__`.

Attribute access still resolves the same names from the same modules, so
`from qualify_models import run_cascade` is unchanged for callers that do have the
`ml` group installed. Only the *timing* of the import moves.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # import-time only for type checkers; never at runtime
    from qualify_models.cascade import CascadeResult, run_cascade
    from qualify_models.filter import run_filter
    from qualify_models.schemas import (
        FilterResult,
        SentimentResult,
        TranscriptionResult,
        VisionResult,
    )
    from qualify_models.sentiment import run_sentiment
    from qualify_models.transcription import run_transcription
    from qualify_models.vision import run_vision

# name -> submodule that defines it.
_LAZY_EXPORTS = {
    "CascadeResult": "qualify_models.cascade",
    "run_cascade": "qualify_models.cascade",
    "run_filter": "qualify_models.filter",
    "FilterResult": "qualify_models.schemas",
    "SentimentResult": "qualify_models.schemas",
    "TranscriptionResult": "qualify_models.schemas",
    "VisionResult": "qualify_models.schemas",
    "run_sentiment": "qualify_models.sentiment",
    "run_transcription": "qualify_models.transcription",
    "run_vision": "qualify_models.vision",
}

# Kept as a literal (not `sorted(_LAZY_EXPORTS)`) so linters can see that the
# TYPE_CHECKING imports above are deliberate re-exports rather than dead ones.
__all__ = [
    "CascadeResult",
    "FilterResult",
    "SentimentResult",
    "TranscriptionResult",
    "VisionResult",
    "run_cascade",
    "run_filter",
    "run_sentiment",
    "run_transcription",
    "run_vision",
]


def __getattr__(name: str) -> Any:
    """Resolve a re-export on first access, importing its module only then."""
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(module_path), name)
    globals()[name] = value  # cache: subsequent lookups skip __getattr__
    return value


def __dir__() -> list[str]:
    return sorted([*globals(), *_LAZY_EXPORTS])
