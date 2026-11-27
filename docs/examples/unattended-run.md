# An unattended run

A feature built by the runner from an approved spec: the start, the wait, one stop and the resume. The feature is `session-revoke` from [A feature, from request to spec](scoping-a-feature.md). [The runner](../reference/runner.md) lists every flag and exit code.

## From a chat session

The kickoff answer was "unattended", so once the spec is approved and its issues are open, the session runs:

```
/pipeline:run-feature session-revoke
```

The command starts the runner detached, waits in the background and ends its turn. No agent is spawned from the chat session, and it does not poll. It comes back when the runner stops.

## From a shell

The same thing by hand, from the repo's dev shell. `scripts/` is the plugin's `scripts/` directory.

Start it in the background:

```bash
scripts/runner.py session-revoke --detach
```

Ask what it is doing:

```bash
scripts/runner.py session-revoke --status
```

`--status` prints the record and exits with the state: `3` while it runs, `0` when the feature is done.

Block until it is no longer running:

```bash
scripts/runner.py session-revoke --wait
```

## A stop

The runner stops, and says why, where a decision belongs to a person. Here the confirming round still failed after the one fix pass:

```bash
scripts/runner.py session-revoke --wait; echo "exit $?"
```

The exit code is `2`: `next` refused. The record names the reason and the command that resumes. There is no third round, so the choice is the user's:

- Fix the finding outside the pipeline, then resume.
- Accept the round open and go on to scoring and the retro:

```bash
scripts/pipeline.py next session-revoke --accept-open
```

Then start the runner again. Every finished run is in `.runs/session-revoke/RUNS.jsonl`, so a step whose agents all finished is not run twice:

```bash
scripts/runner.py session-revoke --detach
```

## A crash

A runner that was killed leaves a record that still says running. `--status` exits `8` (dead). Check the tree, then start it again; the next brief tells its agent that the previous run was cut off and the tree may hold its edits.

```bash
git status
```

```bash
scripts/runner.py session-revoke --detach
```

A runner that is alive and silent past its longest wait is hung (`9`). Stop it, then treat it as dead:

```bash
scripts/runner.py session-revoke --stop
```

## Done

Exit `0`. The runner's last lines name the gate rounds and their result, the spend, the PR body draft (`.runs/session-revoke/PR.md`), the issue drafts, and any security-sensitive paths the feature changed. It has not committed, pushed or opened a PR: those commands are denied to every run.

List the issue drafts, then file them:

```bash
scripts/pipeline.py file-issues session-revoke
```

```bash
scripts/pipeline.py file-issues session-revoke --yes
```
