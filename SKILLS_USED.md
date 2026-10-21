# Skills used

Which agent skill drove which change. Only skills actually loaded in the session are listed.

## v1.3.0

### Slice 1: OpenAPI 3.1 and auth, seeded negatives, contract drift, CI gates

| Skill | What it drove |
| --- | --- |
| `writing-plans` (Superpowers) | The test-first task plan in `TASKS.md` (T1 to T4, acceptance per task, additive plan-format decision). |
| `test-driven-development` (Superpowers) | Every feature started as a failing test: `tests/test_openapi31_auth.py`, `tests/test_property.py`, `tests/test_diff.py`. The red runs found a real crash: 3.1 type-array parameters (`unhashable type: 'list'`). |
| `ci-cd-and-automation` (agent-skills) | `ci.yml` gates (lint, strict types, coverage ≥ 85%, drift fixtures, wheel build and smoke, gitleaks), `codeql.yml` and its config, `dependabot.yml`. |
| `requesting-code-review` (Superpowers) | One independent reviewer pass over the slice 1 range before pushing; findings and fixes are recorded in `TASKS.md`. |
| `verification-before-completion` (Superpowers) | Slice sign-off only after `ruff`, `mypy --strict`, `pytest` with coverage, `make demo` and a green CI run on the pushed head. |
