# Changelog

All notable changes to this project are documented here. The project uses semantic versioning.

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
