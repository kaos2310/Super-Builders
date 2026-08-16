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
if len(sys.argv) < 2:
    raise SystemExit(f"usage: {Path(sys.argv[0]).name} <path-to-external/crosvm>")

crosvm = Path(sys.argv[1]).resolve()
if not crosvm.is_dir():
    raise SystemExit(f"ERROR: crosvm source directory not found: {crosvm}")
if crosvm.name != "crosvm" or crosvm.parent.name != "external":
    raise SystemExit(f"ERROR: expected <aosp>/external/crosvm, got: {crosvm}")

aosp_root = crosvm.parent.parent
bionic_bp = aosp_root / "bionic/libc/Android.bp"
if not bionic_bp.is_file():
    raise SystemExit(f"ERROR: missing Bionic build definition: {bionic_bp}")

bionic_text = bionic_bp.read_text(encoding="utf-8", errors="ignore")
if '//external/llvm-libc:llvmlibc' not in bionic_text:
    raise SystemExit("ERROR: expected Bionic dependency //external/llvm-libc:llvmlibc is absent")

# The selective checkout includes Bionic, but Android 16's libc_bionic also
# whole-archives //external/llvm-libc:llvmlibc. ALLOW_MISSING_DEPENDENCIES can
# postpone this omission until Ninja, so close and validate it before Soong.
print("Syncing Bionic dependency provider: platform/external/llvm-libc")
subprocess.run(
    [
        "repo",
        "sync",
        "-c",
        "-j2",
        "--no-tags",
        "--no-clone-bundle",
        "--force-sync",
        "platform/external/llvm-libc",
    ],
    cwd=aosp_root,
    check=True,
)

llvm_libc_bp = aosp_root / "external/llvm-libc/Android.bp"
if not llvm_libc_bp.is_file():
    raise SystemExit(f"ERROR: llvm-libc Android.bp missing after sync: {llvm_libc_bp}")
llvm_libc_text = llvm_libc_bp.read_text(encoding="utf-8", errors="ignore")
for required in (
    'name: "llvmlibc"',
    'system_shared_libs: []',
    'header_libs: ["libc_headers"]',
):
    if required not in llvm_libc_text:
        raise SystemExit(f"ERROR: llvm-libc provider validation failed: missing {required}")
print("Verified Bionic provider: //external/llvm-libc:llvmlibc")

subprocess.run([sys.executable, str(PREP), *sys.argv[1:]], check=True)
runpy.run_path(str(CORE), run_name="__main__")
