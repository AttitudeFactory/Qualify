"""`qualify_api.meegle.schema.SchemaResolver` — names to keys, cached, with a fake source."""

from __future__ import annotations

import pytest

from qualify_api.meegle.client import FieldMeta, WorkflowNode
from qualify_api.meegle.schema import MeegleSchemaError, SchemaResolver
from qualify_api.meegle.settings import MeegleNames


class Source:
    def __init__(self) -> None:
        self.fields = [
            FieldMeta("field_mail", "Correo", "text"),
            FieldMeta("field_note", "Nota personal", "multi_text"),
            FieldMeta(
                "field_estado",
                "Estado  Qualify",  # double space: names are normalized
                "select",
                (("pendiente", "option_1"), ("Invitada", "option_2"), ("error", "option_8")),
            ),
            FieldMeta("field_ref", "Qualify ref", "text"),
        ]
        self.nodes: dict[int, list[WorkflowNode]] = {
            1: [
                WorkflowNode("started", "started", "Datos"),
                WorkflowNode("state_0", "state_0", "Invitada"),
                WorkflowNode("state_1", "state_1", "Registrada"),
            ]
        }
        self.fields_calls = 0
        self.workflow_calls: list[int] = []

    def fields_meta(self) -> list[FieldMeta]:
        self.fields_calls += 1
        return list(self.fields)

    def workflow(self, work_item_id: int) -> list[WorkflowNode]:
        self.workflow_calls.append(work_item_id)
        return list(self.nodes.get(work_item_id, []))


@pytest.fixture
def source() -> Source:
    return Source()


@pytest.fixture
def resolver(source: Source) -> SchemaResolver:
    return SchemaResolver(source, MeegleNames())


def test_field_keys_are_resolved_by_display_name_once(
    resolver: SchemaResolver, source: Source
) -> None:
    assert resolver.field_key("Correo") == "field_mail"
    assert resolver.field_key("correo") == "field_mail"
    assert resolver.field_key("Estado Qualify") == "field_estado"
    assert resolver.field_key("field_ref") == "field_ref"  # a key works as a name too
    assert source.fields_calls == 1


def test_a_missing_field_refreshes_once_then_raises(
    resolver: SchemaResolver, source: Source
) -> None:
    resolver.field_key("Correo")
    with pytest.raises(MeegleSchemaError, match="Tenant"):
        resolver.field_key("Tenant")
    assert source.fields_calls == 2  # one refresh, in case the field was just added
    source.fields.append(FieldMeta("field_tenant", "Tenant", "text"))
    assert resolver.field_key("Tenant") == "field_tenant"


def test_select_values_come_from_the_options_or_pass_through(
    resolver: SchemaResolver,
) -> None:
    assert resolver.select_value("Estado Qualify", "invitada") == "option_2"
    assert resolver.select_value("Estado Qualify", "ERROR") == "option_8"
    with pytest.raises(MeegleSchemaError, match="vencida"):
        resolver.select_value("Estado Qualify", "vencida")
    # Not a select (a text field named like one): the label itself is the value.
    assert resolver.select_value("Qualify ref", "whatever") == "whatever"


def test_a_select_is_written_as_value_and_label(resolver: SchemaResolver) -> None:
    """The real Open API rejects a bare option value on write (20006, 2026-10-21)."""
    assert resolver.select_field_value("Estado Qualify", "invitada") == {
        "value": "option_2",
        "label": "invitada",
    }
    assert resolver.select_field_value("Qualify ref", "whatever") == "whatever"


def test_node_ids_and_names_are_cached_per_type_and_refreshed_on_miss(
    resolver: SchemaResolver, source: Source
) -> None:
    assert resolver.node_name(1, "started") == "Datos"
    assert resolver.node_id(1, "Registrada") == "state_1"
    assert resolver.node_id(1, "registrada") == "state_1"
    assert source.workflow_calls == [1]  # one read served both
    # Another item of the same type: the cache answers, no call.
    assert resolver.node_name(2, "state_0") == "Invitada"
    assert source.workflow_calls == [1]
    # A key the cache does not know → the workflow of THAT item is read.
    source.nodes[2] = [*source.nodes[1], WorkflowNode("state_9", "state_9", "Kit")]
    assert resolver.node_name(2, "state_9") == "Kit"
    assert source.workflow_calls == [1, 2]
    assert resolver.node_name(2, "nope") is None
    with pytest.raises(MeegleSchemaError, match="Primera"):
        resolver.node_id(2, "Primera publicación")
