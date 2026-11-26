# {{name}}

{{description}}

## Workflow rules

The pipeline plugin (`pipeline@throughline`, enabled in `.claude/settings.json`) loads its workflow
rules — the implicit trigger, the three lanes, the two pauses, the agent-spawn authority — into
every session through its SessionStart hook. They are not restated here. No line from that hook in
this session's context (it starts `Pipeline plugin root:`) → the hook did not run: install the
plugin (`claude plugin install pipeline@throughline`) and read its `briefs/workflow.md` before
acting on any request for new or changed behavior.

The repo's surfaces, gates and budgets are in `.claude/pipeline.json`.

## Product spec

`docs/product/` is the current truth about what {{name}} does. A change to a rule or to
user-visible copy edits the file it belongs to in the same pull request as the code.

## Debt

Known debt goes to a GitHub issue labelled `debt` (what, why, and the trigger to pay it). Never a
TODO list or TODO comment in a file.

## Verify

CI runs the same commands (`.github/workflows/checks.yaml`):

```bash
{{verify}}
```
