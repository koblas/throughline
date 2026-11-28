"""fakes — stand-ins for the toolchains the scripts call, so no test needs Go, Node or a linter.

    tools = fakes.install(self)                       # in setUp: fake go, gofmt, golangci-lint, npx, npm
    tools.go_test_rule({"a/a.go": "if !(n > 3)"}, exit=1, output="--- FAIL: Test_big")
    ...
    self.assertEqual([c["argv"][:2] for c in tools.calls("go")], [["test", "./a/"]])

`install` writes one launcher per tool into a scratch directory, puts it first on PATH for the test
(subprocesses inherit it), and removes it after. The real tools are never reached, whether or not they
are installed, so a test means the same on every machine and in CI.

- `go` is `fake_go.py`: `go list` reads the package directories as Go would (build constraints, test
  files, the module path), `go test` exits as the first matching rule says (each rule matches text in
  the package's sources, after any `-overlay`), `-coverprofile` writes the rule's profile, and
  everything else (`build`, `vet`, `env`, `mod`) succeeds quietly.
- every other tool is `fake_tool.py`: it exits 0, or as `tools.set(name, exit=…, output=…)` says;
  `report=` makes it write that istanbul json where `--coverage.reportsDirectory=` points, as vitest does.

Every call is logged as JSON (tool, argv, cwd) and read back with `calls()`.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
DEFAULT = ("go", "gofmt", "golangci-lint", "npx", "npm")


class FakeTools:
    def __init__(self, test, tools: tuple[str, ...]):
        tmp = tempfile.TemporaryDirectory(prefix="fake-tools.")
        test.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        self.log = self.dir / "calls.jsonl"
        self.rules = self.dir / "go-rules.json"
        self.rules.write_text("[]")
        for name in tools:
            self.add(name)
        env = {"PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}", "FAKE_TOOLS_LOG": str(self.log),
               "FAKE_GO_RULES": str(self.rules), "FAKE_TOOLS_DIR": str(self.dir)}
        patch = mock.patch.dict(os.environ, env)
        patch.start()
        test.addCleanup(patch.stop)

    def add(self, name: str) -> None:
        """Put one more fake tool on PATH."""
        script = HERE / ("fake_go.py" if name == "go" else "fake_tool.py")
        launcher = self.bin / name
        # run_path sets argv[0] to the script's own path, so the tool's name travels in the environment.
        launcher.write_text(f"#!{sys.executable}\nimport os, runpy\nos.environ['FAKE_TOOL_NAME'] = {name!r}\n"
                            f"runpy.run_path({str(script)!r}, run_name='__main__')\n")
        launcher.chmod(0o755)

    def set(self, name: str, exit: int = 0, output: str = "", report: dict | None = None) -> None:
        """How a `fake_tool.py` tool answers every call from now on."""
        (self.dir / f"{name}.json").write_text(json.dumps({"exit": exit, "output": output, "report": report}))

    def go_test_rule(self, contains: dict[str, str], exit: int = 0, output: str = "", profile: str = "") -> None:
        """`go test` exits `exit` and prints `output` when, for every suffix in `contains`, a source file of
        the package (after the overlay) ending with it holds the text. Rules are tried in the order added;
        with none matching, `go test` passes."""
        rules = json.loads(self.rules.read_text())
        rules.append({"contains": contains, "exit": exit, "output": output, "profile": profile})
        self.rules.write_text(json.dumps(rules))

    def calls(self, name: str | None = None) -> list[dict]:
        if not self.log.is_file():
            return []
        calls = [json.loads(line) for line in self.log.read_text().splitlines() if line.strip()]
        return [c for c in calls if name is None or c["tool"] == name]


def install(test, tools: tuple[str, ...] = DEFAULT) -> FakeTools:
    """Fake `tools` for the length of `test` (call from setUp)."""
    return FakeTools(test, tools)
