# A Direct-lane batch

A mechanical migration, replacing a deprecated error helper in three packages, run as a batch: one unit per package, no spec, no kickoff, no pipeline reviewers. The PR is reviewed like any other. `scripts/` is the plugin's `scripts/` directory.

## 1. Write the checklist

```bash
scripts/pipeline.py batch errors-migration --units services/core/todo,services/core/session,libs/httpkit
```

This writes `.runs/errors-migration/BATCH.md`, a checklist in that order, and prints the first unit:

```markdown
- [ ] services/core/todo
- [ ] services/core/session
- [ ] libs/httpkit
```

A long list comes from a file, one unit per line, with `--from-file`. To change the list later, edit the `- [ ] <unit>` lines by hand.

## 2. Change one package and test it

Change `services/core/todo` only. Run its tests, and only its tests, until they pass:

```bash
go test ./services/core/todo/...
```

## 3. Tick the unit

A unit is done only with the command that showed it green:

```bash
scripts/pipeline.py batch errors-migration --done services/core/todo --tests "go test ./services/core/todo/..."
```

It ticks the unit and prints the next one.

## 4. Draft an issue for anything found and not fixed

While migrating `services/core/session`, a handler turns out to swallow an error. That is not this migration. It becomes an issue draft at once:

```bash
scripts/pipeline.py batch errors-migration --found "session handler swallows the store error" --why "services/core/session/handler.go:88 returns nil when Delete fails, so a failed logout looks like a success." --trigger "the next change to services/core/session" --label bug
```

Drafts are filed only on the user's yes:

```bash
scripts/pipeline.py file-issues errors-migration --yes
```

## 5. Finish

When the last unit is ticked, the command reports that all units are done and exits `3`. Run the surface's full gates once, then open one PR for the whole batch.
