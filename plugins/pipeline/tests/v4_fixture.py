"""A v4 feature spec and the product-spec area file it rules against, shared by the v4 tests."""

SPEC = """# Feature: Share a task

<!-- spec-check: v4 -->

## Intent and out of scope

**Primary goal**: an owner shares one task with one member.

**Out of scope**: sharing with groups.

**Excluded paths**: none

**Run**: here

**Area**: sharing

**Screens**: Share dialog

## Decisions

- D-1 (2026-11-25): Understood as an owner sharing one task with one member — confirmed at the kickoff.

## Scenarios

### SCENARIO-01 — Owner shares a task

Action: `SharingService.Share`
Size: large

| Case | Kind | Given | Expect |
| --- | --- | --- | --- |
| 01.1 | happy | an owner and a member | the member sees the task |
| 01.2 | error | a viewer tries | `permission_denied`, "You can't share this task." |

### SCENARIO-02 — Owner stops sharing

Action: `SharingService.Unshare`
Size: small

| Case | Kind | Given | Expect |
| --- | --- | --- | --- |
| 02.1 | happy | a shared task | the member no longer sees it |

## Links

- Product spec: [sharing → Permissions](../product/sharing.md#permissions-and-visibility)
"""

AREA = """# Sharing

## Surface

- `SharingService.Share` refuses a viewer with `permission_denied`.

## Copy and voice

- Refused share: "You can't share this task."

## Screen states

| Screen | State | Copy | Controls |
| --- | --- | --- | --- |
| Share dialog | loading | Loading who has access… | none |
| Share dialog | empty | Only you can see this task. | Add member |
| Share dialog | error | Couldn't load who has access. | Try again |
| Share dialog | populated | member list | Remove |

## Decisions
"""

TRIAGE = "# Triage — share-task\n\nAlready exists: `SharingService`.\n"


def with_issues(spec: str, first: int = 2, second: int = 3) -> str:
    """The spec as `open-issues` leaves it: a sub-issue under each `Size:` line and the feature issue linked."""
    return (spec.replace("Size: large\n", f"Size: large\nIssue: #{first}\n", 1)
                .replace("Size: small\n", f"Size: small\nIssue: #{second}\n", 1)
            + "- Feature issue: #1\n")
