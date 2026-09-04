"""Turning spec fields into the strings that end up in generated files.

Everything here is a pure function from a ``Field`` to a fragment of Python.
It lives apart from ``generate`` so the fragments can be read and tested
without touching the filesystem.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from foundation.forms import NUMBER_PRECISION, NUMBER_SCALE
from scaffold.spec import (
    BOOL,
    DATE,
    ENUM,
    ENUM_LENGTH,
    FK,
    NUMBER,
    TEXT,
    Field,
    Spec,
    SpecError,
)

TEXT_LENGTH = 255
NUMERIC = f"Numeric({NUMBER_PRECISION}, {NUMBER_SCALE})"

#: Foreign keys the foundation always offers. Anything else must be another
#: generated app's table, resolved by looking at what is already on disk.
_FOUNDATION_TARGETS = {
    "user": ("foundation.models", "User", "display_name"),
    "role": ("foundation.models", "Role", "name"),
}


@dataclass(frozen=True)
class Reference:
    """Where a foreign key points, and how to show it in a dropdown."""

    table: str
    module: str
    class_name: str
    label_attr: str

    @property
    def import_line(self) -> str:
        return f"from {self.module} import {self.class_name}"


def resolve_reference(target: str, apps_dir: Path) -> Reference:
    if target in _FOUNDATION_TARGETS:
        module, class_name, label = _FOUNDATION_TARGETS[target]
        return Reference(target, module, class_name, label)
    found = _find_app_model(target, apps_dir)
    if found is None:
        raise SpecError(
            f"fk target {target!r} is not a table I can find: "
            f"expected one of {', '.join(sorted(_FOUNDATION_TARGETS))} "
            "or an app you have already generated"
        )
    return found


def _find_app_model(table: str, apps_dir: Path) -> Reference | None:
    """Read the models already generated, looking for whoever owns ``table``."""
    for model_path in sorted(apps_dir.glob("*/model.py")):
        source = model_path.read_text()
        if f'__tablename__ = "{table}"' not in source:
            continue
        class_name = _class_name_in(source)
        if class_name is None:
            continue
        module = f"{apps_dir.name}.{model_path.parent.name}.model"
        return Reference(table, module, class_name, _label_attr_in(source))
    return None


def _class_name_in(source: str) -> str | None:
    for line in source.splitlines():
        if line.startswith("class ") and "(Base)" in line:
            return line[len("class ") :].split("(", 1)[0].strip()
    return None


def _label_attr_in(source: str) -> str:
    """Best guess at a human label column; a developer can change it afterwards."""
    for line in source.splitlines():
        stripped = line.strip()
        if ": Mapped[str]" in stripped and "mapped_column(String" in stripped:
            return stripped.split(":", 1)[0].strip()
    return "id"


# --- model.py -----------------------------------------------------------------


def model_column(field: Field, references: dict[str, Reference]) -> str:
    name = field.column_name
    optional = "" if field.required or field.type == BOOL else " | None"
    nullable = "False" if field.required or field.type == BOOL else "True"
    if field.type == TEXT:
        return (
            f"{name}: Mapped[str{optional}] = mapped_column("
            f"String({TEXT_LENGTH}), nullable={nullable})"
        )
    if field.type == NUMBER:
        return f"{name}: Mapped[Decimal{optional}] = mapped_column({NUMERIC}, nullable={nullable})"
    if field.type == DATE:
        return f"{name}: Mapped[date{optional}] = mapped_column(Date, nullable={nullable})"
    if field.type == BOOL:
        return f"{name}: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)"
    if field.type == ENUM:
        return (
            f"{name}: Mapped[str{optional}] = mapped_column("
            f"String({ENUM_LENGTH}), nullable={nullable})"
        )
    reference = references[field.name]
    return (
        f"{name}: Mapped[int{optional}] = mapped_column("
        f'ForeignKey("{reference.table}.id"), nullable={nullable})'
    )


def model_relationship(spec: Spec, field: Field, references: dict[str, Reference]) -> str:
    reference = references[field.name]
    return (
        f'{field.name}: Mapped["{reference.class_name} | None"] = relationship(\n'
        f'        "{reference.class_name}", '
        f'foreign_keys="{spec.class_name}.{field.column_name}", lazy="joined"\n    )'
    )


def model_check_constraint(spec: Spec, field: Field) -> str:
    return f'CheckConstraint({_check_condition(field)!r}, name="ck_{spec.table_name}_{field.name}")'


def model_imports(spec: Spec, references: dict[str, Reference]) -> str:
    types = {field.type for field in spec.fields}
    sqlalchemy = {"DateTime", "Integer"}
    if TEXT in types or ENUM in types:
        sqlalchemy.add("String")
    if NUMBER in types:
        sqlalchemy.add("Numeric")
    if DATE in types:
        sqlalchemy.add("Date")
    if BOOL in types:
        sqlalchemy.add("Boolean")
    if FK in types:
        sqlalchemy.add("ForeignKey")
    if any(field.type == ENUM for field in spec.fields):
        sqlalchemy.add("CheckConstraint")

    typing_imports = ["from datetime import datetime"]
    if DATE in types:
        typing_imports = ["from datetime import date, datetime"]
    if NUMBER in types:
        typing_imports.append("from decimal import Decimal")

    orm = ["Mapped", "mapped_column"]
    if FK in types:
        orm.append("relationship")

    lines = [
        *typing_imports,
        "",
        f"from sqlalchemy import {', '.join(sorted(sqlalchemy))}",
        f"from sqlalchemy.orm import {', '.join(orm)}",
        "",
        "from foundation.db import Base",
        "from foundation.models import utcnow",
    ]
    for line in sorted(
        {references[field.name].import_line for field in spec.fields if field.is_reference}
    ):
        if line.startswith("from foundation.models import"):
            lines[-1] = _merge_foundation_models_import(lines[-1], line)
        else:
            lines.append(line)
    return "\n".join(lines)


def _merge_foundation_models_import(existing: str, extra: str) -> str:
    names = set(existing.split("import", 1)[1].split(",")) | set(
        extra.split("import", 1)[1].split(",")
    )
    return "from foundation.models import " + ", ".join(sorted(name.strip() for name in names))


# --- routes.py ----------------------------------------------------------------


def display_expression(field: Field, references: dict[str, Reference]) -> str:
    if field.is_reference:
        label = references[field.name].label_attr
        return f"row.{field.name}.{label} if row.{field.name} else None"
    return f"row.{field.name}"


def form_field_literal(field: Field, references: dict[str, Reference]) -> str:
    name = field.column_name
    base: dict[str, Any] = {
        "name": name,
        "label": field.label,
        "value": f"__RAW__values.get({name!r})",
        "required": field.required,
    }
    if field.type in (TEXT,):
        base["type"] = "text"
    elif field.type == NUMBER:
        base["type"] = "number"
        base["step"] = "any"  # the column takes decimals; the browser defaults to integers
    elif field.type == DATE:
        base["type"] = "date"
    elif field.type == BOOL:
        base["type"] = "checkbox"
    elif field.type == ENUM:
        base["type"] = "select"
        base["options"] = f"__RAW__{_enum_options(field)}"
    else:
        reference = references[field.name]
        base["type"] = "select"
        base["options"] = f"__RAW__{_reference_options(field, reference)}"
    return _literal(base)


def _enum_options(field: Field) -> str:
    options = f'[{{"value": option, "label": option}} for option in {field.name.upper()}_OPTIONS]'
    return options if field.required else f'[{{"value": "", "label": "—"}}] + {options}'


def _reference_options(field: Field, reference: Reference) -> str:
    query = (
        f"session.scalars(select({reference.class_name})"
        f".order_by({reference.class_name}.{reference.label_attr}))"
    )
    options = f'forms.as_options({query}, "id", "{reference.label_attr}")'
    return options if field.required else f'[{{"value": "", "label": "—"}}] + {options}'


def parse_line(field: Field) -> str:
    column = field.column_name
    name = f'raw.get("{column}")'
    required = f", required={field.required}" if field.required else ""
    if field.type == TEXT:
        return (
            f'forms.collect(values, errors, "{column}", forms.text, {name}'
            f"{required}, max_length={TEXT_LENGTH})"
        )
    if field.type == NUMBER:
        return f'forms.collect(values, errors, "{column}", forms.number, {name}{required})'
    if field.type == DATE:
        return f'forms.collect(values, errors, "{column}", forms.day, {name}{required})'
    if field.type == BOOL:
        return f'values["{column}"] = forms.boolean({name})'
    if field.type == ENUM:
        return (
            f'forms.collect(values, errors, "{column}", forms.choice, {name}, '
            f"options={field.name.upper()}_OPTIONS{required})"
        )
    return f'forms.collect(values, errors, "{column}", forms.reference, {name}{required})'


def form_param(field: Field) -> str:
    return f'{field.column_name}: Annotated[str, Form()] = "",'


def submitted_dict(spec: Spec) -> str:
    pairs = ", ".join(f'"{field.column_name}": {field.column_name}' for field in spec.fields)
    return "{" + pairs + "}"


def route_imports(spec: Spec, references: dict[str, Reference]) -> list[str]:
    lines = sorted(
        {
            references[field.name].import_line
            for field in spec.fields
            if field.is_reference and not references[field.name].module.startswith("apps.")
        }
    )
    lines += sorted(
        {
            references[field.name].import_line
            for field in spec.fields
            if field.is_reference and references[field.name].module.startswith("apps.")
        }
    )
    return lines


def reference_rows(spec: Spec, references: dict[str, Reference]) -> list[str]:
    """``(column, label, Model)`` triples the routes use to check an fk exists."""
    return [
        f'("{field.column_name}", "{references[field.name].table}", '
        f"{references[field.name].class_name})"
        for field in spec.fields
        if field.is_reference
    ]


def model_import_names(spec: Spec) -> str:
    names = [spec.class_name]
    names += [f"{field.name.upper()}_OPTIONS" for field in spec.fields if field.type == ENUM]
    names += [f"{field.name.upper()}_TONES" for field in spec.fields if field.type == ENUM]
    return ", ".join(names)


def column_kind(field: Field, *, link: bool = False) -> str:
    if link:
        return "link"
    return {
        NUMBER: "number",
        DATE: "date",
        ENUM: "badge",
    }.get(field.type, "text")


def row_value_expression(
    spec: Spec, field: Field, references: dict[str, Reference], *, link: bool = False
) -> str:
    value = f"forms.display({display_expression(field, references)})"
    if link:
        return (
            f'{{"label": {value}, "href": str(request.url_for("{spec.app}_detail", '
            f"{spec.entity}_id=row.id))}}"
        )
    if field.type == ENUM:
        return (
            f'(None if row.{field.name} is None else {{"label": {value}, "tone": '
            f'{field.name.upper()}_TONES.get(row.{field.name}, "neutral")}})'
        )
    return value


# --- migration ----------------------------------------------------------------


def migration_column(field: Field, references: dict[str, Reference]) -> str:
    name = field.column_name
    nullable = "False" if field.required or field.type == BOOL else "True"
    if field.type == TEXT:
        column_type = f"sa.String({TEXT_LENGTH})"
    elif field.type == NUMBER:
        column_type = f"sa.Numeric({NUMBER_PRECISION}, {NUMBER_SCALE})"
    elif field.type == DATE:
        column_type = "sa.Date()"
    elif field.type == BOOL:
        column_type = "sa.Boolean()"
    elif field.type == ENUM:
        column_type = f"sa.String({ENUM_LENGTH})"
    else:
        reference = references[field.name]
        return (
            f'sa.Column("{name}", sa.Integer(), '
            f'sa.ForeignKey("{reference.table}.id"), nullable={nullable})'
        )
    return f'sa.Column("{name}", {column_type}, nullable={nullable})'


def migration_constraint(spec: Spec, field: Field) -> str:
    return (
        f'sa.CheckConstraint({_check_condition(field)!r}, name="ck_{spec.table_name}_{field.name}")'
    )


def _check_condition(field: Field) -> str:
    """``col IN (...)`` with the options as SQL string literals.

    The options come from a file someone wrote, so they are quoted rather than
    pasted: a lone apostrophe would otherwise end the literal and leave the
    rest of the option standing as SQL in a migration that gets executed.
    """
    values = ", ".join(_sql_string(option) for option in field.options)
    condition = f"{field.name} IN ({values})"
    if not field.required:
        condition = f"{field.name} IS NULL OR {condition}"
    return condition


def _sql_string(value: str) -> str:
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


# --- helpers ------------------------------------------------------------------


def _literal(value: Any) -> str:
    """``repr`` with an escape hatch for values that are code, not data."""
    if isinstance(value, str) and value.startswith("__RAW__"):
        return value[len("__RAW__") :]
    if isinstance(value, dict):
        inner = ", ".join(f"{key!r}: {_literal(item)}" for key, item in value.items())
        return "{" + inner + "}"
    if isinstance(value, list):
        return "[" + ", ".join(_literal(item) for item in value) + "]"
    return repr(value)


def references_for(spec: Spec, apps_dir: Path) -> dict[str, Reference]:
    return {
        field.name: resolve_reference(field.target or "", apps_dir)
        for field in spec.fields
        if field.is_reference
    }
