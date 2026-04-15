You are an autonomous agent to create and update this repo. 
This file specifies your workflow and serves as a map to deeper contents.

# Workflow

1. Read the given prompt, understand your task.
2. Read the relevant files, following the map below.
3. Create a plan under `docs/exec-plans/active`, and wait for user's agreement;
4. Execute the plan. 
5. Update plan's state(`completed` / `failed`)
6. Update all the indexing files;
7. Push the changes to the remote repo with correct and concise descrption.

# Map

```plain-text
DAPT/
- AGENTS.md         # workflow & map for the project
- docs/
    - design-docs/  # design docs for each module
        - index.md  # below are main description for 
                    # each perspective
        - 0_OVERALL_DESIGN.md
        - 1_ARCHITECTURE.md
        - 2_PLAN.md
        - 3_EXECUTION.md
        - 4_MEMORY.md
        - 5_KNOWLEDGE.md
        - 6_EVALUATION.md
    - exec-plans/
        - index.md
        - active/
        - failed
        - completed/
    - references/   # repo-local references and knowledge
        - pentestgpt_v2_tool_skill_layer.md
        - pentest/
            - index.md
            - manifest.json
            - retrieval-contract.md
            - tool-notes/
            - playbooks/
            - exploit-notes/
- imgs/             # images for academic paper
- prompts/          # prompts for each turn
- src/              # source code
    - dapt/
        - executor/ # executor runtime, typed contracts, pentest tools/skills
        - knowledge/ # typed knowledge manifest loader and contracts
- tests/            # automated verification for executor and knowledge layers
```

# Core Principles

1. Check Index/Map, only read files you need instead of reading all the raw files;
2. Everything in repo. No hidden memory, no external source, no hypotheses.
