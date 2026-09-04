# Vendor contracts

A register of supplier agreements, their commercial value, renewal dates, and
the users responsible for them.

## What was asked for

The request for this generated app was:

- "vendor name, contract ref, annual value, renewal date, owner as fk to users, status with active/expiring/renewed/terminated, notes, annual value sensitive, active and expiring are the open states"

`active` and `expiring` are the open queue states. There are no constrained
transitions, so any status can move to any other status. The annual value is
sensitive and is hidden from non-admin users; admins and editors can write
according to their normal permissions, while viewers can read only. Writes
are recorded through `foundation.audit`.

## Regenerating

`uv run python scaffold/generate.py specs/vendor_contracts.yaml` — generated
files are refreshed when they are unchanged, hand-edited files are kept, and
the migration is never rewritten. This file is prose and is not generated.
