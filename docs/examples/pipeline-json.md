# pipeline.json for four repos

Four complete `.claude/pipeline.json` files. Every key is on the [pipeline.json reference](../reference/pipeline-json.md). `docs/check.py` validates each block on this page with the plugin's own validator.

## A single Go service

The file `/pipeline:new-repo` writes for a product repo with one Go surface at the root. The correctness reviewer is the repo's own agent; the test reviewer is the one the plugin ships.

```json title=".claude/pipeline.json"
{
  "pass_conditions": [
    "gate_rounds <= 2",
    "dev_runs_max <= 8",
    "stops <= 1",
    "cost_per_scenario_usd <= 5"
  ],
  "feature_budget_usd": 75,
  "security_paths": "",
  "build_definitions": "",
  "generated_roots": [],
  "surfaces": {
    "go": {
      "language": "go",
      "root": ".",
      "changes": ["."],
      "production": {"include": ["**/*.go"], "exclude": ["**/*_test.go"]},
      "tests": {"include": ["**/*_test.go"]},
      "reviewers": {"correctness": "correctness-reviewer", "test": "pipeline:test-reviewer"},
      "covers": {"correctness": "production Go logic", "test": "Go tests"},
      "phase": [
        {"name": "build", "command": ["go", "build", "./..."]},
        {"name": "lint", "command": ["golangci-lint", "run"]},
        {"name": "test", "command": ["go", "test", "-count=1", "{cover}", "{packages}", "{run}"]}
      ],
      "full_gates": [
        {"name": "go build", "command": ["go", "build", "./..."]},
        {"name": "go lint", "command": ["golangci-lint", "run"]},
        {"name": "go test", "command": ["go", "test", "./..."]}
      ]
    }
  }
}
```

- `security_paths` and `build_definitions` are required; `""` says "none" explicitly.
- `phase` is what `check.py phase` runs on the packages a run touched. `full_gates` is the whole surface, run once per gate round.
- `{cover}`, `{packages}` and `{run}` are filled in by `check.py`: the coverage flags, the packages named, and a `-run` pattern.

## A Go and TypeScript monorepo

Two surfaces, generated code, security-sensitive paths, a codegen request, and per-edit formatting.

```json title=".claude/pipeline.json"
{
  "pass_conditions": ["gate_rounds <= 2", "dev_runs_max <= 8", "stops <= 1", "cost_per_scenario_usd <= 5"],
  "feature_budget_usd": 75,
  "security_paths": "^(go/services/auth/|go/libs/interceptors/|web/packages/auth/)",
  "build_definitions": "(^|/)Makefile$|(^|/)buf(\\.gen)?\\.yaml$",
  "generated_roots": ["go/gen/", "web/packages/api/"],
  "top_dirs": ["go", "web", "protos", "docs", ".claude"],
  "requests": {
    "codegen": {
      "command": ["make", "codegen"],
      "note": "After a codegen, grep both generated roots for the new symbol."
    }
  },
  "briefs": {
    "correctness-reviewer": ["proof.md", "storage.md"],
    "architect": ["navigation.md"]
  },
  "surfaces": {
    "go": {
      "language": "go",
      "root": "go",
      "changes": ["go", "protos"],
      "production": {"include": ["go/**/*.go"], "exclude": ["**/*_test.go", "go/gen/**"]},
      "tests": {"include": ["go/**/*_test.go"], "exclude": ["go/gen/**"]},
      "reviewers": {"correctness": "correctness-reviewer", "test": "pipeline:test-reviewer"},
      "covers": {"correctness": "production Go logic", "test": "Go tests"},
      "lint": {"include": ["go/**/*.go"], "command": ["golangci-lint", "run", "{package}"], "only_file": true},
      "format": {
        "include": ["go/**/*.go"],
        "tool": "go",
        "steps": [
          {"label": "gofmt {file}", "command": ["gofmt", "-w", "{abs}"], "cwd": ".", "timeout": 30},
          {"label": "go vet {package}", "command": ["go", "vet", "{package}"], "timeout": 120}
        ]
      },
      "phase": [
        {"name": "build", "command": ["go", "build", "./..."]},
        {"name": "tidy", "command": ["go", "mod", "tidy", "-diff"]},
        {"name": "lint", "command": ["golangci-lint", "run", "{packages/...}"]},
        {"name": "test", "command": ["go", "test", "-count=1", "-v", "{cover}", "{packages}", "{run}"]}
      ],
      "full_gates": [{"name": "go test-all", "command": ["make", "-C", "go", "test-all"]}]
    },
    "web": {
      "language": "ts",
      "root": "web",
      "changes": ["web", "protos"],
      "workspaces": ["web/packages/*"],
      "production": {
        "include": ["web/packages/**/src/**/*.ts", "web/packages/**/src/**/*.tsx"],
        "exclude": ["**/*.d.ts", "**/*.test.*", "web/packages/api/**"]
      },
      "tests": {"include": ["web/packages/**/*.test.ts", "web/packages/**/*.test.tsx"]},
      "reviewers": {"correctness": "ts-correctness-reviewer", "test": "ui-test-reviewer"},
      "covers": {"correctness": "production TypeScript logic", "test": "frontend tests"},
      "lint": {"command": ["npx", "--no-install", "eslint", "{surface_file}"], "only_file": false},
      "format": {
        "include": ["web/**/*.ts", "web/**/*.tsx"],
        "tool": "npx",
        "steps": [
          {"label": "prettier {file}", "command": ["npx", "--no-install", "prettier", "--write", "--log-level", "warn", "{abs}"], "timeout": 60}
        ]
      },
      "phase": [
        {"name": "tsc", "command": ["npx", "tsc", "-b", "--noEmit", "--force"]},
        {"name": "lint", "command": ["npx", "eslint", "packages/{workspace}"]},
        {"name": "test", "command": ["npm", "test", "-w", "@acme/{workspace}", "--", "--run", "{cover}", "{filter}"]}
      ],
      "test_related": ["npx", "--no-install", "vitest", "related", "{workspace_file}", "--run"],
      "full_gates": [
        {"name": "web test", "command": ["npm", "test", "--workspaces"]},
        {"name": "web lint", "command": ["npm", "run", "lint", "--workspaces"]}
      ],
      "ui": {"url": "http://localhost:5173", "start": ["npm", "run", "dev"]}
    }
  }
}
```

- `changes` lists `protos` on both surfaces: a proto change generates into each, so it makes both surfaces' full gates run.
- `generated_roots` keeps `go/gen/` and `web/packages/api/` out of the coverage and diff checks.
- `requests.codegen` is the one command a developer run can ask for by ending its reply `RUNNER: codegen`. A reply names a request; it never supplies a command.
- `build_definitions` matches the files that decide what `make codegen` does. A feature that edits one is refused the command until a person has read the change.
- `briefs` hands `storage.md` and `navigation.md`, the repo's own files under `.claude/briefs/`, to the agents named.
- `ui` on `web` makes the gate screenshot each screen state for the correctness reviewer.

## A Python surface through an adapter

`go` and `ts` are built in. Any other `language` names an `adapter`. [A language adapter](language-adapter.md) has the script.

```json title=".claude/pipeline.json"
{
  "pass_conditions": ["gate_rounds <= 2", "dev_runs_max <= 8", "stops <= 1", "cost_per_scenario_usd <= 5"],
  "feature_budget_usd": 50,
  "security_paths": "^src/acme/auth/",
  "build_definitions": "(^|/)pyproject\\.toml$",
  "surfaces": {
    "py": {
      "language": "python",
      "adapter": ["python3", ".claude/scripts/py-adapter.py"],
      "root": ".",
      "production": {"include": ["src/**/*.py"]},
      "tests": {"include": ["tests/**/test_*.py"]},
      "reviewers": {"correctness": "py-correctness-reviewer", "test": "py-test-reviewer"},
      "covers": {"correctness": "production Python logic", "test": "pytest tests"},
      "phase": [
        {"name": "lint", "command": ["ruff", "check", "{files}"]},
        {"name": "test", "command": ["pytest", "-q", "--cov=src", "--cov-report=json:{report}/coverage.json"]}
      ],
      "test_one": ["pytest", "-q", "{file}", "-k", "{name}"],
      "full_gates": [
        {"name": "ruff", "command": ["ruff", "check", "."]},
        {"name": "pytest", "command": ["pytest", "-q"]}
      ]
    }
  }
}
```

- `{files}` is the surface's changed files; `{report}` is a scratch directory the test step writes and the adapter's `coverage` operation reads.
- `test_one` runs a scenario's named acceptance test alone; exit 0 is a pass.
- Both reviewers are the repo's own: the plugin's `test-reviewer` reviews Go tests.

## A single-session repo

The work is done in the session; no conductor, no runner. `pass_conditions` and `feature_budget_usd` are left out, since only those two read them.

```json title=".claude/pipeline.json"
{
  "mode": "single-session",
  "security_paths": "",
  "build_definitions": "",
  "surfaces": {
    "go": {
      "language": "go",
      "root": ".",
      "production": {"include": ["**/*.go"], "exclude": ["**/*_test.go"]},
      "tests": {"include": ["**/*_test.go"]},
      "reviewers": {"correctness": "correctness-reviewer", "test": "pipeline:test-reviewer"},
      "format": {
        "include": ["**/*.go"],
        "tool": "go",
        "steps": [{"command": ["gofmt", "-w", "{abs}"]}]
      },
      "phase": [
        {"name": "build", "command": ["go", "build", "./..."]},
        {"name": "test", "command": ["go", "test", "-count=1", "{cover}", "{packages}", "{run}"]}
      ]
    }
  }
}
```

The per-edit hook, the acceptance-test lock, `check.py phase` and the diff-coverage check work the same as in pipeline mode. [How to use single-session mode](../guides/configure/single-session.md) covers the rest.
