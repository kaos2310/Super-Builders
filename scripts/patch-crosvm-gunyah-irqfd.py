#!/usr/bin/env python3
"""Pinned launcher for the known-good Android 16 r4 crosvm build wrapper.

The large dependency/preflight wrapper is frozen at a reviewed commit.  This
branch supplies the current CORE/MEMORY/CMA helpers from its own scripts/
directory, so small Gunyah fixes remain isolated and auditable.
"""
from pathlib import Path
import sys
import urllib.request

BASE_COMMIT = "e8e733757dcae2ff93c710217ee1703ed0eff4dd"
BASE_URL = (
    "https://raw.githubusercontent.com/kaos2310/Super-Builders/"
    f"{BASE_COMMIT}/scripts/patch-crosvm-gunyah-irqfd.py"
)

try:
    with urllib.request.urlopen(BASE_URL, timeout=30) as response:
        source = response.read().decode("utf-8")
except Exception as exc:
    raise SystemExit(f"ERROR: cannot fetch pinned crosvm wrapper {BASE_COMMIT}: {exc}")

# The frozen wrapper resolves PREP/CORE/MEMORY/CMA relative to __file__. Keep
# __file__ pointing at this branch's launcher so it consumes the fixed helpers.
namespace = {
    "__name__": "__main__",
    "__file__": str(Path(__file__).resolve()),
}
exec(compile(source, BASE_URL, "exec"), namespace, namespace)
