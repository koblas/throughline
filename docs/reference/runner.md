# The runner

`plugins/pipeline/scripts/runner.py` drives a feature from its approved spec to its retro with no chat session. `/pipeline:run-feature` starts it from a chat session.

## Invocations

| Invocation | Does |
|---|---|
| `runner.py <slug> [flags]` | Runs the feature in the foreground. |
| `runner.py <slug> --detach` | Starts it in the background and returns once the new runner has written its record. |
| `runner.py <slug> --status [--json]` | Prints the status record and exits with the state. |
| `runner.py <slug> --wait [--json]` | Blocks until the runner is no longer running, then prints the record. |
| `runner.py <slug> --stop` | Sends SIGTERM and waits for it. |
| `runner.py --unfinished` | Lists stopped, dead and hung runners. The session-start hook runs it. |

## Flags

| Flag | Default | Does |
|---|---|---|
| `--feature-budget USD` | `feature_budget_usd` in the config | Stops the runner once the feature's runs add up to it. Checked before every call, so parallel reviewers can overshoot by one step. |
| `--run-budget USD` | `4` | Caps one run. |
| `--run-timeout MIN` | `40` | Stops a headless run still going after this long. |
| `--permission-mode MODE` | `acceptEdits` | One of `acceptEdits`, `auto`, `bypassPermissions`, `dontAsk`. `bypassPermissions` drops the allow-list. |
| `--base REF` | none | The ref the feature is diffed against at the first gate, when it has commits. |
| `--exclude PATH…` | none | Out-of-pipeline paths. Remembered. |
| `--dry-run` | off | Prints the first step and stops before running anything. |
| `--claude CLI` | `claude` | The CLI to run. |

## Exit codes

What the runner exits with when it stops:

| Exit | Means |
|---|---|
| `0` | The feature is done. |
| `1` | The runner itself failed. |
| `2` | The conductor refused (a fold or split verdict, a confirming round still failing, no reviewer to re-run), or a reviewer's reply holds a blocking finding the parser could not read. |
| `4` | The plan judge would not accept a plan. |
| `5` | The feature budget is spent. |
| `6` | A run failed, returned nothing or outlived `--run-timeout`; the environment is missing a tool, the sandbox profile or the worktree's own Go module cache; or another runner already holds the feature. |
| `7` | Interrupted by SIGTERM, SIGINT or SIGHUP. |
| `11` | The repo is single-session: nothing runs unattended there. |

`--status` and `--wait` exit with the state:

| Exit | State |
|---|---|
| `0` | Done. |
| `3` | Running. |
| the stop's own code | Stopped. |
| `8` | Dead: the record says running and the runner is gone. |
| `9` | Hung: alive and silent for longer than its longest wait. |
| `10` | Never started. |

## Behavior

- **One runner per feature.** A second start is refused while the first lives.
- **Resumable.** Every finished run is in `.runs/<slug>/RUNS.jsonl`. A step whose agents all finished is recorded; one that was cut short runs again in full.
- **Retries.** An API or network failure is tried again twice, after 30 s and then 120 s, before the runner stops.
- **Stalls.** After two developer runs in a row that tick no plan step, or a reply that opens `BLOCKED:`, the conductor refuses and the runner stops with `2`. The first stop of a scenario on its locked acceptance test goes to a judge, which unlocks only a change that leaves the test's assertions as they are.
- **Status record.** Kept in the git directory as `claude-runner/<slug>.json`, per worktree, never committed: pid, step, spend, last lines and, once stopped, the reason and the resume command. A live runner rewrites its heartbeat every 30 s.
- **Sandbox.** Every headless run uses `.claude/runner-settings.json` with `--setting-sources project`. The user's interactive settings do not shape it.
- **Denied to every run.** Commit, push and opening a PR, whatever `--permission-mode` says.
- **Full gates.** The runner runs each touched surface's `full_gates` at every gate round and files a failure as a BLOCKER. A gate that failed runs again every round until it is seen green.
- **Requests.** A developer reply that opens `RUNNER: <name>` gets that entry of the config's `requests` run, and its run started again.
