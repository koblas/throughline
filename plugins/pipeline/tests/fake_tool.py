"""fake_tool — any toolchain command a test fakes (`fakes.py`): log the call, answer as told, else exit 0."""

import json
import os
import sys
from pathlib import Path

name = Path(sys.argv[0]).name
with open(os.environ["FAKE_TOOLS_LOG"], "a") as log:
    log.write(json.dumps({"tool": name, "argv": sys.argv[1:], "cwd": os.getcwd()}) + "\n")
answer = Path(os.environ["FAKE_TOOLS_DIR"]) / f"{name}.json"
told = json.loads(answer.read_text()) if answer.is_file() else {}
if told.get("output"):
    print(told["output"])
sys.exit(told.get("exit", 0))
