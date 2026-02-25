# EduSAT - Claude Session Notes

## Project Overview
Educational SAT solver (DPLL + CDCL) written in C++. Technion course project for "Algorithms in Logic".
Active research: implementing and benchmarking **Chronological Backtracking (CB)** vs Non-Chronological Backtracking (NCB).
Reference paper: `papers/MoehleBiere-SAT19.pdf` ("Backing Backtracking", Moehle & Biere SAT'19).

## Key Files
- [edusat.cpp](../edusat.cpp) — main solver (~842 lines)
- [edusat.h](../edusat.h) — class definitions, data structures, enums
- [options.h](../options.h) / [options.cpp](../options.cpp) — CLI option parsing
- [Makefile](../Makefile) — build config

## Build
```bash
make          # produces ./edusat
make clean    # clean build artifacts
```
Compiler: `g++ -Wall -O2 -std=c++11`

## Usage
```bash
./edusat <cnf_file> [-v <0-2>] [-timeout <secs>] [-valdh <0|1>] [-cb <0|1>] [-cbh <0|1|2>] [-cbt <int>]
```
- `-cb 1` enables Chronological Backtracking
- `-cbh 0` always-CB (default when `-cb 1`): backtrack to `c-1`
- `-cbh 1` limited-CB: backtrack to `c-1` if gap `c-j > T`, else fall back to NCB (`j`); threshold set with `-cbt T` (default 100)
- `-cbh 2` reusetrail-CB: backtrack to `δ(k)-1` where `k` = highest-VSIDS var in trail levels `(j, c]`
- `-valdh 0` = phase-saving (default), `-valdh 1` = litscore
- Output: prints `s SAT` or `s UNSAT`; on SAT writes `assignment.txt`

## Solver Architecture
### Key Algorithms
- BCP with 2-watched literals
- MINISAT-style VSIDS variable activity
- 1UIP conflict analysis + clause learning
- Restart with dynamic thresholds (100–1000 conflicts)

### Backtracking Modes

Variables: `c` = conflict level (`dl`), `j` = asserting level from `analyze()`, `T` = threshold

| Mode | CLI | Backtrack target `b` | Notes |
|------|-----|----------------------|-------|
| NCB | `-cb 0` | `j` | standard 1UIP |
| Always-CB | `-cb 1 -cbh 0` | `c - 1` | always one step back |
| Limited-CB | `-cb 1 -cbh 1` | `c-1` if `c-j > T`, else `j` | NCB fallback for small gaps |
| Reusetrail-CB | `-cb 1 -cbh 2` | `δ(k) - 1` | `k` = highest-VSIDS var in trail `(j,c]` |

Core functions:
- `backtrack_ncb(j)` — clears entire trail above level `j`
- `backtrack_cb(b, j)` — preserves trail entries with `dlevel ≤ b`, removes rest
- `backtrack_cb_preserve(k)` — pre-analysis step: backs up to level `k` for 1UIP
- `determine_backtrack_level(j)` — selects `b` based on active `-cbh` heuristic
- `reusetrail_backtrack_level(j)` — trail scan for reusetrail-CB target
- `recompute_separators()` — rebuilds trail separators after CB

### Literal Encoding (internal)
- Var `i` (1-indexed) → positive lit `2i`, negative lit `2i-1`
- `v2l(i)` raw → internal, `l2v(l)` internal → var, `l2rl(l)` → signed CNF lit

### Key Data Structures (Solver class)
```cpp
vector<Clause>  cnf;          // clause database
trail_t         trail;        // assignment stack
vector<int>     separators;   // decision level boundaries in trail
vector<int>     decision_lits;
vector<vector<int>> watches;  // lit → clause indices
vector<VarState> state;       // current assignments
vector<int>     antecedent;   // var → reason clause
vector<int>     dlevel;       // var → decision level
// Stats:
int  num_conflicts;           // every conflict (incl. 1-lit-skip, ≥ num_learned)
int  num_propagations;        // BCP queue dequeues
int  num_cb_backtracks;       // conflicts resolved via CB path
int  num_ncb_backtracks;      // conflicts resolved via NCB path
long long total_backtrack_distance; // sum of (c - actual_b) per conflict
```

## Branch Structure
- `cb` (current) — CB implementation, fuzzing harness
- `master` — stable NCB baseline

## Verification / Testing

### Quick Validation (AIM benchmark suite, ~seconds)
```bash
bash test/easy_cnf_instances/check.sh ./edusat
# Reports: cb=0 : SAT ok/total | UNSAT ok/total
#          cb=1 : SAT ok/total | UNSAT ok/total
```
Tests 40 AIM instances in both NCB (cb=0) and CB (cb=1) modes.
Instance naming: `aim-*yes*.cnf` = SAT, `aim-*no*.cnf` = UNSAT.

### Full Differential / Fuzzing Validation (run in background — takes a long time)
Compares CB output vs baseline NCB output on random CNF instances:
```bash
python ./scripts/run_fuzz_and_solve.py \
  --solver_path ./edusat --solver-args "-cb 1" \
  --solver2 ./edusat \
  --max 1000 --timeout 300 &
```
- Uses `libs/cnffuzzdd2013/cnfuzz` to generate random DIMACS CNFs
- Saves any disagreeing instances for debugging
- `--max` = number of fuzz iterations, `--timeout` = per-solve timeout (seconds)

## Development Notes
- CB always-CB (`-cbh 0`) is implemented and tested
- Limited-CB (`-cbh 1`) and reusetrail-CB (`-cbh 2`) planned — see `.claude/plans/vectorized-snacking-beaver.md` for full implementation plan
- CB optimization: if conflict clause has exactly 1 lit at max level and rest strictly lower, skip 1UIP analysis and backtrack to second-highest level directly (counts as `num_cb_backtracks`, does not increment `num_learned`)
- `num_conflicts` ≥ `num_learned` when 1-lit-skip fires; `Avg-BT-distance` is the primary comparison metric (NCB ≈ large, always-CB ≈ 1)
- `assignment.txt` is written on SAT — validated against all clauses before output
- `Assert()` macro wraps assertions with file/line; `Abort()` for fatal errors
