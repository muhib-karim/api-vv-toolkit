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

### Slice 2: reports and Pages, the Action, the LLM re-run, docs and release

| Skill | What it drove |
| --- | --- |
| `ui-ux-pro-max` | The design-system query (developer-tool palette, a mono plus sans pairing, stacked cards instead of a table on mobile, a WCAG checklist) behind the HTML matrix and Pages landing tokens. |
| `impeccable` | The craft floor applied to `report.py` and `scripts/build_site.py`: status as icon plus word, themed selection and focus, tabular numerals, no eyebrows or hero metrics. Also a headless render review at 1280px, 390px and in dark mode, which led to three fixes (redundant gate label, caption collapse, two-up priority and status on mobile), and the mechanical detector. Its only findings were cross-theme false positives; the real same-theme pairs measure ≥ 6.1:1. |
| `test-driven-development` (Superpowers) | `tests/test_report.py` accessibility and structure tests were written and failed before the template rewrite. The `scripts/build_site.py` tests were written after the script; that is noted in TASKS.md. |
| `ci-cd-and-automation` (agent-skills) | Composite `action.yml` (inputs passed through env, outputs, job summary), `.github/workflows/action.yml` dogfood, the Pages build in CI, and the notes-driven `release.yml`. |
| `systematic-debugging` (Superpowers, method) | The first dogfood run failed with every request getting `ConnectError`. The downloaded report artifact pointed to the root cause (the demo app imports `api_vv`, which that step hadn't installed, and the readiness loop didn't fail), which was fixed rather than retried. |
| `archify` | Loaded for the architecture section. Its HTML renderer wasn't used because the README needs Mermaid; its code-backed method (each node traced to a source file) shaped the new flowchart. |
| `writing-plans` (Superpowers) | The slice 2 checklist in TASKS.md. |
| `verification-before-completion` (Superpowers) | Sign-off only after `ruff`, `mypy --strict`, `pytest` with coverage, `make demo`, a local run of the action's step scripts, and CI, CodeQL and the Action dogfood green on the pushed head. |

Not used, by choice: Graphify and Understand Anything (the Mermaid diagram was traced directly
from the nine source modules), Playwright (headless Chromium alone captured every screenshot),
and Caveman and Ponytail (output style only).
