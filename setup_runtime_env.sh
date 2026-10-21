#!/usr/bin/env bash
# Usage: source ./setup_runtime_env.sh

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "Please source this script instead of executing it:" >&2
  echo "  source ./setup_runtime_env.sh" >&2
  exit 1
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export DCNC_PROJECT_ROOT="$PROJECT_ROOT"

if [[ -d "$PROJECT_ROOT/third_party/alib" && -d "$PROJECT_ROOT/third_party/vnep_approx" ]]; then
  export WORKSPACE_ROOT="${WORKSPACE_ROOT:-$PROJECT_ROOT/third_party}"
elif [[ -d "$PROJECT_ROOT/../workspace/dcnc_dynvmp" ]]; then
  export WORKSPACE_ROOT="${WORKSPACE_ROOT:-$PROJECT_ROOT/../workspace/dcnc_dynvmp}"
else
  export WORKSPACE_ROOT="${WORKSPACE_ROOT:-$HOME/workspace/dcnc_dynvmp}"
fi

CONDA_SH="${CONDA_SH:-$HOME/miniconda3/etc/profile.d/conda.sh}"
if [[ -f "$CONDA_SH" ]]; then
  # shellcheck disable=SC1090
  source "$CONDA_SH"
fi
if command -v conda >/dev/null 2>&1; then
  conda activate dcnc_dag >/dev/null 2>&1 || true
fi

case ":${PYTHONPATH:-}:" in
  *":$PROJECT_ROOT/src:"*) ;;
  *) export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}" ;;
esac

chmod +x "$PROJECT_ROOT/tools/run_dynvmp_bridge.sh" 2>/dev/null || true
chmod +x "$PROJECT_ROOT/paper_helpers.sh" 2>/dev/null || true
chmod +x "$PROJECT_ROOT/verify_runtime.sh" 2>/dev/null || true
chmod +x "$PROJECT_ROOT/tools/dynvmp_bridge.py" 2>/dev/null || true

export DCNC_DYNVMP_CMD="bash $PROJECT_ROOT/tools/run_dynvmp_bridge.sh"
export OUT="${OUT:-$PROJECT_ROOT/results_paper_edge}"
export GRB_LICENSE_FILE="${GRB_LICENSE_FILE:-$HOME/gurobi.lic}"
export DCNC_TD_MODE="${DCNC_TD_MODE:-heuristic}"
export DYNVMP_PYTHON="${DYNVMP_PYTHON:-$HOME/miniconda3/envs/dynvmp-py2/bin/python}"

if [[ -f "$PROJECT_ROOT/paper_helpers.sh" ]]; then
  # shellcheck disable=SC1090
  source "$PROJECT_ROOT/paper_helpers.sh"
fi

echo "[setup] project root: $PROJECT_ROOT"
echo "[setup] workspace root: $WORKSPACE_ROOT"
echo "[setup] python: $(command -v python || true)"
echo "[setup] DynVMP python: $DYNVMP_PYTHON"
echo "[setup] DCNC_DYNVMP_CMD=$DCNC_DYNVMP_CMD"
echo "[setup] DCNC_TD_MODE=$DCNC_TD_MODE"
echo "[setup] OUT=$OUT"
