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

# The workflow intentionally prunes hardware/interfaces after the initial sync.
# libgrallocusage still requires the legacy gralloc HIDL ABI. Restore only the
# interface definitions needed for allocator@2.0 -> mapper@2.0 -> common@1.0,
# rather than re-expanding the full hardware/interfaces product graph.
hw_interfaces = aosp_root / "hardware/interfaces"
if not (hw_interfaces / ".git").exists():
    raise SystemExit(f"ERROR: hardware/interfaces git worktree missing: {hw_interfaces}")

graphics_hidl_paths = (
    "graphics/allocator/2.0/Android.bp",
    "graphics/allocator/2.0/IAllocator.hal",
    "graphics/mapper/2.0/Android.bp",
    "graphics/mapper/2.0/IMapper.hal",
    "graphics/mapper/2.0/types.hal",
)
print("Restoring minimal legacy graphics HIDL interfaces")
subprocess.run(
    ["git", "checkout", "HEAD", "--", *graphics_hidl_paths],
    cwd=hw_interfaces,
    check=True,
)

# These HIDL interfaces are not self-contained: generated allocator/mapper
# libraries depend on libhidlbase/android.hidl.base@1.0, libhwbinder internals,
# and libfmq-base. Sync the three small provider projects explicitly so Ninja
# cannot defer another missing-provider failure.
legacy_hidl_projects = (
    "platform/system/libhidl",
    "platform/system/libhwbinder",
    "platform/system/libfmq",
)
print("Syncing legacy HIDL runtime providers: " + ", ".join(legacy_hidl_projects))
subprocess.run(
    [
        "repo",
        "sync",
        "-c",
        "-j2",
        "--no-tags",
        "--no-clone-bundle",
        "--force-sync",
        *legacy_hidl_projects,
    ],
    cwd=aosp_root,
    check=True,
)

provider_checks = {
    aosp_root / "hardware/interfaces/graphics/allocator/2.0/Android.bp": (
        'name: "android.hardware.graphics.allocator@2.0"',
        '"android.hardware.graphics.mapper@2.0"',
    ),
    aosp_root / "hardware/interfaces/graphics/mapper/2.0/Android.bp": (
        'name: "android.hardware.graphics.mapper@2.0"',
        '"android.hardware.graphics.common@1.0"',
    ),
    aosp_root / "hardware/interfaces/graphics/common/1.0/Android.bp": (
        'name: "android.hardware.graphics.common@1.0"',
    ),
    aosp_root / "system/libhidl/Android.bp": (
        'name: "libhidlbase"',
        'name: "libhidltransport"',
    ),
    aosp_root / "system/libhidl/transport/base/1.0/Android.bp": (
        'name: "android.hidl.base@1.0"',
    ),
    aosp_root / "system/libhwbinder/Android.bp": (
        'name: "libhwbinder-impl-internal"',
    ),
    aosp_root / "system/libfmq/Android.bp": (
        'name: "libfmq-base"',
    ),
}
for path, needles in provider_checks.items():
    if not path.is_file():
        raise SystemExit(f"ERROR: legacy HIDL provider missing: {path}")
    text = path.read_text(encoding="utf-8", errors="ignore")
    missing = [needle for needle in needles if needle not in text]
    if missing:
        raise SystemExit(f"ERROR: legacy HIDL provider validation failed for {path}: {missing}")

print(
    "Verified legacy graphics HIDL closure: "
    "allocator@2.0 -> mapper@2.0 -> common@1.0 + libhidlbase/libhwbinder/libfmq"
)

subprocess.run([sys.executable, str(PREP), *sys.argv[1:]], check=True)
runpy.run_path(str(CORE), run_name="__main__")
