# Brief: planning coverage

_Paths: bare `scripts/`, `briefs/`, `agents/`, `commands/` are in the pipeline plugin, `.claude/…` are the repo's (`briefs/core.md`)._

For `architect`, the `developer` writing a small scenario's plan, and the gate reviewers who hold the
code to it. Read with `briefs/core.md` (core) and `briefs/build.md`.

## Planning: the coverage the gate will demand

`scripts/pipeline.py plan-check` checks a plan's shape, its `covers` entries and its setup source before the
first developer run; it does not judge the items below — those are the gate reviewers' (and the
checkpoint's, when it is on).

The spec's cases are the behaviour the user approved; the items below are the technical
coverage no case table lists, and they are steps of their own — never folded into a case.

Every architect checklist for a new or changed handler carries, as named steps:

- **One fault test per fallible call** — each store call, decrypt/encrypt, and downstream
  RPC the handler makes. Include the call that re-reads on a resume or retry branch, not
  just the first one.
- **Every numeric bound tested just outside it**, with the in-bound case as the control
  (skew windows, count limits, TTL clamps).
- **Every fallback branch of an error mapper** — the `default:` arm, not just the named
  codes. A mapper is tested by **one table with a row per arm plus `default:`**, each row's
  expected status and copy written as literals; the plan names that table as one step. No
  `//nolint:exhaustive` in a mapper: list every case, so an arm identical to `default:` shows
  (`golangci` requires a reason on every `//nolint`).
- **A changed publish call site gets a named mutation that deletes the publish call**, not
  only mutations of the fields it sets — the assertion must pin the event's action
  (`briefs/proof.md` → *Assertions that prove nothing*).
- **An absence is planned with its control** — the step names the table that holds both the
  absent and the present row (`briefs/proof.md` → *Assertions that prove nothing*).

For a store adapter that decodes items or writes a conditioned transaction, add:

- **One decode-fault test per decoded item kind** — the root item as well as the child
  rows. A corrupt-child-row test on a read does not cover a corrupt root item on the same
  read.
- **One test per conditioned slot, plus the case where several slots fail at once.** When
  the slot registration order decides which sentinel wins, a test must pin that order (swap
  the order → red). A precedence stated in the spec and implemented is still untested until
  a test pins it.

For a frontend component, hook or auth-client change, add:

- **One error-state test per fallible call** — each query, mutation, token request and
  Connect call the code makes; the test asserts the user-visible state and copy that rule it
  (`briefs/build.md` → *What rules a scenario*), not just that nothing threw.
- **A callee documented "never throws" is still a fallible call** unless the plan cites the
  code that guarantees it; it gets a rejection test. The test drives the real function, or
  a stub the plan shows matches how the real callee fails — a mocked rejection the callee
  never produces proves an unreachable branch.
- **Loading and empty states** for every query a screen renders.
- **Every numeric bound tested just outside it** (timeouts, retry counts, expiry skew), as
  for Go.
- **Cache consistency** — after each mutation, the query that shows the changed data
  reflects it (invalidated or updated).

For any plan, Go or frontend:

- **Advice round-trips through its own check** — when code both refuses a value and
  suggests a corrected one (an error quoting the value to use instead), a named test feeds
  each suggested value back through the same check and asserts it passes.
- **A sibling inherits its twin's pin** — when a plan adds a sibling of something an
  existing test or a STATE.md binding decision pins (another lazy page, another theme,
  another push shape, a call beside one with a timeout or retry bound), the sibling gets the
  same pin as a named step, unless the plan says why not.
- **Every arm of every new branch is a named test** — each `switch` case, ternary, threshold,
  set-membership or early return, and each accepted input class (file types, heading
  orders, platforms), and each conjunct of a compound guard — removed alone, it reddens a
  test. One passing arm does not cover the others; an `it.each` / table over the arms is the
  expected shape. Each arm's assertion must be able to fail
  (`briefs/proof.md` → *Assertions that prove nothing*).
- **Every other writer of state the scenario writes or trusts** — when the scenario writes
  or trusts a cookie, storage key, URL/query parameter or stored registry value, list who
  else can write or overwrite it (another flow, a forced re-auth, a second tab, an
  operator, a value stored by an earlier release that already holds the field). Each
  becomes a `### Build` test of what the reader does with a value this scenario did not
  write, or the step says `no other writer: <why>`.
- **A result can land after its context is gone** — for each async call whose handler
  writes state or moves focus (a mutation's `onError`/`onSuccess`, a fetch continuation, a
  timer), list the ways its UI context can end while it is in flight: cancel, close, a
  sibling flow taking the screen, the same context reopened. Each is a named test that
  holds the call, ends the context, then settles it, or the step says
  `cannot outlive its context: <why>`.
- **Lifetime and ordering of records that other things depend on** — three cases, each a
  named test:
  - *Retention outlives every dependent.* For any TTL, prune or retention rule on a record
    that another record, token or session depends on — including a conditional prune, such
    as idling out after a failed touch — the step names the longest-lived dependent and
    tests that the record is still present for that long. The bound is the dependent's
    lifetime, not the record's own TTL, tested per the numeric-bound rule above with
    **literals**, so a constant changed to shorten retention reddens it.
  - *Compensation against a late original.* For any compensating or cleanup call, the step
    enumerates its orderings against an original call that lands late — original first,
    compensation first, concurrent — and gives each a named test. The compensation-first
    row asserts the late original cannot resurrect the state: undoing only what is visible
    now loses to a commit that lands after. The concurrent row is named to match
    `scripts/race-gate.py`'s `CONCURRENCY_RE` (`briefs/core.md` →
    *Verification*).
  - *Frontend: pending is a state.* A mutation's pending state gets its own test: dismissal
    (Escape, overlay, Cancel) and re-submit while pending. A settle after the context ends
    is the item above.
