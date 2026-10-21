# api-vv-toolkit v1.3.0

OpenAPI contract plus written requirements in; API tests, a requirement-to-verdict
traceability matrix and a CI gate out. This release adds OpenAPI 3.1, seeded negative and
property-based generation, contract drift checks, a reusable GitHub Action and a rebuilt HTML
report.

## Highlights

- **Use it from any workflow:** `uses: muhib-karim/api-vv-toolkit@v1` validates, generates, runs
  and reports, and gates on requirement verdicts. With `baseline-spec`, it also fails on
  breaking contract drift. Outputs: `gate`, `failed-requirements`, `breaking-changes`,
  `report-dir` and `junit`.
- **`api-vv diff old.yaml new.yaml`:** classifies every change as breaking or non-breaking from
  an existing client's point of view, as text, JSON or Markdown. Exits 1 on any breaking change.
  Renamed operationIds, renamed path placeholders and 3.0 → 3.1 migrations aren't reported as
  changes. Changes it can't analyse fail closed.
- **OpenAPI 3.1 alongside 3.0:** `type` arrays, `examples` maps and `webhooks` (listed, never
  tested). Fixes a crash on 3.1 type-array parameters and lost `null` for 3.0 `nullable` +
  `allOf`.
- **Auth from environment variable names only:** bearer, basic and apiKey in header, query or
  cookie. `credentials_env` must name variables; otherwise `API_VV_AUTH_<SCHEME>` is read. Each
  secured operation gets an `invalid credentials` negative.
- **Seeded negatives:** `pattern` support, and
  `generate --property-cases N --seed S` for random valid (expect 2xx) and single-violation
  (expect 4xx) requests. The same seed regenerates a byte-identical plan.
- **Reports:** an accessible, mobile-friendly HTML matrix (requirement → tests → result with
  "why it failed"), JUnit XML, CSV and Markdown. The Pages site is rebuilt by CI from a live run
  against the bundled demo API.
- **Measured:** a live LLM gate re-run on 2026-10-21 with claude-opus-5-5, claude-sonnet-5 and
  gpt-6-sol (`results/2026-10-21-llm-gate/`). Acceptance was 95%, 76% and 95%.

## Quality gates

These run in CI on every push: ruff, `mypy --strict` on the package, pytest with coverage ≥ 85%
on Python 3.11 and 3.12, CodeQL (security-and-quality), gitleaks, Dependabot, a wheel build and
smoke test, the seeded-defect demo, the Action dogfood workflow and a Docker build.

## Compatibility

- Plans keep `version: "1.0"`. New fields (`seed`, `property_cases`, `Spec.webhooks`,
  `auth: invalid`) are optional, so 1.2 plans still load in 1.3. Plans written by 1.3 aren't
  readable by 1.2.
- Generated plans gain one `invalid credentials` case per secured operation, which changes
  untraced-test counts.

## Install

```bash
pip install https://github.com/muhib-karim/api-vv-toolkit/releases/download/v1.3.0/api_vv_toolkit-1.3.0-py3-none-any.whl
```

Verify the download against `SHA256SUMS.txt` attached to this release. Full details are in
[CHANGELOG.md](https://github.com/muhib-karim/api-vv-toolkit/blob/main/CHANGELOG.md).
