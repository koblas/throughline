# How to add a reviewer

The gate runs a correctness reviewer and a test reviewer for each surface. The plugin ships `test-reviewer` for Go tests and no correctness reviewer, so each surface names agents of the repo's own.

## 1. Generate the agent

```
/pipeline:new-reviewer correctness-reviewer
```

The command asks for the reviewer's purpose, the globs that trigger it, where to put it (`.claude/agents/` by default), its checklist with an example of a BLOCKER, a MAJOR and a MINOR, and its model tier. It then writes the agent file.

## 2. Check the frontmatter

`type: reviewer` and `triggers:` are both required. Reviewers are discovered by those two lines; one missing either is invisible.

```markdown
---
name: correctness-reviewer
description: Chief Correctness Officer for the Go services. …
type: reviewer
triggers: ["**/*.go"]
tools: Read, Glob, Grep
model: opus
---
```

## 3. Put it on the gate

Being discovered is not being on the gate. Name the agent in the surface's `reviewers` in `.claude/pipeline.json`:

```json
"reviewers": {"correctness": "correctness-reviewer", "test": "pipeline:test-reviewer"}
```

A repo's own agent is named bare; a plugin agent carries the `pipeline:` prefix. A reviewer no surface names runs only ad hoc: [How to run reviewers on a path](../run/run-reviewers.md).

## 4. Restart the session

An agent added, renamed or moved is not loaded until the session restarts.

## 5. Give it extra briefs

To hand the reviewer briefs besides its standard ones, add it to the config's `briefs` map under its bare name. The [pipeline.json reference](../../reference/pipeline-json.md) describes the map.
