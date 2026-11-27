# Files the pipeline reads and writes

Where each artifact lives in a repo that runs the pipeline.

## Committed

| Path | Holds | Written by |
|---|---|---|
| `.claude/pipeline.json` | The repo's surfaces, gates and budgets. | The maintainer, or `/pipeline:new-repo` |
| `.claude/runner-settings.json` | The unattended runner's sandbox and permission profile. | The maintainer |
| `.claude/briefs/repo.md` | What every pipeline agent needs to know about this repo. | The maintainer |
| `.claude/briefs/*.md` | The repo's other briefs, handed out by the config's `briefs` map. | The maintainer |
| `.claude/agents/` | The repo's own agents, including its reviewers. | The maintainer, or `/pipeline:new-reviewer` |
| `docs/product/<area>.md` | The product spec: rules, surface names, codes, copy, screen states, decisions. | `product-vision` |
| `docs/specs/<slug>.md` | A feature spec. | The scoping procedure |
| `docs/specs/<slug>.retro.md` | A feature's retro, with its metrics. | `pipeline-reviewer` |
| `docs/process-reviews.md` | The decision on each rule candidate, at each process review. | The user |

## Run output, gitignored

Everything under `.runs/<slug>/`:

| Path | Holds |
|---|---|
| `triage.md` | The triage brief. Posted on the feature issue when the issues open. |
| `PIPELINE.json` | The conductor's cursor. |
| `SCENARIO-NN.md` | A scenario's plan: its checklist and ticks. |
| `STATE.md` | Inherited context, rewritten by the developer at the end of each scenario. |
| `REVIEW-NN.md` | A gate round's findings and verdict. |
| `METRICS.md` | The feature's cost ledger. Copied into the retro. |
| `RUNS.jsonl` | Every finished run of the unattended runner. |
| `PR.md` | The PR body draft, with a `Closes #N` for each built scenario. |
| `BATCH.md` | A Direct-lane batch's checklist. |
| `screens/` | The screenshots of each screen state, for a surface with a `ui`. |

## Outside the worktree

| Path | Holds |
|---|---|
| `<git-common-dir>/pipeline/<slug>/ISSUES.md` | The feature's issue drafts. Removing a worktree never loses them. |
| `<git-dir>/claude-runner/<slug>.json` | The runner's status record, per worktree. Never committed. |
