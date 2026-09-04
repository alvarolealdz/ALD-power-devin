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


def test_description_workflow_tones_and_samples_are_parsed():
    spec = parse(
        {
            **MINIMAL,
            "description": "  A useful description.  ",
            "fields": [
                {"name": "label", "type": "text", "sample": ["One", "Two"]},
                {
                    "name": "status",
                    "type": "enum",
                    "options": ["draft", "done"],
                    "workflow": True,
                    "required": True,
                    "open": ["draft"],
                    "tones": {"done": "success"},
                },
            ],
        }
    )
    assert spec.description == "A useful description."
    assert spec.workflow_field is spec.fields[1]
    assert spec.fields[1].open == ("draft",)
    assert spec.fields[1].closed == ("done",)
    assert spec.fields[1].tone("done") == "success"
    assert spec.fields[1].tone("draft") == "neutral"
    assert spec.fields[0].sample == ("One", "Two")


def test_singular_title_is_parsed_and_overrides_the_default():
    spec = parse({**MINIMAL, "singular": "A widget"})
    assert spec.singular == "A widget"
    assert spec.singular_title == "A widget"


def test_singular_heading_only_uppercases_the_first_character():
    assert parse({**MINIMAL, "singular": "KYC review"}).singular_heading == "KYC review"
    assert parse({**MINIMAL, "singular": "refund"}).singular_heading == "Refund"


@pytest.mark.parametrize("decimals", [-1, 5, True, "2"])
def test_number_decimals_are_bounded_integers(decimals):
    with pytest.raises(SpecError, match="decimals"):
        parse({**MINIMAL, "fields": [{"name": "amount", "type": "number", "decimals": decimals}]})


def test_decimals_are_rejected_on_non_numbers():
    with pytest.raises(SpecError, match="only applies"):
        parse({**MINIMAL, "fields": [{"name": "label", "type": "text", "decimals": 2}]})


def test_unit_field_must_be_text_or_enum_and_exist():
    with pytest.raises(SpecError, match="does not exist"):
        parse(
            {**MINIMAL, "fields": [{"name": "amount", "type": "number", "unit_field": "currency"}]}
        )
    with pytest.raises(SpecError, match="text or enum"):
        parse(
            {
                **MINIMAL,
                "fields": [
                    {"name": "amount", "type": "number", "unit_field": "count"},
                    {"name": "count", "type": "number"},
                ],
            }
        )
    with pytest.raises(SpecError, match="must be sensitive when the number is"):
        parse(
            {
                **MINIMAL,
                "fields": [
                    {
                        "name": "amount",
                        "type": "number",
                        "sensitive": True,
                        "unit_field": "currency",
                    },
                    {"name": "currency", "type": "text"},
                ],
            }
        )


@pytest.mark.parametrize(
    "sample",
    [
        {"min": 4},
        {"max": 9},
        {"min": 9, "max": 4},
        {"min": "low", "max": 4},
        {"min": "99999999999999.5", "max": "100000000000000"},
    ],
)
def test_number_sample_ranges_are_validated(sample):
    with pytest.raises(SpecError, match="sample"):
        parse(
            {
                **MINIMAL,
                "fields": [{"name": "amount", "type": "number", "sample": sample}],
            }
        )


@pytest.mark.parametrize(
    "singular",
    ["x" * 61, "line\nbreak"],
)
def test_singular_title_is_validated(singular):
    with pytest.raises(SpecError, match="singular"):
        parse({**MINIMAL, "singular": singular})


@pytest.mark.parametrize(
    ("field", "message"),
    [
        (
            {"name": "status", "type": "enum", "options": ["draft"], "tones": {"draft": "bad"}},
            "tone",
        ),
        ({"name": "label", "type": "text", "workflow": True}, "workflow"),
        ({"name": "label", "type": "text", "sample": "unknown"}, "sample"),
    ],
)
def test_new_field_options_are_validated(field, message):
    with pytest.raises(SpecError, match=message):
        parse({**MINIMAL, "fields": [field]})


def test_empty_sample_lists_are_rejected():
    with pytest.raises(SpecError, match="sample list cannot be empty"):
        parse({**MINIMAL, "fields": [{"name": "label", "type": "text", "sample": []}]})


def test_two_workflow_fields_are_rejected():
    with pytest.raises(SpecError, match="at most one"):
        parse(
            {
                **MINIMAL,
                "fields": [
                    {
                        "name": "first",
                        "type": "enum",
                        "required": True,
                        "options": ["a"],
                        "workflow": True,
                    },
                    {
                        "name": "second",
                        "type": "enum",
                        "required": True,
                        "options": ["b"],
                        "workflow": True,
                    },
                ],
            }
        )


@pytest.mark.parametrize(
    ("open_states", "message"),
    [
        ([], "non-empty"),
        (["draft", "draft"], "duplicates"),
        (["unknown"], "one of"),
        (["draft", "done"], "closed"),
    ],
)
def test_workflow_open_states_are_validated(open_states, message):
    with pytest.raises(SpecError, match=message):
        parse(
            {
                **MINIMAL,
                "fields": [
                    {
                        "name": "status",
                        "type": "enum",
                        "required": True,
                        "options": ["draft", "done"],
                        "workflow": True,
                        "open": open_states,
                    }
                ],
            }
        )


def test_open_states_are_rejected_without_workflow():
    with pytest.raises(SpecError, match="only applies"):
        parse(
            {
                **MINIMAL,
                "fields": [
                    {
                        "name": "status",
                        "type": "enum",
                        "options": ["draft", "done"],
                        "open": ["draft"],
                    }
                ],
            }
        )


def test_workflow_transitions_parse_and_default_allowed_targets():
    spec = parse(
        {
            **MINIMAL,
            "fields": [
                {
                    "name": "status",
                    "type": "enum",
                    "required": True,
                    "options": ["pending", "approved", "rejected", "escalated"],
                    "workflow": True,
                    "transitions": {
                        "pending": ["approved", "escalated"],
                        "approved": [],
                    },
                }
            ],
        }
    )
    field = spec.workflow_field
    assert field is not None
    assert field.transitions == {
        "pending": ("approved", "escalated"),
        "approved": (),
    }
    assert field.allowed_from("pending") == ("approved", "escalated")
    assert field.allowed_from("approved") == ()
    assert field.allowed_from("rejected") == ("pending", "approved", "escalated")


@pytest.mark.parametrize(
    ("transitions", "message"),
    [
        ({"unknown": ["approved"]}, "transition state"),
        ({"pending": ["unknown"]}, "transition target"),
        ({"pending": ["pending"]}, "itself"),
    ],
)
def test_workflow_transitions_are_validated(transitions, message):
    with pytest.raises(SpecError, match=message):
        parse(
            {
                **MINIMAL,
                "fields": [
                    {
                        "name": "status",
                        "type": "enum",
                        "required": True,
                        "options": ["pending", "approved"],
                        "workflow": True,
                        "transitions": transitions,
                    }
                ],
            }
        )


def test_transitions_are_rejected_without_workflow():
    with pytest.raises(SpecError, match="only applies"):
        parse(
            {
                **MINIMAL,
                "fields": [
                    {
                        "name": "status",
                        "type": "enum",
                        "required": True,
                        "options": ["pending", "approved"],
                        "transitions": {"pending": ["approved"]},
                    }
                ],
            }
        )


def test_workflow_fields_are_required():
    with pytest.raises(SpecError, match="workflow fields must be required"):
        parse(
            {
                **MINIMAL,
                "fields": [
                    {
                        "name": "status",
                        "type": "enum",
                        "options": ["pending", "approved"],
                        "workflow": True,
                    }
                ],
            }
        )


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"fields": [{"name": "a", "type": "text"}]}, "entity"),
        ({**MINIMAL, "entity": "Widget"}, "snake_case"),
        ({**MINIMAL, "fields": []}, "non-empty"),
        ({**MINIMAL, "fields": [{"name": "id", "type": "text"}]}, "provided by the generator"),
        ({**MINIMAL, "fields": [{"name": "metadata", "type": "text"}]}, "reserved"),
        ({**MINIMAL, "app": "health"}, "shadow"),
        ({**MINIMAL, "entity": "user"}, "belongs to foundation"),
        ({**MINIMAL, "fields": [{"name": "a", "type": "blob"}]}, "type must be one of"),
        ({**MINIMAL, "fields": [{"name": "a", "type": "enum"}]}, "options list"),
        (
            {**MINIMAL, "fields": [{"name": "a", "type": "enum", "options": [" draft"]}]},
            "surrounding whitespace",
        ),
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


def test_required_sensitive_fields_make_create_admin_only():
    spec = parse(
        {
            **MINIMAL,
            "fields": [{"name": "note", "type": "text", "required": True, "sensitive": True}],
        }
    )
    assert spec.create_is_admin_only is True
    assert parse(MINIMAL).create_is_admin_only is False


def test_a_sensitive_bool_is_allowed_for_admin_only_toggles():
    field = parse(
        {**MINIMAL, "fields": [{"name": "flag", "type": "bool", "sensitive": True}]}
    ).fields[0]
    assert field.sensitive is True


def test_a_bool_cannot_be_required():
    """An unchecked box submits nothing, so the requirement could never bite."""
    with pytest.raises(SpecError, match="bool cannot be required"):
        parse({**MINIMAL, "fields": [{"name": "flag", "type": "bool", "required": True}]})


@pytest.mark.parametrize("value", ["false", "no", 0, 1, None])
def test_flags_have_to_be_yaml_booleans(value):
    """``bool("false")`` is True, which would mean the opposite of what it says."""
    with pytest.raises(SpecError, match="expected true or false"):
        parse({**MINIMAL, "fields": [{"name": "a", "type": "text", "required": value}]})


def test_a_field_cannot_take_an_fks_relationship_name():
    """The fk defines ``owner`` too, and the second one would overwrite it."""
    with pytest.raises(SpecError, match="collides"):
        parse(
            {
                **MINIMAL,
                "fields": [
                    {"name": "owner", "type": "fk", "target": "user"},
                    {"name": "owner", "type": "text"},
                ],
            }
        )


@pytest.mark.parametrize(
    ("option", "message"),
    [("x" * 65, "longer than"), ("", "blank"), ("a\nb", "control character")],
)
def test_enum_options_have_to_fit_the_column(option, message):
    with pytest.raises(SpecError, match=message):
        parse({**MINIMAL, "fields": [{"name": "a", "type": "enum", "options": [option]}]})


def test_singular_heading_capitalises_only_the_first_character():
    from scaffold.spec import Spec

    assert Spec.singular_heading.fget(type("S", (), {"singular_title": "refund"})()) == "Refund"
    assert (
        Spec.singular_heading.fget(type("S", (), {"singular_title": "KYC review"})())
        == "KYC review"
    )
