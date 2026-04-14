`DAPT` means Dependency-aware Auto Pentest Project. 

# Features

- Multi-Agent Architecture: Planner, Executor, Perceptor
- Fully autonomous: the user only needs to specify the target url;
- Attack Dependency-Aware Candidate Selection: human expert-like strategy to choose the attack path

# Workflow

1. Input: User provides the target url;
2. In each turn:
    1. The Planner obtains information/observations and constructus both the search tree and the attack dependency graph. 
    2. The planner chooses a node using attack dependency-aware strategy, delegates the Executor to extend an action node;
    3. The Perceptor summarizes the output from Executor and feeds back to the Planner.
3. Output: the complete Exp and the report.
