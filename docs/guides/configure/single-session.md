# How to use single-session mode

In single-session mode the work is done in the session itself. The repo keeps the lanes, the testing rule and the per-edit checks, and drops the agent roster, the two pauses, the conductor and the runner.

## 1. Set the mode

```json
{
  "mode": "single-session"
}
```

Add the key to `.claude/pipeline.json`. `pass_conditions` and `feature_budget_usd` may then be left out. [pipeline.json for four repos](../../examples/pipeline-json.md#a-single-session-repo) has a complete file.

## 2. Work in the session

At session start the plugin loads the lanes and the testing rule, with a short note in place of the pipeline-only rules. Build the change in the session. The per-edit hook formats and vets each file a surface covers, and `check.py phase` runs the surface's checks:

```bash
scripts/check.py phase --go ./internal/session/
```

`runner.py` and `pipeline.py next` refuse to run.

## 3. Write the retro when a Full-lane feature closes

```
/pipeline:retro <feature-slug>
```

With no run ledger, the retro is written from the feature's merged PRs. [How to write a feature's retro](../run/write-a-retro.md) has the details.
