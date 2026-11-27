# How to write a feature's retro

A build driven by `pipeline.py next` or the runner writes the retro as its last step. `/pipeline:retro` writes one on its own: for a single-session repo, where the conductor does not run, or for a feature whose retro was skipped.

## 1. Run the command when the feature closes

```
/pipeline:retro <feature-slug>
```

It needs `docs/specs/<feature-slug>.md`. With a run ledger under `.runs/<feature-slug>/` the retro is written from it. Without one, the evidence comes from the feature's merged PRs: their gate findings, review comments and fix commits.

## 2. Name the PRs when it finds the wrong ones

The PRs are the merged ones whose title, body or branch names the slug or one of the spec's issues. Pass them by number when that finds the wrong ones or none:

```
/pipeline:retro <feature-slug> --pr 41 --pr 44
```

## 3. Read and commit it

The retro is `docs/specs/<feature-slug>.retro.md`. The session reports the escaped defects and the rule candidates. Commit the retro with the feature, like its spec; the command never commits it.

When the retro is the fifth Full-lane retro since the last process review, the command says a process review is due: each open rule candidate is adopted as a script or dropped.
