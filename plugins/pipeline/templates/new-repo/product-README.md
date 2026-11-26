# {{name}} product spec

The current truth about what {{name}} does, one file per area (`<area>.md`, matching an
`area:<area>` issue label). A feature spec under `docs/specs/` links here and does not restate it;
when a feature changes a rule, the area file changes in the same pull request.

Each area file holds:

- **Business rules** — what the product guarantees, stated as current behaviour.
- **Surface** — command, RPC, endpoint, field, event and screen names. Names outlive code, so they
  are ruled here before any is built.
- **Copy and voice** — every user-visible string the area owns.
- **Screen states** — `| Screen | State | Copy | Controls |`, with loading, empty, error and
  populated for every screen (where the area has screens).
- **Decisions** — dated, numbered entries (`D-<n> (YYYY-MM-DD): <decision> — <why>`). A decision
  that changes is amended in place with a new date, not appended as a contradiction.

## Not-built marks

A requirement written here but not built yet carries its open tracking issue inline:

```markdown
- Members can transfer ownership of an account. (not built: #123)
```

The pipeline plugin's `scripts/not-built.py` fails when a mark names no issue, or names one that
is closed or does not exist. Close the issue and remove the mark in the same pull request.

## Areas

| File | Covers |
| --- | --- |
