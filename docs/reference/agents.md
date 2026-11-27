# Agents

The agents in `plugins/pipeline/agents/`, spawned as `pipeline:<name>`. A repo's own agents, such as its surface reviewers, are spawned by their bare name.

### `triage`

Scopes a request against the codebase before any design: locates the affected services, packages and screens, finds prior art in the repo, reproduces a bug when there is one, and reports what exists against what must be built. Read-only. Runs first on any request that might be a feature or a behavior change, and ends with the lane.

### `product-vision`

Rules a feature's surface and copy at scoping, after the kickoff: names, codes, copy, screen states and dated decisions, written into `docs/product/<area>.md`. Edits only `docs/product/`; writes no code and gives no verdict on the finished code.

### `architect`

Turns one approved scenario into an ordered implementation checklist, `SCENARIO-XX.md`: the acceptance test first, then behavior batches in the cadence the build brief assigns. Reads the specification, the product spec it links and the triage brief. Writes no code.

### `developer`

Implements one scenario by executing the architect's checklist, or, in fix mode, applies the consolidated reviewer findings. Takes the feature slug and scenario ID from the invoking prompt.

### `test-reviewer`

Reviews the Go tests: that the change is tested at all, that bug fixes, security guards and atomic store adapters have a test that went red first, that corner cases are covered, and that structure, naming and fakes follow the project conventions. Returns ranked findings; writes no tests.

### `refuter`

Tries to prove each MAJOR finding of a gate round wrong before it costs a fix pass. Reads the code and tests each one names and answers STANDS or REFUTED with the evidence. `pipeline.py next` runs it once per gate round that has reviewer MAJORs. Raises no findings and changes no files.

### `pipeline-reviewer`

Reviews changes to the pipeline itself (`.claude/` and the plugin): contradictions between files, policy stated twice instead of cited, pointers to sections or files that no longer exist, rules loaded into every context when one agent needs them, and scripts whose documented behavior no longer matches. Also writes the post-feature retro from a feature's `METRICS.md`. Returns ranked findings; does not rewrite files.
