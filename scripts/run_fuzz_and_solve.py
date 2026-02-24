import argparse
import subprocess
import tempfile
import os
import shutil

def run_once(args, iteration=None):
    # Create a temporary file for the CNF
    with tempfile.NamedTemporaryFile(suffix=".cnf", delete=False) as tmp_cnf:
        cnf_path = tmp_cnf.name
    try:
        # Run the fuzzer to generate a CNF file
        fuzz_cmd = f'{args.fuzzer} {args.fuzz_args}'.strip().split()
        with open(cnf_path, "w") as out:
            subprocess.run(fuzz_cmd, stdout=out, check=True)
        if iteration is not None:
            print(f"\n--- Iteration {iteration+1} ---")
        print(f"Fuzzed CNF written to {cnf_path}")

        # Helper to extract SAT/UNSAT from solver output
        def get_sat_status(output):
            for line in output.splitlines():
                l = line.strip().upper()
                # Remove log prefixes like '[...]'
                if l.startswith('['):
                    l = l.split(']')[-1].strip()
                # look for lines that start with 's '
                if l.startswith('S '):
                    l = l[2:].strip()
                else:
                    continue
                if 'UNSAT' in l:
                    return "UNSAT"
                if 'SAT' in l:
                    return "SAT"
            return "UNKNOWN"

        # Run the first solver
        solver_cmd = [args.solver_path]
        if args.solver_args:
            solver_cmd.extend(args.solver_args.split())
        solver_cmd.append(cnf_path)
        print(f"Running solver: {' '.join(solver_cmd)}")
        result1 = subprocess.run(solver_cmd, capture_output=True, text=True, timeout=args.timeout)
        print("Solver 1 output:")
        print(result1.stdout)
        if result1.stderr:
            print("Solver 1 errors:")
            print(result1.stderr)
        status1 = get_sat_status(result1.stdout)

        # Run the second solver if provided
        status2 = None
        if args.solver2:
            solver2_cmd = [args.solver2, cnf_path]
            print(f"Running solver 2: {' '.join(solver2_cmd)}")
            result2 = subprocess.run(solver2_cmd, capture_output=True, text=True, timeout=args.timeout)
            print("Solver 2 output:")
            print(result2.stdout)
            if result2.stderr:
                print("Solver 2 errors:")
                print(result2.stderr)
            status2 = get_sat_status(result2.stdout)

        # Compare results if both solvers were run
        keep_cnf = False
        if status2 is not None:
            print(f"\nComparison: Solver 1 = {status1}, Solver 2 = {status2}")
            if status1 == status2:
                print("Both solvers agree. Deleting temporary CNF file.")
            else:
                print("Disagreement: Solvers returned different results!")
                print(f"CNF file kept at: {cnf_path}")
                keep_cnf = True
        else:
            # Only one solver, delete CNF
            print("Only one solver used. Deleting temporary CNF file.")

        if not keep_cnf:
            os.remove(cnf_path)
        return not keep_cnf  # True if OK, False if disagreement
    except Exception as e:
        print(f"Error occurred: {e}\nCNF file kept at: {cnf_path}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Run SAT solver(s) on a fuzzed CNF instance and compare results.")
    parser.add_argument("--solver_path", help="Path to the primary SAT solver executable")
    parser.add_argument("--solver2", help="Path to a second SAT solver for comparison")
    parser.add_argument("--solver-args", default="", help="Additional command line arguments for the primary solver")
    parser.add_argument("--fuzzer", default="libs/cnffuzzdd2013/cnfuzz", help="Path to the cnfuzz executable")
    parser.add_argument("--fuzz-args", default="", help="Arguments to pass to the fuzzer")
    parser.add_argument("--max", type=int, default=1, help="Maximum number of fuzz/solve iterations (default: 1)")
    parser.add_argument("--timeout", type=float, default=30, help="Timeout in seconds for each solver run (default: 30)")
    args = parser.parse_args()

    for i in range(args.max):
        ok = run_once(args, iteration=i)
        if not ok:
            print(f"Stopped after {i+1} iteration(s) due to disagreement or error.")
            break
    else:
        print(f"Completed {args.max} iteration(s) with no disagreements.")

if __name__ == "__main__":
    main()
