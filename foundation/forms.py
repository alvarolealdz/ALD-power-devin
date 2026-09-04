"""Turning submitted strings into column values.

HTML forms only ever send strings, and an untouched optional input arrives as
``""``. These helpers do the narrow job of converting one submitted value and
saying clearly when it cannot be converted; deciding what to do about that is
the route's business.
"""

from collections.abc import Callable, Iterable, Mapping, MutableMapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

TRUTHY = frozenset({"1", "true", "on", "yes"})

# What a numeric column can hold. Generated models use the same two numbers.
NUMBER_PRECISION = 18
NUMBER_SCALE = 4


class FieldError(ValueError):
    """Raised when a submitted value cannot be used."""


def text(raw: str | None, *, required: bool = False, max_length: int | None = None) -> str | None:
    value = (raw or "").strip()
    if not value:
        return _missing(required)
    if max_length is not None and len(value) > max_length:
        raise FieldError(f"must be at most {max_length} characters")
    return value


def number(raw: str | None, *, required: bool = False) -> Decimal | None:
    """A finite decimal that the column can hold.

    ``Decimal`` happily parses ``NaN`` and ``Infinity``, and SQLite stores
    anything wider than the column as a float, losing digits without a word.
    Both are refused here rather than written.
    """
    value = (raw or "").strip()
    if not value:
        return _missing(required)
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise FieldError("must be a number") from error
    if not parsed.is_finite():
        raise FieldError("must be a finite number")
    digits, scale = NUMBER_PRECISION, NUMBER_SCALE
    exponent = parsed.as_tuple().exponent
    if not isinstance(exponent, int) or -exponent > scale:
        raise FieldError(f"must have at most {scale} decimal places")
    if len(parsed.as_tuple().digits) + exponent > digits - scale:
        raise FieldError(f"must have at most {digits - scale} digits before the decimal point")
    return parsed


def day(raw: str | None, *, required: bool = False) -> date | None:
    value = (raw or "").strip()
    if not value:
        return _missing(required)
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise FieldError("must be a date (YYYY-MM-DD)") from error


def boolean(raw: str | None) -> bool:
    """An unchecked checkbox is not submitted at all, which is a plain false."""
    return (raw or "").strip().lower() in TRUTHY


def choice(raw: str | None, options: Iterable[str], *, required: bool = False) -> str | None:
    value = (raw or "").strip()
    if not value:
        return _missing(required)
    allowed = tuple(options)
    if value not in allowed:
        raise FieldError(f"must be one of {', '.join(allowed)}")
    return value


def reference(raw: str | None, *, required: bool = False) -> int | None:
    value = (raw or "").strip()
    if not value:
        return _missing(required)
    if not value.isdigit():
        raise FieldError("must be a reference id")
    return int(value)


def collect(
    values: MutableMapping[str, Any],
    errors: MutableMapping[str, str],
    name: str,
    parse: Callable[..., Any],
    raw: str | None,
    **options: Any,
) -> None:
    """Run one parser, routing the result into ``values`` or ``errors``."""
    try:
        values[name] = parse(raw, **options)
    except FieldError as error:
        errors[name] = str(error)


def as_options(rows: Iterable[Any], value_attr: str, label_attr: str) -> list[dict[str, Any]]:
    """Select options for a foreign key, built from whatever rows you hand it."""
    return [
        {"value": getattr(row, value_attr), "label": str(getattr(row, label_attr))} for row in rows
    ]


def display(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, datetime):
        return value.strftime("%-d %b %Y, %H:%M")
    if isinstance(value, date):
        return value.strftime("%-d %b %Y")
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    return str(value)


def submitted(form: Mapping[str, Any], name: str) -> str | None:
    raw = form.get(name)
    return raw if isinstance(raw, str) else None


def _missing(required: bool) -> None:
    if required:
        raise FieldError("is required")
