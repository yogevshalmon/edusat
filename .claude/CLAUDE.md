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
./edusat <cnf_file> [-v <0-2>] [-timeout <secs>] [-valdh <0|1>] [-cb <0|1>]
```
- `-cb 1` enables Chronological Backtracking
- `-valdh 0` = phase-saving (default), `-valdh 1` = litscore
- Output: prints `s SAT` or `s UNSAT`; on SAT writes `assignment.txt`

## Solver Architecture
### Key Algorithms
- BCP with 2-watched literals
- MINISAT-style VSIDS variable activity
- 1UIP conflict analysis + clause learning
- Restart with dynamic thresholds (100–1000 conflicts)

### Backtracking Modes
- `backtrack_ncb()` — standard: clears trail above backtrack level
- `backtrack_cb()` — chronological: selectively removes only conflicting assignments, preserves others
- `backtrack_cb_preserve()` — pre-analysis backtrack for CB path
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
- Current CB status: implemented, needs optimization and testing (commit `7d913eb`)
- CB optimization: if conflict clause has exactly 1 lit at max level and rest strictly lower, skip 1UIP analysis and backtrack to second-highest level directly
- `assignment.txt` is written on SAT — validated against all clauses before output
- `Assert()` macro wraps assertions with file/line; `Abort()` for fatal errors
