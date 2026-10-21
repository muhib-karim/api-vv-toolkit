# Project brain: api-vv-toolkit

Handoff note for the next session. Short on purpose; details live in TASKS.md and git history.

## Status

Slice 1 is done (CI and CodeQL green on `43961d2`). In slice 2, done so far: HTML matrix
redesign, Pages landing (`scripts/build_site.py`), composite `action.yml` plus dogfood workflow
(green), live LLM re-run (`results/2026-10-21-llm-gate/`), 1.3.0 bump, CHANGELOG, release notes
and the notes-driven `release.yml`.

## Next step

README refresh (badges, screenshot `docs/assets/traceability-matrix.png`, Action usage,
mermaid, roadmap, links), SKILLS_USED, TASKS and HANDOFF. Then push and wait for green, then
print PU_DONE.

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
2026-10-21 19:40Z claude-code/claude-opus-5-5: slice 2 features done (report, site, action, LLM re-run, release); README and handoff next.
