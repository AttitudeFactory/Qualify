"""The template engine's Python half (plan-mvp-plantillas-remotion.md §2; contract in
``packages/render/CONTRACT.md``).

Remotion renders; this package decides. Four seams, each testable offline:

- :mod:`manifest` / :mod:`registry` — what a template declares (typed ports, immutable
  version, several outputs) and how the published ones are found.
- :mod:`props` — turning a Post (brief + copy + brand kit + product media) into the JSON a
  composition receives, validated against the manifest BEFORE anything is rendered.
- :mod:`recipes` — the recipe router: six ordered rules, always three options with their
  ETA/cost, the suggested one marked, the rule recorded.
- :mod:`client` / :mod:`adapter` — the HTTP client for the render service and the
  ``GenerationProvider`` that lets the existing router, budget check and usage events
  treat a template render like any other engine.

Nothing here imports Pillow: the founder's decision of 2026-10-05 is that pixels are
Remotion's job. Photo normalization at upload stays in :mod:`qualify_creative.photo`.
"""

from qualify_creative.render.manifest import (
    CostModel,
    DurationSpec,
    InputPort,
    OutputKind,
    OutputPort,
    PortType,
    TemplateManifest,
)
from qualify_creative.render.props import (
    BrandProps,
    ProductProps,
    PropsProblem,
    RenderProps,
    build_props,
    validate_props,
)
from qualify_creative.render.recipes import (
    Engine,
    PostFacts,
    RecipeOption,
    suggest_recipes,
)
from qualify_creative.render.registry import TemplateRegistry, default_templates_dir

__all__ = [
    "BrandProps",
    "CostModel",
    "DurationSpec",
    "Engine",
    "InputPort",
    "OutputKind",
    "OutputPort",
    "PortType",
    "PostFacts",
    "ProductProps",
    "PropsProblem",
    "RecipeOption",
    "RenderProps",
    "TemplateManifest",
    "TemplateRegistry",
    "build_props",
    "default_templates_dir",
    "suggest_recipes",
    "validate_props",
]
