# Skills

The skills in `plugins/pipeline/skills/`, available as `pipeline:<name>`.

### `tdd`

Arguments: what to implement.

The red-green-refactor cycle. Used for a scenario's acceptance test, and for every unit test on the mandatory test-first set: bug fixes, security guards, atomic store adapters.

### `adr`

Arguments: the decision's title or description.

Creates an Architecture Decision Record in `docs/adr/`, from a description of the decision and its context or from a conversation that refines it.

### `api-conventions`

HTTP and REST boundary rules, stack-agnostic: controller shape, URL design, request and response modeling, validation ownership, status codes, HTTP semantics, idempotency. Used when designing or reviewing an endpoint, its DTOs or error payloads, or the line between input-format validation and domain rules.

### `legacy-code`

The approach of Michael Feathers' *Working Effectively With Legacy Code*, language-agnostic: adding tests to code that has none, untangling shared mutable state, replacing deprecated patterns, language and framework migrations, dependency rewrites.
