# Hooks

The plugin's hooks, from `plugins/pipeline/hooks/hooks.json`. Claude Code runs them in every session where the plugin is enabled.

| Event | Matcher | Command | Timeout |
|---|---|---|---|
| `SessionStart` | all | `session-context.py` | 10 s |
| `SessionStart` | all | `runner.py --unfinished` | 10 s |
| `PreToolUse` | `Edit\|Write\|MultiEdit` | `check.py lock` | 10 s |
| `PostToolUse` | `Edit\|Write\|MultiEdit` | `check.py hook` | 150 s |

## `SessionStart`

`session-context.py` prints the workflow rules into the session: the lanes, the two pauses, the testing rule and the spawn authority. In a single-session repo it leaves out the pipeline-only rules and prints a short note in their place. In a repo without `.claude/pipeline.json` it prints one line saying the pipeline is not set up there.

`runner.py --unfinished` lists stopped, dead and hung runners, says when a runner is going, and says when a feature is specified, unfinished and nothing is running it.

## `PreToolUse`: the lock

`check.py lock` refuses an edit (exit `2`) that changes the text of a scenario's acceptance test while a build run is pending for that scenario. It also refuses edits to the feature's `PIPELINE.json` and to the plan's `Acceptance test:` line. Other tests in the same file are untouched. A fix pass is not a build run. `pipeline.py unlock` lifts it.

It sees `Edit`, `Write` and `MultiEdit` only, not a shell command or a helper the test calls. It fails open: a test it cannot find, or anything it cannot read, lets the edit through.

## `PostToolUse`: the per-edit check

`check.py hook` formats the edited file in place with the `format` steps of the surface that covers it. It is silent on success. On failure it exits `2` with at most 50 lines on stderr, which Claude Code feeds back to the agent that made the edit. A missing tool is reported the same way, once per session. A config that does not load is reported with the key at fault, and the edit is not formatted or vetted.
