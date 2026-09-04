# Widgets

The neutral example app generated from the generator PR. It demonstrates a
small editable table with labels, quantities, dates, a boolean flag, workflow
status, an optional owner, and an internal note.

## What was asked for

This app is generated from `specs/widgets.yaml`, the deliberately domain-neutral
example spec used to exercise the scaffold. Its fields are:

- label, quantity, due date, active, status (`draft`, `review`, or `done`),
  owner as a foreign key to users, and an internal note
- `draft` and `review` are open workflow states; `done` is closed
- the internal note is sensitive and is visible only to admins

Admins and editors can write according to their normal permissions, viewers
can read only, and writes are recorded through `foundation.audit`.

## Regenerating

`uv run python scaffold/generate.py specs/widgets.yaml` — generated files are
refreshed when they are unchanged, hand-edited files are kept, and the
migration is never rewritten. This file is prose and is not generated.
