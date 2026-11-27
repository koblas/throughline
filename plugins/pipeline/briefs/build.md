# Brief: building a scenario

_Paths: bare `scripts/`, `briefs/`, `agents/`, `commands/` are in the pipeline plugin, `.claude/…` are the repo's (`briefs/core.md`)._

For `architect`, `developer` and the step-5a checkpoint reviewers (when the checkpoint is on). Read with `briefs/core.md` (core).

**What rules a scenario.** The feature spec (`docs/specs/<slug>.md`: intent, decisions, case
tables) and the product spec its `**Area**:` line names (`docs/product/<area>.md`: rules, surface,
codes, copy) are binding; implement their strings verbatim and invent none. A Light-lane spec says
`**Area**: none`: there its `## Decisions` and the code's existing behaviour rule — it adds no
surface or copy, so an `Expect` cell quotes only what the code already says. Reviewers hold the
code to the same sources.

## Build cadence: the double loop

This is the one statement of when a test must fail before code exists. `briefs/workflow.md`, the `tdd`
skill, `architect` and `developer` cite it; none restates it.

**Outer loop — test-first, always.** Each scenario has exactly one **acceptance test** at its
observable boundary: the handler / `Server` method (Go) or the screen (React). It is written
before any production code, and it must fail **at its assertion, for the expected reason**. The
failing output goes in the developer's report. It is named on the scenario's
`Acceptance test:` line in the feature spec (see *Scenario traceability*), and a scenario is not
ticked until that test passes.

**Inner loop — depends on what the code is.** Test-first (red → green → refactor, per the `tdd`
skill) stays **mandatory** for:

- **Bug fixes** — the test must have failed before the fix.
- **Security guards** — authn/authz decisions, MFA, token and session issuance or validation,
  single-use consume, anything under `core/identity`.
- **Store adapters with an atomicity or conditional-write claim** — `ConditionExpression`,
  transactions, single-use or exactly-once semantics.

Everything else is built as **code-first small batches**: one behaviour per batch — write the
code, then its unit tests in the same batch, then refactor while green, then the next batch.
Refactor every batch, not once at the end. Nothing ships untested — `test-reviewer`'s "untested
change is a BLOCKER" is unchanged. What changes is only whether a unit test must be *seen red*
before its code exists.

The architect marks each scenario's cadence in the plan: `Cadence: test-first` (any mandatory
item above is touched) or `Cadence: code-first`. `scripts/pipeline.py next` copies it into `METRICS.md`
(`briefs/metrics.md`).

## Sizing

The sizing pass (and each architect's `Size:` line) **splits** a scenario predicted to exceed
any of:

- **5 behaviour batches** in `### Build`;
- **one production package** — one `go/services/<group>/<name>` / `go/libs/<name>` package or
  one frontend workspace. Proto scaffold, generated code, `cmd` wiring and fakes do not count,
  nor does the thin `publicapi` handler in front of the service the scenario changes — the
  acceptance test sits there by rule;
- **the p90 of past scenarios** — the orchestrator runs `scripts/feature-metrics.py
  --scenario-p90` and pastes the number it prints into the sizing prompt. Below 20 recorded
  scenarios it says so, and this threshold is off.

The plan header records the verdict and its numbers:
`Size: OWNS A RUN — 4 batches, 1 package (services/core/todo)` or
`Size: SPLIT — 7 batches > 5`. A scenario that cannot be split says why on that line.

## Small scenarios

**Small is the default size.** Only a scenario the sizing pass marks **`large`** — its
`Size: large` line — gets an architect's plan. Mark a scenario
large when it is predicted past **3 build batches** or one package, touches the mandatory
test-first set above, or hits a `briefs/planning.md` "Lifetime and ordering" case (a retention rule a
dependent relies on, a compensating call): its named orderings do not fit the small checklist.
Any doubt → `large`.

Every other scenario skips the architect. Its first developer run writes `SCENARIO-XX.md`
itself — the architect's header lines (`architect` → *Plan format*) and a checklist of **at
most 15 lines**, each test step ending `covers NN.k` (*Scenario traceability*) and the
acceptance step naming its `setup from` (*Acceptance test setup*) — before any code, then builds
as usual. Every run is tagged `size: small`. With the checkpoint off, what backs a small plan
up is mechanical: `check.py phase` fails a changed block no test runs, and the mutation sample
before the last run names a changed line no test notices.

## Bounded runs

A scenario is built by several short developer runs, not one long one.

| Run | Covers | Starts from |
| --- | --- | --- |
| 1 | Scaffold + Acceptance (red) — written from the scenario's `happy` case, then locked | plan, `STATE.md` |
| 2..n | Build, **at most 3 behaviour batches** each | plan with ticks, `STATE.md`, previous phase report |
| last | the remaining batches (at most 3), then Sweep + Verify + tick + `STATE.md` rewrite | plan with ticks, `STATE.md`, previous phase report, the mutation survivors of what earlier runs built |

**The run that writes the acceptance test is not a run that builds to it.** From run 2 on, a
`PreToolUse` hook (`scripts/check.py lock`) refuses an edit that changes that one test; fix
passes are exempt, and the orchestrator can `pipeline.py unlock` a test that is itself wrong.
It is a guardrail, not a seal — it does not see a shell command or a helper the test calls.
A build run that stops on the lock for a setup-only change (a fixture, a cleanup, a mock's
shape) is unlocked once by the runner's judge; anything else, or a second stop, goes to a
person (`briefs/orchestration.md` → *A locked acceptance test that is wrong*).

Each run ends with a **phase report of at most 30 lines**:

```markdown
## Phase report — SCENARIO-NN run 2 (Build steps 3–5)
Changed: `go/services/core/todo/share.go:40-96` Share; `handler_test.go` 4 tests
State: acceptance test green; narrow loop 18 passed
Do not redo: stub for Store.Unshare already in memory.go:120
Next: Step 6
```

`scripts/pipeline.py next` puts it in the next run's brief; the next run never sees a transcript.

**The plan's ticks are how a scenario moves.** `next` chooses each run from them and nothing
else. Tick a step once its work is on disk and its check has been seen — including a step an
earlier run did and left unticked. A run that cannot do what its steps need opens its reply
`BLOCKED: <what it needs>` and stops; two runs in a row that tick nothing stop the scenario
too. Where the brief's `Environment:` line offers it, `RUNNER: codegen` as the first line gets
the repo's `codegen` request run for you and your run started again.
A run that has read enough to pass about half its context stops at the next batch boundary,
ticks what is done, and hands off with a phase report naming the next step.

## Scenario traceability

The link runs **from the spec to the test**, never from the test to the spec — test code
carries no scenario IDs (`briefs/fix-pass.md` → *Fixing a finding*: run reports are not kept, citations rot).

A built scenario names its acceptance test on an `Acceptance test:` line of its own block in
`docs/specs/<slug>.md`, below its `Size:` and `Issue:` lines — writing that line is the tick:

```markdown
Acceptance test: `go/services/core/account/provision_test.go` `TestFirstProvisionCreatesAnAdminMember`
```

A frontend test is named by file and the full `describe › it` title:
`` `frontend/packages/app/src/pages/members.test.tsx` `members page › lists every member` ``.
The line holds nothing else and does not wrap. Nobody closes the scenario's
sub-issue by hand: once `pipeline.py next` records the scenario done it writes `Closes #N` into the PR
body draft (`.runs/<slug>/PR.md`), and the PR closes it on merge.

**Every approved case is planned.** A scenario is a table of cases (`intent-and-goal` →
*Scenario format*). The acceptance test proves its `happy` case; every other case is a named
test in a `### Build` step. Each such step — the acceptance step included — ends `covers NN.k[, NN.k]`; only ids in a
`covers` list count. A FOLDed scenario's cases are covered in the absorbing scenario's plan.
Case ids live in the plan, never in test code.

`scripts/spec-check.py <feature-slug>` checks that every scenario has exactly one `Action` and
a well-formed case table, that the spec has the four sections, that every built scenario's
`Acceptance test:` line names a test that exists in that file, that it is the test the plan's
`Acceptance test:` line names, and that every case id of the scenario appears in its plan. The
developer runs it right after writing the line; the final gate runs it with `--run`, which also
runs each named test alone — a scenario is done when its test passes, not when it exists. A spec
without the `<!-- spec-check: v4 -->` marker fails.

## Acceptance test setup: copied, never written

The acceptance test is locked after its first run (`scripts/check.py lock`), so a wrong setup
stops the scenario even when its assertions are right. Plan its setup from code that already
runs:

- **Copy the setup from a passing test of the same surface.** The acceptance step names
  `setup from <test file>:<line>` — an existing, passing test that drives the same handler,
  `Server` method, page or hook. The test copies that file's module mocks, fakes, fixtures and
  options wholesale and changes only what the scenario changes. A mock written fresh misses
  what the real module is called for elsewhere: a `vi.fn()` that returns `undefined` where the
  caller chains `.catch`, an `@/authClient` mock missing a method the request middleware calls.
  Only when no test drives that surface yet, write `setup from: none — <why>` and name the
  real module each stub replaces.
- **Shared doubles are imported, never copied** — a copied frontend setup takes its `fetch`
  stub from the shared helper (`ui-testing` → *Repeated construction*).
- **The acceptance test is lint-clean before it locks.** When the run that writes it ends,
  `scripts/pipeline.py` lints its file; a finding sends that run back once, with the
  linter's output, before the lock engages (idioms: `go-testing` / `ui-testing` →
  *Lint-clean test idioms*).
- **Name the real signature of every return value read.** For each function whose result the
  test — or the code under test, through a mock the test supplies — reads, the step gives the
  signature and what each value means, copied from the source (`GetPasswordHash(ctx, id)
  (hash string, resetRequired bool, err error)` — no password is `ErrNotFound`, not a `false`).
  A mock's return value takes the shape the real callee produces.

`plan-check` checks the `setup from` citation is present; whether it is the right test, and the
signatures, are the orchestrator's read of the plan (`briefs/orchestration.md` →
*Judgement calls* → *Read the plan's deviations*).

## Planning: the coverage the gate will demand

Its own brief, `briefs/planning.md`: the technical coverage every plan names as steps.
