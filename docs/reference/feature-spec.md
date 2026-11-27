# Feature spec format

A feature spec is `docs/specs/<slug>.md`. `spec-check.py` parses it, so the shapes below are exact. [A feature, from request to spec](../examples/scoping-a-feature.md) is a complete one.

## The file

The marker `<!-- spec-check: v4 -->` is required. The file has four `##` sections, in this order, and no other:

| Section | Holds |
|---|---|
| `## Intent and out of scope` | The header lines below. |
| `## Decisions` | Entries `D-<n> (YYYY-MM-DD): <decision> — <why>`, D-1 first. D-1 is the reading confirmed at the kickoff. |
| `## Scenarios` | One `### SCENARIO-NN — <title>` block per scenario. |
| `## Links` | The product spec link and the feature issue. |

## Header lines

| Line | Value |
|---|---|
| `**Primary goal**:` | The main business value, and who it is for. |
| `**Out of scope**:` | The concerns explicitly excluded. |
| `**Excluded paths**:` | Globs the feature must not change, or `none`. A change under one is a BLOCKER at every review. |
| `**Run**:` | `here` or `unattended`: the kickoff answer. |
| `**Area**:` | The `docs/product/<area>.md` file the ruling went into, or `none` in the Light lane. |
| `**Screens**:` | Each screen the feature adds or changes, named as the area's Screen states table names it, or `none`. |
| `**Approved**:` | `<YYYY-MM-DD> scenarios <digest>`. Written by `spec-check --approval` as the last line of the section. Never written by hand. |

## A scenario block

```markdown
### SCENARIO-NN — <who does what, in domain language>

Action: <the one RPC, endpoint or user interaction>
Size: <large | small>
Issue: #<N>
Acceptance test: `<file>` `<test>`

| Case | Kind | Given | Expect |
| --- | --- | --- | --- |
| NN.1 | happy | <precondition> | <observable outcome> |
```

| Part | Rule |
|---|---|
| Heading | `###`, the id `SCENARIO-NN`, an em dash, a title. |
| `Action:` | Exactly one per scenario, at the start of its line, no bold. |
| `Size:` | `large` or `small`, from the sizing pass. |
| `Issue:` | Written by `open-issues`. |
| `Acceptance test:` | Written by the developer when the scenario is built. The line holds nothing else and does not wrap. A Go test is named by file and function; a frontend test by file and the full `describe › it` title. |
| Table | Four cells per row, no empty cell, no `\|` inside a cell. |
| Case id | `NN.k`, carrying the scenario's own number, unique in the spec. |
| `Kind` | `happy`, `empty`, `edge` or `error`. Exactly one `happy` row. |
| `Expect` of an `error` row | Names an outcome the user or caller gets: quoted copy, a copy constant, a wire code or HTTP status, `unchanged`, or `n/a — <why>`. |

## What `--approval` holds the spec to

- Every `path:line` it cites exists and reaches that line; every cited repo path exists unless its line calls it new.
- Every symbol cited beside its file is a whole word in that file.
- Full lane: every quoted string and wire code in an `error` row is in the area file, and every screen on the `**Screens**:` line has a loading, empty, error and populated row in the area's `| Screen | State | Copy | Controls |` table.
- Light lane (`**Area**: none`): it names no screens, and every string and wire code an `error` row quotes is already in the code.

`pipeline.py open-issues` and a build's first `pipeline.py next` refuse a spec with no `**Approved**:` line, or whose scenarios changed since it was written.
