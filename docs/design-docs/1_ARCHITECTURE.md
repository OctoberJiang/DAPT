`DAPT` means Dependency-aware Auto Pentest Project

# Architecture

Multi-agent, respectively Planner, Executor, Perceptor.

- Planner
    - Job: the orchstrator of the whole system, responsible for proposing hypotheses, selecting attack path and adjusting dynamically based on the feedbacks.
    - DO NOT: directly uses tools / interacts with the environment

- Executor
    - Job: receives command from the planner, invokes corresponding tools with correct parameters, revises if the tool fails. After interacting with the environment, it passes raw output to the Perceptor.
    - DO NOT: makes attack decisions; summarize the output in advance 

- Perceptor
    - Job: receives raw output from the executor, optionally summarizes/extracts key information in a structured way, feeds back to the Planner and writes to the memory.
    - DO NOT: makes attack decisions; modify the existing memory content

## Sub-Plans

> Naming Criteria: `1_X_<plan-name>`

- `1_1_perceptor-contracts-and-artifacts`: completed Perceptor package layout, typed contracts, and repo-local artifact conventions.
- `1_2_reference-aligned-parsing-runtime`: completed PentestGPT-reference-aligned parsing runtime for executor raw outputs.
- `1_3_planner-feedback-and-memory-staging`: completed planner feedback envelope and append-only memory staging flow.
- `1_4_perceptor-reference-aligned-proofs`: completed tests and proof fixtures that lock the Perceptor to the design and reference behavior.
