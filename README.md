<p align="center"><img src="docs/banner.svg" alt="api-vv-toolkit: from OpenAPI spec and written requirements to tested, traceable verdicts" width="100%"></p>

<p align="center"><b>Generate API tests from an OpenAPI contract and written requirements, run them, and get a requirements traceability matrix with a CI gate.</b></p>

<p align="center">
  <a href="https://github.com/muhib-karim/api-vv-toolkit/actions/workflows/ci.yml"><img src="https://github.com/muhib-karim/api-vv-toolkit/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/muhib-karim/api-vv-toolkit" alt="License: MIT"></a>
  <img src="https://img.shields.io/github/languages/top/muhib-karim/api-vv-toolkit" alt="Top language">
  <img src="https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg" alt="Python 3.11 | 3.12">
  <a href="https://github.com/muhib-karim/api-vv-toolkit/releases"><img src="https://img.shields.io/github/v/release/muhib-karim/api-vv-toolkit" alt="Release"></a>
  <a href="https://muhib-karim.github.io/api-vv-toolkit/"><img src="https://img.shields.io/badge/demo-seeded%20defects-brightgreen.svg" alt="Demo report"></a>
  <a href="#measured-results-the-llm-gate-against-live-models"><img src="https://img.shields.io/badge/results-measured%20live-blue.svg" alt="Measured results"></a>
  <a href="CITATION.cff"><img src="https://img.shields.io/badge/cite-CITATION.cff-informational.svg" alt="Cite"></a>
</p>

# api-vv-toolkit

api-vv-toolkit reads an OpenAPI contract and a list of written requirements. It generates API
tests from them, runs the tests against a live service and reports which requirements are
verified, which failed and which have no test at all. Every test records the requirement it
checks, so a failure points back to what the service was supposed to do.

**Seeded-defect demo (not an external production audit):** [the HTML traceability report](https://muhib-karim.github.io/api-vv-toolkit/) from the
seeded-defect demo below, rebuilt by CI from `main` on every push
([CSV matrix](https://muhib-karim.github.io/api-vv-toolkit/traceability.csv),
[JUnit XML](https://muhib-karim.github.io/api-vv-toolkit/junit.xml)).

An optional LLM step can suggest extra test scenarios. Its suggestions are checked against the
spec before they enter the plan, and the prompt, raw reply and accept/reject reason are stored
with the plan so a reviewer can see why each one was kept or dropped.

## Key features

- **OpenAPI 3.0/3.1 parsing** into typed pydantic models, with local `$ref` resolution and
  explicit errors for unsupported input (remote/recursive refs, non-JSON bodies).
- **Requirements file validated against the spec**: each requirement selects the operations,
  responses and check types it covers.
- **Six rule-based generators** (happy path, schema boundaries, parameter boundaries, required
  omission, auth required, status coverage) producing deterministic, fingerprinted test ids.
- **Reviewable YAML test plan** between generation and execution, re-validated before it runs.
- **Async executor** (httpx) checking status codes, JSON Schema of response bodies, documented
  headers and optional latency budgets.
- **Traceability reports** in Markdown, self-contained HTML, CSV and JUnit XML, plus a
  configurable exit-code gate for CI.
- **Optional LLM-assisted scenarios** (OpenAI-compatible or Anthropic, or an offline `mock`
  replay) behind a spec validation gate, with prompt, raw reply and accept/reject reason stored
  in the plan.
- **Six-command CLI** (`api-vv parse | validate-requirements | generate | run | report | trace`),
  a Dockerfile and a release workflow that publishes a wheel, sdist and checksums.

## Inspect the demo

The demo runs against the bundled local widget API with two deliberately seeded defects. It demonstrates traceability and failure reporting, not a production service certification. No paid model call is needed for this demo.

![Captured demo report](docs/assets/demo-report.png)

*Screenshot captured from the public demo on 11 October 2026. It is an example report, not a current health monitor.*

## The problem

API test suites and requirements are usually written by different people at different times,
and they drift apart. Tests get added for bugs and removed when they are flaky. Requirements get
reworded. After a few releases nobody can say which requirement a test protects, or whether a
given requirement is tested at all. A green CI run then shows that the tests passed. It does not
show that the requirements were met.

Regulated and safety-conscious teams (medical, automotive, finance, public sector) are asked for
this evidence directly. An auditor wants a requirements traceability matrix: for each
requirement, the tests that verify it and the latest result of each. Keeping that matrix by hand
in a spreadsheet is slow and goes out of date quickly.

This tool derives the matrix from the same data the tests run from, so it cannot drift from them:

- trace links come from structural selectors in the requirements file (operation, response code,
  check type), not from test names;
- a requirement counts as verified only when a passing test covers every response and check it
  names. Having a generated test is not enough;
- the run fails (non-zero exit code) when a must-priority requirement is failed, partially
  covered or not covered. Which priorities and statuses fail the run is configurable.

## Architecture: how it works

```mermaid
flowchart LR
    S[OpenAPI 3.0/3.1 spec] --> P[Parse and resolve local refs]
    R[Requirements YAML] --> V[Validate requirements against spec]
    P --> G1[Rule-based generators]
    V --> G1
    P --> G2[LLM-assisted generator]
    V --> G2
    G2 --> GATE{Validation gate:<br/>schema, known operation,<br/>documented response}
    GATE -- rejected --> AUDIT[(Audit log in plan:<br/>prompt, raw response, reason)]
    GATE -- accepted --> PLAN
    G1 --> PLAN[YAML test plan]
    PLAN --> HR[Human review and edit]
    HR --> X[Async executor]
    X --> VER[Verdicts: status, body schema,<br/>headers, latency budget]
    VER --> M[Traceability matrix]
    M --> OUT[Markdown, HTML, CSV, JUnit XML<br/>and exit-code gate]
```

1. **Parse.** The OpenAPI document is loaded into typed pydantic models (operations, parameters,
   request bodies, response schemas and headers, security schemes). Local `$ref`s are resolved.
   Remote refs, recursive refs and unsupported parameter styles are rejected with a clear error
   instead of being skipped.
2. **Generate.** Rule-based generators produce deterministic cases:

   | Generator | What it produces |
   | --- | --- |
   | `happy-path` | a valid request built from schema examples, defaults and constraints |
   | `schema-boundary` | min/max length, minimum/maximum, item counts (below, at, above each bound), out-of-enum values, wrong types, omitted required fields, unexpected properties when `additionalProperties: false` |
   | `parameter-boundary` | the same rules applied to path, query, header and cookie parameters |
   | `required-omission` | a missing required body or parameter |
   | `auth-required` | the request with credentials removed, expecting the documented 401/403 |
   | `status-coverage` | a disabled review case for each documented response no generator reached |

   Cases are deduplicated by a fingerprint of the request, and the fingerprint becomes the case
   id (`TC-fcf6e146d3f7`), so ids stay the same across regenerations.
3. **Review.** The plan is plain YAML. A reviewer can disable a case, change an expected status
   or fill in a review case before running it. Edits are re-validated when the plan is run.
4. **Execute.** httpx sends the requests asynchronously with a concurrency limit and timeouts.
   Retries are off by default and apply only to transport errors on GET/HEAD/OPTIONS. Each
   response is checked against the expected status, the JSON Schema of the documented body
   (using the jsonschema library), documented headers and any latency budget on the requirement.
5. **Report.** The traceability matrix lists requirement, tests and latest verdicts, plus tests that
   trace to no requirement and operations that no requirement covers. It is written as
   Markdown, self-contained HTML (inline CSS, no scripts or external assets), CSV for
   spreadsheet workflows and JUnit XML for CI systems.

## Quick start

Requires Python 3.11 or newer.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev,demo]'
make demo
```

With your own API:

```bash
api-vv validate-requirements --spec openapi.yaml --requirements requirements.yaml
api-vv generate --spec openapi.yaml --requirements requirements.yaml --out plan.yaml
# review and edit plan.yaml
api-vv run --plan plan.yaml --base-url http://localhost:8000 --config config.yaml --out results.yaml
api-vv report --plan plan.yaml --results results.yaml --out-dir reports/
api-vv trace --plan plan.yaml --results results.yaml --format csv --out matrix.csv
```

Exit codes: `0` gate passed, `1` gate failed, `2` invalid input.

A requirement names the operations and responses it covers. The optional `checks` list narrows
the match to specific generated checks:

```yaml
requirements:
  - id: REQ-003
    text: A widget name longer than eight characters is rejected.
    priority: must            # must | should | could
    verification_method: test # test | demonstration | inspection | analysis
    covers:
      - operation_id: createWidget
        responses: ['422']
        checks: ['boundary:name:maxLength:above']
  - id: REQ-012
    text: The health endpoint responds within one second in this local demo.
    priority: should
    verification_method: test
    latency_ms: 1000
    covers: [{operation_id: health, responses: ['200'], checks: [happy-path]}]
```

Requirements verified by `inspection` or `analysis` stay in the matrix but never get
generated tests. They show as not covered, which is accurate.

The config file sets concurrency, timeouts, retries, the gate, the LLM provider and the names of
environment variables that hold credentials (`credentials_env: {DemoKey: API_VV_DEMO_KEY}`).
Secrets themselves never appear in config, plans, results or reports.


### Install a release build

Every tagged release carries a wheel, an sdist and `SHA256SUMS.txt`, built and tested by the [release workflow](.github/workflows/release.yml):

```sh
pip install https://github.com/muhib-karim/api-vv-toolkit/releases/download/v1.2.0/api_vv_toolkit-1.2.0-py3-none-any.whl
```

Check the file against `SHA256SUMS.txt` on the [Releases page](https://github.com/muhib-karim/api-vv-toolkit/releases/latest).

## Demo: two seeded defects

`examples/demo_api/` is a small Starlette service with an OpenAPI 3.1 contract, twelve
requirements and two deliberate bugs, described in
[its README](examples/demo_api/README.md):

1. the name length check allows 9 characters where the contract says 8;
2. `DELETE /widgets/{widget_id}` returns 200 where the contract says 204.

`make demo` starts the service on a loopback port, runs the CLI end to end and writes everything
to `runs/demo/`. Output from a run:

```text
$ make demo
.venv/bin/python scripts/demo.py
Validated 12 requirements
Generated 31 cases (31 enabled)
LLM proposals: 1 accepted, 1 rejected
Executed: 29 passed, 2 failed, 0 skipped
Gate: FAIL (REQ-003, REQ-008)
Wrote Markdown, HTML, CSV and JUnit reports to runs/demo
Gate: FAIL (REQ-003, REQ-008)
Expected defects confirmed: REQ-003, REQ-008
```

The gate prints twice because both `run` and `report` apply it. The last line comes from the
demo script, which exits non-zero unless exactly those two requirements fail. The CI demo job
relies on this.

Excerpt from the generated matrix ([full report](docs/sample-report.md),
[CSV](docs/sample-traceability.csv)):

| Requirement | Priority | Status | Test cases → latest verdict |
| --- | --- | --- | --- |
| REQ-002: A valid widget can be created. | must | verified | TC-49e39d3e97cf → passed |
| REQ-003: A widget name longer than eight characters is rejected. | must | failed | TC-fcf6e146d3f7 → failed |
| REQ-007: The secure endpoint rejects unauthenticated requests. | must | verified | TC-bc42e8332169 → passed |
| REQ-008: Deleting a widget returns 204 with no body. | must | failed | TC-13777f5b2f2f → failed |
| REQ-010: Reading absent widget 999 returns a documented not-found response. | must | verified | TC-bf3867a1d253 → passed |

```text
## Execution findings

- TC-fcf6e146d3f7 (failed): status: expected 422, got 201
- TC-13777f5b2f2f (failed): status: expected 204, got 200; response status is undocumented
```

The failing REQ-003 case, as it appears in the plan:

```yaml
- id: TC-fcf6e146d3f7
  name: 'createWidget: boundary:name:maxLength:above'
  operation_id: createWidget
  body: {name: xxxxxxxxx, role: reader, age: 30}
  has_body: true
  expected_status: '422'
  negative: true
  generators: [schema-boundary]
  checks: [boundary:name:maxLength:above]
  requirement_ids: [REQ-003]
```

The matrix also lists 20 untraced tests: boundary and type checks that ran but that no
requirement claims. They are shown so a reviewer can decide whether a requirement is missing
or the tests are unnecessary.

## Keeping the LLM path honest

The LLM generator is optional and off unless `--llm` is passed. It is treated as a source of
suggestions that must be checked, not as a trusted author.

- **Schema-constrained output.** The model must return JSON matching a fixed schema
  (`proposals[]` with operation, parameters, body, expected status and a `negative` flag). OpenAI-compatible
  endpoints get it as `response_format: json_schema`, Anthropic as a forced tool call.
  Temperature defaults to 0. Models that reject a fixed temperature, `max_tokens` or a forced
  tool call are handled by config (`temperature: null`, `token_param: max_completion_tokens`,
  `tool_choice: auto`) rather than by code changes.
- **Spec validation gate.** Each proposal must name a known operation, use only declared
  parameters with schema-valid values, expect a documented response, stay within the requirement
  it was asked about, and mark any schema-invalid body as `negative: true`. Proposals that
  contradict an existing case's expectation for the same request are rejected.
- **Recorded provenance.** For every requirement the plan stores the prompt, the raw response
  and one review entry per proposal. From the demo plan:

  ```yaml
  requirement_id: REQ-010
  provider: mock
  reviews:
  - index: 0
    accepted: true
    reason: validated
    case_id: TC-bf3867a1d253
  - index: 1
    accepted: false
    reason: unknown operation; proposal is outside the requested requirement coverage
    case_id: null
  ```

- **Opt-in per requirement.** The model is only asked about requirements whose cover selects the
  `llm-scenario` check, and the prompt lists the exact operation and status pairs it may target
  (`allowed_targets`). Asking about any other requirement costs a call whose proposals the gate
  must reject (see the measured results below).
- **Never auto-trusted.** Accepted proposals land in the same reviewable plan as rule-based cases
  and are tagged `generators: [llm]`. A requirement is only traced to an LLM case if its selectors
  explicitly allow `llm-scenario` checks, so a model cannot claim coverage of a requirement it
  was not scoped to.
- **Secrets.** Base URL and API key come from environment variables named in the config. They
  are not logged, and provider errors are reduced to the exception type so response bodies and
  headers are not echoed.
- **Offline by default.** The `mock` provider replays hand-written fixtures
  (`examples/demo_api/mock_responses.yaml`). Tests, CI and the demo make no model calls, and the
  test suite blocks sockets entirely.

## Measured results: the LLM gate against live models

**Question.** When real models propose test cases, how many survive the spec validation gate,
and do the accepted cases find real defects or just add noise?

**Setup (2026-10-17, live calls, not mock).** The seeded-defect demo API with the 12 demo
requirements, eight of which (REQ-003 to REQ-010) opt in to model proposals in
[`examples/llm_experiment/requirements.yaml`](examples/llm_experiment/requirements.yaml). Each
model ran three times per prompt version. Every accepted case was then executed against the demo
service. *v1.1.0 prompt* is the 1.1.0 prompt and requirement selection (it asks the model about
all 12 requirements); *v1.2.0 prompt* is this release. Both use the same request options, which
newer models need (see above).

| Model | Prompt | Runs | Model calls / run | Proposals | Accepted | Acceptance | LLM cases executed | Failed on seeded defects | Wrong expectations | Seeded defects hit |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| claude-haiku-4-5 | v1.1.0 | 3 | 12 | 348 | 84 | 24% | 48 | 3 | 0 | defect-1 |
| claude-haiku-4-5 | v1.2.0 | 3 | 8 | 153 | 135 | 88% | 102 | 12 | 21 | defect-2 |
| claude-opus-5-5 | v1.1.0 | 3 | 12 | 206 | 88 | 43% | 68 | 16 | 3 | defect-1, defect-2 |
| claude-opus-5-5 | v1.2.0 | 3 | 8 | 116 | 108 | 93% | 86 | 20 | 5 | defect-1, defect-2 |
| claude-sonnet-5 | v1.1.0 | 3 | 12 | 172 | 33 | 19% | 18 | 4 | 2 | defect-1, defect-2 |
| claude-sonnet-5 | v1.2.0 | 3 | 8 | 86 | 61 | 71% | 50 | 7 | 10 | defect-1, defect-2 |
| gpt-6-sol | v1.1.0 | 3 | 12 | 114 | 45 | 39% | 29 | 3 | 0 | defect-1 |
| gpt-6-sol | v1.2.0 | 3 | 8 | 49 | 46 | 94% | 31 | 3 | 0 | defect-1 |

**Findings.**

- **Acceptance went up for every model** (Haiku 4.5 24% to 88%, Opus 5.5 43% to 93%, Sonnet 5 19%
  to 71%, GPT-6 Sol 39% to 94%) while each run made 8 model calls instead of 12, a third fewer.
- **Accepted is not the same as right.** The gate checks a proposal against the contract, not the
  model's reading of it. With more of their proposals getting through, Haiku's wrong expectations
  rose from 0 to 21 over three runs and Sonnet's from 2 to 10 (for example, Haiku 4.5 expected 422 for the
  valid 7-character name `widgetx`, maximum 8; the API returned 201, case TC-6e871078aede). Opus 5.5 (5) and GPT-6 Sol (0) stayed low. Accepted LLM cases still
  need the human review step the plan is built around.
- **Opus 5.5 and Sonnet 5 hit both seeded defects** with model-proposed cases under both prompts;
  GPT-6 Sol and Haiku 4.5 hit one per prompt version.
- **Three of the four models needed request options the 1.1.0 client did not have:** Sonnet 5 and
  Opus 5.5 reject `temperature`, Opus 5.5 rejects a forced tool call, and GPT-6 Sol requires
  `max_completion_tokens`.

Column notes: *Acceptance* is accepted proposals over all proposals. *LLM cases executed* counts
accepted cases left in the plan after de-duplication, summed over runs. A failed LLM case is
attributed to a seeded defect when the demo's own code explains it (a 9-character name that the
contract rejects but the service accepts; a delete that returns 200 instead of 204); every other
failure is a *wrong expectation*, meaning the model expected a status the contract does not
support. Per-run plans, raw model replies, review reasons and results are in
[`results/2026-10-17-llm-gate/`](results/2026-10-17-llm-gate/).

**What the first live run showed.** On v1.1.0 every model lost most proposals at the gate, for
three reasons the offline mock fixtures never exercised:

1. The generator asked about every requirement, but the gate only traces a proposal to a
   requirement that selects `llm-scenario`. In the demo only REQ-010 did, so 11 of 12 calls could
   never produce an accepted case.
2. Models proposed statuses the requirement did not cover (for example 422 or 200 for a 404
   requirement), because the prompt never said which statuses were in scope.
3. Smaller models flattened `parameters` to `{"widget_id": 1}` instead of grouping by location
   (`{"path": {"widget_id": 1}}`), which the schema rejects.

v1.2.0 only queries opted-in requirements, sends the allowed operation/status pairs and shows the
parameter shape in the prompt.

**Limits.** One small demo API with two seeded defects and 12 requirements; three runs per cell;
the defect attribution is specific to this demo. The numbers say how the gate and prompt behave
here, not how any model performs on real services. Rule-based cases already catch both seeded
defects on their own; the question measured here is whether model cases add signal or noise.

**Reproduce (live, billed).** With `API_VV_LLM_BASE_URL` and `API_VV_LLM_API_KEY` set:

```bash
make llm-gate PROVIDER=anthropic MODEL=claude-haiku-4-5 OUT=results/2026-10-17-llm-gate/claude-haiku-4-5/v1.2.0/r1
make llm-gate-report   # rebuilds summary.json and table.md from the run directories
```

## Design decisions

- **Plan as a file, not an in-memory step.** Generation and execution are separate commands with
  a YAML file between them. That file is what a reviewer reads, edits and signs off. Results
  carry a digest of the plan they ran, and reports refuse results from a different plan.
- **Structural trace links.** Requirements select tests by operation, response and check type.
  Renaming a test cannot break traceability, and the executor rejects a plan whose stored
  links disagree with the selectors.
- **Evidence-based status.** `verified` needs a passing test for every covered response and
  check. Any failure makes the requirement `failed`. Passing tests that leave some response or
  check uncovered give `partially covered`, and no passing test gives `not covered`.
- **Review cases instead of guesses.** When no generator can produce a trustworthy expectation
  (for example, an invalid input on an operation with no documented 4xx response), the tool writes
  a disabled case with a `review_reason` instead of inventing a status code.
- **Fail loudly on unsupported input.** Remote refs, recursive refs, non-JSON request bodies and
  non-scalar parameters raise errors at parse time instead of producing incomplete plans.
- **Five runtime dependencies**: pydantic, PyYAML, httpx, jsonschema and jinja2. There are no
  provider SDKs: each LLM adapter is a single httpx POST.

## Limitations

- OpenAPI support is a subset: JSON request bodies, scalar parameters with `form`/`simple`
  style, local refs only. XML and multipart request bodies and `deepObject` parameters are
  rejected. Callbacks, webhooks and links are ignored.
- Generated requests are stateless. There is no setup/teardown or chaining (for example, create
  then read the created id). Stateful flows are written as edited or hand-added plan cases.
- Value synthesis handles common JSON Schema keywords and formats. Complex `oneOf`/`anyOf` bodies
  may need an authored example.
- Response bodies are read fully into memory, and schema `pattern`s from the spec run
  as-is, so point it at specs and services you trust.
- The OpenAI and Anthropic adapters are tested against mocked HTTP responses, not live endpoints.

## Roadmap

- Stateful sequences (create, read, delete) with values extracted from earlier responses.
- Requirement import from CSV and ReqIF.
- Diff reports between two runs of the same plan.
- Property-based value generation for bodies without examples.

## Testing

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev,demo]'
make lint       # ruff check, ruff format --check
make typecheck  # mypy --strict src
make test       # pytest with coverage (fails under 85%)
make demo       # seeded-defect demo; exits non-zero unless exactly REQ-003 and REQ-008 fail
```

The suite has 129 pytest tests covering the parser, generators, executor, LLM adapters,
reports and CLI. The executor tests run the demo app in-process through
`httpx.ASGITransport`, and the test suite blocks sockets entirely, so no network or model
calls are made. CI ([ci.yml](.github/workflows/ci.yml)) runs lint, type checks and tests on
Python 3.11 and 3.12, then the demo and a Docker build smoke test.

## Project structure

```text
src/api_vv/
  cli.py        argparse entry point (api-vv) and exit-code gate
  spec.py       OpenAPI loading and local $ref resolution
  models.py     pydantic models: spec, requirements, config, plan, results
  generate.py   rule-based generators and case fingerprinting
  llm.py        optional LLM proposals (OpenAI-compatible, Anthropic, mock) and validation gate
  execute.py    async httpx executor and response verdicts
  report.py     traceability matrix; Markdown, HTML, CSV and JUnit output
  io.py         YAML/JSON reading and writing
examples/demo_api/  Starlette demo service with two seeded defects, its spec and requirements
scripts/demo.py     end-to-end demo runner used by `make demo` and CI
tests/              pytest suite
docs/               banner, screenshots, sample report and CSV matrix
```

## Citation

If you use api-vv-toolkit or its LLM gate results, please cite it (GitHub's "Cite this repository"
button reads [`CITATION.cff`](CITATION.cff)):

```bibtex
@software{karim_api_vv_toolkit_2026,
  author  = {Karim, Muhib},
  title   = {api-vv-toolkit: requirements-traced API verification with a gated LLM test generator},
  year    = {2026},
  version = {1.2.0},
  url     = {https://github.com/muhib-karim/api-vv-toolkit}
}
```

## Contributing and license

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md) and [CHANGELOG.md](CHANGELOG.md).
[Mermaid](https://mermaid.js.org/) renders the architecture diagram and the
[OpenAPI Specification](https://spec.openapis.org/oas/latest.html) defines the input format.

Released under the [MIT License](LICENSE).
