# {{name}}

{{description}}

## Workflow

All work here is the **Direct lane**: make the change, verify it, open a PR. No spec, no
scenarios, no pipeline, and no `.claude/pipeline.json` — the pipeline plugin is enabled for its
skills, and its SessionStart hook says the pipeline is not set up here, so it is never entered
implicitly.

- Explain *why* in comments next to the change, not only in the commit message.
- Secrets are never committed; the comment next to whatever needs one says how it is made.
- Known debt goes to a GitHub issue labelled `debt` (what, why, and the trigger to pay it).
  Never a TODO list or TODO comment in a file.

## Verify

CI runs the same commands (`.github/workflows/checks.yaml`):

```bash
{{verify}}
```
