# Brief: reviewing

_Paths: bare `scripts/`, `briefs/`, `agents/`, `commands/` are in the pipeline plugin, `.claude/…` are the repo's (`briefs/core.md`)._

For every reviewer. Read with `briefs/core.md` (core).

## Reviewing: scope and completeness

**Read the delta, not the tree.** Your prompt names a diff file (written by `/pipeline:run-reviewers`),
a commit range, or a file list. Start from the diff file — or `git diff <range> -- <files>`
if you have `Bash` and no file was given — and read only what the diff touches. Widen to a whole file when the diff alone cannot settle a
question, or to verify a specific claim you are about to make (a caller that must exist, a
contract that must still hold) — and name in the finding which file you opened and why.

**Re-review after a fix pass:** judge whether the fix discharges your prior findings, plus
anything the fix itself introduced. A surface the fix did not touch has nothing new in it.

**Report every finding in the round you find it.** Do not hold a MINOR back "for the next
pass", do not open with a finding you then withdraw, and do not re-raise a finding the
previous round already recorded as deferred. Every BLOCKER and MAJOR is listed. **MINOR and NIT
are capped: at most 5 MINORs and 3 NITs, most consequential first**, then one line —
`Not listed: N MINOR, M NIT (<the kinds>)`. Each listed one becomes an issue draft the user
must triage, so a long tail costs more than it saves; a smell lint already reports (length, doc
budget, test shape) is not listed at all.

**Say what you could not check.** A path you had no way to exercise — an environment you
cannot change, a backend you cannot reach (no docker → testcontainers skipped) — is reported
as unchecked, not silently passed and not guessed at.

**Do not run `-race`.** The acceptance-review race gate owns it (core `briefs/core.md` → *Verification*). Report
a suspected race as a finding, with the interleaving that produces it.

## Severity

One contract for every reviewer; each reviewer's own file gives its domain examples.

- **BLOCKER** — data loss, cross-request leakage, reachable panic, silently wrong result,
  untested change, any change to a file under the spec's `**Excluded paths**`.
- **MAJOR** — defect with a constructible failure.
- **MINOR** — smell with no constructible failure.
- **NIT** — preference; never blocks.

A finding with no concrete failure is downgraded to MINOR and labeled as such. Only BLOCKER
and MAJOR block a gate.
