#!/usr/bin/env python3
"""
submit_edusat_pbs_jobs.py — Submit one PBS job per EduSAT backtracking config.

Each PBS job iterates over all .cnf files in the benchmark directory and writes
per-instance results in a layout identical to compare_configs.py, so the same
--analyze_only / plotting pipeline works on both local and HPC results:

    <base_out_dir>/
        <config_name>/
            <instance_stem>/
                output.txt    — raw solver stdout
                error.txt     — raw solver stderr
                timing.txt    — elapsed_time_seconds, exit_code, ...
                info.txt      — config, args, hostname, cpu_mhz, ...

Usage:
    # Submit all jobs
    python3 scripts/submit_edusat_pbs_jobs.py

    # Dry-run: print PBS scripts without submitting
    python3 scripts/submit_edusat_pbs_jobs.py --dry_run

    # Analyze / plot results after jobs finish (uses compare_configs.py)
    source .venv/bin/activate
    python3 scripts/compare_configs.py --output_dir <base_out_dir> --analyze_only
"""

import argparse
import os
import subprocess
import tempfile

# ---------------------------------------------------------------------------
# Per-run configuration  ← edit this section
# One entry per config; each becomes a separate PBS job.
# ---------------------------------------------------------------------------
PBS_RUNS = [
    {
        "run_name":    "ncb",
        "solver_args": "-cb 0",
        "vnode":       "z019",        # e.g. "z022"
    },
    {
        "run_name":    "always_cb",
        "solver_args": "-cb 1 -cbh 0",
        "vnode":       "z020",
    },
    {
        "run_name":    "limited_cb",
        "solver_args": "-cb 1 -cbh 1",
        "vnode":       "z021",
    },
    {
        "run_name":    "reusetrail_cb",
        "solver_args": "-cb 1 -cbh 2",
        "vnode":       "z022",
    },
]

# ---------------------------------------------------------------------------
# Global PBS / path configuration  ← edit this section
# ---------------------------------------------------------------------------
SOLVER_PATH    = "/home/yshalmon/technion/courses/algoinlogic/edusat/edusat"
BENCHMARK_DIR  = "/TODO/path/to/cnf/benchmarks"   # directory of .cnf files
BASE_OUT_DIR   = "/TODO/path/to/results/edusat"
BASE_LOG_DIR   = "/TODO/path/to/results/edusat/logs"
RUNS_DIR       = "/TODO/path/to/results/edusat/pbs_runs"  # PBS .out/.err + temp scripts

QUEUE          = "zeus_long_q"
WALLTIME       = "24:00:00"
EMAIL          = "yshalmon@campus.technion.ac.il"

# Execution parameters
TIMEOUT_SEC     = 320   # hard wall-clock limit (SIGTERM then SIGKILL)
KILL_AFTER_SEC  = 10    # grace period before SIGKILL after SIGTERM
MEM_LIMIT_MB    = 8192  # per-process virtual memory cap
SOLVE_TIME_SEC  = 300   # -timeout flag passed to edusat (soft internal limit)


# ---------------------------------------------------------------------------
# PBS script template (one per run)
# ---------------------------------------------------------------------------

def build_pbs_script(run: dict) -> str:
    run_name    = run["run_name"]
    solver_args = run["solver_args"]
    vnode       = run["vnode"]

    run_out_dir = os.path.join(BASE_OUT_DIR, run_name)
    run_log_dir = os.path.join(BASE_LOG_DIR, run_name)

    return f"""#!/bin/bash
#PBS -N {run_name}
#PBS -q {QUEUE}
#PBS -o {RUNS_DIR}/{run_name}.out
#PBS -e {RUNS_DIR}/{run_name}.err
#PBS -l walltime={WALLTIME}
#PBS -l select=1:ncpus=1:mem={MEM_LIMIT_MB}mb:vnode={vnode}
#PBS -l place=excl
#PBS -M {EMAIL}

cd $PBS_O_WORKDIR

OUTPUT_DIR="{run_out_dir}"
solver="{SOLVER_PATH}"
run_name="{run_name}"
solver_args="{solver_args}"

LOG_DIR="{run_log_dir}"
mkdir -p "$LOG_DIR"

LOGFILE="$LOG_DIR/{run_name}_$(date +'%Y%m%d_%H%M%S').log"

mkdir -p "$OUTPUT_DIR"

TIMEOUT_SEC={TIMEOUT_SEC}
KILL_AFTER_SEC={KILL_AFTER_SEC}
MEM_LIMIT_MB={MEM_LIMIT_MB}
SOLVE_TIME_SEC={SOLVE_TIME_SEC}

bench_dir="{BENCHMARK_DIR}"
echo "Run started: $(date)" >> "$LOGFILE"
echo "Config: ${{run_name}}  args: ${{solver_args}}" >> "$LOGFILE"

for cnf in "$bench_dir"/*.cnf "$bench_dir"/*.cnf.gz; do
    [ -f "$cnf" ] || continue
    cnf_basename=$(basename "$cnf")

    # Strip extensions to get instance stem (matches Python's Path.stem)
    instance_stem="${{cnf_basename%.cnf.gz}}"
    instance_stem="${{instance_stem%.cnf}}"

    # Skip if already done (allows resuming interrupted runs)
    instance_dir="$OUTPUT_DIR/${{instance_stem}}"
    if [ -f "$instance_dir/output.txt" ]; then
        echo "$(date --iso-8601=seconds) Skipping ${{instance_stem}} (already done)" >> "$LOGFILE"
        continue
    fi

    mkdir -p "$instance_dir"

    output_path="$instance_dir/output.txt"
    error_path="$instance_dir/error.txt"
    time_path="$instance_dir/timing.txt"
    info_path="$instance_dir/info.txt"

    cpu_mhz=$(awk '/^cpu MHz/ {{sum+=$4; n++}} END {{ if (n) printf("%.1f", sum/n); else print "N/A" }}' /proc/cpuinfo)
    echo "$(date --iso-8601=seconds) Running ${{run_name}} on ${{instance_stem}}, CPU MHz: ${{cpu_mhz}}, host: $(hostname)" >> "$LOGFILE"

    # Write run info (same fields as compare_configs.py)
    echo "config: ${{run_name}}"         > "$info_path"
    echo "solver_args: ${{solver_args}}" >> "$info_path"
    echo "solver: ${{solver}}"           >> "$info_path"
    echo "instance: ${{cnf_basename}}"   >> "$info_path"
    echo "timeout: ${{SOLVE_TIME_SEC}}"  >> "$info_path"
    echo "cpu_mhz: ${{cpu_mhz}}"         >> "$info_path"
    echo "hostname: $(hostname)"         >> "$info_path"
    echo "start_time: $(date --iso-8601=seconds)" >> "$info_path"

    # Use /tmp for local I/O (faster than shared NFS on most HPC clusters)
    tmpdir=$(mktemp -d /tmp/cnf.XXXXXX)

    # Decompress if needed
    if [[ "$cnf" == *.gz ]]; then
        if ! gunzip -c "$cnf" > "$tmpdir/${{cnf_basename%.gz}}"; then
            echo "Failed to decompress $cnf" >> "$LOGFILE"
            rm -rf "$tmpdir"
            continue
        fi
        infile="$tmpdir/${{cnf_basename%.gz}}"
    else
        if ! cp "$cnf" "$tmpdir/"; then
            echo "Failed to copy $cnf to $tmpdir" >> "$LOGFILE"
            rm -rf "$tmpdir"
            continue
        fi
        infile="$tmpdir/${{cnf_basename}}"
    fi

    local_out="$tmpdir/output.txt"
    local_err="$tmpdir/error.txt"

    # Run solver
    # edusat usage: ./edusat <options> <cnf_file>
    start_time=$(date +%s.%N)
    ( ulimit -v $((MEM_LIMIT_MB*1024)); \\
      taskset -c 0 timeout --signal=TERM --kill-after=$KILL_AFTER_SEC \\
      $TIMEOUT_SEC "$solver" $solver_args -v 0 -timeout $SOLVE_TIME_SEC "$infile" \\
      >"$local_out" 2>"$local_err" )
    RC=$?
    end_time=$(date +%s.%N)

    elapsed=$(echo "$end_time - $start_time" | bc)

    echo "$(date --iso-8601=seconds) Finished ${{instance_stem}} rc=$RC time=${{elapsed}}s" >> "$LOGFILE"

    # Append timeout marker so the parser can detect it
    if [ $RC -eq 124 ] || [ $RC -eq 137 ]; then
        echo "TIMEOUT REACHED" >> "$local_out"
    fi

    # Save timing (same format as compare_configs.py)
    echo "elapsed_time_seconds: $elapsed" > "$time_path"
    echo "exit_code: $RC"                >> "$time_path"
    echo "timeout_used: $TIMEOUT_SEC"    >> "$time_path"
    echo "end_time: $(date --iso-8601=seconds)" >> "$time_path"

    # Move outputs from tmpdir to shared storage
    if [ -f "$local_out" ]; then
        mv -f "$local_out" "$output_path" || cp -f "$local_out" "$output_path"
    else
        echo "NO OUTPUT GENERATED" > "$output_path"
    fi

    if [ -f "$local_err" ]; then
        mv -f "$local_err" "$error_path" || cp -f "$local_err" "$error_path"
    else
        : > "$error_path"
    fi

    rm -rf "$tmpdir"
done

echo "Run finished: $(date)" >> "$LOGFILE"
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Submit one PBS job per EduSAT backtracking config.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry_run", action="store_true",
        help="Print PBS scripts to stdout instead of submitting via qsub.",
    )
    args = parser.parse_args()

    os.makedirs(BASE_OUT_DIR, exist_ok=True)
    os.makedirs(BASE_LOG_DIR, exist_ok=True)
    os.makedirs(RUNS_DIR,     exist_ok=True)

    for run in PBS_RUNS:
        run_name    = run["run_name"]
        run_out_dir = os.path.join(BASE_OUT_DIR, run_name)
        run_log_dir = os.path.join(BASE_LOG_DIR, run_name)
        os.makedirs(run_out_dir, exist_ok=True)
        os.makedirs(run_log_dir, exist_ok=True)

        script = build_pbs_script(run)

        if args.dry_run:
            print(f"{'='*60}")
            print(f"# DRY RUN — PBS script for: {run_name}")
            print(f"{'='*60}")
            print(script)
            continue

        with tempfile.NamedTemporaryFile(
            "w", delete=False, dir=RUNS_DIR, suffix=".pbs"
        ) as tmp:
            tmp.write(script)
            tmp_path = tmp.name

        try:
            res = subprocess.run(
                ["qsub", tmp_path],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
            )
            print(f"Submitted {run_name}: {res.stdout.strip()}")
        except subprocess.CalledProcessError as e:
            print(f"qsub failed for {run_name}: {e.stderr.strip()}")
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


if __name__ == "__main__":
    main()
