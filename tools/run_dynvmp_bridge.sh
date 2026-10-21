#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Prefer the vendored, licensed snapshots that produced the artifact.
if [[ -d "$PROJECT_ROOT/third_party/alib" && -d "$PROJECT_ROOT/third_party/vnep_approx" ]]; then
  WORKSPACE_ROOT="${WORKSPACE_ROOT:-$PROJECT_ROOT/third_party}"
  DEFAULT_ALIB_SRC="$WORKSPACE_ROOT/alib"
  DEFAULT_VNEP_SRC="$WORKSPACE_ROOT/vnep_approx"
elif [[ -d "$PROJECT_ROOT/../workspace/dcnc_dynvmp" ]]; then
  WORKSPACE_ROOT="${WORKSPACE_ROOT:-$PROJECT_ROOT/../workspace/dcnc_dynvmp}"
  DEFAULT_ALIB_SRC="$WORKSPACE_ROOT/alib-master"
  DEFAULT_VNEP_SRC="$WORKSPACE_ROOT/vnep-approx-master"
else
  WORKSPACE_ROOT="${WORKSPACE_ROOT:-$HOME/workspace/dcnc_dynvmp}"
  DEFAULT_ALIB_SRC="$WORKSPACE_ROOT/alib-master"
  DEFAULT_VNEP_SRC="$WORKSPACE_ROOT/vnep-approx-master"
fi

PY2="${DYNVMP_PYTHON:-$HOME/miniconda3/envs/dynvmp-py2/bin/python}"
if [[ ! -x "$PY2" ]]; then
  echo "[run_dynvmp_bridge] DynVMP Python interpreter not found: $PY2" >&2
  exit 2
fi

# Make the local repositories importable even if the user did not run pip install -e .
ALIB_SRC="${ALIB_SRC:-$DEFAULT_ALIB_SRC}"
VNEP_SRC="${VNEP_SRC:-$DEFAULT_VNEP_SRC}"
TOOLS_BRIDGE="$PROJECT_ROOT/tools/dynvmp_bridge.py"
if [[ ! -f "$TOOLS_BRIDGE" ]]; then
  TOOLS_BRIDGE="$WORKSPACE_ROOT/tools/dynvmp_bridge.py"
fi

if [[ ! -f "$TOOLS_BRIDGE" ]]; then
  echo "[run_dynvmp_bridge] dynvmp_bridge.py not found in project tools/ or workspace tools/." >&2
  exit 2
fi

export PYTHONPATH="$ALIB_SRC:$VNEP_SRC${PYTHONPATH:+:$PYTHONPATH}"
export ALIB_EXPERIMENT_HOME="${ALIB_EXPERIMENT_HOME:-$PROJECT_ROOT/.runtime/alib_experiment_home}"
mkdir -p "$ALIB_EXPERIMENT_HOME/input" "$ALIB_EXPERIMENT_HOME/output" "$ALIB_EXPERIMENT_HOME/log"
export GRB_LICENSE_FILE="${GRB_LICENSE_FILE:-$HOME/gurobi.lic}"
# Tree decomposition mode: heuristic (default), auto, pace, pace-strict.
export DCNC_TD_MODE="${DCNC_TD_MODE:-heuristic}"
# Optional PACE path if the user wants to try PACE. Not required for the default heuristic mode.
if [[ -d "$WORKSPACE_ROOT/PACE2017-TrackA-master" ]]; then
  export PACE_TD_ALGORITHM_PATH="${PACE_TD_ALGORITHM_PATH:-$WORKSPACE_ROOT/PACE2017-TrackA-master}"
fi

exec "$PY2" "$TOOLS_BRIDGE" "$@"
