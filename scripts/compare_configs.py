#!/usr/bin/env python3
"""
compare_configs.py — Compare EduSAT backtracking configurations on a CNF benchmark set.

Runs NCB and CB variants (always-CB, limited-CB, reusetrail-CB) on every .cnf file
in a given directory, saves structured per-instance results, and optionally plots
summary statistics.

Output layout (mirrors PBS job output for easy analysis):
    <output_dir>/
        <config_name>/
            <instance_name>/
                output.txt    — raw solver stdout
                error.txt     — raw solver stderr
                timing.txt    — elapsed_time_seconds, exit_code
                info.txt      — config, instance, args, hostname
                stats.json    — parsed solver statistics

Usage:
    source .venv/bin/activate
    python3 scripts/compare_configs.py --cnf_dir <dir> [options]

    --cnf_dir      DIR     Directory containing .cnf files (required)
    --solver       PATH    Path to edusat binary (default: ./edusat)
    --output_dir   DIR     Where to write results (default: ./results/compare_<timestamp>)
    --timeout      SECS    Per-solve timeout in seconds (default: 60)
    --jobs         N       Parallel worker processes (default: cpu_count)
    --configs      NAMES   Comma-separated subset of configs to run
                           (ncb, always_cb, limited_cb, reusetrail_cb; default: all)
    --analyze_only         Skip solving; just parse existing output_dir and plot
    --no_plot              Run solves but skip plotting
    --plot_dir     DIR     Where to save plots (default: <output_dir>/plots)
"""

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration definitions
# Each entry mirrors a PBS_RUNS entry: name + extra solver args.
# ---------------------------------------------------------------------------
CONFIGS = [
    {
        "name": "ncb",
        "label": "NCB (baseline)",
        "args": ["-cb", "0"],
    },
    {
        "name": "always_cb",
        "label": "Always-CB (cbh=0)",
        "args": ["-cb", "1", "-cbh", "0"],
    },
    {
        "name": "limited_cb",
        "label": "Limited-CB (cbh=1)",
        "args": ["-cb", "1", "-cbh", "1"],
    },
    {
        "name": "reusetrail_cb",
        "label": "Reusetrail-CB (cbh=2)",
        "args": ["-cb", "1", "-cbh", "2"],
    },
]

# ---------------------------------------------------------------------------
# Output parsing
# ---------------------------------------------------------------------------

def parse_solver_output(text: str) -> dict:
    """Parse edusat stdout into a stats dict. Missing fields are None."""
    stats = {
        "result": None,           # SAT / UNSAT / TIMEOUT / ERROR
        "restarts": None,
        "conflicts": None,
        "learned_clauses": None,
        "decisions": None,
        "implications": None,
        "propagations": None,
        "cb_backtracks": None,
        "ncb_backtracks": None,
        "avg_bt_distance": None,
        "time_solver": None,      # time reported by solver itself
        "vars": None,
        "clauses": None,
    }

    patterns = {
        "restarts":        r"### Restarts:\s+(\d+)",
        "conflicts":       r"### Conflicts:\s+(\d+)",
        "learned_clauses": r"### Learned-clauses:\s+(\d+)",
        "decisions":       r"### Decisions:\s+(\d+)",
        "implications":    r"### Implications:\s+(\d+)",
        "propagations":    r"### Propagations:\s+(\d+)",
        "cb_backtracks":   r"### CB-backtracks:\s+(\d+)",
        "ncb_backtracks":  r"### NCB-backtracks:\s+(\d+)",
        "avg_bt_distance": r"### Avg-BT-distance:\s+([\d.]+)",
        "time_solver":     r"### Time:\s+([\d.]+)",
        "vars":            r"vars:\s*(\d+)",
        "clauses":         r"clauses:\s*(\d+)",
    }

    for key, pat in patterns.items():
        m = re.search(pat, text)
        if m:
            val = m.group(1)
            stats[key] = float(val) if "." in val else int(val)

    for verdict in ("SAT", "UNSAT", "TIMEOUT"):
        if re.search(rf"\bS {verdict}\b", text, re.IGNORECASE):
            stats["result"] = verdict
            break

    return stats


# ---------------------------------------------------------------------------
# Single solve worker (runs in subprocess pool)
# ---------------------------------------------------------------------------

def run_instance(task: dict) -> dict:
    """
    Execute the solver on one (config, instance) pair.
    Returns a result dict suitable for JSON serialisation.
    """
    solver   = task["solver"]
    cnf_path = task["cnf_path"]
    extra    = task["config_args"]
    timeout  = task["timeout"]
    out_dir  = Path(task["instance_out_dir"])
    config   = task["config_name"]
    label    = task["config_label"]

    out_dir.mkdir(parents=True, exist_ok=True)

    output_path = out_dir / "output.txt"
    error_path  = out_dir / "error.txt"
    timing_path = out_dir / "timing.txt"
    info_path   = out_dir / "info.txt"
    stats_path  = out_dir / "stats.json"

    cmd = [solver] + extra + ["-v", "0", cnf_path]

    # Write info file
    with open(info_path, "w") as f:
        f.write(f"config: {config}\n")
        f.write(f"label: {label}\n")
        f.write(f"solver: {solver}\n")
        f.write(f"instance: {os.path.basename(cnf_path)}\n")
        f.write(f"args: {' '.join(extra)}\n")
        f.write(f"timeout: {timeout}\n")
        f.write(f"hostname: {socket.gethostname()}\n")
        f.write(f"start_time: {datetime.now().isoformat()}\n")

    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            text=True,
        )
        rc = proc.returncode
        stdout = proc.stdout
        stderr = proc.stderr
    except subprocess.TimeoutExpired as e:
        elapsed = time.perf_counter() - t0
        stdout = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = (e.stderr or b"").decode(errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
        stdout += "\nTIMEOUT REACHED\n"
        rc = 124
    except Exception as e:
        elapsed = time.perf_counter() - t0
        stdout = ""
        stderr = str(e)
        rc = -1

    elapsed = time.perf_counter() - t0

    output_path.write_text(stdout)
    error_path.write_text(stderr)

    with open(timing_path, "w") as f:
        f.write(f"elapsed_time_seconds: {elapsed:.4f}\n")
        f.write(f"exit_code: {rc}\n")
        f.write(f"timeout_used: {timeout}\n")
        f.write(f"end_time: {datetime.now().isoformat()}\n")

    stats = parse_solver_output(stdout)
    stats["elapsed_wall_time"] = round(elapsed, 4)
    stats["exit_code"] = rc
    stats["instance"] = os.path.basename(cnf_path)
    stats["config"] = config

    if rc == 124 and stats["result"] is None:
        stats["result"] = "TIMEOUT"
    elif rc != 0 and stats["result"] is None:
        stats["result"] = "ERROR"

    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)

    return stats


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

def run_all(cnf_files, configs, solver, output_dir, timeout, jobs):
    tasks = []
    for cfg in configs:
        for cnf in cnf_files:
            instance_name = Path(cnf).stem
            tasks.append({
                "solver":           solver,
                "cnf_path":         str(cnf),
                "config_name":      cfg["name"],
                "config_label":     cfg["label"],
                "config_args":      cfg["args"],
                "timeout":          timeout,
                "instance_out_dir": str(Path(output_dir) / cfg["name"] / instance_name),
            })

    print(f"Running {len(tasks)} tasks ({len(cnf_files)} instances × {len(configs)} configs) "
          f"with {jobs} workers, timeout={timeout}s")

    results = []
    n_done = 0
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(run_instance, t): t for t in tasks}
        for fut in as_completed(futures):
            n_done += 1
            task = futures[fut]
            try:
                res = fut.result()
                status = res.get("result", "?")
                bt = res.get("avg_bt_distance")
                bt_str = f"  avg_bt={bt:.2f}" if bt is not None else ""
                print(f"  [{n_done}/{len(tasks)}] {task['config_name']:15s}  "
                      f"{Path(task['cnf_path']).name:35s}  {status}{bt_str}")
                results.append(res)
            except Exception as e:
                print(f"  [{n_done}/{len(tasks)}] ERROR {task['config_name']} "
                      f"{task['cnf_path']}: {e}", file=sys.stderr)

    return results


# ---------------------------------------------------------------------------
# Result loading (for --analyze_only)
# Works with both local runs (stats.json present) and raw PBS output
# (stats.json absent — falls back to parsing output.txt + timing.txt).
# ---------------------------------------------------------------------------

def _parse_timing(timing_path: Path) -> dict:
    """Parse timing.txt into a small dict."""
    out = {}
    for line in timing_path.read_text().splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if k == "elapsed_time_seconds":
            try:
                out["elapsed_wall_time"] = float(v)
            except ValueError:
                pass
        elif k == "exit_code":
            try:
                out["exit_code"] = int(v)
            except ValueError:
                pass
    return out


def load_results(output_dir, config_names):
    """
    Walk <output_dir>/<config_name>/<instance_dir>/ and collect stats.

    Priority:
      1. stats.json  — written by compare_configs.py local runs
      2. output.txt  — raw solver stdout from PBS jobs; parsed on the fly,
                       and the resulting stats.json is cached for later calls.
    """
    results = []
    for cfg_name in config_names:
        cfg_dir = Path(output_dir) / cfg_name
        if not cfg_dir.exists():
            continue
        for instance_dir in sorted(cfg_dir.iterdir()):
            if not instance_dir.is_dir():
                continue
            stats_file  = instance_dir / "stats.json"
            output_file = instance_dir / "output.txt"
            timing_file = instance_dir / "timing.txt"

            if stats_file.exists():
                with open(stats_file) as f:
                    results.append(json.load(f))
                continue

            # Fallback: build stats from raw PBS output files
            if not output_file.exists():
                continue

            stats = parse_solver_output(output_file.read_text())
            stats["config"]   = cfg_name
            # Restore instance name: PBS uses stem as dir name, add .cnf back
            stats["instance"] = instance_dir.name + ".cnf"

            if timing_file.exists():
                stats.update(_parse_timing(timing_file))

            rc = stats.get("exit_code", 0)
            if stats["result"] is None:
                if rc in (124, 137):
                    stats["result"] = "TIMEOUT"
                elif rc not in (0, None):
                    stats["result"] = "ERROR"

            # Cache so subsequent calls are fast
            with open(stats_file, "w") as f:
                json.dump(stats, f, indent=2)

            results.append(stats)
    return results


# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------

def print_summary(results, configs):
    from collections import defaultdict

    by_config = defaultdict(list)
    for r in results:
        by_config[r["config"]].append(r)

    header = f"{'Config':20s} {'N':>4}  {'SAT':>4}  {'UNSAT':>5}  {'TIMEOUT':>7}  "
    header += f"{'Avg-BT-dist':>12}  {'Avg-conflicts':>14}  {'Avg-time(s)':>11}"
    print("\n" + "=" * len(header))
    print(header)
    print("=" * len(header))

    for cfg in configs:
        name = cfg["name"]
        rows = by_config.get(name, [])
        if not rows:
            continue
        n_sat     = sum(1 for r in rows if r.get("result") == "SAT")
        n_unsat   = sum(1 for r in rows if r.get("result") == "UNSAT")
        n_timeout = sum(1 for r in rows if r.get("result") == "TIMEOUT")
        bt_vals   = [r["avg_bt_distance"]   for r in rows if r.get("avg_bt_distance")   is not None]
        conf_vals = [r["conflicts"]          for r in rows if r.get("conflicts")         is not None]
        time_vals = [r["elapsed_wall_time"]  for r in rows if r.get("elapsed_wall_time") is not None]
        avg = lambda xs: sum(xs) / len(xs) if xs else float("nan")
        print(f"{name:20s} {len(rows):>4}  {n_sat:>4}  {n_unsat:>5}  {n_timeout:>7}  "
              f"{avg(bt_vals):>12.2f}  {avg(conf_vals):>14.1f}  {avg(time_vals):>11.3f}")

    print("=" * len(header))


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def make_plots(results, configs, plot_dir):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        print("matplotlib/numpy not available — skipping plots.")
        return

    Path(plot_dir).mkdir(parents=True, exist_ok=True)

    from collections import defaultdict
    by_config = defaultdict(list)
    for r in results:
        by_config[r["config"]].append(r)

    cfg_names  = [c["name"]  for c in configs if c["name"] in by_config]
    cfg_labels = [c["label"] for c in configs if c["name"] in by_config]
    colors     = plt.cm.tab10.colors

    # ---- 1. Cactus plot: wall time vs #instances solved ----
    fig, ax = plt.subplots(figsize=(8, 5))
    for i, (name, label) in enumerate(zip(cfg_names, cfg_labels)):
        rows = by_config[name]
        solved_times = sorted(
            r["elapsed_wall_time"]
            for r in rows
            if r.get("result") in ("SAT", "UNSAT") and r.get("elapsed_wall_time") is not None
        )
        ax.step(solved_times, range(1, len(solved_times) + 1),
                where="post", label=label, color=colors[i % len(colors)])
    ax.set_xlabel("Wall-clock time (s)")
    ax.set_ylabel("Instances solved")
    ax.set_title("Cactus plot — instances solved vs time")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(plot_dir, "cactus.png"), dpi=150)
    plt.close(fig)

    # ---- 2. Box plot: Avg-BT-distance ----
    fig, ax = plt.subplots(figsize=(8, 5))
    bt_data = [
        [r["avg_bt_distance"] for r in by_config[name] if r.get("avg_bt_distance") is not None]
        for name in cfg_names
    ]
    bp = ax.boxplot(bt_data, patch_artist=True, notch=False)
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
    ax.set_xticks(range(1, len(cfg_labels) + 1))
    ax.set_xticklabels(cfg_labels, rotation=15, ha="right")
    ax.set_ylabel("Avg backtrack distance per conflict")
    ax.set_title("Backtrack distance distribution by config")
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(plot_dir, "bt_distance_boxplot.png"), dpi=150)
    plt.close(fig)

    # ---- 3. Bar chart: mean conflicts ----
    fig, ax = plt.subplots(figsize=(8, 5))
    mean_conflicts = []
    std_conflicts  = []
    for name in cfg_names:
        vals = [r["conflicts"] for r in by_config[name] if r.get("conflicts") is not None]
        mean_conflicts.append(np.mean(vals) if vals else 0)
        std_conflicts.append(np.std(vals)   if vals else 0)
    x = np.arange(len(cfg_names))
    bars = ax.bar(x, mean_conflicts, yerr=std_conflicts, capsize=4,
                  color=colors[:len(cfg_names)], alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(cfg_labels, rotation=15, ha="right")
    ax.set_ylabel("Mean conflicts")
    ax.set_title("Mean conflicts per config (±1 std)")
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(plot_dir, "mean_conflicts.png"), dpi=150)
    plt.close(fig)

    # ---- 4. Scatter: NCB time vs CB time (per instance) ----
    ncb_time = {r["instance"]: r["elapsed_wall_time"]
                for r in by_config.get("ncb", [])
                if r.get("elapsed_wall_time") is not None}
    cb_configs = [n for n in cfg_names if n != "ncb"]
    if ncb_time and cb_configs:
        fig, axes = plt.subplots(1, len(cb_configs), figsize=(5 * len(cb_configs), 5), squeeze=False)
        for j, cb_name in enumerate(cb_configs):
            ax = axes[0][j]
            cb_time = {r["instance"]: r["elapsed_wall_time"]
                       for r in by_config[cb_name]
                       if r.get("elapsed_wall_time") is not None}
            common = sorted(set(ncb_time) & set(cb_time))
            if common:
                xs = [ncb_time[inst] for inst in common]
                ys = [cb_time[inst]  for inst in common]
                ax.scatter(xs, ys, s=20, alpha=0.7, color=colors[(cfg_names.index(cb_name)) % len(colors)])
                lim = max(max(xs), max(ys)) * 1.05
                ax.plot([0, lim], [0, lim], "k--", linewidth=0.8, label="y=x")
            ax.set_xlabel("NCB time (s)")
            ax.set_ylabel(f"{cb_name} time (s)")
            ax.set_title(f"NCB vs {cb_name}")
            ax.grid(True, alpha=0.3)
            ax.legend(fontsize=8)
        fig.suptitle("Per-instance time: NCB vs CB variants", y=1.01)
        fig.tight_layout()
        fig.savefig(os.path.join(plot_dir, "time_scatter.png"), dpi=150, bbox_inches="tight")
        plt.close(fig)

    # ---- 5. CB vs NCB backtrack ratio (stacked bar, per CB config) ----
    cb_only = [n for n in cfg_names if n != "ncb"]
    if cb_only:
        fig, ax = plt.subplots(figsize=(8, 5))
        cb_means   = []
        ncb_means  = []
        valid_labels = []
        for name in cb_only:
            rows = by_config[name]
            cb_vals  = [r["cb_backtracks"]  for r in rows if r.get("cb_backtracks")  is not None]
            ncb_vals = [r["ncb_backtracks"] for r in rows if r.get("ncb_backtracks") is not None]
            if cb_vals and ncb_vals:
                cb_means.append(np.mean(cb_vals))
                ncb_means.append(np.mean(ncb_vals))
                valid_labels.append(next(c["label"] for c in configs if c["name"] == name))
        if valid_labels:
            x = np.arange(len(valid_labels))
            ax.bar(x, cb_means,  label="CB backtracks",  color="steelblue", alpha=0.85)
            ax.bar(x, ncb_means, label="NCB backtracks", color="salmon",
                   alpha=0.85, bottom=cb_means)
            ax.set_xticks(x)
            ax.set_xticklabels(valid_labels, rotation=15, ha="right")
            ax.set_ylabel("Mean backtracks per instance")
            ax.set_title("CB vs NCB backtrack breakdown (mean)")
            ax.legend()
            ax.grid(True, axis="y", alpha=0.3)
            fig.tight_layout()
            fig.savefig(os.path.join(plot_dir, "bt_breakdown.png"), dpi=150)
            plt.close(fig)

    print(f"Plots saved to: {plot_dir}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Compare EduSAT backtracking configs on a CNF benchmark directory.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--cnf_dir",      required=False, help="Directory of .cnf files")
    parser.add_argument("--solver",       default="./edusat", help="Path to edusat binary")
    parser.add_argument("--output_dir",   default=None,
                        help="Output directory (default: ./results/compare_<timestamp>)")
    parser.add_argument("--timeout",      type=int, default=60, help="Per-solve timeout (s)")
    parser.add_argument("--jobs",         type=int, default=os.cpu_count(),
                        help="Parallel workers (default: cpu count)")
    parser.add_argument("--configs",      default=None,
                        help="Comma-separated config names to run (default: all)")
    parser.add_argument("--analyze_only", action="store_true",
                        help="Skip solving; load existing results and plot")
    parser.add_argument("--no_plot",      action="store_true", help="Skip plotting")
    parser.add_argument("--plot_dir",     default=None,
                        help="Directory for plots (default: <output_dir>/plots)")

    args = parser.parse_args()

    # Select configs
    if args.configs:
        names = {n.strip() for n in args.configs.split(",")}
        configs = [c for c in CONFIGS if c["name"] in names]
        if not configs:
            parser.error(f"No matching configs for: {args.configs}")
    else:
        configs = CONFIGS

    # Output directory
    if args.output_dir is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output_dir = f"./results/compare_{ts}"
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)

    plot_dir = args.plot_dir or str(Path(args.output_dir) / "plots")

    if args.analyze_only:
        print(f"Loading results from: {args.output_dir}")
        results = load_results(args.output_dir, [c["name"] for c in configs])
        if not results:
            print("No results found in output_dir (no stats.json or output.txt).", file=sys.stderr)
            sys.exit(1)
    else:
        if not args.cnf_dir:
            parser.error("--cnf_dir is required unless --analyze_only is set")
        cnf_files = sorted(Path(args.cnf_dir).glob("*.cnf"))
        if not cnf_files:
            print(f"No .cnf files found in {args.cnf_dir}", file=sys.stderr)
            sys.exit(1)

        solver = os.path.abspath(args.solver)
        if not os.path.isfile(solver):
            print(f"Solver not found: {solver}", file=sys.stderr)
            sys.exit(1)

        print(f"Solver:     {solver}")
        print(f"CNF dir:    {args.cnf_dir}  ({len(cnf_files)} instances)")
        print(f"Output dir: {args.output_dir}")
        print(f"Configs:    {', '.join(c['name'] for c in configs)}")
        print()

        results = run_all(cnf_files, configs, solver, args.output_dir,
                          args.timeout, args.jobs)

    print_summary(results, configs)

    if not args.no_plot:
        make_plots(results, configs, plot_dir)


if __name__ == "__main__":
    main()
