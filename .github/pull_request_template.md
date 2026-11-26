<!--
The PR title becomes the squash-merge commit message and feeds the changelog, so it must be a
Conventional Commit, e.g. `feat(runner): resume a stopped run` or `fix: ...`. See CONTRIBUTING.md.
-->

## What and why

## How it was tested

- [ ] `python3 -m unittest discover -s plugins/pipeline/tests` passes
- [ ] `ruff check .` passes
- [ ] `claude plugin validate .` passes (if manifests, agents, commands, hooks or skills changed)

## Notes for the reviewer
