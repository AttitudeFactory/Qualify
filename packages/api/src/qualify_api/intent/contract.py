"""`IntentSignal` — the published contract for the commercial intent of one comment
(m-24789644, Interacciones · Fase A).

Published before the classifier exists so the consumer (QUA-229, Conversaciones) can
build against it from day one. What it promises:

- **Multi-label.** A comment can ask about price AND availability at once; each assigned
  class carries its own confidence in [0, 1].
- **`general` is exclusive.** A comment is either general (non-commercial) or carries at
  least one commercial class, never both — "general" means "no commercial question here",
  so pairing it with one is a contradiction, rejected at construction.
- **`commercial_intent` is derived, never stored on its own.** It is `True` exactly when
  some commercial class is present. It is serialized for consumers but recomputed on
  every read, so a payload cannot make it disagree with `classes`.
- **An additional signal.** It does not touch sentiment (QUA-21); it is persisted apart,
  with the same four-part provenance `sentiment.AnalysisVersion` keys on.

Field names stay English like the rest of the code: the ticket's `intencion_comercial`
is `commercial_intent` here.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_serializer,
    field_validator,
)


class IntentClass(StrEnum):
    """What the person commenting needs to know. Values are the persisted/serialized
    form — renaming one is a contract change for every consumer."""

    PRODUCT = "product"
    PRICE = "price"
    AVAILABILITY = "availability"  # stock / existencias
    MODELS = "models"  # another model or an additional version
    VARIANTS = "variants"  # size, colour or another option of the same product
    QUANTITIES = "quantities"  # units available, minimum order, wholesale
    STORE = "store"  # shop / point of sale
    LOCATION = "location"  # address
    HOURS = "hours"
    OTHER_COMMERCIAL = "other_commercial"  # shipping, payment, warranty…
    GENERAL = "general"  # not commercial


COMMERCIAL_CLASSES: Final = frozenset(c for c in IntentClass if c is not IntentClass.GENERAL)

#: Visible (Spanish) label per class, for the Interacciones UI.
INTENT_CLASS_LABELS: Final[Mapping[IntentClass, str]] = MappingProxyType(
    {
        IntentClass.PRODUCT: "Producto",
        IntentClass.PRICE: "Precio",
        IntentClass.AVAILABILITY: "Disponibilidad",
        IntentClass.MODELS: "Modelos",
        IntentClass.VARIANTS: "Variantes",
        IntentClass.QUANTITIES: "Cantidades",
        IntentClass.STORE: "Tienda",
        IntentClass.LOCATION: "Ubicación",
        IntentClass.HOURS: "Horario",
        IntentClass.OTHER_COMMERCIAL: "Otra consulta comercial",
        IntentClass.GENERAL: "Comentario general",
    }
)


class IntentSignal(BaseModel):
    """The commercial intent of one comment (`messages` row, channel=comment) under one
    analysis version."""

    model_config = ConfigDict(frozen=True)

    comment_id: UUID  # `messages.id`
    source_id: str = Field(min_length=1)  # Meta's comment id
    classes: Mapping[IntentClass, float]  # assigned class -> confidence
    detector_version: str = Field(min_length=1)
    pipeline_version: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    # NULL when the model exposes no pinned revision — same honest-null rule as
    # `qualify_models.schemas.SentimentResult.model_revision`; never invent one.
    model_revision: str | None = None

    @field_validator("classes")
    @classmethod
    def _check_classes(cls, value: Mapping[IntentClass, float]) -> Mapping[IntentClass, float]:
        if not value:
            raise ValueError("an IntentSignal needs at least one class")
        for intent_class, confidence in value.items():
            if not 0.0 <= confidence <= 1.0:
                raise ValueError(f"confidence for {intent_class} must be in [0, 1]")
        if IntentClass.GENERAL in value and len(value) > 1:
            raise ValueError("'general' cannot be combined with a commercial class")
        # Read-only view: a frozen model whose dict could still be mutated in place would
        # let `classes` drift from what was validated.
        return MappingProxyType(dict(value))

    @field_serializer("classes")
    def _serialize_classes(self, value: Mapping[IntentClass, float]) -> dict[str, float]:
        return {str(intent_class): confidence for intent_class, confidence in value.items()}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def commercial_intent(self) -> bool:
        return any(intent_class in COMMERCIAL_CLASSES for intent_class in self.classes)
