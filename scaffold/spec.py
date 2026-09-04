"""The spec: what an app is, before any code exists.

```yaml
app: inventory              # optional, defaults to the entity name pluralised
entity: item                # snake_case, singular
title: Items                # optional, human label for the screens
fields:
  - name: label
    type: text
    required: true
  - name: category
    type: enum
    options: [alpha, beta]
  - name: owner
    type: fk
    target: user
  - name: internal_note
    type: text
    sensitive: true
```

Anything else is a spec error, raised before a single file is written.
"""

import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import Any

import yaml

TEXT = "text"
NUMBER = "number"
DATE = "date"
BOOL = "bool"
ENUM = "enum"
FK = "fk"
FIELD_TYPES = (TEXT, NUMBER, DATE, BOOL, ENUM, FK)

#: Enum values are stored in a column this wide; codegen emits the same number.
ENUM_LENGTH = 64

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
_RESERVED_FIELD_NAMES = frozenset({"id", "created_at", "updated_at", "metadata", "registry"})
_RESERVED_APP_NAMES = frozenset(
    {
        "health",
        "static",
        "switch_user",
        "switch-user",
        "docs",
        "redoc",
        "openapi.json",
    }
)
_FOUNDATION_TABLES = frozenset({"user", "role", "audit_log"})
_FIELD_KEYS = frozenset({"name", "type", "label", "required", "sensitive", "options", "target"})
_SPEC_KEYS = frozenset({"app", "entity", "title", "fields"})


class SpecError(ValueError):
    """Raised when a spec cannot be turned into an app."""


@dataclass(frozen=True)
class Field:
    name: str
    type: str
    label: str
    required: bool = False
    sensitive: bool = False
    options: tuple[str, ...] = ()
    target: str | None = None

    @property
    def column_name(self) -> str:
        """FKs get the conventional ``_id`` suffix; everything else is as written."""
        return f"{self.name}_id" if self.type == FK else self.name

    @property
    def is_reference(self) -> bool:
        return self.type == FK


@dataclass(frozen=True)
class Spec:
    app: str
    entity: str
    title: str
    fields: tuple[Field, ...] = dataclass_field(default_factory=tuple)

    @property
    def class_name(self) -> str:
        return "".join(part.capitalize() for part in self.entity.split("_"))

    @property
    def table_name(self) -> str:
        return self.entity

    @property
    def mount_path(self) -> str:
        return f"/{self.app.replace('_', '-')}"

    @property
    def singular_title(self) -> str:
        return _humanise(self.entity)

    @property
    def sensitive_fields(self) -> tuple[Field, ...]:
        return tuple(field for field in self.fields if field.sensitive)

    @property
    def visible_fields(self) -> tuple[Field, ...]:
        """The fields everyone sees. Sensitive ones are added back for admins only."""
        return tuple(field for field in self.fields if not field.sensitive)

    @property
    def create_is_admin_only(self) -> bool:
        """A required field nobody but an admin can see means nobody but an admin can create."""
        return any(field.required and field.sensitive for field in self.fields)


def load(path: str | Path) -> Spec:
    """Read and validate a spec file."""
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as error:
        raise SpecError(f"{path}: not valid YAML: {error}") from error
    if not isinstance(raw, dict):
        raise SpecError(f"{path}: expected a mapping at the top level")
    return parse(raw)


def parse(raw: dict[str, Any]) -> Spec:
    _reject_unknown_keys(raw, _SPEC_KEYS, "spec")
    entity = _identifier(raw.get("entity"), "entity")
    if entity in _FOUNDATION_TABLES:
        raise SpecError(f"table {entity!r} belongs to foundation")
    app = _identifier(raw.get("app") or _pluralise(entity), "app")
    if app in _RESERVED_APP_NAMES:
        raise SpecError(f"app {app!r} would shadow a foundation route")
    title = str(raw.get("title") or _humanise(app))

    raw_fields = raw.get("fields")
    if not isinstance(raw_fields, list) or not raw_fields:
        raise SpecError("fields must be a non-empty list")

    fields = tuple(_parse_field(item, index) for index, item in enumerate(raw_fields))
    _reject_duplicates(fields)
    return Spec(app=app, entity=entity, title=title, fields=fields)


def _parse_field(raw: Any, index: int) -> Field:
    where = f"fields[{index}]"
    if not isinstance(raw, dict):
        raise SpecError(f"{where}: expected a mapping")
    _reject_unknown_keys(raw, _FIELD_KEYS, where)

    name = _identifier(raw.get("name"), f"{where}.name")
    if name in _RESERVED_FIELD_NAMES:
        if name in {"metadata", "registry"}:
            raise SpecError(
                f"{where}: {name!r} is reserved (it already means something on the model)"
            )
        raise SpecError(f"{where}: {name!r} is provided by the generator, drop it from the spec")

    field_type = raw.get("type")
    if field_type not in FIELD_TYPES:
        raise SpecError(
            f"{where}: type must be one of {', '.join(FIELD_TYPES)}, got {field_type!r}"
        )

    options = _parse_options(raw, where, field_type)
    target = _parse_target(raw, where, field_type)
    required = _flag(raw, "required", where)
    sensitive = _flag(raw, "sensitive", where)
    if required and field_type == BOOL:
        raise SpecError(
            f"{where}: a bool cannot be required — an unchecked box submits nothing, "
            "so the value would always be allowed to be false"
        )
    if sensitive and field_type == BOOL:
        raise SpecError(
            f"{where}: a bool cannot be sensitive — an unchecked box and a hidden one "
            "look the same on submit"
        )

    return Field(
        name=name,
        type=field_type,
        label=str(raw.get("label") or _humanise(name)),
        required=required,
        sensitive=sensitive,
        options=options,
        target=target,
    )


def _parse_options(raw: dict[str, Any], where: str, field_type: str) -> tuple[str, ...]:
    options = raw.get("options")
    if field_type != ENUM:
        if options:
            raise SpecError(f"{where}: options only apply to enum fields")
        return ()
    if not isinstance(options, list) or not options:
        raise SpecError(f"{where}: enum fields need a non-empty options list")
    values = tuple(str(option) for option in options)
    if len(set(values)) != len(values):
        raise SpecError(f"{where}: duplicate enum options")
    for value in values:
        if value != value.strip():
            raise SpecError(
                f"{where}: enum option {value!r} has surrounding whitespace, "
                "which the form strips before validating"
            )
        if not value.strip():
            raise SpecError(f"{where}: enum options cannot be blank")
        if len(value) > ENUM_LENGTH:
            raise SpecError(
                f"{where}: enum option {value!r} is longer than the "
                f"{ENUM_LENGTH} characters the column holds"
            )
        if any(character in value for character in "\r\n\x00"):
            raise SpecError(f"{where}: enum option {value!r} contains a control character")
    return values


def _parse_target(raw: dict[str, Any], where: str, field_type: str) -> str | None:
    target = raw.get("target")
    if field_type != FK:
        if target:
            raise SpecError(f"{where}: target only applies to fk fields")
        return None
    if not target:
        raise SpecError(f"{where}: fk fields need a target table")
    return _identifier(target, f"{where}.target")


def _flag(raw: dict[str, Any], key: str, where: str) -> bool:
    """A flag is a YAML boolean.

    ``bool("false")`` is ``True``, so a quoted flag would quietly mean the
    opposite of what it says; the spec says so rather than guessing.
    """
    value = raw.get(key, False)
    if not isinstance(value, bool):
        raise SpecError(f"{where}.{key}: expected true or false, got {value!r}")
    return value


def _reject_unknown_keys(raw: dict[str, Any], allowed: frozenset[str], where: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise SpecError(f"{where}: unknown keys {', '.join(unknown)}")


def _reject_duplicates(fields: tuple[Field, ...]) -> None:
    """Every attribute a field puts on the model has to be its own.

    An fk claims two of them — the ``_id`` column and the relationship named
    after the field — and a second field landing on either one would silently
    overwrite it in the generated class.
    """
    seen: dict[str, int] = {}
    for index, field in enumerate(fields):
        claimed = {field.column_name}
        if field.is_reference:
            claimed.add(field.name)
        for attribute in sorted(claimed):
            owner = seen.get(attribute)
            if owner is None:
                seen[attribute] = index
                continue
            if fields[owner].name == field.name and fields[owner].type == field.type:
                raise SpecError(f"duplicate field {field.name!r}")
            raise SpecError(
                f"field {field.name!r} collides with {fields[owner].name!r}: "
                f"both would define {attribute!r} on the model"
            )


def _identifier(value: Any, where: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.match(value):
        raise SpecError(f"{where}: expected a lower_snake_case identifier, got {value!r}")
    return value


def _pluralise(word: str) -> str:
    if word.endswith(("s", "x", "z", "ch", "sh")):
        return f"{word}es"
    if word.endswith("y") and word[-2:-1] not in "aeiou":
        return f"{word[:-1]}ies"
    return f"{word}s"


def _humanise(name: str) -> str:
    return name.replace("_", " ").capitalize()
