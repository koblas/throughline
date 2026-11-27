# Brief: feature metrics

_Paths: bare `scripts/`, `briefs/`, `agents/`, `commands/` are in the pipeline plugin, `.claude/…` are the repo's (`briefs/core.md`)._

Orchestrator only — no agent reads this or the ledger it describes.

## Run tags

The **first line of every agent prompt** is a tag. `scripts/pipeline.py next` prints it for
every prompt from the first plan to the retro; for a prompt the orchestrator writes itself
(scoping), `scripts/pipeline.py tag <kind> <slug> [unit]` prints it and rejects a word that
is not a kind:

```
run: <kind> unit: <unit> feature: <feature-slug> [size: small] [agent: <name>]
```

| Kind | Agent | Unit |
| --- | --- | --- |
| `scope` | triage, product-vision (the product-spec ruling), the sizing architect | `feature` |
| `plan` | architect | `SCENARIO-NN` |
| `build` | developer, each bounded run | `SCENARIO-NN` |
| `checkpoint` | step-5a: the touched surfaces' test reviewers | `SCENARIO-NN` |
| `checkpoint-fix` | developer fixing checkpoint findings | `SCENARIO-NN` |
| `review` | every reviewer in a gate round | `REVIEW-NN` |
| `gate-fix` | developer fixing a gate round | `REVIEW-NN` it fixes |
| `fix` | shorthand: booked as `checkpoint-fix` when the unit is exactly `SCENARIO-NN`, else `gate-fix` | bare `SCENARIO-NN` or `REVIEW-NN` |
| `final` | pipeline-reviewer retro | `feature` |
| `refute` | `refuter`, once per gate round that has reviewer MAJORs, when `REFUTE_MAJORS` is on (off since 2026-10-10) | `REVIEW-NN` |
| `judge` | a single-purpose call `scripts/runner.py` makes in place of an orchestrator's judgement (and, in runs before 2026-10-06, its start-up preflight) | the scenario or `REVIEW-NN` it rules on; `feature` for an old preflight |

`agent: <name>` is added by `scripts/runner.py` to the runs it starts headless: such a
transcript is a top-level session with no agent metadata.

A kind is a row of this table, never an agent name (`developer`, `architect`): the script
books an unknown kind as `other`. `scripts/pipeline.py` prints the tag line for every
checkpoint and review prompt. `size: small` marks every run of a small scenario. `scripts/feature-metrics.py` reads
only this line to attribute a run; prose is never parsed for it once a feature is tagged. A
completed feature has **zero** runs of kind `other` or with no unit — the script prints the
count.

## Feature metrics

`.runs/<feature-slug>/METRICS.md` is the feature's cost ledger (gitignored run output; the retro
copies it into the committed retro under `## Metrics`). **No agent reads
it** — it exists so a person can judge a pipeline change against earlier features. The
scenario and gate rows are appended by `scripts/pipeline.py next`; nobody rewrites a row.

```markdown
| Scenario | Size | Plan size | Cadence | Dev runs | Checkpoint mutants (killed/survived/invalid) | Checkpoint findings (B/M/m/n) | Checkpoint fix pass |
| SCENARIO-01 | normal | 4 batches, 1 pkg | code-first | 3 | 7/1/0 | 0/1/2/0 | yes |

<Checkpoint mutants lists the Go sample, then the frontend one, when a scenario has both:
`7/1/0; 5/0/0`. While the checkpoint is off (`pipeline.py` `CHECKPOINT`), the findings cell
reads `off` and the scenario is left out of `checkpoint_fix_pct`.>

## Final gate
| Round | Reviewers run | Findings (B/M/m/n) | Mutants (killed/survived/invalid, secs) | Verdict |
| --- | --- | --- | --- | --- |
| 1 | arch, correctness, test; 3 security-sensitive paths (hunt is manual) | 1/2/4/1 | 16/3/1, 210s | FAIL |
| 2 | correctness, test | 0/0/1/0 | n/a | PASS WITH FOLLOW-UPS |

<"Reviewers run" also notes how many security-sensitive paths the round changed. The
pipeline does not run `/security-hunt`; a hunt the user runs is tagged
`run: review unit: adhoc feature: security-hunt` and is not part of this ledger.>

## Tokens
<output of `scripts/feature-metrics.py <feature-slug>`, pasted once at the end: weighted
tokens (model-blind, the unit of every baseline), dollars at each run's own model price, and
agent time. An `UNPRICED MODELS` line means a model needs a row in the script's `PRICES`>

## Escaped defects
| Found | Defect | Where | Link |
| 2026-10-14 | refresh accepted a revoked session | `go/services/core/authn/refresh.go:88` | PR / issue |
```

**Escaped defects** are defects in the feature's code found after it merged, within 30 days.
Whoever finds one appends a row under the heading — earlier rows are never edited. A feature
with no rows at 30 days had none; write `none at 30 days` once so an empty table is not
mistaken for one nobody checked.

## Judging a pipeline change

`.claude/ADOPTION-efficiency.md` holds the baseline and the pass thresholds a pipeline change
is judged against. One feature is a signal, not proof.
