#!/usr/bin/env bash
set -eo pipefail

# Usage: ./check.sh /path/to/edusat [extra_solver_args]
# Runs all easy CNF instances twice: NCB (cb=0) and CB (cb=1), counting SAT/UNSAT hits.

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 /path/to/edusat [extra_solver_args]" >&2
  exit 2
fi

SOLVER="$1"
shift || true
if [[ $# -gt 0 ]]; then
  EXTRA_ARGS=("$@")
else
  EXTRA_ARGS=()
fi

if ! SOLVER_ABS=$(realpath "$SOLVER" 2>/dev/null); then
  echo "Solver path invalid: $SOLVER" >&2
  exit 1
fi
if [[ ! -x "$SOLVER_ABS" ]]; then
  echo "Solver not executable: $SOLVER_ABS" >&2
  exit 1
fi

# Always work from the directory that contains this script and the CNF files
cd "$(dirname "$0")"
shopt -s nullglob
echo "Working dir: $(pwd)"
echo "Solver: $SOLVER_ABS"
echo "Extra args: ${EXTRA_ARGS[*]:-(none)}"

GLOBAL_FAIL=0

run_suite() {
  local cb_flag=$1
  echo "=== Running suite with cb=$cb_flag ==="
  local sat_ok=0 sat_total=0
  local unsat_ok=0 unsat_total=0

  local cb_args=()
  if [[ $cb_flag -ne 0 ]]; then
    cb_args=(-cb "$cb_flag")
  fi

  echo "Looking for SAT instances..."
  for f in aim-*yes*.cnf; do
    if [[ ! -f "$f" ]]; then
      echo "No SAT files found"
      break
    fi
    sat_total=$((sat_total + 1))
    echo "Testing SAT: $f"
    set +e
    out=$("$SOLVER_ABS" "${cb_args[@]}" "$f" 2>&1 | tail -n 1)
    set -e
    if [[ "$out" =~ SAT ]]; then
      sat_ok=$((sat_ok + 1))
    else
      echo "  -> got: $out"
    fi
  done

  echo "Looking for UNSAT instances..."
  for f in aim-*no*.cnf; do
    if [[ ! -f "$f" ]]; then
      echo "No UNSAT files found"
      break
    fi
    unsat_total=$((unsat_total + 1))
    echo "Testing UNSAT: $f"
    set +e
    out=$("$SOLVER_ABS" "${cb_args[@]}" "$f" 2>&1 | tail -n 1)
    set -e
    if [[ "$out" =~ UNSAT ]]; then
      unsat_ok=$((unsat_ok + 1))
    else
      echo "  -> got: $out"
    fi
  done

  echo "cb=$cb_flag : SAT $sat_ok/$sat_total | UNSAT $unsat_ok/$unsat_total"
  if [[ $sat_ok -ne $sat_total || $unsat_ok -ne $unsat_total ]]; then
    GLOBAL_FAIL=1
  fi
  echo ""
}

echo "Starting tests..."
run_suite 0
run_suite 1
echo "Done."
if [[ $GLOBAL_FAIL -ne 0 ]]; then
  echo "ERROR: Some tests failed." >&2
  exit 1
fi
