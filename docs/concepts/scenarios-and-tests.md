# Scenarios and tests

The pipeline's unit of work is the scenario. It is what the user approves, what one developer builds, and what one acceptance test proves.

## A scenario is one action and its outcomes

A scenario names exactly one `Action`: one RPC, one endpoint, or one user interaction. Under it is a table of cases, each an outcome the user could observe:

| Kind | Covers |
|---|---|
| `happy` | The outcome when it works. Exactly one per scenario. |
| `empty` | No data, no matches, no candidates. |
| `edge` | A boundary, with a row on each side of it and literal values. |
| `error` | Invalid input, a caller who may not, a refusal the user sees. One row per distinct code or message. |

A second action is a second scenario. A different outcome of the same action is a row. Faults of the code's own dependencies, such as a failed store read, are not cases: the user never approved them, so the architect plans them instead.

The `Expect` cell of each row quotes the product spec. Codes and copy are ruled there and not invented in the table.

## The spec links to tests, never the reverse

The feature spec (`docs/specs/<slug>.md`) is committed. Test code carries no scenario ids. A built scenario names its acceptance test on one line of its own block in the spec, and writing that line is the tick. `spec-check` checks that the named test exists; at the gate it also runs each named test alone. A scenario is done when its test passes, not when it exists.

## The double loop

**Outer loop: test-first, always.** Each scenario has one acceptance test at its observable boundary: the handler or the screen. It is written before any production code and must fail at its assertion, for the expected reason. The failing output goes in the developer's report.

**Inner loop: depends on the code.** Strict red, green, refactor stays mandatory for three kinds of change:

- bug fixes: the test must have failed before the fix;
- security guards: authentication and authorization decisions, token and session handling;
- store adapters that claim atomicity: conditional writes, transactions, exactly-once semantics.

Everything else is built in code-first batches: one behavior per batch, the code, then its unit tests in the same batch, then a refactor while green. Nothing ships untested either way. The only difference is whether a unit test must be seen red before its code exists.

## The lock

The run that writes the acceptance test is never a run that builds to it. From the second run on, a `PreToolUse` hook refuses an edit that changes that one test. Other tests in the same file are untouched, and fix passes are exempt.

The lock is a guardrail, not a seal: it sees the edit tools, not a shell command or a helper the test calls. When the locked test is itself wrong, `pipeline.py unlock` lifts it. The acceptance test's setup is therefore copied from a passing test of the same surface, not written fresh: a wrong setup stops the scenario even when the assertions are right.

## Bounded runs

A scenario is built by several short developer runs, not one long one: one run for the scaffold and the failing acceptance test, then runs of at most three behavior batches. Each ends with a phase report of at most 30 lines, and the next run starts from that report and the plan's ticks. It never sees the previous transcript. Two runs in a row that tick nothing stop the scenario.

## Sizing

Small is the default. A small scenario skips the architect: its first developer run writes a checklist of at most 15 lines, then builds. The sizing pass marks a scenario `large`, and gives it an architect's plan, when it is predicted past three build batches or one package, or touches the mandatory test-first set. A scenario predicted past five batches or one production package is split before the spec is written.

## What backs the tests up

- **Diff coverage.** `check.py phase` fails a changed block no test runs.
- **Mutation sample.** Before the last run of a scenario, and again at the gate, changed lines are broken one at a time. A mutant no test kills is named for the developer or the reviewer to rule on.
- **Absence-only tests.** A test that asserts only that something did not happen, with no control showing it can happen, is listed for a ruling.

The long form is the plugin's [build brief](https://github.com/koblas/throughline/blob/main/plugins/pipeline/briefs/build.md) and [proof brief](https://github.com/koblas/throughline/blob/main/plugins/pipeline/briefs/proof.md). [Feature spec format](../reference/feature-spec.md) has the exact shapes.
