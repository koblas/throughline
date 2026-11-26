---
description: Set up the baseline a new repository starts from — the shared pipeline plugin enabled, a short CLAUDE.md, SECURITY.md, docs/product/ (product repos), a CI workflow and the standard issue labels. Asks whether it is a product or an infrastructure repo and, for a product repo, its surfaces; shows every file and label before writing, and never replaces an existing file without asking.
argument-hint: <optional — product | infrastructure, and anything already decided>
allowed-tools: Read, Glob, AskUserQuestion, Bash(${CLAUDE_PLUGIN_ROOT}/scripts/new-repo.py *), Bash(git rev-parse *)
---

Set up this repository's baseline. Already decided: **$ARGUMENTS**

The baseline: start from the shared plugin, a short CLAUDE.md, SECURITY.md, docs/product/, CI and
the labels. Infrastructure repos use the Direct lane only, with issues for debt.
`${CLAUDE_PLUGIN_ROOT}/scripts/new-repo.py` writes it (its docstring is the full reference); this
command asks the questions, shows the plan and gets the yes. Work from the repo root
(`git rev-parse --show-toplevel`); a directory that is not a git repository is refused — say so and
stop.

## 1. Look before asking

Glob the repo for what already exists: `CLAUDE.md`, `.claude/CLAUDE.md`, `.claude/settings.json`,
`.claude/pipeline.json`, `SECURITY.md`, `docs/product/`, `.github/workflows/`, and the build files
that name the surfaces (`go.mod`, `package.json`, their directories). Use them to propose answers,
not to skip asking.

## 2. Ask (one AskUserQuestion call, only what is not already decided)

1. **Kind** — *product* (runs the pipeline: features, specs, scenarios) or *infrastructure*
   (Direct lane only: config, deploys, manifests; debt in issues, no `.claude/pipeline.json`).
2. **Description** — one sentence on what the repo is. It heads CLAUDE.md and SECURITY.md.
3. **Product only — the surfaces**, each: a name, its language (`go` or `ts`; the pipeline knows
   no other), its root directory, and its build, test and (optional) lint commands, run from that
   root. Propose them from the build files found in step 1.
4. **Verify** — the commands CI runs from the repo root. A product repo defaults to each surface's
   build, lint and test; an infrastructure repo must name them (fleet's is a `kubectl kustomize`
   loop over every `kustomization.yaml`).

## 3. Show the plan

Write the answers as JSON (shape: the script's docstring) and run, sandboxed, without `--yes`:

```bash
${CLAUDE_PLUGIN_ROOT}/scripts/new-repo.py files --answers - <<'EOF'
{"kind": "...", "description": "...", "surfaces": {...}, "verify": [...]}
EOF
```

```bash
${CLAUDE_PLUGIN_ROOT}/scripts/new-repo.py labels --kind <kind>
```

`labels` calls `gh label list`: it needs `dangerouslyDisableSandbox: true` and a GitHub remote; a
repo with no remote yet skips the labels and says to run this step once it has one.

Show the user both plans as they print: each file with its action (`create`, `merge`, `append`,
`skip — … exists`), and each label (`create`, `exists`, `exists, differs`). Then ask one question
covering:

- go ahead with the plan as shown;
- for each `skip — <path> exists`: keep it (the default) or replace it (`--overwrite <path>`) —
  read the existing file and say what replacing it loses before asking;
- for each label that `exists, differs` (GitHub's default `bug`, typically): keep it or change it
  (`--update`).

Nothing is written before that answer.

## 4. Write

Run the same two commands with `--yes`, plus `--overwrite <path>` for each file the user chose to
replace and `--update` if they chose to change the differing labels. Both need
`dangerouslyDisableSandbox: true`: the sandbox denies every write to `.claude/settings.json`, and
`labels` calls `gh`. A `gh` failure is printed per label: report it and do not retry blindly.

## 5. Report

What was written, skipped and created, and what is left to the user:

- **Reviewers** the script lists as missing (a product repo's gate names a correctness and a test
  reviewer per surface; the plugin ships only `pipeline:test-reviewer`): each is one
  `/pipeline:new-reviewer <name>` before the first feature.
- `security_paths` and `build_definitions` in `.claude/pipeline.json` start empty; SECURITY.md's
  sections start as headings. Both are filled as the repo takes shape.
- The CI workflow sets up only the toolchains of the surfaces it knows; an infrastructure repo's
  may need its tool installed (add a step above *Verify*).

Never commit, push or open a pull request from this command: the files are left for the user to
review and commit.
