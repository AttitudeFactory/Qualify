"""The `LayerSpec` contract (m-25017283, ADR 49 §2 item 2): `schema.py` (pydantic),
`catalog_v1.json` (the closed catalog's numbers; `packages/render` keeps its own copy, a
comparison test lands with whichever branch merges second) and `layer_spec_v1.schema.json`
(the committed JSON Schema for `packages/render`)."""

from qualify_creative.layer_spec.schema import (
    LAYOUT_VERSION,
    SPEC_VERSION,
    Anchor,
    CarouselPlace,
    CarouselRole,
    ContainerColor,
    HighlightContent,
    HighlightKind,
    InfoBlock,
    InfoKind,
    LayerSpec,
    LayoutId,
    PhotoReading,
    PriceRef,
    catalog,
    export_json_schema,
    free_text_problems,
    json_schema,
)

__all__ = [
    "LAYOUT_VERSION",
    "SPEC_VERSION",
    "Anchor",
    "CarouselPlace",
    "CarouselRole",
    "ContainerColor",
    "HighlightContent",
    "HighlightKind",
    "InfoBlock",
    "InfoKind",
    "LayerSpec",
    "LayoutId",
    "PhotoReading",
    "PriceRef",
    "catalog",
    "export_json_schema",
    "free_text_problems",
    "json_schema",
]
