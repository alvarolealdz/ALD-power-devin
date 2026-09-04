# How your team would use this

Someone wants a new internal tool. Here is the whole loop.

## 1. They write a spec

One YAML file, `specs/<name>.yaml`: the entity, its fields, which are
required, which are sensitive, and — if there is a queue — which enum field
drives it, which states are open, which moves are allowed. Copy
`specs/kyc_queue.yaml` and change the nouns. Ten to forty lines, no code.

Then `apps/<name>/spec.md`: the request in plain English, as it was asked. It
sits next to the generated code so the next reader sees *why* before *what*.

## 2. You run three commands

```bash
uv run python scaffold/generate.py specs/<name>.yaml   # app + migration
uv run alembic upgrade head                            # apply it
uv run python scaffold/seed.py specs/<name>.yaml --rows 25   # optional demo data
```

Restart uvicorn. The app is in the nav, on the home page, in the audit feed.
Nothing in `foundation/` was edited. If the spec is wrong the generator says
so and writes nothing.

If the tool needs something the spec cannot say — a computed field, a
custom action, an integration — edit the generated `routes.py` or templates
like any other module. Regenerating later keeps every file you changed and
tells you which ones it kept.

## 3. The reviewer checks

- `git diff --stat`: is everything under `apps/<name>/`, `specs/`,
  `migrations/versions/` and `README.md`? Anything in `foundation/` or
  `scaffold/` is a platform change and needs its own justification.
- `spec.md` says what the spec does. Sensitive fields are marked sensitive.
  Terminal states have `[]` in `transitions:`.
- If files were hand-edited: every write still goes through
  `foundation.audit`; `TITLE`, `DESCRIPTION`, `SINGULAR`, `MODEL`,
  `WORKFLOW_FIELD`, `OPEN_STATES` are still there (the README lists what each
  one feeds).
- `uv run pytest` and `uv run ruff check .` pass. The new app's name is in
  the list in `test_the_spec_alone_reproduces_the_committed_app`
  (`tests/test_generate.py`), so the spec is proven to be the source of truth;
  a hand-edited app is left off that list on purpose, and the PR says so.

## 4. What lands in main

The spec, the migration, the generated app, its `spec.md`, one line added to
the README's command list. One PR, one imperative commit message per app.
From then on the app is code the team owns: it can be edited, tested and
deleted like anything else in the repo, and the platform underneath it does
not know it exists.
