"""fake_go — `go` for the tests (`fakes.py`): enough of `go list` and `go test` for the plugin's scripts.

- `go list [-e] -f TEMPLATE PKG…`: each package directory read as Go would read it under the default
  build tags. A file whose `//go:build` constraint is not a negation is left out; `_test.go` files are
  TestGoFiles, or XTestGoFiles when their package ends `_test`. The template may name `.Dir`,
  `.ImportPath` and `len` of `.GoFiles`, `.CgoFiles`, `.TestGoFiles`, `.XTestGoFiles`.
- `go test … PKG…`: the first rule of `$FAKE_GO_RULES` whose texts all appear in the package's sources
  (an `-overlay` replaces a file as Go's would) gives the exit status and output; `-coverprofile=F`
  writes the rule's profile (`{module}` is the module path). No rule: it passes.
- `go env GOMODCACHE`: `$GOMODCACHE`, else a scratch path. Everything else exits 0.
"""

import json
import os
import re
import sys
from pathlib import Path

argv = sys.argv[1:]
cwd = Path.cwd()
with open(os.environ["FAKE_TOOLS_LOG"], "a") as log:
    log.write(json.dumps({"tool": "go", "argv": argv, "cwd": str(cwd)}) + "\n")

TAKES_VALUE = {"-f", "-run", "-timeout", "-overlay", "-covermode", "-coverprofile", "-tags", "-count", "-p"}


def flag(name: str) -> str | None:
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def packages() -> list[Path]:
    out, skip = [], False
    for a in argv[1:]:
        if skip:
            skip = False
            continue
        if a.startswith("-"):
            skip = a in TAKES_VALUE
            continue
        if a.endswith("/..."):
            base = cwd / a[:-4]
            out += sorted({p.parent for p in base.rglob("*.go")})
        else:
            out.append((cwd / a).resolve())
    return out


def module(d: Path) -> tuple[Path, str]:
    for p in [d, *d.parents]:
        if (p / "go.mod").is_file():
            m = re.search(r"^module\s+(\S+)", (p / "go.mod").read_text(), re.M)
            return p, m.group(1) if m else ""
    return d, ""


def overlay() -> dict[str, str]:
    path = flag("-overlay")
    return json.loads(Path(path).read_text()).get("Replace", {}) if path else {}


def source(path: Path, replace: dict[str, str]) -> str:
    return Path(replace.get(str(path), path)).read_text()


def included(text: str) -> bool:
    m = re.search(r"^//go:build\s+(.+)$", text, re.M)
    return not m or m.group(1).strip().startswith("!")


def go_list() -> int:
    template = flag("-f") or "{{.ImportPath}}"
    for d in packages():
        root, mod = module(d)
        files = sorted(d.glob("*.go")) if d.is_dir() else []
        texts = {f: f.read_text() for f in files}
        go = [f for f in files if not f.name.endswith("_test.go") and included(texts[f])]
        tests = [f for f in files if f.name.endswith("_test.go") and included(texts[f])]
        xtest = [f for f in tests if re.search(r"^package\s+\w+_test\b", texts[f], re.M)]
        rel = d.relative_to(root).as_posix()
        values = {".Dir": str(d), ".ImportPath": mod if rel == "." else f"{mod}/{rel}"}
        counts = {".GoFiles": len(go), ".CgoFiles": 0, ".TestGoFiles": len(tests) - len(xtest), ".XTestGoFiles": len(xtest)}
        line = re.sub(r"\{\{len (\.\w+)\}\}", lambda m: str(counts[m.group(1)]), template)
        print(re.sub(r"\{\{(\.\w+)\}\}", lambda m: values[m.group(1)], line))
    return 0


def go_test() -> int:
    replace = overlay()
    pkgs = packages() or [cwd]
    sources = {f.as_posix(): source(f, replace) for d in pkgs if d.is_dir() for f in d.glob("*.go")}
    rules = json.loads(Path(os.environ["FAKE_GO_RULES"]).read_text())
    rule = next((r for r in rules if all(any(p.endswith(suffix) and text in s for p, s in sources.items())
                                          for suffix, text in r["contains"].items())), None)
    rule = rule or {"exit": 0, "output": "\n".join(f"ok  \t{module(d)[1]}\t0.01s" for d in pkgs), "profile": ""}
    if (prof := flag("-coverprofile")):
        _, mod = module(pkgs[0])
        Path(prof).write_text(rule.get("profile", "").replace("{module}", mod) or "mode: set\n")
    if rule.get("output"):
        print(rule["output"])
    return rule.get("exit", 0)


command = argv[0] if argv else ""
if command == "list":
    sys.exit(go_list())
if command == "test":
    sys.exit(go_test())
if command == "env" and "GOMODCACHE" in argv:
    print(os.environ.get("GOMODCACHE") or Path(os.environ["FAKE_TOOLS_DIR"]) / "gomodcache")  # as Go reads it
sys.exit(0)
