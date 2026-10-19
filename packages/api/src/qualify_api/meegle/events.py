"""The recorded value of one Meegle change, typed (`envelope.parse_meegle_delivery` stores
`{"source": …, "data": {…}}`; this is the `data` the handlers read).

Only what the handlers use is modelled; everything else is ignored, never rejected. The
shapes come from the Event Listener docs (verified 2026-10-19): every event carries
`user_info` (who did it), `work_item_info[0]` (which item) and `work_item_type_key`;
`1001`/`1009`/`1005`/`3001` add `field_info[]` with `before_field_value` /
`after_field_value` as strings; `2001`/`2004` add `node_info.update_nodes[]` (template node
keys) and `node_info.reason`; `1005` adds `reason`.

`source` is at the top level of the recorded value, next to `data`: `normal`, `automation`,
`system` — or `openapi`, Qualify's own write-back, which the handlers never act on.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from qualify_api.meegle.envelope import SOURCE_OPENAPI


class WorkItemRef(BaseModel):
    model_config = ConfigDict(extra="ignore")
    work_item_id: int
    work_item_name: str = ""
    work_item_type_key: str = ""


class NodeInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    update_nodes: list[str] | None = None
    reason: str | None = None


class FieldChange(BaseModel):
    """One entry of `field_info[]`. Meegle sends every value as a string (a select's option
    VALUE, a JSON list for multi-valued fields, `""` for empty) — rendering is the
    notifier's job (`tickets.py`), with the field metadata of the item's type."""

    model_config = ConfigDict(extra="ignore")
    field_key: str = ""
    alias: str = ""
    field_type: str = ""
    before_field_value: str | None = None
    after_field_value: str | None = None


class UserInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_key: str = ""
    name_cn: str = ""
    name_en: str = ""
    email: str = ""

    def display_name(self) -> str:
        return self.name_en or self.name_cn or self.email or self.user_key


class EventData(BaseModel):
    model_config = ConfigDict(extra="ignore")
    event_type: int
    idempotent_key: str
    work_item_type_key: str = ""
    project_key: str = ""
    flow_type: int | None = None
    reason: str | None = None
    work_item_info: list[WorkItemRef] = []
    node_info: NodeInfo | None = None
    field_info: list[FieldChange] = []
    user_info: UserInfo | None = None


class MeegleEvent(BaseModel):
    """The recorded value of one Meegle change (`envelope.parse_meegle_delivery`)."""

    model_config = ConfigDict(extra="ignore")
    source: str | None = None
    data: EventData

    @property
    def work_item_id(self) -> int | None:
        return self.data.work_item_info[0].work_item_id if self.data.work_item_info else None

    @property
    def is_own_write(self) -> bool:
        return self.source == SOURCE_OPENAPI

    @property
    def actor(self) -> str:
        """Who to name in a notice: the person, or the non-human source when there is none."""
        if self.data.user_info is not None and self.data.user_info.display_name():
            return self.data.user_info.display_name()
        if self.source == "automation":
            return "una automatización"
        if self.source == "system":
            return "el sistema"
        return "alguien"
