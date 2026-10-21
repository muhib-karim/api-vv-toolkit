# v1.3.0 upgrade: tasks

Branch `upgrade/v1.3.0`, cut from `main` at `1085a2f`. The work is split into two slices. Each task
below is test-first: a failing test, then the code, then `ruff`, `mypy --strict src` and `pytest`.

## Slice 1: generator, drift and CI gates

### T1. OpenAPI 3.1 alongside 3.0, plus auth from env var names (DoD 1)

- [x] 3.1 `type: [x, "null"]` unions parse, sample and mutate. A 3.0 `nullable` schema with no
      single `type` (for example `allOf` or `$ref` plus `nullable`) becomes `anyOf [schema, null]`
      instead of silently losing `null`.
- [x] `webhooks` are listed on `Spec.webhooks` but never turned into cases. A 3.1 document with
      webhooks and no `paths` fails with a clear message. `parse` prints how many were ignored.
- [x] Parameter and media-type `examples` maps (`{name: {value: ...}}`) feed the happy path when
      there is no single `example`.
- [x] The HTTP `scheme` is matched case-insensitively (`Bearer`, `BASIC`).
- [x] `credentials_env` values must be environment variable names (`^[A-Za-z_][A-Za-z0-9_]*$`);
      unknown scheme names are rejected when a plan runs. When the config doesn't name a variable,
      `API_VV_AUTH_<SCHEME>` is read, so CI can supply credentials with no config file.
- [x] Generated auth negatives: besides `missing authentication` (`auth: omit`), each operation
      that requires auth gets `invalid credentials` (`auth: invalid`). It sends a fixed, obviously
      fake value in the scheme's slot and expects the documented 401/403.

### T2. Negative and property-based generation, seeded (DoD 2)

- [x] `pattern`: the happy path synthesizes a matching string from the regex (a small sampler over
      `re._parser`). A `pattern:<path>` case sends a non-matching string and expects 4xx.
- [x] `generate --property-cases N --seed S`: N schema-valid random requests per operation (expect
      2xx, check `property:valid`) and N random invalid requests (one random violation each, expect
      4xx, check `property:invalid`). Path parameters keep their example values. Each operation's
      RNG is seeded from `"{seed}:{operation id}"`, so adding an operation doesn't reshuffle the
      others. `Plan.seed` and `Plan.property_cases` record what was used (additive optional fields).
- [x] Same seed gives a byte-identical plan; a different seed gives different values; every
      `property:valid` instance validates and every `property:invalid` one does not.

### T3. Contract drift: `api-vv diff OLD NEW` (DoD 3)

- [x] New `api_vv/diff.py` compares two parsed specs. Operations are keyed by method plus the
      templated path, with placeholder names ignored (`/w/{id}` == `/w/{widgetId}`).
- [x] Breaking: operation removed, required parameter added or made required, request body added
      or made required, request schema tightened (new required property, enum value removed, type
      narrowed, min/max/length/pattern tightened, `additionalProperties: false`), response
      narrowed (2xx/default status removed, media type removed, property removed or no longer
      required, type changed or widened, enum value added), security added to an open operation,
      composition change that can't be compared (fails closed).
- [x] Non-breaking: the inverse relaxations and additions.
- [x] `--format text|json|md`, `--out`. Exit 1 if any change is breaking, 0 if not, 2 for invalid
      input. Fixture specs live in `tests/fixtures/diff/`.

### T4. CI quality gates (DoD 6)

- [x] `ci.yml`: also runs on `push` to `upgrade/**`; ruff check and format, `mypy --strict src`,
      pytest with `--cov-fail-under=85` on Python 3.11 and 3.12; coverage XML artifact; gitleaks
      job (pinned binary, history plus tree, `--redact`); the existing demo and docker jobs stay.
- [x] `codeql.yml` (security-and-quality) with `.github/codeql/codeql-config.yml` ignoring
      recorded `results/**`, `runs/**` and the deliberately broken diff fixtures. Any alert in
      `src/` is fixed, never ignored.
- [x] `.github/dependabot.yml` for pip and github-actions, weekly, grouped.
- [x] Regenerate `docs/sample-report.md` and `docs/sample-traceability.csv` (generator output
      changed); `make demo` still fails on exactly REQ-003 and REQ-008.
- [x] Pushed with `push.sh`. CI run 39660210674 (check 3.11 and 3.12, gitleaks, build, demo,
      docker) and CodeQL run 39660210679 were green on `37eb9a7`, with 0 open code-scanning
      alerts. The one earlier alert (`py/implicit-string-concatenation-in-list`, inherited from
      `scripts/llm_gate_summary.py`) was fixed on this branch with byte-identical output.
      The final head is recorded in `docs/PROJECT_BRAIN.md`.

### Notes for slice 2

- GitHub now warns that Node 20 actions and CodeQL Action v3 are deprecated (v3 retires
  December 2026). Dependabot is configured to open the bumps; take them, or bump to
  `codeql-action@v4` while doing the Action work.

## Slice 2: reports, Pages, Action, LLM re-run, docs (DoD 4, 5, 7, 8, 9)

- [x] DoD 4. The HTML matrix shows requirement → tests → result with endpoint, expected and
      actual status, latency and "why it failed". It is accessible (landmarks, skip link,
      captioned table, scoped headers, icon plus word status, AA contrast in both themes) and
      mobile-friendly (cards below 720px, script-free "not verified" filter). JUnit XML is
      unchanged and tested. `scripts/build_site.py` builds the Pages landing from a live demo
      run in CI (pages.yml from main; a preview artifact in the CI demo job). Nothing is
      committed by hand.
- [x] DoD 5. Composite `action.yml` (`uses: muhib-karim/api-vv-toolkit@v1`) and the dogfood
      workflow `.github/workflows/action.yml`: the gate must name exactly REQ-003 and REQ-008,
      and drift must be 0 for the compatible fixture and > 0 for the breaking one.
- [x] DoD 7. The endpoint answered, so the study was re-run live on 2026-10-21 for
      claude-opus-5-5, claude-sonnet-5 and gpt-6-sol, 3 runs each
      (`results/2026-10-21-llm-gate/`). The 2026-10-17 study is kept as it was. No endpoint or
      key appears in any file; this was checked against the environment values and with
      gitleaks.
- [x] DoD 8. README refresh (badges including CodeQL and coverage, headless screenshot,
      quickstart, Action usage, mermaid, roadmap, links), CHANGELOG [1.3.0] - 2026-10-21, the
      1.3.0 bump (pyproject, `__version__`, CITATION), SKILLS_USED, this file, HANDOFF.md,
      RELEASE_NOTES_v1.3.0.md, and `release.yml` (tag v*: tests, version check, wheel, sdist,
      SHA256SUMS, release body from `RELEASE_NOTES_<tag>.md`).
- [ ] DoD 9. Push with push.sh and wait for CI, CodeQL and the dogfood to be green on the head;
      the PU_DONE line follows that. Run ids are in HANDOFF.md.

Process note: `tests/test_site.py` was written after `scripts/build_site.py` (a CI helper), not
before it.

## Review (slice 1)

One independent reviewer pass over `1085a2f..HEAD` (Superpowers `requesting-code-review`): no
Critical findings. The 3 Important and 5 Minor findings were all fixed in `fix: address slice 1
review findings`, each with a new test:

- I1: a changed pattern, format, const or multipleOf passed as safe. Now breaking.
- I2: `required` changes on non-local properties were missed. Now classified.
- I3: security scheme definitions weren't compared. Now compared.
- M1: synth had no size caps and broke on float sizes.
- M2: `auth: invalid` failed on unsupported schemes.
- M3: request media type changes were ignored.
- M4: default env var names could collide.
- M5: the gitleaks binary sat inside the checkout it scanned.

Set aside on purpose: an `anyOf`/`oneOf` branch added counts as unanalysed (fails closed by
design). `wrong-type` sends `1` to a string query parameter (existed before this branch).

## Blockers

None.
