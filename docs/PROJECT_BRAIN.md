# Project brain: api-vv-toolkit

Handoff note for the next session. Short on purpose; details live in TASKS.md and git history.

## Status

v1.3.0 upgrade on branch `upgrade/v1.3.0`. Slice 1 (OpenAPI 3.1 + auth, seeded negative and
property generation, `api-vv diff`, CI gates) is done: it was reviewed and pushed, CI and CodeQL were
green on `37eb9a7` (CI run 39660210674, CodeQL run 39660210679, 0 alerts), and 256 tests pass
at about 98% coverage.

## Next step

Wait for the slice 2 message: DoD 4 (HTML/JUnit report and Pages live run), 5 (action.yml plus
dogfood), 7 (LLM gate re-run), 8 (README, CHANGELOG [1.3.0], version bump, HANDOFF) and 9.

## Decisions

- Runtime dependencies stay at five (pydantic, PyYAML, httpx, jsonschema, jinja2). The property
  generator and regex sampler are written in-house, with no hypothesis.
- Plan format stays `version: "1.0"`. New fields (`Plan.seed`, `Plan.property_cases`,
  `Spec.webhooks`, `auth: invalid`) are optional and additive, so old plans still load.
- `api-vv diff` fails closed: a schema change it can't analyse counts as breaking.

## Gotchas

- Run pytest one process at a time: `pytest -x -q -p no:cacheprovider`.
- Generator output changes case ids. Regenerate `docs/sample-*` from `make demo`.

## Session log
2026-10-21 19:20Z claude-code/claude-opus-5-5: slice 1 done locally (T1-T4 plus review fixes); next push and CI.
2026-10-21 19:25Z claude-code/claude-opus-5-5: slice 1 pushed; CI and CodeQL green and 0 alerts; waiting for slice 2.
