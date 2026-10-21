# LLM gate re-run, 2026-10-21 (live model calls)

**Labels:** run on 2026-10-21 (19:23 to 19:29 UTC) with `claude-opus-5-5`, `claude-sonnet-5`
and `gpt-6-sol`. Three runs per model, with api-vv-toolkit 1.3.0 code from branch
`upgrade/v1.3.0`. These are live, billed calls through the configured model endpoint, not the
mock provider. The endpoint address and credentials came from environment variables
(`API_VV_LLM_BASE_URL`, `API_VV_LLM_API_KEY`) and appear in no file here.

**Why the re-run is comparable.** The LLM path didn't change between 1.2.0 and 1.3.0:
`src/api_vv/llm.py`, `examples/llm_experiment/requirements.yaml` and
`scripts/llm_gate_experiment.sh` are byte-identical. So the `v1.3.0` rows below use the same
prompt and requirement selection as the `v1.2.0` rows of the
[2026-10-17 study](../2026-10-17-llm-gate/README.md). Per-model request options are recorded
in each run's `config.yaml`. They match the earlier study: `temperature: null` throughout,
`tool_choice: auto` for Opus, and `max_completion_tokens` for gpt-6-sol. Two things differ:
the 1.3.0 generator adds one deterministic `invalid credentials` case to every plan, and the
2026-10-17 study also ran `claude-haiku-4-5`, which wasn't re-run (it isn't one of the current
models requested).

Layout: `<model>/v1.3.0/r<N>/` holds `config.yaml`, `plan.yaml` (prompts, raw replies and one
review per proposal), `results.yaml` (execution against the seeded-defect demo API) and the
`gen.log` and `run.log` logs. `summary.json` and `table.md` were rebuilt with
`python scripts/llm_gate_summary.py --report results/2026-10-21-llm-gate`.

| Model | Prompt | Runs | Model calls / run | Proposals | Accepted | Acceptance | LLM cases executed | Failed on seeded defects | Wrong expectations | Seeded defects hit |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| claude-opus-5-5 | v1.3.0 | 3 | 8 | 110 | 105 | 95% | 82 | 19 | 6 | defect-1, defect-2 |
| claude-sonnet-5 | v1.3.0 | 3 | 8 | 104 | 79 | 76% | 64 | 9 | 7 | defect-1, defect-2 |
| gpt-6-sol | v1.3.0 | 3 | 8 | 63 | 60 | 95% | 39 | 7 | 0 | defect-1 |

## Against the 2026-10-17 `v1.2.0` rows (same prompt)

| Model | Acceptance 10-17 → 10-21 | Failed on seeded defects | Wrong expectations | Defects hit |
|---|---|---|---|---|
| claude-opus-5-5 | 93% → 95% | 20 → 19 | 5 → 6 | both, both |
| claude-sonnet-5 | 71% → 76% | 7 → 9 | 10 → 7 | both, both |
| gpt-6-sol | 94% → 95% | 3 → 7 | 0 → 0 | defect-1, defect-1 |

The findings of the earlier study hold:

- The spec gate accepts most proposals once the prompt lists the allowed operation and status
  pairs.
- Opus and Sonnet proposals reach both seeded defects. gpt-6-sol's reach only the `maxLength`
  defect (defect-1).
- Accepted cases still include some wrong expectations: a status the contract doesn't promise
  for that input. That is why model cases only count toward a requirement through the same
  evidence rules as generated cases.

Three runs per model is a small sample, so read the differences between dates as run-to-run
variation, not as model changes.
