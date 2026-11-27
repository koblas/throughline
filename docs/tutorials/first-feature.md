# Your first feature

You take one request through the whole pipeline: triage, the kickoff, scenarios, the build, the gate and the PR draft. You answer two questions on the way. Everything else runs without you.

The blocks marked *Example* come from one made-up feature, letting a member sign out another of their sessions, in a Go service. Your repo's text differs; the shape is the same.

!!! note "Before you start"
    You need a repo where the plugin is installed and configured: [How to install the plugin](../guides/install/install.md), then [How to configure a repo](../guides/configure/configure-a-repo.md), or [How to start a new repo](../guides/configure/new-repo.md) for an empty one. Each surface in `.claude/pipeline.json` names reviewers that exist ([How to add a reviewer](../guides/configure/add-a-reviewer.md)). The `gh` CLI is signed in: approval opens GitHub issues.

## 1. Ask for the behavior

Open Claude Code in the repo and say what you want, in your own words. There is no command to type.

```
Members should be able to sign out one of their other sessions from Settings.
```

The session says in one line what it treats the request as, and that triage is running. It enters a fresh worktree named after the feature.

## 2. Read the triage result

The `triage` agent reads the code and reports what exists, what is affected and what it could not answer. Its last line is the lane.

```text title="Example"
Lane: Full — a new RPC (SessionService.Revoke) and a new control on Settings › Sessions.
```

A Full lane runs every step below. A Direct lane ends here: the session does the work.

## 3. Answer the kickoff

The session stops and shows the kickoff card. This is the first of the two pauses.

```markdown title="Example"
## Kickoff — session-revoke
Understood as: A signed-in member can end any one of their own other sessions from
  Settings › Sessions. The current session is not revocable there. Admins revoking
  other members' sessions is out of scope.
Open questions: Should a revoked session's refresh token fail at once, or at its next use?
Issue: none
Run: unattended in the background (`/pipeline:run-feature`) — recommended — or here in this session?
```

Correct the reading if it is wrong, answer the open question, and pick how to run. For this tutorial, answer **here**: you see each step as it happens.

```
Reading is right. Fail at once. Run it here.
```

Your answer becomes decision D-1 of the feature spec.

## 4. Approve the scenarios

The `product-vision` agent writes the names, codes and copy into `docs/product/<area>.md`. The session then proposes scenarios. Each is one action and every outcome you care about for it.

```markdown title="Example"
### SCENARIO-01 — a member signs out one of their other sessions

Action: `SessionService.Revoke`
Size: small

| Case | Kind | Given | Expect |
| --- | --- | --- | --- |
| 01.1 | happy | the member has two sessions and names the other one | `OK`; the session is gone from `List`; its refresh token fails with `session_revoked` |
| 01.2 | edge | the member names their current session | `FAILED_PRECONDITION` `cannot_revoke_current`: "Sign out to end this session." |
| 01.3 | error | the session belongs to another member, or was already revoked | `NOT_FOUND` `session_not_found`: "That session no longer exists." |
```

Read the scenarios and the product-spec diff. Ask for changes until they are right; that is conversation, not a gate. Then approve. This is the second pause, and the last.

```
Approved.
```

Approval writes `docs/specs/session-revoke.md`, runs `spec-check --approval`, and opens the feature issue with one sub-issue per scenario.

## 5. Watch the build

From here the session calls `pipeline.py next` and does what it prints, step after step. For each scenario you see:

1. A developer run that writes the acceptance test from the `happy` case and shows it failing at its assertion.
2. One or more developer runs that build to it, in batches, each ending with a short phase report.
3. The scenario's `Acceptance test:` line written into the spec. That line is the tick.

```markdown title="Example"
## Phase report — SCENARIO-01 run 2 (Build steps 3–5)
Changed: `services/core/session/revoke.go:1-74` Revoke; `revoke_test.go` 4 tests
State: acceptance test green; narrow loop 18 passed
Do not redo: stub for Store.Delete already in memory.go:120
Next: Step 6
```

You do not answer anything.

## 6. Read the gate

When every scenario is built, the gate runs: the correctness and test reviewers of each surface the diff touches, a mutation sample, and `spec-check --run`, which runs each scenario's named test alone.

A round with a BLOCKER or a MAJOR gets one fix pass, then one confirming round. A round with only MINORs and NITs passes; each of those becomes an issue draft.

```markdown title="Example: the gate rows of METRICS.md"
| Round | Reviewers run | Findings (B/M/m/n) | Mutants (killed/survived/invalid, secs) | Verdict |
| --- | --- | --- | --- | --- |
| 1 | correctness, test | 0/1/2/0 | 16/3/1, 210s | FAIL |
| 2 | correctness | 0/0/1/0 | n/a | PASS WITH FOLLOW-UPS |
```

## 7. Take the result

At `DONE` the session names three things:

- **The PR body draft**, `.runs/session-revoke/PR.md`, with a `Closes #N` line for each scenario's sub-issue.
- **The issue drafts** for the MINORs and NITs. Say yes to file them, or drop the ones you do not want.
- **The retro**, `docs/specs/session-revoke.retro.md`, with the feature's metrics and cost.

Nothing is committed or pushed. Ask for the commit and the PR when you have read the diff.

## Next

- Run the next feature without watching: [How to run a feature unattended](../guides/run/run-unattended.md).
- See the whole spec this feature produced: [A feature, from request to spec](../examples/scoping-a-feature.md).
- Understand why each step exists: [Why it exists](../concepts/why.md).
