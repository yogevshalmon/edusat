echo off
echo ********************* SAT:
(for /f %%f in ('dir /b *yes*.cnf') do C:\Users\Ofer\source\repos\chrono\Debug\chrono.exe %1 %%f | grep  -i "s satisfiable") > tmp_sat
grep -c  "s SATISFIABLE" tmp_sat
echo supposed to be 48
echo ********************* UNSAT:
(for /f %%f in ('dir /b *no*.cnf') do C:\Users\Ofer\source\repos\chrono\Debug\chrono.exe %1 %%f | grep  -i unsatisfiable) > tmp_unsat
grep -c "UNSATISFIABLE" tmp_unsat
echo supposed to be 24
