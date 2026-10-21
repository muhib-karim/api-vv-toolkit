# v1.3.0 upgrade: tasks

Branch `upgrade/v1.3.0`, cut from `main` at `1085a2f`. The work is split into two slices. Each task
below is test-first: a failing test, then the code, then `ruff`, `mypy --strict src` and `pytest`.

## Slice 1: generator, drift and CI gates

### T1. OpenAPI 3.1 alongside 3.0, plus auth from env var names (DoD 1)

- [ ] 3.1 `type: [x, "null"]` unions parse, sample and mutate. A 3.0 `nullable` schema with no
      single `type` (for example `allOf` or `$ref` plus `nullable`) becomes `anyOf [schema, null]`
      instead of silently losing `null`.
- [ ] `webhooks` are listed on `Spec.webhooks` but never turned into cases. A 3.1 document with
      webhooks and no `paths` fails with a clear message. `parse` prints how many were ignored.
- [ ] Parameter and media-type `examples` maps (`{name: {value: ...}}`) feed the happy path when
      there is no single `example`.
- [ ] The HTTP `scheme` is matched case-insensitively (`Bearer`, `BASIC`).
- [ ] `credentials_env` values must be environment variable names (`^[A-Za-z_][A-Za-z0-9_]*$`);
      unknown scheme names are rejected when a plan runs. When the config doesn't name a variable,
      `API_VV_AUTH_<SCHEME>` is read, so CI can supply credentials with no config file.
- [ ] Generated auth negatives: besides `missing authentication` (`auth: omit`), each operation
      that requires auth gets `invalid credentials` (`auth: invalid`). It sends a fixed, obviously
      fake value in the scheme's slot and expects the documented 401/403.

### T2. Negative and property-based generation, seeded (DoD 2)

- [ ] `pattern`: the happy path synthesizes a matching string from the regex (a small sampler over
      `re._parser`). A `pattern:<path>` case sends a non-matching string and expects 4xx.
- [ ] `generate --property-cases N --seed S`: N schema-valid random requests per operation (expect
      2xx, check `property:valid`) and N random invalid requests (one random violation each, expect
      4xx, check `property:invalid`). Path parameters keep their example values. Each operation's
      RNG is seeded from `"{seed}:{operation id}"`, so adding an operation doesn't reshuffle the
      others. `Plan.seed` and `Plan.property_cases` record what was used (additive optional fields).
- [ ] Same seed gives a byte-identical plan; a different seed gives different values; every
      `property:valid` instance validates and every `property:invalid` one does not.

### T3. Contract drift: `api-vv diff OLD NEW` (DoD 3)

- [ ] New `api_vv/diff.py` compares two parsed specs. Operations are keyed by method plus the
      templated path, with placeholder names ignored (`/w/{id}` == `/w/{widgetId}`).
- [ ] Breaking: operation removed, required parameter added or made required, request body added
      or made required, request schema tightened (new required property, enum value removed, type
      narrowed, min/max/length/pattern tightened, `additionalProperties: false`), response
      narrowed (2xx/default status removed, media type removed, property removed or no longer
      required, type changed or widened, enum value added), security added to an open operation,
      composition change that can't be compared (fails closed).
- [ ] Non-breaking: the inverse relaxations and additions.
- [ ] `--format text|json|md`, `--out`. Exit 1 if any change is breaking, 0 if not, 2 for invalid
      input. Fixture specs live in `tests/fixtures/diff/`.

### T4. CI quality gates (DoD 6)

- [ ] `ci.yml`: also runs on `push` to `upgrade/**`; ruff check and format, `mypy --strict src`,
      pytest with `--cov-fail-under=85` on Python 3.11 and 3.12; coverage XML artifact; gitleaks
      job (pinned binary, history plus tree, `--redact`); the existing demo and docker jobs stay.
- [ ] `codeql.yml` (security-and-quality) with `.github/codeql/codeql-config.yml` ignoring
      recorded `results/**`, `runs/**` and the deliberately broken diff fixtures. Any alert in
      `src/` is fixed, never ignored.
- [ ] `.github/dependabot.yml` for pip and github-actions, weekly, grouped.
- [ ] Regenerate `docs/sample-report.md` and `docs/sample-traceability.csv` (generator output
      changed); `make demo` still fails on exactly REQ-003 and REQ-008.
- [ ] Push with `push.sh`, then wait for CI and CodeQL to be green on the branch head:
      `SLICE1_DONE <sha>`.

## Slice 2 (not started): DoD 4, 5, 7, 8, 9

HTML/JUnit report polish and the Pages live run, composite `action.yml` plus dogfood workflow, LLM
gate re-run, README/CHANGELOG/version bump, HANDOFF.md.

## Blockers

None yet.
