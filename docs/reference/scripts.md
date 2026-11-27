# Scripts

The programs in `plugins/pipeline/scripts/`. Python 3.12 or later, standard library only. Each reads the repo it runs in through `.claude/pipeline.json`.

## `pipeline.py`

The conductor and its helpers. Subcommands that write to GitHub list what they would do and act only with `--yes`.

| Subcommand | Does |
|---|---|
| `next <slug>` | Records the last step, then prints the next one: `## Spawn`, `## Judge`, `## Run`, `REFUSED` or `DONE`. |
| `record <slug>` | Records the last step only. |
| `gate <slug> --round NN` | Runs a gate round's mechanical step alone, for a gate outside the conductor. |
| `checkpoint <slug> SCENARIO-NN --pre TREE` | Runs the per-scenario checkpoint, which is off by default. |
| `plan-check <slug> SCENARIO-NN` | Reports what is mechanically wrong with a plan. |
| `unlock <slug> SCENARIO-NN` | Lets a build run edit the scenario's acceptance test. |
| `fold <slug> SCENARIO-NN SCENARIO-MM` | Records that one scenario is delivered by another's plan. |
| `evaluate [<slug>]` | Scores a feature's pass conditions so far. `--draft` prints the default conditions and the metrics they may name. |
| `tag <kind> <slug> [unit]` | Prints a run tag, the first line of an agent prompt. |
| `snap` | Prints the working tree's tree id. |
| `claim [N]` | Lists the open, unassigned, unblocked issues; with `N`, assigns it. `--lane` also labels its lane. |
| `open-issues <slug>` | Lists the spec's feature issue and scenario sub-issues; with `--yes`, creates them. |
| `file-issues <slug>` | Lists a feature's issue drafts; with `--yes`, creates them. `--drop TITLE` removes one. |
| `post-review <slug> --pr N` | Shows a gate round's findings as one PR review; with `--yes`, posts it. |
| `debt <slug> <title>` | Drafts an issue for a debt found while building and not fixed. `--close HOW` removes the draft when a build pays it off. |
| `batch <slug>` | The Direct lane: writes a checklist with `--units` or `--from-file`, ticks a unit with `--done` and `--tests`, drafts an issue with `--found`. |
| `retro <slug>` | Prints the retro brief; with `--reply FILE`, writes the retro. |

### Flags of `next`

| Flag | Does |
|---|---|
| `--plan-ok` | The current scenario's plan passed the deviation scan. |
| `--only A,B` | Re-gate: the reviewers to re-run. `none` re-runs the checks alone. |
| `--accept-open` | The user accepts a gate round that failed after the one fix pass. |
| `--base REF` | The ref the feature is diffed against at the first gate. Default `HEAD`; remembered. |
| `--exclude PATH…` | Out-of-pipeline paths. Remembered. |
| `--ran RESULT` | The result of a command run for the developer, for its next brief. |
| `--finding LINE` | A finding from outside the reviewers, in the shared format. Repeatable. |
| `--note TEXT` | What happened outside the reviewers, for the round's metrics row. |
| `--drop-pending` | Forgets the step that was printed and prints it again. |
| `--cut-off` | The last run was cut off before it reported. |
| `--env-note TEXT` | What this environment cannot do, repeated in every plan, build and fix brief. Remembered; cleared with an empty string. |
| `--adapter-ok` | A person read this feature's change to a language adapter. |
| `--reply AGENT=FILE` | An agent's reply in a file, instead of the session transcript. |
| `--json` | Also prints the action as JSON. |

## `runner.py`

Drives a feature from its approved spec to its retro with no chat session. [The runner](runner.md) lists its flags and exit codes.

## `check.py`

Mechanical checks outside the agent loop. Passing output is suppressed.

| Mode | Does |
|---|---|
| `lock` | The `PreToolUse` hook. Refuses an edit that changes a locked acceptance test, the feature's `PIPELINE.json` or the plan's `Acceptance test:` line. Fails open: a test it cannot find lets the edit through. |
| `hook` | The `PostToolUse` hook. Formats the edited file with its surface's `format` steps. On failure exits `2` with at most 50 lines, which Claude Code feeds back to the agent. A missing tool is reported once per session. |
| `phase` | Runs a surface's checks at a phase boundary: `--go <packages>`, `--ts <workspace>`, or `--surface <name>`. Build, lint, absence-only tests, tests, diff coverage, then the surface's own `phase` steps. |

## `spec-check.py`

Checks a feature spec, `docs/specs/<slug>.md`. Exit status is non-zero if any check fails.

| Invocation | Checks |
|---|---|
| `spec-check.py <slug>` | The four-section format; one `Action` and one `happy` case per scenario; each built scenario's named acceptance test exists, matches its plan, and every case id appears in the plan. |
| `--approval` | Also every cited path, line and symbol; every `error` case's outcome; copy coverage against the product spec. On success writes the `**Approved**:` line. |
| `--run` | Also runs each named acceptance test on its own. |

## The others

| Script | Does |
|---|---|
| `session-context.py` | Prints the workflow rules into every session at start. |
| `new-repo.py` | Writes the files, labels and GitHub settings of `/pipeline:new-repo`. |
| `diff-coverage.py` | Checks every Go block the diff adds or changes is executed by a test. |
| `mutation-sample.py` | Mutates a sample of the feature's changed lines and lists the survivors. |
| `absence-only.py` | Lists new or changed tests that assert only that something did not happen. |
| `race-gate.py` | The feature's single `go test -race` pass, at the first gate round. |
| `not-built.py` | Checks every requirement the product spec marks unbuilt has an open issue. |
| `feature-metrics.py` | The token ledger of one feature: every agent run, plus the orchestrator. |
| `retro-stats.py` | Counts how often each class of escaped defect has recurred across retros. |
| `pipeline_config.py` | Loads and validates `.claude/pipeline.json`. A module, not a command. |
| `adapters.py` | The language adapter protocol. A module, not a command. |
