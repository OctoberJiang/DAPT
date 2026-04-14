# Plan

Tree-based. 

- Root: target
- Branch: attack path
- Node: a stateful reasoning unit
    - Observation
    - Hypothesis
    - Action
    - Effect

The Planner makes hypotheses given the observations, making attack decisions and delegate the Executor to execute that. After executing, the Perceptor summarizes and feedbacks to the Planner, the path is pruned/extended.

## Key Insight 01: Attack Decision Making based on Attack Dependency Graph

The DAPT maintains an Attack Dependency Graph. 

- What: It records the candidates, their preceding conditions, consequentionl effects and how they unlock the following actions.
-
- How to Update
    - Who: planner
    - When: It updates when a new event occurs: new observation, execution outcome, new candidate weaknesses, etc. 
- Function: When the planner faces multiple candidates, it should make choices based on the
    -

## Sub-Plans

> Naming Criteria: `2_X_<plan-name>`
