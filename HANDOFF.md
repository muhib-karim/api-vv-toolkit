# Handoff: api-vv-toolkit v1.3.0

Branch `upgrade/v1.3.0`, cut from `main` at `1085a2f`. It was pushed only through the gated push
script and is ready for review and merge by the coordinator. No PR has been opened.

- Session model: `claude-opus-5-5` (Claude Code), 2026-10-21.
- LLM study models (live calls): `claude-opus-5-5`, `claude-sonnet-5`, `gpt-6-sol`.

## What changed

| DoD | Change | Where |
| --- | --- | --- |
| 1 | OpenAPI 3.1 alongside 3.0 (type arrays, nullable without a single type, `examples` maps, webhooks listed but never tested). Auth from env var names only (bearer, basic, apiKey in header, query or cookie), `API_VV_AUTH_<SCHEME>` fallback, invalid-credential negatives | `spec.py`, `models.py`, `execute.py`, `generate.py` |
| 2 | `pattern` sampler and negatives; seeded `--property-cases N --seed S` | `synth.py`, `generate.py` |
| 3 | `api-vv diff OLD NEW`: breaking or non-breaking, exit 1 on breaking | `diff.py`, `tests/fixtures/diff/` |
| 4 | Accessible, mobile-friendly HTML matrix; JUnit XML; Pages landing built in CI from a live demo run | `report.py`, `scripts/build_site.py`, `pages.yml` |
| 5 | Composite Action plus dogfood workflow | `action.yml`, `.github/workflows/action.yml` |
| 6 | CI gates: ruff, `mypy --strict src`, coverage ≥ 85% on 3.11 and 3.12, gitleaks, wheel smoke test, CodeQL with config, Dependabot | `.github/` |
| 7 | Live LLM gate re-run, labelled by date and model | `results/2026-10-21-llm-gate/` |
| 8 | README refresh, CHANGELOG [1.3.0], 1.3.0 bump, release notes, notes-driven `release.yml`, SKILLS_USED, TASKS | repo root, `docs/` |

## RUN (executed in this session, with evidence)

- Local, on the final code: `ruff check`, `ruff format --check`, `mypy --strict src` (and
  `mypy` over src, examples, scripts and tests), and `pytest -x -q -p no:cacheprovider`: 260
  passed, 97.62% coverage. `make demo` gave `Gate: FAIL (REQ-003, REQ-008)`.
- Red-green TDD for the slice 1 features and the report redesign (see TASKS.md).
- The action's step scripts were run locally against a short-lived demo server (stopped
  afterwards): gate=fail with failed=REQ-003,REQ-008, drift breaking=14, and the enforce step
  passing and failing as configured.
- The HTML matrix and landing page were rendered with headless Chromium at 1280px, 390px and in
  dark mode, and reviewed visually. `docs/assets/traceability-matrix.png` comes from that run.
  The contrast of every same-theme text pair was computed (worst: 6.09:1 light, 7.58:1 dark).
- Live LLM study: 9 runs, 2026-10-21 19:23 to 19:29 UTC. Every run's generate step exited 0.
  The summary was rebuilt with `scripts/llm_gate_summary.py`.
- One independent code review of slice 1. All 3 Important and 5 Minor findings were fixed.
- GitHub Actions, all green on `9250ba5` (the head before this file was added):
  - CI run 39663317040: check on 3.11 and 3.12, gitleaks, build, demo with the Pages preview,
    docker
  - CodeQL run 39663316952 (0 results, 0 open alerts on the branch)
  - Action dogfood run 39663316989
- The CI Pages preview artifact (run 39663317040) states "Built by GitHub Actions run
  39663317040 from commit 9250ba5" and shows `Gate: FAIL (REQ-003, REQ-008)`.
- Earlier evidence:
  - slice 1 head `43961d2`: CI run 39660484446 and CodeQL run 39660484480
  - the first dogfood failure (run 39662370789, `ConnectError`), root-caused and fixed in
    run 39662618191

## INFERRED (not executed here)

- **Pages deployment:** `pages.yml` only deploys from `main`, so the live site updates after
  merge. The same `build_site.py` step was proven on the branch through the CI preview
  artifact.
- **`@v1` for consumers:** the floating `v1` tag doesn't exist yet. After merge and the
  `v1.3.0` tag, a maintainer needs to create or move `v1` to the release commit (a tag update,
  which the push script doesn't do). Until then, consumers can pin `@v1.3.0` or a commit SHA.
  The action itself was exercised through `uses: ./`.
- **Release workflow:** the new `release.yml` (version check, notes file, `SHA256SUMS.txt`,
  `--notes-file`) hasn't run, because no tag was pushed. Its steps mirror the working
  agent-eval-harness release and the previous `release.yml`.
- **CodeQL on the PR to main:** the branch analysis has 0 results, and main never ran CodeQL.
  So the PR check should see no new alerts. That is expected, not yet observed.
- **Dependabot:** the config is valid YAML in the same format as the working sibling repo.
  Its first PRs will only appear after merge.

## Follow-ups for the coordinator

1. Review and merge `upgrade/v1.3.0`, then tag `v1.3.0`. The release workflow publishes the
   wheel, sdist, `SHA256SUMS.txt` and `RELEASE_NOTES_v1.3.0.md`.
2. Point `v1` at the `v1.3.0` commit so `uses: muhib-karim/api-vv-toolkit@v1` resolves.
3. GitHub warns that Node 20 actions and CodeQL Action v3 are deprecated (v3 retires in December
   2026). Accept the Dependabot bumps (for example `codeql-action@v4`) when they arrive.
4. Plans written by 1.3 add optional fields, so 1.2 can't read them (1.3 still reads 1.2
   plans). This is stated in the release notes.
