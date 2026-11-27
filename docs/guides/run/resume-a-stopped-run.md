# How to resume a stopped run

The runner stops where a decision belongs to a person. Its status record holds the reason and the command that resumes.

## 1. Read the state

```bash
scripts/runner.py <feature-slug> --status
```

The exit code is the state. [The runner](../../reference/runner.md#exit-codes) lists them all.

## 2. Act on it

| Exit | State | Do this |
|---|---|---|
| `2` | The conductor refused: a confirming round still failing, a blocked developer, a scenario to fold or split | Read the reason. Fix what it names, or make the call it asks for, then start the runner again. |
| `4` | The plan judge would not accept a plan | Read the plan's deviations; send it back to the architect or accept it with `pipeline.py next <slug> --plan-ok`. |
| `5` | The feature budget is spent | Decide whether to spend more. Resume with a larger `--feature-budget`. |
| `6` | A run failed, timed out or returned nothing; or the environment is missing a tool | When the record says running it again is a reasonable first answer, resume. Otherwise fix what it names. |
| `7` | Interrupted | Resume when ready. |
| `8` | Dead: the runner is gone with no stop record | Run `git status`, then resume. |
| `9` | Hung: alive and silent past its longest wait | Stop it with `--stop`, then treat it as dead. |
| `1` | The runner itself failed | Read the traceback in the record. Do not resume. |

## 3. Resume

Run it again. Every finished run is in `.runs/<slug>/RUNS.jsonl`: a step whose agents all finished is not repeated, and one that was cut short runs again in full.

```bash
scripts/runner.py <feature-slug> --detach
```

After a dead or interrupted runner, the next brief tells its agent that the previous run was cut off and the tree may hold its edits.

## A gate round that still fails

There is one fix pass and one confirming round. When the confirming round fails, either fix the findings outside the pipeline, or accept the round open and go on to scoring and the retro:

```bash
scripts/pipeline.py next <feature-slug> --accept-open
```

!!! warning "One driver per feature"
    Do not drive one feature with both the runner and a chat session at the same time. To hand a feature back to chat, clear the runner's environment note first: `scripts/pipeline.py next <slug> --env-note ''`.
