# Security

{{description}} This file lists what is worth attacking in {{name}} and the rules that defend it.
It is for security reviews; build rules live in `CLAUDE.md` and `.claude/`. Keep it short and
true: every line either points a reviewer at something worth attacking or stops one re-reporting
something already reasoned about.

## Reporting a vulnerability

Do not open a public issue. Use GitHub's private vulnerability reporting on this repository
(Security → Report a vulnerability). Include the commit or release you ran, what you did, and
what an attacker gains.

## What is worth protecting

| Asset | Where it lives | Rule |
| --- | --- | --- |

## Trust boundaries

Where attacker-controlled input enters, and what each side trusts the other to have checked.

## Sensitive paths

A change under any of these paths gets a security review before it merges. In a repo with
`.claude/pipeline.json`, this list is its `security_paths` pattern; keep the two in step.

## Reviews

A security review runs before each release and on any pull request that touches a sensitive path.
Each confirmed finding becomes an issue labelled `security`.

## Known non-issues

Findings that were investigated and are **not** vulnerabilities, with the reason. A reviewer may
re-raise one only by showing the reason no longer holds.

Format: `- <what it looks like> — <why it is fine> (<path:line of the guard>)`
