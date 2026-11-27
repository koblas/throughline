# Brief: fix passes

_Paths: bare `scripts/`, `briefs/`, `agents/`, `commands/` are in the pipeline plugin, `.claude/…` are the repo's (`briefs/core.md`)._

For the `developer` in fix mode and the orchestrator writing a fix-pass brief. Read with
`briefs/core.md` (core), `briefs/build.md` and `briefs/planning.md` (a fix adds tests to its rules).

## Fix passes: no new behaviour

A fix pass applies BLOCKER and MAJOR findings, and only those. **No MINOR or NIT is folded
in**, not even one in a file a blocking fix already edits: every MINOR and NIT is an issue
draft for the feature (the gate drafts them itself; `pipeline.py file-issues <slug>` lists them), filed on the user's yes.
Anything else the fix turns up and leaves becomes a draft too
(`scripts/pipeline.py debt <slug> "<title>"`). **Moving a check
from one function to another is a behaviour change** for every caller that ran it: each
such caller needs a row that fails without the check (for advice, the round-trip in
`briefs/planning.md`).

**A blocking fix that adds behaviour plans its tests.** When the fix for a finding adds
runtime behaviour (a detached context, a timeout, a retry, a new branch), the fix-pass brief
names, before dispatch:

- the **positive assertion** for each new branch — what DID happen, not only what did not —
  with a control arm that differs in one variable;
- for every new numeric bound, the **in-bound and just-outside-bound tests** (the
  `briefs/planning.md` rule applies to fix passes unchanged);
- the **mutation expected to redden each test**.

**A finding about a state's lifecycle is enumerated before it is fixed.** When a finding
concerns when a flag, ref or stored value is set or cleared, or a late async result, the
fix-pass brief first lists every site that sets or clears that state and every exit path
from the condition it guards, with the test that pins each. A fix that moves, adds or
removes a set or a clear names, per exit path, the row that fails without it.

**A test a fix pass adds or changes is proven before hand-back.** Run the
`briefs/proof.md` → *Mutation verification* check on it and confirm each spy or
refusal control was actually hit.

**A test cited in the feature spec is never retired or renamed without repointing the
citation in the same pass.** The citing line names the replacement test, and the fix pass
runs `scripts/spec-check.py <slug>` (without `--run`; the gate still runs `--run`).

A test that reads `ctx.Err()` from a value that defaults to nil, or a bound test that
cannot see the bound's value, passes whether or not the new branch works — it proves nothing.

## Fixing a finding

1. **Sweep the population, not the instances (MANDATORY).** Finding names instances reviewer
   happened to find; never whole population. Before calling any finding fixed:
   - Changed a **sentinel, error value, or code**? Enumerate every consumer — in Go,
     `LSP` `findReferences` on symbol AND `incomingCalls` on every function returning it
     (the repo's navigation brief, if it has one); grep for frontend — and confirm each one handles new
     value. New sentinel reaching 2 of 6 handlers is not a fix.
   - Changed a **pattern in one file**? Grep whole repo for that shape, fix or consciously
     exempt every hit.
   - Copied code, or changed code existing in a copy? Fix copy in same pass, or hoist shared
     part.
   Report sweep: what you searched for, how many hits, what you fixed, what you left and why.
   "Fixed the named files" is not a sweep.
2. **Verify at the consumer, not at the change (MANDATORY).** Fix is correct only where value is
   consumed. After changing error/code/sentinel, follow it to outermost boundary observing it —
   HTTP handler, edge mapping, SPA — and confirm externally visible behavior is what finding
   intended. Fix easily right inside own package and wrong one layer out (new code falling into
   generic `else` branch, turning transient error into permanent one). Name that boundary in
   report.
3. **Comments state the contract, not the change history (MANDATORY).** Every fix pass adds
   prose, and two rules keep regressing because each pass re-derives them:
   - **No review-round, finding or spec citations in any comment — tests included.**
     `(REVIEW-04's MAJOR 2)`, `R7`, `SCENARIO-04` belong in report or PR. Those reports are
     gitignored run output, gone with the worktree (only the spec and its retro are committed);
     citation become dead reference. State
     the rule instead. Test comments follow the repo's test skills → *Test comments*: name
     is documentation, default no comment, max 2 lines.
   - **No diff-narration.** Comment whose subject is *what this pass changed* ("only this
     function's body changed", "the duplicate that used to live here", "round 4 type-asserted
     only X") is correct on commit it lands in and false on next one. Test: **does deleting the
     historical clause destroy information about the current contract?** If no, delete it. If
     yes — e.g. "this function used to have no repair path at all", which explains why it is
     named *repair* — keep it.
   Before finishing, `grep -rn "REVIEW-0" --include="*.go"` excluding `_test.go`, confirm zero.

4. **Replacing a default means inheriting its whole contract (MANDATORY).** Before swapping out
   framework-provided default (an error handler, HTTP middleware, an RPC interceptor,
   `json.Marshaler`), enumerate **every responsibility the default had** and **every caller it
   served** — then confirm your replacement covers all of them, or state which it deliberately
   drops.
   - Read default's source, not its docs: a default can rank one error type over another, and a
     replacement that checks only one silently changes a status code (`repo.md` has a worked case).
   - Global registration serve **every** operation, not ones brief described. If some operations
     answer in different shape (HTML vs JSON), single replacement break them.
   - "The tests pass" is not evidence: default's untested responsibilities stay untested after
     you replace it.
   Report enumeration — what default did, what you cover, what you dropped and why.

5. **When you make an input shape unreachable, find the tests that depended on reaching it
    (MANDATORY).** Test still passing after its trigger removed is no longer testing what its
    name says — it silently retargeted onto different code path.
    - Relaxing a `required` constraint, widening a type, adding a default, short-circuiting a
      validation all remove input shapes. Ask which branches those shapes were only route to.
    - **Check coverage, not just green.** `go test -coverprofile` before and after: function or
      branch dropping to `0.0%` is signal. Green tells you nothing here — tests still pass, they
      just pass somewhere else.
    - Guard watching *shape* of a thing (type assertion, table's contents) does not prove thing
      is *reachable*. If only guard is shape-based, branch can become dead and stay green.
    Report what you checked and what moved.
