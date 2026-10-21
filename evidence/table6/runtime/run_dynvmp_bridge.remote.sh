#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Prefer a sibling workspace that travels together with the project.
if [[ -d "$PROJECT_ROOT/../workspace/dcnc_dynvmp" ]]; then
  WORKSPACE_ROOT="${WORKSPACE_ROOT:-$PROJECT_ROOT/../workspace/dcnc_dynvmp}"
else
  WORKSPACE_ROOT="${WORKSPACE_ROOT:-$HOME/workspace/dcnc_dynvmp}"
fi

PY2="${DYNVMP_PYTHON:-$HOME/miniconda3/envs/dynvmp-py2/bin/python}"
if [[ ! -x "$PY2" ]]; then
  echo "[run_dynvmp_bridge] DynVMP Python interpreter not found: $PY2" >&2
  exit 2
fi

# Make the local repositories importable even if the user did not run pip install -e .
ALIB_SRC="$WORKSPACE_ROOT/alib-master"
VNEP_SRC="$WORKSPACE_ROOT/vnep-approx-master"
TOOLS_BRIDGE="$PROJECT_ROOT/tools/dynvmp_bridge.py"
if [[ ! -f "$TOOLS_BRIDGE" ]]; then
  TOOLS_BRIDGE="$WORKSPACE_ROOT/tools/dynvmp_bridge.py"
fi

if [[ ! -f "$TOOLS_BRIDGE" ]]; then
  echo "[run_dynvmp_bridge] dynvmp_bridge.py not found in project tools/ or workspace tools/." >&2
  exit 2
fi

export PYTHONPATH="$ALIB_SRC:$VNEP_SRC${PYTHONPATH:+:$PYTHONPATH}"
export ALIB_EXPERIMENT_HOME="${ALIB_EXPERIMENT_HOME:-$WORKSPACE_ROOT/alib_experiment_home}"
mkdir -p "$ALIB_EXPERIMENT_HOME/input" "$ALIB_EXPERIMENT_HOME/output" "$ALIB_EXPERIMENT_HOME/log"
export GRB_LICENSE_FILE="${GRB_LICENSE_FILE:-$HOME/gurobi.lic}"
# Tree decomposition mode: heuristic (default), auto, pace, pace-strict.
export DCNC_TD_MODE="${DCNC_TD_MODE:-heuristic}"
# Optional PACE path if the user wants to try PACE. Not required for the default heuristic mode.
if [[ -d "$WORKSPACE_ROOT/PACE2017-TrackA-master" ]]; then
  export PACE_TD_ALGORITHM_PATH="${PACE_TD_ALGORITHM_PATH:-$WORKSPACE_ROOT/PACE2017-TrackA-master}"
fi

exec "$PY2" "$TOOLS_BRIDGE" "$@"
