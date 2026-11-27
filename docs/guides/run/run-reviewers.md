# How to run reviewers on a path

`/pipeline:run-reviewers` with paths is an ad-hoc review: it is not a gate round and records nothing on a feature.

## 1. Name the paths

```
/pipeline:run-reviewers internal/session, internal/store
```

Paths are separated by commas. Every reviewer agent whose `triggers:` match files under those paths runs, including reviewers no surface names for the gate.

## 2. Read the findings

Each reviewer lists findings most severe first, in the shared format, and ends with one verdict line: **PASS**, **PASS WITH FOLLOW-UPS** or **BLOCKED**. [Gate and severity](../../reference/gate.md) defines the severities.

## Review a change to the pipeline itself

Changes under `.claude/` do not enter the pipeline. Review them with the plugin's `pipeline-reviewer`:

```
/pipeline:run-reviewers .claude
```

## Run the gate round of a feature

With no paths, the command runs the feature's gate round, which `pipeline.py next` drives. It is the same round the build reaches on its own after the last scenario.
