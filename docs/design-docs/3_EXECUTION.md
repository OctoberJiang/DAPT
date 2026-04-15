# Execution

## Definition

Execution is the process where the Executor receives commands from the Planner, selects the corresponding tools, passes correct parameters and stores the output in the repo. If the execution fails, the Executor is able to do execution-level retry if the problem is caused by common problems(network, lack of parameter, etc.), while it cannot make planning-level modification.

## Input

Planner's request of invoking target tools, along with parameters.

## Output

The execution(interaction with the environment)'s raw output, which should be stored locally.

## Sub-Plans 

> Naming Criteria: `3_X_<plan-name>`

- `3_1_contracts-and-layout`: completed executor data model and storage conventions.
- `3_2_executor-runtime`: completed executor dispatch, retry, and persistence runtime.
- `3_3_reference-aligned-proofs`: completed proof tool/skill implementations and executor tests.
- `3_4_cli-pentest-tool-catalog`: completed first real pentest tool adapter catalog.
- `3_5_recon-web-skills`: completed reusable reconnaissance and web-exploitation skill library.
- `3_6_credential-ad-privesc-catalog`: completed credential, Active Directory, and privilege-escalation tool/skill catalog.
