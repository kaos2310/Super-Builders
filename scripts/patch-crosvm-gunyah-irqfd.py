#!/usr/bin/env python3
from pathlib import Path
import runpy
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PREP = HERE / "prepare-crosvm-binder-deps.py"
CORE = HERE / "patch-crosvm-gunyah-irqfd-core.py"

if not PREP.is_file():
    raise SystemExit(f"ERROR: missing dependency preflight helper: {PREP}")
if not CORE.is_file():
    raise SystemExit(f"ERROR: missing crosvm patch core helper: {CORE}")

subprocess.run([sys.executable, str(PREP), *sys.argv[1:]], check=True)
runpy.run_path(str(CORE), run_name="__main__")
