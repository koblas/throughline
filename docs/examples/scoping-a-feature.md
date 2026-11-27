# A feature, from request to spec

One made-up feature, `session-revoke`, at each stage of scoping in the Full lane. The formats are the ones the scripts parse; [Feature spec format](../reference/feature-spec.md) is the reference for them.

## The request

```
Members should be able to sign out one of their other sessions from Settings.
```

## Triage

The `triage` agent's brief is saved to `.runs/session-revoke/triage.md` and later posted as a comment on the feature issue. Every claim cites a file and line. It ends with the lane:

```text
Lane: Full — a new RPC (SessionService.Revoke) and a new control on Settings › Sessions.
```

## The kickoff card

```markdown
## Kickoff — session-revoke
Understood as: A signed-in member can end any one of their own other sessions from
  Settings › Sessions. The current session is not revocable there. Admins revoking
  other members' sessions is out of scope.
Open questions: Should a revoked session's refresh token fail at once, or at its next use?
Issue: none
Run: unattended in the background (`/pipeline:run-feature`) — recommended — or here in this session?
```

The answer, "Reading is right. Fail at once. Run unattended.", becomes D-1 and the `**Run**:` line below.

## The product ruling

`product-vision` writes into `docs/product/sessions.md`: the rule, each surface name, each code with its copy, the screen states and a dated decision. An excerpt:

```markdown
## Revoking a session

A member can revoke any of their own sessions except the one making the request.
A revoked session's refresh token fails at once.

| Code | Status | Copy |
| --- | --- | --- |
| `cannot_revoke_current` | `FAILED_PRECONDITION` | "Sign out to end this session." |
| `session_not_found` | `NOT_FOUND` | "That session no longer exists." |
| `session_revoked` | `UNAUTHENTICATED` | "You were signed out." |

| Screen | State | Copy | Controls |
| --- | --- | --- | --- |
| Settings › Sessions | loading | "Loading sessions…" | none |
| Settings › Sessions | empty | n/a — the current session is always listed | none |
| Settings › Sessions | error | "Sessions could not be loaded." | **Try again** |
| Settings › Sessions | populated | one row per session: device, last seen | **Sign out** on every row but the current one |

- D-4 (2026-11-27): revocation takes effect at once, not at the token's next refresh — the member expects the other device to be out now.
```

## The finished spec

`docs/specs/session-revoke.md`, after approval, the sizing pass, `spec-check --approval` and `open-issues --yes`. The `Issue:` lines, the `Feature issue:` line and the `**Approved**:` line are written by those scripts, never by hand.

```markdown
# Revoke a session

<!-- spec-check: v4 -->

## Intent and out of scope

**Primary goal**: A member who left a session open on another device can end it from Settings.

**Out of scope**: Admins revoking other members' sessions. Revoking the current session.

**Excluded paths**: none

**Run**: unattended

**Area**: `sessions`

**Screens**: Settings › Sessions

**Approved**: 2026-11-27 scenarios 1a06ae1358945954

## Decisions

- D-1 (2026-11-27): a member ends one of their own other sessions; the current session and other members' sessions are out — confirmed at the kickoff.
- D-2 (2026-11-27): the list and the revoke control ship together as two scenarios — the control has no screen without the list.

## Scenarios

### SCENARIO-01 — a member signs out one of their other sessions

Action: `SessionService.Revoke`
Size: small
Issue: #142

| Case | Kind | Given | Expect |
| --- | --- | --- | --- |
| 01.1 | happy | the member has two sessions and names the other one | `OK`; the session is gone from `List`; its refresh token fails with `session_revoked` |
| 01.2 | edge | the member names their current session | `FAILED_PRECONDITION` `cannot_revoke_current`: "Sign out to end this session." |
| 01.3 | error | the session belongs to another member, or was already revoked | `NOT_FOUND` `session_not_found`: "That session no longer exists." |

### SCENARIO-02 — a member clicks Sign out on a session row

Action: member clicks **Sign out** on a row of Settings › Sessions
Size: small
Issue: #143

| Case | Kind | Given | Expect |
| --- | --- | --- | --- |
| 02.1 | happy | two sessions are listed | the row is removed; the current session's row stays and has no **Sign out** |
| 02.2 | error | the session is already gone | the row is removed; "That session no longer exists." |
| 02.3 | error | the request fails | the row stays; "Sessions could not be loaded." with **Try again** |

## Links

- Product spec: [sessions → Revoking a session](../product/sessions.md#revoking-a-session)
- Feature issue: #141
```

## What to notice

- **One `Action` per scenario.** The RPC and the click are two scenarios. A different outcome of the same action is a row, never a scenario.
- **Exactly one `happy` case.** It is the scenario's acceptance test.
- **`Expect` quotes the product spec.** `spec-check --approval` fails an `error` row whose code or copy is not in the area file.
- **One `error` row per distinct outcome.** Another member's session and a session already revoked get the same code and copy, so they share row 01.3.
- **No implementation.** The spec names no package, table or component. The architect and developer decide those.

## After the build

When a scenario is built, the developer adds one line under its `Issue:` line. Writing it is the tick:

```markdown
Acceptance test: `services/core/session/revoke_test.go` `TestRevokeEndsTheOtherSession`
```
