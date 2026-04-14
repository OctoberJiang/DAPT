# Execution

## Definition

Execution is the process where the Executor receives commands from the Planner, selects the corresponding tools, passes correct parameters and stores the output in the repo. If the execution fails, the Executor is able to do execution-level retry if the problem is caused by common problems(network, lack of parameter, etc.), while it cannot make planning-level modification.

## Input

Planner's request of invoking target tools, along with parameters.

## Output

The execution(interaction with the environment)'s raw output, which should be stored locally.

## Sub-Plans 

> Naming Criteria: `3_X_<plan-name>`

