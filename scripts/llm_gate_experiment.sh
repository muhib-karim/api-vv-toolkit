#!/usr/bin/env bash
# One live run of the LLM gate experiment: generate a plan with model proposals for
# examples/llm_experiment/requirements.yaml, execute it against the seeded-defect demo API and
# leave plan.yaml, results.yaml and logs in OUT_DIR. Needs API_VV_LLM_BASE_URL and
# API_VV_LLM_API_KEY in the environment; makes real (billed) model calls.
#
# usage: scripts/llm_gate_experiment.sh OUT_DIR PROVIDER MODEL [EXTRA_LLM_YAML]
#   e.g. scripts/llm_gate_experiment.sh runs/haiku/r1 anthropic claude-haiku-4-5
#        scripts/llm_gate_experiment.sh runs/sol/r1 openai gpt-6-sol \
#          $'  token_param: max_completion_tokens\n  temperature: null\n'
set -euo pipefail
out=$1 provider=$2 model=$3 extra=${4:-}
python=${PYTHON:-.venv/bin/python}
port=${PORT:-18765}
mkdir -p "$out"
sed -e "s/provider: mock/provider: $provider/" -e "s/model: mock-v1/model: $model/" \
  -e '/fixtures:/d' examples/demo_api/config.yaml > "$out/config.yaml"
printf '  timeout_seconds: 120\n%s' "$extra" >> "$out/config.yaml"
start=$(date +%s)
status=0
"$python" -m api_vv.cli generate --spec examples/demo_api/openapi.yaml \
  --requirements examples/llm_experiment/requirements.yaml --llm \
  --config "$out/config.yaml" --out "$out/plan.yaml" > "$out/gen.log" 2>&1 || status=$?
echo "GEN_EXIT $status $(( $(date +%s) - start ))s" >> "$out/gen.log"
[ "$status" -eq 0 ] || { cat "$out/gen.log"; exit "$status"; }
API_VV_DEMO_KEY=demo-only-key "$python" -m uvicorn examples.demo_api.app:app \
  --host 127.0.0.1 --port "$port" --no-access-log > "$out/app.log" 2>&1 &
app=$!
trap 'kill $app' EXIT
sleep 3
API_VV_DEMO_KEY=demo-only-key "$python" -m api_vv.cli run --plan "$out/plan.yaml" \
  --base-url "http://127.0.0.1:$port" --config "$out/config.yaml" \
  --out "$out/results.yaml" > "$out/run.log" 2>&1 || true
tail -n 2 "$out/gen.log"
