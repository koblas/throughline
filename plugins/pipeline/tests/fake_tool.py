"""fake_tool — any toolchain command a test fakes (`fakes.py`): log the call, answer as told, else exit 0.

Told a `report`, it writes it as `coverage-final.json` into the `--coverage.reportsDirectory=DIR` it was
passed, as vitest's json reporter would.
"""

import json
import os
import sys
from pathlib import Path

name = os.environ.get("FAKE_TOOL_NAME") or Path(sys.argv[0]).name
with open(os.environ["FAKE_TOOLS_LOG"], "a") as log:
    log.write(json.dumps({"tool": name, "argv": sys.argv[1:], "cwd": os.getcwd()}) + "\n")
answer = Path(os.environ["FAKE_TOOLS_DIR"]) / f"{name}.json"
told = json.loads(answer.read_text()) if answer.is_file() else {}
if told.get("report") is not None:
    for arg in sys.argv[1:]:
        if arg.startswith("--coverage.reportsDirectory="):
            out = Path(arg.split("=", 1)[1])
            out.mkdir(parents=True, exist_ok=True)
            (out / "coverage-final.json").write_text(json.dumps(told["report"]))
if told.get("output"):
    print(told["output"])
sys.exit(told.get("exit", 0))
