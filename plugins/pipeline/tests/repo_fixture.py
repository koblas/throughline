"""The repo config a scratch test repo needs: copies of content_buddy's, kept under fixtures/.

`install(root)` writes `<root>/.claude/pipeline.json` and `<root>/.claude/runner-settings.json`, the two
repo files the scripts read from the repo root (never from beside themselves).
"""

import json
import shutil
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CONFIG = FIXTURES / "pipeline.json"
PROFILE = FIXTURES / "runner-settings.json"


def install(root: Path, config: dict | None = None, profile: bool = True) -> Path:
    """Put the fixture config (or `config`) and the runner profile into the repo at `root`."""
    dot = Path(root) / ".claude"
    dot.mkdir(parents=True, exist_ok=True)
    if config is None:
        shutil.copyfile(CONFIG, dot / "pipeline.json")
    else:
        (dot / "pipeline.json").write_text(json.dumps(config, indent=1) + "\n")
    if profile:
        shutil.copyfile(PROFILE, dot / "runner-settings.json")
    return dot / "pipeline.json"


def content_buddy() -> dict:
    return json.loads(CONFIG.read_text())


# A Go-only repo at the module root (exemplar): one `go` surface rooted at `.`.
EXEMPLAR = {
    "pass_conditions": ["gate_rounds <= 2"],
    "feature_budget_usd": 40,
    "security_paths": "^internal/auth/",
    "build_definitions": "(^|/)Makefile$",
    "requests": {},
    "generated_roots": ["gen/"],
    "top_dirs": ["cmd", "internal", "docs", ".claude"],
    "surfaces": {
        "go": {
            "language": "go",
            "root": ".",
            "changes": ["."],
            "production": {"include": ["**/*.go"], "exclude": ["**/*_test.go", "gen/**"]},
            "tests": {"include": ["**/*_test.go"], "exclude": ["gen/**"]},
            "reviewers": {"correctness": "correctness-reviewer", "test": "pipeline:test-reviewer"},
            "covers": {"correctness": "production Go logic", "test": "Go tests"},
            "lint": {"include": ["**/*.go"], "command": ["golangci-lint", "run", "{package}"], "only_file": True},
            "format": {"include": ["**/*.go"], "exclude": ["gen/**"], "tool": "go",
                       "steps": [{"label": "gofmt {file}", "command": ["gofmt", "-w", "{abs}"], "timeout": 30},
                                 {"label": "go vet {package}", "command": ["go", "vet", "{package}"]}]},
            "phase": [{"name": "build", "command": ["go", "build", "./..."]},
                      {"name": "lint", "command": ["golangci-lint", "run", "{packages/...}"]},
                      {"name": "test", "command": ["go", "test", "-count=1", "-v", "{cover}", "{packages}", "{run}"]}],
            "full_gates": [{"name": "go test", "command": ["go", "test", "./..."]}],
        }
    },
}
