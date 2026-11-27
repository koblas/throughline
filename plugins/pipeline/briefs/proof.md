# Brief: proving a claim

_Paths: bare `scripts/`, `briefs/`, `agents/`, `commands/` are in the pipeline plugin, `.claude/…` are the repo's (`briefs/core.md`)._

For `developer` and the test / ui-test / correctness reviewers — what counts as evidence. Read with `briefs/core.md` (core).

## Mutation verification

A guard, a test, or an "absence" claim is proven by breaking the thing and seeing the
specific test go red — not by the suite being green.

**Save the original so a crash cannot leave the mutation behind. Copy it — do not stash.**
Every Bash call is a fresh shell, so the backup path must be **recomputable** in the restore
call, not held in a variable. Derive it from the worktree's git dir and the file's full
repo-relative path — both unique to this worktree and this file:

```bash
# backup call
R=$(git rev-parse --show-toplevel); F=<repo-relative path>
B="$(git rev-parse --absolute-git-dir)/mutation/$F"
test ! -e "$B" || { echo "stale backup $B — cmp it against the tree before touching either"; exit 1; }
mkdir -p "$(dirname "$B")" && cp "$R/$F" "$B" && test -f "$B" || exit 1
```

Apply the mutation (Edit is fine), run the targeted test, observe RED. Then:

```bash
# restore call — recompute, never remember
R=$(git rev-parse --show-toplevel); F=<repo-relative path>
B="$(git rev-parse --absolute-git-dir)/mutation/$F"
cp "$B" "$R/$F" && cmp "$B" "$R/$F" && rm "$B"   # byte-identical, then clear for the next guard
```

**Never locate a backup by glob or `ls`.** `$TMPDIR` is shared by every session and agent on
the machine, and many packages have a `handler.go`: `ls $TMPDIR/mutation-handler.go.* | tail -1`
once restored `core/sendemail/handler.go` over `core/todo/handler.go`. A `$$`-suffixed name
does not help — the restore call's `$$` is a different shell's. A linked worktree's git dir is
`.git/worktrees/<name>`, so the path above cannot collide across worktrees or files.

**A stale backup is data, not litter.** If the `test ! -e` guard fires, an earlier run crashed
mid-mutation and that file may be the only good copy. `cmp` it against the tree before
deleting anything.

Shortcuts, only under their preconditions:

- **Edit, then the inverse Edit** — fine for a one-hunk mutation, but take the backup and still
  run the restore call after the inverse Edit: a crash between the two Edits leaves the mutation
  live, `cmp` proves the inverse landed, and `rm` clears the path for the next guard.
- **`git checkout -- <file>`** restores from the index, so it is correct only if the file is
  tracked (`git ls-files --error-unmatch`) **and** `git diff --quiet -- <file>` passed before
  the mutation. Under "don't commit until asked" the file is usually modified or new, so this
  is the exception — check, do not assume.

**`git stash push -- <file>` is the wrong tool.** It reverts the file to `HEAD`, which
discards every uncommitted change in it — not just your mutation — and the stash stack is
shared across worktrees and sessions.

Rules:

- **Mutate only the guards the plan names.** The architect lists which guards need
  mutation verification; do not spread it to every branch you touched. If you find an
  unnamed guard that clearly needs it, do it and say why in the report.
- **Reviewers never mutate the worktree.** Reviewers run in parallel; a mutation in the
  shared tree poisons every concurrent run. Mutate a `git archive HEAD | tar -x -C
  "$TMPDIR/<unique>"` export instead. Only the developer (who runs alone) mutates in place.
- **Verify guards INDIVIDUALLY.** Two guards that only go red when BOTH are disabled means
  either can be deleted silently. Disable one at a time.
- A mutation that breaks compilation is **not** evidence. If every test fails, you proved
  the file parses, nothing more. Make the mutation surgical and still-valid.
- Say which mutation you ran and which test it reddened. "Mutation-verified" alone is not a
  claim anyone can check.
- **Run the affected file, not the whole suite.** A mutation targets one file; a full-suite run
  per check is the most repeated waste in a long scenario.
- **Two reddened tests are not two behaviours.** If a pair shares its Given, When and Then, it
  is one case named twice, and a mutation report counting both overstates the coverage
  verified. Check that each test you cite discriminates something the others do not.

## Assertions that prove nothing

Assertions that look like proof and are not recur in a few shapes:

- Asserting against a constant the fixture set, or a value copied out of the production
  code being tested. A pin derived by reading the code pins nothing.
- A library option set in code (an IDNA profile flag, a parser mode, a TLS or cookie
  option) with no row whose result changes when that option is flipped. Each option the
  code sets is a branch; flipping it is the mutation.
- Negative assertions satisfied by nothing happening at all — the dominant shape. An
  absence claim needs a **control arm** that shows the thing DOES happen when the guard is
  removed, and the control must differ from the claim in exactly one variable. **The default
  shape is one table**: the absent case is a row of the same `it.each` / Go table as the
  present case, differing in the one variable, so the probe is shown working in that test.
  Only an absence that cannot share a table names its control in a comment inside it —
  `// control: <title or func name of the sibling test in the same file>`.
  `scripts/absence-only.py` lists the new or changed tests that do neither: `scripts/check.py
  phase` fails on them in the developer's own run (the locked acceptance test excepted), and
  the checkpoint brief lists them under *Absence-only tests* for the surface's test
  reviewer. The reviewer rules on each: where a control exists and differs in
  one variable, name it and raise only a NIT for the missing comment; otherwise it is a
  MAJOR — the test passes with the code under test deleted. A test that names a control is
  not listed, so the script's silence is not proof: the reviewer still reads the diff.
- Observables that cannot fire on the path under test.
- Comparing against a value read from the code under test (a theme shade, a parsed literal,
  a looked-up label) without first guarding it non-empty — `toContain("")` passes against
  anything.
- Asserting a store is empty without first proving it was non-empty and that the same probe
  would have seen it.
- Comments overclaiming what the test below them covers.
- A substring assertion (`Contains`, unanchored regex) that sibling content could satisfy —
  a preheader, sign-off, footer or neighbouring paragraph carrying the same text. Anchor it to
  the element under test (e.g. `>\s*` + `QuoteMeta(text)` + `\s*</div>`, or an exact-one
  match), and check the text is not already present elsewhere in the output. (Distinct from
  `go-testing` → subset matchers, which is about collections, not rendered text.)
- The same trap over events: a `.last()` / most-recent-message assertion with no action or
  kind pin is satisfied by an earlier event of a different action carrying the same field
  (a fixture's REGISTER_TOKEN before the PASSWORD_CHANGE under test). Pin the action first;
  the mutation that proves it deletes the publish call (`briefs/planning.md`).

When a refactor removes a call site, **every existing `.not.toHaveBeenCalled()` on that
symbol becomes unfalsifiable.** Repoint them at the new reachable observable, or they pass
with the guard deleted.
