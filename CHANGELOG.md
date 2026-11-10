# Changelog

All notable changes to this project are documented here. The project uses semantic versioning.

## [Unreleased]

### Fixed

- String-typed path, query, header and cookie parameters no longer get a `wrong-type` negative.
  Parameters are sent as text, so the integer `1` arrived as the valid string `1` and a correct
  server failed the case. Negatives that survive serialization (a non-date for `format: date`,
  a non-number for `integer`) are kept. A requirement that selected `wrong-type:<in>.<name>` for
  a plain string parameter has no such case any more and needs another check.
- Unquoted YAML dates such as `example: 2024-01-15` stay strings. They were loaded as
  `datetime.date` and `generate` stopped with `invalid or unreadable input (TypeError)`.
- OpenAPI 3.1 `$ref` beside annotations (`description`, `summary`, `readOnly`, `example`,
  `default`, `x-*`) keeps the referenced object. Such a parameter crashed the parser, a
  response or request body lost its content, and a schema property lost its boundary cases.
  Constraint siblings are still combined through `allOf`; 3.0 still ignores siblings.
- Plans are byte-identical across runs. Review cases for uncovered statuses were emitted in
  set order, which follows `PYTHONHASHSEED`, so the same input gave different plan files and
  digests. They are now sorted.
- Exit code 1 is only ever a failed gate or breaking drift. A malformed `--base-url`
  (`http://localhost:80a0`, port 99999), an empty `components:`, `info:` or `paths:` section,
  an empty mock fixtures file and any unexpected error now exit 2; the last keeps its traceback.
- JUnit XML stays well-formed when an error message carries a control character (a response
  key, for instance); characters XML 1.0 forbids are replaced with U+FFFD.
- Response media types are matched case-insensitively and without parameters, so a contract
  documenting `application/json; charset=utf-8` no longer reports every response as
  undocumented. An exact key still wins.
- Nullable numeric response headers (`nullable: true` in 3.0, `["integer", "null"]` in 3.1)
  are read as numbers instead of failing their own schema.
- `api-vv diff` reports a required response header that becomes optional
  (`response-header-optional`) and an OAuth scope added to an existing security alternative
  (`security-scope-added`) as breaking. Both were silent.
- The Anthropic adapter turns an unexpected reply shape into the redacted
  `LLM provider request failed` error instead of a traceback; so does a malformed LLM base URL.
- Smaller: tab-indented or BOM-prefixed `.json` documents load (they are parsed as JSON, so
  `1e5` is a number); HEAD responses are not checked for a body; untraced case ids are escaped
  in the Markdown report; the HTML "tests run" tally excludes skipped cases; an empty config
  file means defaults.

### Security

- The `demo` extra requires `starlette>=1.3.1,<2`. Earlier versions carry CVE-2026-48710,
  CVE-2026-48817, CVE-2026-48818, CVE-2026-54282 and CVE-2026-54283. Only the bundled demo API
  uses starlette; the five runtime dependencies are unchanged.

### CI

- Every action is pinned to a commit, checkouts do not persist credentials, and the Pages
  workflow grants `pages: write` and `id-token: write` to the deploy job only.
- New `audit` job: `pip-audit` over the runtime and demo dependencies, and zizmor over the
  workflows. The gitleaks download is checked against its published sha256.
- Tests run on Python 3.11 to 3.14. `mypy --strict` also covers tests, scripts and examples.
- The demo job fails when `docs/sample-report.md` or `docs/sample-traceability.csv` differ
  from a fresh run.
- The release workflow triggers on full `vX.Y.Z` tags only, so moving the floating `v1` tag
  no longer starts a release run that fails. Jobs have timeouts. Dependabot also tracks the
  Docker base image.

## [1.3.0] - 2026-10-21

### Added

- Accessible, mobile-friendly HTML traceability matrix. Each requirement row lists its tests
  with endpoint, expected and actual status, latency and verdict, plus a "Why it failed"
  disclosure. Status is shown as icon and word, never colour alone. Rows stack into cards on
  narrow screens, light and dark themes follow the system, and a script-free filter shows only
  requirements that aren't verified.
- GitHub Pages landing page built by CI from a live run against the bundled demo API: workflow
  run and commit, gate verdict, the defects it named, the CLI transcript, a contract-drift
  sample and every evidence file (`scripts/build_site.py`).
- Composite GitHub Action (`action.yml`): `uses: muhib-karim/api-vv-toolkit@v1` validates,
  generates (optional property cases and gated LLM proposals), runs, reports and gates, and with
  `baseline-spec` it also fails on breaking drift. Outputs `gate`, `failed-requirements`,
  `breaking-changes`, `report-dir` and `junit`. `.github/workflows/action.yml` dogfoods it.
- A live LLM gate re-run on 2026-10-21 with `claude-opus-5-5`, `claude-sonnet-5` and
  `gpt-6-sol` (`results/2026-10-21-llm-gate/`). The 2026-10-17 study is kept unchanged.
- The release workflow builds the wheel and sdist, writes `SHA256SUMS.txt`, and publishes the
  GitHub release with `RELEASE_NOTES_<tag>.md` as its body.
- OpenAPI 3.1 alongside 3.0: `type` arrays such as `["string", "null"]`, `examples` maps on
  parameters and media types, and `webhooks`, which are listed on `Spec.webhooks` (and by
  `parse`) but never tested.
- Authentication from environment variable names only. `credentials_env` values must be variable
  names; a scheme with no entry reads `API_VV_AUTH_<SCHEME>`. Each secured operation gets an
  `invalid credentials` case (`auth: invalid`) that sends a fake, scheme-shaped credential and
  expects the documented 401/403.
- `pattern` support: happy paths synthesize a matching string, and a `pattern:<path>` negative
  breaks only the pattern (`api_vv.synth`, a regex sampler with no new dependency).
- Seeded property-based cases: `generate --property-cases N --seed S` adds N random schema-valid
  requests (expect 2xx) and N single-violation requests (expect 4xx) per operation. The same
  seed regenerates a byte-identical plan. Against the demo API they catch the seeded `maxLength`
  defect on their own.
- `api-vv diff OLD NEW`: classifies contract drift as breaking or non-breaking from an existing
  client's point of view, as text, JSON or Markdown. Exits 1 on any breaking change.
- CI: CodeQL (security-and-quality), a gitleaks job, Dependabot, a wheel build and smoke test,
  drift-fixture checks, and runs on `upgrade/**` pushes.

### Fixed

- A 3.1 parameter whose `type` is an array crashed the parser (`unhashable type: 'list'`).
- A 3.0 `nullable: true` on a schema without a single `type` (`allOf`, `$ref`) silently dropped
  `null`.
- HTTP authentication scheme names are matched case-insensitively (`Bearer`, `BASIC`).

## [1.2.0] - 2026-10-18

### Changed

- The LLM generator only queries requirements whose cover selects the `llm-scenario` check. The
  gate could never accept proposals for any other requirement, so those calls were pure cost.
- The prompt lists the allowed operation and status pairs (`allowed_targets`) and shows the
  grouped parameter shape (`{"path": {...}}`), the two most common live rejection reasons.

### Added

- `llm` config options for newer models: `max_tokens`, `token_param`
  (`max_tokens` or `max_completion_tokens`), `temperature` (`null` omits it) and `tool_choice`
  (`tool` or `auto` for Anthropic models that reject a forced tool call).
- A measured study of the LLM gate against four live models, three runs each, before and after
  the prompt change: `results/2026-10-17-llm-gate/`, `examples/llm_experiment/`,
  `scripts/llm_gate_experiment.sh`, `scripts/llm_gate_summary.py` and `make llm-gate`.
- `CITATION.cff`.

## [1.1.0] - 2026-10-03

### Fixed

- Execution timeouts and per-requirement latency budgets must be finite numbers. `NaN` and
  infinity are now rejected when the config or requirements file is loaded; an infinite value
  previously passed validation and effectively switched the limit off.

### Added

- Tests for the finite-number checks.
- CI publishes the seeded-defect demo report (HTML, CSV matrix, JUnit) to GitHub Pages.
- Package metadata: author and project URLs.

## [1.0.0] - 2026-09-29

### Added

- OpenAPI 3.0/3.1 parser with local `$ref` resolution; remote refs, recursive refs and
  unsupported parameter styles are rejected with explicit errors.
- Requirements file model (id, text, priority, verification method, covered operations,
  responses and check selectors, optional latency budget) and cross-validation against the spec.
- Rule-based generators: happy path, schema boundaries (length, range, item counts), enum,
  wrong type, required-field omission, `additionalProperties`, missing authentication and
  documented-status review templates.
- Optional LLM-assisted generator for OpenAI-compatible Chat Completions and Anthropic Messages
  APIs, with a deterministic `mock` provider. Every proposal is validated against the spec and
  its prompt, raw response and accept/reject reason are recorded in the plan.
- Reviewable YAML test plan with stable, fingerprint-derived case ids and deduplication.
- Async executor (bounded concurrency, timeouts, opt-in retries for safe methods) that checks
  status codes, response body and header schemas and per-requirement latency budgets.
- Traceability matrix and reports in Markdown, self-contained HTML, CSV and JUnit XML, with a
  configurable exit-code gate.
- `api-vv` CLI with `parse`, `validate-requirements`, `generate`, `run`, `report` and `trace`.
- Demo API with two seeded defects, `make demo`, CI workflow and Docker image.
