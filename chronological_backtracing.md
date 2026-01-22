# Chronological Backtracking Implementation on Non-CB Solvers

## Overview

This document summarizes the algorithms and implementation details for adding chronological backtracking (CB) to traditional non-chronological backtracking (NCB) SAT solvers.

## Background

### Traditional Non-Chronological Backtracking (NCB)
- When a conflict occurs at decision level *d*, analyze the conflict
- Learn a conflict clause
- Backtrack to the assertion level *b* (typically *b < d-1*)
- Continue solving from level *b*

### Chronological Backtracking (CB)
- After learning a clause at level *d*, backtrack chronologically to level *d-1*
- Only backtrack to assertion level *b* if conflict analysis at *d-1* fails
- Preserves the search tree structure better
- Can lead to shorter proofs and better performance

## Key Concepts

### Decision Levels
- **Current Level (d)**: The level where conflict occurred
- **Assertion Level (b)**: The level where learned clause becomes unit
- **Backtrack Level**: Where solver actually backtracks to

### Why CB Can Help
1. Maintains learned clauses that might be useful
2. Preserves variable assignments that don't contribute to conflicts
3. Can avoid redundant search in some cases
4. Often leads to better phase saving behavior

## Explaining core algorithms from paper:

Now we show the implementation of the high-level algorithms CDCL (Algorithm 1), BCP (Algorithm 2) and Backtrack (Algorithm 3) with CB. In fact, we show both the NCB and the CB versions of each function. For CDCL and BCP most of the code is identical, except for the lines marked with either ncb or cb. Consider the high-level CDCL algorithm in Algorithm 1. It operates in a loop that finishes after either all the variables are assigned (SAT) or when an empty clause is derived (UNSAT). Inside the loop, BCP is invoked. BCP returns a falsified conflicting clause if there is a conflict. If there is no conflict, a new decision is taken and pushed to the trail. The first difference between CB and NCB shows up right after a conflict detection. The code between lines 4 – 8 is applied only in the case of CB. If the conflicting clause contains one literal l from the maximal decision level, we let BCP propagating that literal at the second highest decision level in conflicting cls. Otherwise, the solver backtracks to the maximal decision level in the conflicting clause before applying conflict analysis. This is because, as we saw in the example, the conflicting clause may be implied at a decision level earlier than the current level. The conflict analysis function returns the 1UIP variable to be assigned and the conflict clause σ. If σ is empty, the solver returns UNSAT. Assume σ is not empty. The backtrack level bl is calculated differently for NCB and CB. As one might expect, bl comprises the second highest decision level in σ in the case of NCB case and the previous decision level in the case of CB (note that for CB the solver has already backtracked to the maximal decision level in the conflicting clause). Subsequently, the solver backtracks to bl and pushes the 1UIP variable to the trail before continuing to the next iteration of the loop. Consider now the implementation of BCP in Algorithm 2. BCP operates in a loop as long as there exists at least one unvisited literal in the trail ν. For the first unvisited literal l, BCP goes over all the clauses watched by l. Assume a clause β is visited. If β is a unit clause, that is, all β’s literals are falsified except for one unassigned literal k, BCP pushes k to the trail. After storing k’s implication reason in reason(k), BCP calculates and stores k’s implication level level (k). The implication level calculation comprises the only difference between CB and NCB versions of BCP. The current decision level always serves as the implication level for NCB, while the maximal level in β is the implication level for CB. Note that in CB a literal may be implied not at the current decision level. As usual, BCP returns the falsified conflicting clause, if such is discovered. Finally, consider the implementation of Backtrack in Algorithm 3. For the NCB case, given the target decision level bl , Backtrack simply unassigns and pops all the literals from the trail ν, whose decision level is greater than bl . The CB case is different, since literals assigned at different decision levels are interleaved on the trail. When backtracking to decision level bl , Backtrack removes all the literals assigned after bl , but it puts aside all the literals assigned before bl in a queue μ maintaining their relative order. Afterwards, μ’s literals are returned to the trail in the same order.


## Core Algorithm: CB modification CDCL template

ncb: marks the NCB code 
cb: marks the CB code

### Main Solving Loop Modification

```
function CDCL-SOLVE():
    level = 0
    while true:
        conflict_cls = propagate()
        if conflict_cls ≠ NULL: // we hit a conflict
            if conflict_cls contains (only) one literal from max_level then
                backtrack(seconds highest decision level in conflict_cls) // cb
                continue // cb
            else
                backtrack(maximum level in conflict_cls) // cb


            1uip, learnt_cls = analyze(conflict_cls)
            if learnt_cls empty (or any other specific indication of the sovler): // mean we hit a global unsat
                return unsat

            add_clause(learnt_cls)

            // CHOOSE CB or NCB on-th-fly here!!!
            if CB:
                bl = curr_decision_level - 1 //cb
            else: // ncb
                bl = seconds highest decision level in learnt_cls (regular)
            
            backtrack(bl)
            push 1uip
      
        else:
            ... // continue with decision logic
```

### BCP
```
dll: current decsion level

dl : current decision level
ν: the trail, stack of decisions and implications
ncb: marks the NCB code 
cb: marks the CB code BCP()  
1: while ν contains at least one unvisited literal do 
2:      l := first literal in ν, unvisited by BCP 
3:      wcls := clauses watched by l 
4:      for β ∈ wcls do  
5:          if β is unit then 
6:              k := the unassigned literal of β 
7:              Push k to the end of ν 
8:              reason(k) := β 
9:              level (k) := dl // ncb
10:             level (k) := max level in β //cb
11:         else 
12:             if β is falsified then  
13: return β  return null
```

### BACKTRACK

dl : current decision level 
ν: the trail, stack of decisions and implications 
level index (bl + 1): the index in ν of bl + 1’s decision literal
Backtrack(bl): //NCB version
Assume: bl < dl 
1: while ν.size() ≥ level index (bl + 1) do 
2:      Unassign ν.back() 
3:      Pop from ν

Backtrack(bl) : //CB Version
Assume: bl < dl 
1: Create an empty queue μ 
2: while ν.size() ≥ level index (bl + 1) do 
3:      if level (ν.back()) ≤ bl then 
4:          Enqueue ν.back() to μ 
5:      else  
6:          Unassign ν.back()  
7:      Pop from ν 
8: while μ is not empty do 
9:      Push μ.first() to t
10:     Dequeue from μ

## Combining CB and NCB

Our algorithm can easily be modified to heuristically choose whether to use CB or NCB for any given conflict. The decision can be made, for each conflict, in the main function in (### Main Solving Loop Modification) by setting the backtrack level to either the second highest decision level in σ for NCB or the previous decision level for CB.
In our implementation, NCB is always applied before C conflicts are recorded since the beginning of the solving process, where C is a user-given threshold. After C conflicts, we apply CB whenever the difference between the CB backtrack level (that is, the previous decision level) and the NCB backtrack level (that is, the second highest decision level in σ) is higher than a user-given threshold T. We introduced the option of delaying CB for C first conflicts, since backtracking chronologically makes sense only after the solver had some time to aggregate variable scores, which are quite random in the beginning. When the scores are random or close to random, the solver is less likely to proceed with the same decisions after NCB.

## Important Notes

### Correctness Considerations
1. CB maintains soundness and completeness of CDCL
2. Learned clauses are still valid regardless of backtrack strategy
3. The asserting property of learned clauses is preserved

### Performance Considerations
1. CB can increase or decrease solving time depending on instance
2. Works particularly well on structured instances
3. May require tuning restart strategies
4. Interaction with clause deletion policies needs attention

### Implementation Tips
1. Minimal changes to existing NCB solver (main change in backtrack decision)
2. No changes needed to: propagation, conflict analysis, clause learning
3. Phase saving becomes more important with CB
4. Consider hybrid approaches for robustness

### When CB Helps Most
- Structured industrial instances
- Instances with many learned clauses
- When phase saving is effective
- Problems with local structure

### When CB Might Not Help
- Random instances
- Very hard UNSAT instances
- Instances requiring large backjumps
- When assertion level is far from current level