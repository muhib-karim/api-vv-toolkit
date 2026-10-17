# LLM gate study, 2026-10-17 (live model calls)

Four models, two prompt versions (`v1.1.0`, `v1.2.0`), three runs each, against the seeded-defect
demo API with `examples/llm_experiment/requirements.yaml`. Layout:
`<model>/<prompt version>/r<N>/` holds the run's `config.yaml`, `plan.yaml` (prompts, raw model
replies and one review per proposal), `results.yaml` (execution against the demo service) and
logs. `summary.json` and `table.md` are rebuilt with `make llm-gate-report`.

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

See the "Measured results" section of the top-level README for the setup, findings and limits.
