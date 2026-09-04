import pytest

from scaffold.spec import SpecError, parse

MINIMAL = {"entity": "widget", "fields": [{"name": "label", "type": "text"}]}


def test_defaults_come_from_the_entity_name():
    spec = parse(MINIMAL)
    assert (spec.app, spec.class_name, spec.table_name) == ("widgets", "Widget", "widget")
    assert spec.mount_path == "/widgets"


def test_fk_columns_get_an_id_suffix():
    spec = parse({**MINIMAL, "fields": [{"name": "owner", "type": "fk", "target": "user"}]})
    assert spec.fields[0].column_name == "owner_id"


def test_sensitive_fields_are_split_out():
    spec = parse(
        {
            **MINIMAL,
            "fields": [
                {"name": "label", "type": "text"},
                {"name": "note", "type": "text", "sensitive": True},
            ],
        }
    )
    assert [field.name for field in spec.visible_fields] == ["label"]
    assert [field.name for field in spec.sensitive_fields] == ["note"]


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"fields": [{"name": "a", "type": "text"}]}, "entity"),
        ({**MINIMAL, "entity": "Widget"}, "snake_case"),
        ({**MINIMAL, "fields": []}, "non-empty"),
        ({**MINIMAL, "fields": [{"name": "id", "type": "text"}]}, "provided by the generator"),
        ({**MINIMAL, "fields": [{"name": "a", "type": "blob"}]}, "type must be one of"),
        ({**MINIMAL, "fields": [{"name": "a", "type": "enum"}]}, "options list"),
        ({**MINIMAL, "fields": [{"name": "a", "type": "fk"}]}, "target"),
        (
            {**MINIMAL, "fields": [{"name": "a", "type": "text", "options": ["x"]}]},
            "options only apply",
        ),
        ({**MINIMAL, "colour": "red"}, "unknown keys"),
        (
            {
                **MINIMAL,
                "fields": [{"name": "a", "type": "text"}, {"name": "a", "type": "text"}],
            },
            "duplicate field",
        ),
    ],
)
def test_bad_specs_are_rejected(raw, message):
    with pytest.raises(SpecError, match=message):
        parse(raw)


def test_a_field_cannot_be_required_and_sensitive():
    """A non-admin never sees it, so requiring it would lock them out of the form."""
    with pytest.raises(SpecError, match="required and sensitive"):
        parse(
            {
                **MINIMAL,
                "fields": [{"name": "note", "type": "text", "required": True, "sensitive": True}],
            }
        )


def test_a_bool_cannot_be_sensitive():
    with pytest.raises(SpecError, match="bool cannot be sensitive"):
        parse({**MINIMAL, "fields": [{"name": "flag", "type": "bool", "sensitive": True}]})
