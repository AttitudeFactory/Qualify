"""Template manifest — CONTRACT.md §1, as a pydantic model.

A manifest is the template's public face: which ports it takes, which outputs it yields,
how long a render takes. It is versioned and immutable once published: a change bumps
`version`, and every piece ever rendered keeps `(id, version)` in its provenance, which is
what makes "template v2 outperforms v1" a query instead of an anecdote (design D16).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PortType(StrEnum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    IMAGE = "image"
    IMAGE_LIST = "image[]"
    VIDEO = "video"
    BRAND_KIT = "brand_kit"
    PRODUCT_LIST = "product[]"


class OutputKind(StrEnum):
    VIDEO = "video"
    STILL = "still"


class InputPort(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: PortType
    optional: bool = False
    #: `string`: max characters. `image[]` / `product[]`: max items.
    max: int | None = Field(default=None, ge=1)
    #: `image[]` / `product[]`: min items.
    min: int | None = Field(default=None, ge=0)
    #: `string`: the only values accepted.
    enum: tuple[str, ...] | None = None

    @model_validator(mode="after")
    def _bounds(self) -> InputPort:
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("port min cannot exceed max")
        if self.enum is not None and self.type is not PortType.STRING:
            raise ValueError("enum applies to string ports only")
        return self

    @property
    def is_list(self) -> bool:
        return self.type in (PortType.IMAGE_LIST, PortType.PRODUCT_LIST)


class OutputPort(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: OutputKind
    width: int = Field(ge=16)
    height: int = Field(ge=16)
    #: The Remotion composition id, `<template-id>-v<version>--<port>` (CONTRACT §3; Remotion
    #: only allows letters, digits and hyphens in an id, so underscores become hyphens).
    composition: str

    @property
    def aspect_ratio(self) -> str:
        return _aspect(self.width, self.height)

    @property
    def media_type(self) -> str:
        """The `image_assets.media_type` value this output lands as."""
        return "video" if self.kind is OutputKind.VIDEO else "image"

    @property
    def extension(self) -> str:
        return "mp4" if self.kind is OutputKind.VIDEO else "png"


class DurationSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    #: `script` — derived from the texts/photos by the composition; `fixed` — `min_sec`.
    from_: str = Field(default="script", alias="from")
    min_sec: float = Field(default=8, gt=0)
    max_sec: float = Field(default=30, gt=0)

    @model_validator(mode="after")
    def _range(self) -> DurationSpec:
        if self.min_sec > self.max_sec:
            raise ValueError("duration min_sec cannot exceed max_sec")
        return self


class CostModel(BaseModel):
    """Render TIME, not money (CONTRACT §1): the service runs on our own machine."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    seconds_per_video_sec: float = Field(default=2.0, ge=0)
    seconds_per_still: float = Field(default=4.0, ge=0)

    def eta_seconds(self, outputs: dict[str, OutputPort], video_duration_sec: float) -> float:
        total = 0.0
        for port in outputs.values():
            if port.kind is OutputKind.VIDEO:
                total += self.seconds_per_video_sec * video_duration_sec
            else:
                total += self.seconds_per_still
        return round(total, 1)


class TemplateManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    version: int = Field(ge=1)
    name: str
    niche: tuple[str, ...] = ()
    serves_angles: tuple[str, ...] = ()
    inputs: dict[str, InputPort]
    outputs: dict[str, OutputPort]
    duration: DurationSpec = DurationSpec()
    cost_model: CostModel = CostModel()

    @model_validator(mode="after")
    def _well_formed(self) -> TemplateManifest:
        if not self.outputs:
            raise ValueError(f"template {self.id} declares no outputs")
        for port, out in self.outputs.items():
            expected = self.composition_id(port)
            if out.composition != expected:
                raise ValueError(
                    f"output {port!r} of {self.id} v{self.version} names composition "
                    f"{out.composition!r}; the contract requires {expected!r}"
                )
        return self

    def composition_id(self, port: str) -> str:
        return f"{self.id.replace('_', '-')}-v{self.version}--{port}"

    @property
    def key(self) -> str:
        return f"{self.id}@{self.version}"

    @property
    def render_count(self) -> int:
        """Every output is one render for licensing purposes (backlog §0.1)."""
        return len(self.outputs)

    @property
    def has_video_output(self) -> bool:
        return any(o.kind is OutputKind.VIDEO for o in self.outputs.values())

    def serves(self, angle: str) -> bool:
        return not self.serves_angles or angle in self.serves_angles

    def fits_niche(self, niche: str | None) -> bool:
        return niche is None or not self.niche or niche in self.niche

    def required_photos(self) -> tuple[int, int | None]:
        """(min, max) photos the template takes; (0, 0) when it has no photo port."""
        port = self.inputs.get("photos")
        if port is None or port.type is not PortType.IMAGE_LIST:
            return (0, 0)
        return (port.min or 0, port.max)

    @property
    def needs_video(self) -> bool:
        port = self.inputs.get("video")
        return port is not None and port.type is PortType.VIDEO and not port.optional


def _aspect(width: int, height: int) -> str:
    from math import gcd

    g = gcd(width, height)
    return f"{width // g}:{height // g}"
