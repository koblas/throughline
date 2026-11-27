# How to set up for development

The plugin's scripts need Python 3.12 or later. Many tests drive `go`, `npx`, `git` and `ps` in scratch repos, so those must be on `PATH`. The documentation site needs [`uv`](https://docs.astral.sh/uv/).

## 1. Run the tests

```bash
make test
```

runs `python3 plugins/pipeline/tests/run.py`, sharded over one worker process per CPU.

## 2. Lint

```bash
uvx ruff@0.17.5 check
```

uses the repo's `ruff.toml`: bug-finding rules only, no formatter.

## 3. Build the site

```bash
make docs
```

runs `docs/check.py` and the strict site build. [How to write documentation](docs.md) covers the site.

## 4. Open a PR

The PR title is a [Conventional Commit](https://www.conventionalcommits.org/): PRs are squash-merged and release-please builds the changelog from the titles. [`CONTRIBUTING.md`](https://github.com/koblas/throughline/blob/main/CONTRIBUTING.md) lists the types.
