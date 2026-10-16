"""Names → keys: resolve the item's field keys, select values and node ids once, by name.

The team builds the "Alta de cliente" type by hand in Meegle's UI (plan §2, M0), so the
field keys (`field_abc123`) and the select option values are unknown to the code and may
differ between the real space and a test space. Only the **display names** are agreed
(`MeegleNames`), and this resolver turns them into what the Open API wants:

- `field_key("Correo")` → the key, from `POST /field/all` (one call per process, cached);
- `select_value("Estado Qualify", "invitada")` → the option value for that label (or the
  label itself when the field is not a select, so a `text` "Estado Qualify" still works);
- `node_id(work_item_id, "Registrada")` / `node_name(work_item_id, "state_2")` → from the
  item's workflow. Node ids are template-level (`state_0`, `started`, …: the same for every
  item of the type), so the map is cached per work item TYPE; a miss re-reads the workflow
  of the item at hand before giving up, which also covers a template edit.

A name that does not resolve is `MeegleSchemaError`. The handlers let it propagate: the
queue retries with backoff, which gives whoever is editing the item type time to add the
missing field, and ends `dead` with the name in `last_error` if nobody does.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from typing import Protocol

from qualify_api.meegle.client import FieldMeta, WorkflowNode
from qualify_api.meegle.settings import MeegleNames


class MeegleSchemaError(LookupError):
    """A configured field or node name does not exist in the work item type."""


class SchemaSource(Protocol):
    def fields_meta(self) -> list[FieldMeta]: ...

    def workflow(self, work_item_id: int) -> list[WorkflowNode]: ...


def _norm(name: str) -> str:
    return " ".join(name.split()).casefold()


class SchemaResolver:
    def __init__(self, source: SchemaSource, names: MeegleNames | None = None) -> None:
        self._source = source
        self.names = names or MeegleNames()
        self._lock = threading.Lock()
        self._fields: dict[str, FieldMeta] | None = None  # by normalized name
        self._nodes_by_name: dict[str, str] = {}  # normalized name -> node id
        self._nodes_by_key: dict[str, str] = {}  # node id / state_key -> display name

    # -- fields ----------------------------------------------------------------------

    def _load_fields(self, *, force: bool = False) -> dict[str, FieldMeta]:
        with self._lock:
            if self._fields is None or force:
                by_name: dict[str, FieldMeta] = {}
                for meta in self._source.fields_meta():
                    if meta.name:
                        by_name.setdefault(_norm(meta.name), meta)
                    by_name.setdefault(_norm(meta.key), meta)
                self._fields = by_name
            return self._fields

    def field(self, name: str) -> FieldMeta:
        meta = self._load_fields().get(_norm(name))
        if meta is None:
            meta = self._load_fields(force=True).get(_norm(name))
        if meta is None:
            raise MeegleSchemaError(f"field {name!r} not found in the work item type")
        return meta

    def field_key(self, name: str) -> str:
        return self.field(name).key

    def select_value(self, name: str, label: str) -> str:
        meta = self.field(name)
        if not meta.options:
            return label
        value = meta.option_value(label)
        if value is None:
            raise MeegleSchemaError(f"field {name!r} has no option labelled {label!r}")
        return value

    # -- nodes -----------------------------------------------------------------------

    def _index_nodes(self, nodes: Iterable[WorkflowNode]) -> None:
        with self._lock:
            for node in nodes:
                if not node.name:
                    continue
                self._nodes_by_name[_norm(node.name)] = node.id
                self._nodes_by_key[node.id] = node.name
                if node.state_key:
                    self._nodes_by_key[node.state_key] = node.name

    def node_id(self, work_item_id: int, name: str) -> str:
        key = _norm(name)
        node_id = self._nodes_by_name.get(key)
        if node_id is None:
            self._index_nodes(self._source.workflow(work_item_id))
            node_id = self._nodes_by_name.get(key)
        if node_id is None:
            raise MeegleSchemaError(f"node {name!r} not found in work item {work_item_id}")
        return node_id

    def node_name(self, work_item_id: int, node_key: str) -> str | None:
        """The display name behind a node id / state key of the event, or None if the
        workflow of that item does not have it either (a node of another flow)."""
        name = self._nodes_by_key.get(node_key)
        if name is None:
            self._index_nodes(self._source.workflow(work_item_id))
            name = self._nodes_by_key.get(node_key)
        return name
