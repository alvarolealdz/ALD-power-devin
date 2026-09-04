# Feature flags

A plain CRUD panel for runtime switches by environment. Each row identifies a
flag, describes its purpose, records whether it is enabled, and names the
user who last modified it.

## What was asked for

The request for this generated app was:

- "flag key, description, enabled bool, environment as dev/staging/prod, last modified by as fk to users, nothing sensitive and no workflow on this one since it's a plain CRUD panel"

There are no sensitive fields and no workflow decisions. The
`last_modified_by` field is a plain foreign key that the editor picks; it is
not set automatically. Admins and editors can write according to their
normal permissions, while viewers can read only. Writes are recorded through
`foundation.audit`.

## Regenerating

`uv run python scaffold/generate.py specs/feature_flags.yaml` — generated
files are refreshed when they are unchanged, hand-edited files are kept, and
the migration is never rewritten. This file is prose and is not generated.
