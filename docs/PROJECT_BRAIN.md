# Project brain: api-vv-toolkit

Handoff note for the next session. Short on purpose; details live in TASKS.md and git history.

## Status

v1.3.0 upgrade on branch `upgrade/v1.3.0`. Slice 1 (OpenAPI 3.1 + auth, seeded negative and
property generation, `api-vv diff`, CI gates) is implemented, reviewed and green locally
(256 tests, about 98% coverage, demo gate unchanged). Next it is pushed and checked on CI.

## Next step

Push with push.sh and get CI and CodeQL green on the head. Then wait for slice 2 (DoD 4, 5, 7, 8, 9).

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
