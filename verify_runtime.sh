#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "[verify] checking maintained shell syntax"
while IFS= read -r -d '' script; do
  bash -n "$script"
done < <(
  find "$PROJECT_ROOT" -type f -name '*.sh' \
    -not -path "$PROJECT_ROOT/.git/*" \
    -not -path "$PROJECT_ROOT/.runtime/*" \
    -not -path "$PROJECT_ROOT/build/*" \
    -not -path "$PROJECT_ROOT/dist/*" \
    -not -path "$PROJECT_ROOT/results/*" \
    -not -path "$PROJECT_ROOT/results_paper_edge/*" \
    -print0
)
echo "[verify] shell syntax ok"

# shellcheck disable=SC1090
source "$PROJECT_ROOT/setup_runtime_env.sh"

python - <<'PY'
import importlib.util
spec = importlib.util.find_spec("dcnc_sim")
print("[verify] dcnc_sim spec:", spec)
if spec is None:
    raise SystemExit(1)
PY

python scripts/run_edge_experiments.py --help >/dev/null
echo "[verify] edge CLI ok"

echo "[verify] bridge wrapper: $DCNC_DYNVMP_CMD"
echo "[verify] bridge td mode: ${DCNC_TD_MODE}"

echo "[verify] running a small greedy smoke test"
python scripts/run_edge_experiments.py \
  --output-dir "$OUT/00_smoke/verify_greedy" \
  --slots 20 \
  --seeds 1 \
  --seed-start 0 \
  --progress-every 10 \
  --interference-model primary \
  --fixed-k 1 \
  --dcnc-solver greedy \
  --policies DCNC-DAG \
  --cases driving_milan >/dev/null

echo "[verify] greedy smoke test ok"
echo "[verify] next exact check: $DCNC_DYNVMP_CMD --help"
