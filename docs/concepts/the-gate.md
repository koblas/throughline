# The gate

The gate is the review a feature gets after every scenario is built and before the PR. It is the one step the pipeline never skips in the Full and Light lanes.

## Who reviews

The gate asks two questions per surface the diff touches: is the production code correct, and do the tests prove it. Each surface in `.claude/pipeline.json` names one reviewer agent for each question. Only those run at the gate.

The reviewers are the repo's choice. The plugin ships a test reviewer for Go and no correctness reviewer: correctness depends on the repo's own rules, so every surface names an agent under the repo's `.claude/agents/`. Any other reviewer agent in the repo runs ad hoc, through `/pipeline:run-reviewers <paths>`.

## What a round contains

A gate round is more than the reviewers:

- the diff of the feature, written to a file each reviewer starts from;
- the two reviewers of each touched surface, run in parallel;
- a mutation sample over the changed lines, with every survivor handed to the test reviewer;
- `spec-check --run`, which runs each scenario's named acceptance test alone;
- on a surface with a `ui`, one screenshot per screen state, which the correctness reviewer holds to the product spec's Screen states table;
- under the unattended runner, each touched surface's full gates.

Reviewers read the delta, not the tree. They list every finding at every severity in the round they find it, and say what they could not check.

## Severity

One contract for every reviewer:

| Severity | Means | Blocks |
|---|---|---|
| BLOCKER | Data loss, cross-request leakage, a reachable panic, a silently wrong result, an untested change, a change under the spec's excluded paths | Yes |
| MAJOR | A defect with a constructible failure | Yes |
| MINOR | A smell with no constructible failure | No |
| NIT | A preference | No |

A finding with no concrete failure is downgraded to MINOR.

## One fix pass

BLOCKERs and MAJORs get one fix pass by the `developer` in fix mode. The round after it confirms that fix and nothing else: only the reviewers that blocked, plus any whose concern the fix touched, run again. A fix that touches a security-sensitive file is always re-read by its correctness reviewer.

There is no third round. A confirming round that still fails stops, and its findings go to the user: fix them outside the pipeline, or accept the round open.

A round with only MINORs and NITs is **PASS WITH FOLLOW-UPS**, which is done. No fix pass follows it. Each MINOR and NIT becomes an issue draft. The drafts are kept in the git common directory, outside every worktree, so removing a worktree never loses them, and they reach GitHub only on the user's yes.

## The refuter

A wrong MAJOR costs a fix pass. The `refuter` agent reads the code and tests each MAJOR names and answers STANDS or REFUTED with evidence. It raises no findings of its own. It is off by default.

## What the gate does not do

The gate does not run a security review. When a round changes a path matching the repo's `security_paths`, the pipeline says so on the round's metrics row and again when the feature finishes. Running a review is the user's call and never blocks the gate.

The race detector is not a reviewer's job either: it runs once per feature at the first gate round, scoped to the packages the feature changed. A race is a BLOCKER.

The long form is the plugin's [review brief](https://github.com/koblas/throughline/blob/main/plugins/pipeline/briefs/review.md) and [orchestration brief](https://github.com/koblas/throughline/blob/main/plugins/pipeline/briefs/orchestration.md).
