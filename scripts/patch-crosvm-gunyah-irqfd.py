#!/usr/bin/env python3
# Full AOSP build wrapper for Android 16 r4 crosvm/Gunyah patches.
from pathlib import Path
import os
import re
import runpy
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PREP = HERE / "prepare-crosvm-binder-deps.py"
CORE = HERE / "patch-crosvm-gunyah-irqfd-core.py"
MEMORY = HERE / "patch-crosvm-gunyah-memory-contiguity.py"
CMA = HERE / "patch-crosvm-gunyah-cma-backport.py"


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def require_tokens(path: Path, tokens: tuple[str, ...], label: str) -> str:
    if not path.is_file():
        fail(f"{label} missing: {path}")
    text = path.read_text(encoding="utf-8", errors="ignore")
    missing = [token for token in tokens if token not in text]
    if missing:
        fail(f"{label} validation failed for {path}: {missing}")
    return text


def require_aidl_snapshot(root: Path, interface: str, version: int) -> None:
    path = root / "aidl_api" / interface / str(version)
    if not path.is_dir():
        fail(f"Stable AIDL snapshot missing: {path}")
    if not (path / ".hash").is_file():
        fail(f"Stable AIDL snapshot hash missing: {path / '.hash'}")


def require_aidl_current(root: Path, interface: str, generated_version: int) -> None:
    """Validate an unfrozen Stable-AIDL current version without inventing a frozen snapshot."""
    api_root = root / "aidl_api" / interface
    current = api_root / "current"
    if not current.is_dir():
        fail(f"Stable AIDL current API dump missing: {current}")

    frozen_versions = sorted(
        int(path.name)
        for path in api_root.iterdir()
        if path.is_dir() and path.name.isdigit()
    )
    if not frozen_versions:
        fail(f"Stable AIDL has no frozen snapshots: {api_root}")

    latest_frozen = frozen_versions[-1]
    expected_current = latest_frozen + 1
    if generated_version != expected_current:
        fail(
            f"Stable AIDL current version mismatch for {interface}: "
            f"generated V{generated_version}, expected V{expected_current} after frozen V{latest_frozen}"
        )

    # The latest frozen snapshot must remain hashed; the generated current version
    # intentionally lives under aidl_api/<interface>/current and has no V<N> snapshot yet.
    require_aidl_snapshot(root, interface, latest_frozen)
    print(
        f"Verified unfrozen Stable-AIDL {interface}: "
        f"current=V{generated_version}, latest_frozen=V{latest_frozen}"
    )


for helper in (PREP, CORE, MEMORY, CMA):
    if not helper.is_file():
        fail(f"required crosvm patch helper missing: {helper}")

if len(sys.argv) != 2:
    fail(f"usage: {Path(sys.argv[0]).name} <path-to-external/crosvm>")

crosvm = Path(sys.argv[1]).resolve()
if not crosvm.is_dir():
    fail(f"crosvm source directory not found: {crosvm}")
if crosvm.name != "crosvm" or crosvm.parent.name != "external":
    fail(f"expected <aosp>/external/crosvm, got: {crosvm}")

aosp_root = crosvm.parent.parent

# The workflow's minimal sync intentionally omits a few transitive providers.
# Close only those known gaps here; do not resync hardware/interfaces or crosvm.
bionic_bp = aosp_root / "bionic/libc/Android.bp"
require_tokens(bionic_bp, ('//external/llvm-libc:llvmlibc',), "Bionic build definition")

dependency_projects = (
    "platform/external/llvm-libc",
    "platform/system/libhidl",
    "platform/system/libhwbinder",
    "platform/system/libfmq",
)
print("Syncing deferred crosvm dependency providers: " + ", ".join(dependency_projects))
subprocess.run(
    [
        "repo", "sync", "-c", "-j2", "--no-tags", "--no-clone-bundle",
        "--force-sync", *dependency_projects,
    ],
    cwd=aosp_root,
    check=True,
)
require_tokens(
    aosp_root / "external/llvm-libc/Android.bp",
    ('name: "llvmlibc"', 'system_shared_libs: []', 'header_libs: ["libc_headers"]'),
    "llvm-libc provider",
)
print("Verified Bionic provider: //external/llvm-libc:llvmlibc")

# Restore the complete graphics provider closure because the crosvm build reaches
# libui/libgui transitively. This does not reintroduce unrelated hardware trees.
hw_interfaces = aosp_root / "hardware/interfaces"
if not (hw_interfaces / ".git").exists():
    fail(f"hardware/interfaces git worktree missing: {hw_interfaces}")
print("Restoring complete frameworks/native graphics HIDL/AIDL/stable-C provider closure")
subprocess.run(
    ["git", "checkout", "HEAD", "--", "graphics", "media/1.0"],
    cwd=hw_interfaces,
    check=True,
)

# Validate the generated Stable-AIDL aliases dynamically. Android 16 r4 exposes
# graphics-common V7 as the unfrozen current API: V7 is therefore NOT required as
# a literal `version: \"7\"` entry or aidl_api/.../7/.hash snapshot.
graphics_root = require_tokens(
    aosp_root / "hardware/interfaces/graphics/Android.bp",
    (
        'name: "android.hardware.graphics.allocator-latest"',
        'name: "android.hardware.graphics.common-latest"',
        'name: "android.hardware.graphics.allocator-ndk_static"',
        'name: "android.hardware.graphics.common-ndk_static"',
    ),
    "graphics Stable-AIDL defaults",
)
alloc_match = re.search(r'"android\.hardware\.graphics\.allocator-V(\d+)"', graphics_root)
common_match = re.search(r'"android\.hardware\.graphics\.common-V(\d+)"', graphics_root)
if not alloc_match or not common_match:
    fail("cannot derive graphics Stable-AIDL latest versions from graphics/Android.bp")
allocator_version = int(alloc_match.group(1))
graphics_common_version = int(common_match.group(1))

allocator_bp = aosp_root / "hardware/interfaces/graphics/allocator/aidl/Android.bp"
common_bp = aosp_root / "hardware/interfaces/graphics/common/aidl/Android.bp"
require_tokens(
    allocator_bp,
    (
        'name: "android.hardware.graphics.allocator"',
        'frozen: true',
        'ndk: {',
        f'version: "{allocator_version}"',
        '"android.hardware.common-V2"',
    ),
    "graphics allocator Stable-AIDL provider",
)
require_tokens(
    common_bp,
    (
        'name: "android.hardware.graphics.common"',
        'host_supported: true',
        'frozen: false',
        'ndk: {',
        '"android.hardware.common-V2"',
    ),
    "graphics common Stable-AIDL current provider",
)
require_aidl_snapshot(
    aosp_root / "hardware/interfaces/graphics/allocator/aidl",
    "android.hardware.graphics.allocator",
    allocator_version,
)
require_aidl_current(
    aosp_root / "hardware/interfaces/graphics/common/aidl",
    "android.hardware.graphics.common",
    graphics_common_version,
)
require_aidl_snapshot(
    aosp_root / "hardware/interfaces/common/aidl",
    "android.hardware.common",
    2,
)
print(
    "Verified graphics Stable-AIDL closure: "
    f"allocator-V{allocator_version} frozen + graphics-common-V{graphics_common_version} current"
)

# Recreate only ownership-team metadata missing from the partial checkout. Team
# definitions do not alter build semantics, but Soong requires every referenced team.
team_stub_root = aosp_root / "local-missing-teams"
if team_stub_root.exists():
    shutil.rmtree(team_stub_root)
team_stub_root.mkdir(parents=True, exist_ok=True)
ref_re = re.compile(r'\b(?:team|default_team)\s*:\s*"(?P<name>trendy_team_[^"]+)"')
name_re = re.compile(r'\bname\s*:\s*"(?P<name>trendy_team_[^"]+)"')
refs, defs = set(), set()
for base, dirs, files in os.walk(aosp_root):
    dirs[:] = [d for d in dirs if d not in {".repo", "out", "local-missing-teams"}]
    if "Android.bp" not in files:
        continue
    bp = Path(base) / "Android.bp"
    text = bp.read_text(encoding="utf-8", errors="ignore")
    refs.update(m.group("name") for m in ref_re.finditer(text))
    defs.update(m.group("name") for m in name_re.finditer(text))
missing_teams = sorted(refs - defs)
team_bp = team_stub_root / "Android.bp"
with team_bp.open("w", encoding="utf-8") as f:
    f.write("// Generated ownership-only team stubs after late provider closure.\n\n")
    for name in missing_teams:
        f.write("team {\n")
        f.write(f'    name: "{name}",\n')
        f.write(f'    trendy_team_id: "{name}",\n')
        f.write("}\n\n")
print(f"Refreshed {len(missing_teams)} missing trendy team stub(s)")

# Prepare exact-tag Binder/APEX stubs, then apply the patch chain in dependency order.
subprocess.run([sys.executable, str(PREP), str(crosvm)], check=True)
runpy.run_path(str(CORE), run_name="__main__")
subprocess.run([sys.executable, str(MEMORY), str(crosvm)], check=True)
subprocess.run([sys.executable, str(CMA), str(crosvm)], check=True)

# Fail closed on the source invariants required by the target device.
post_checks = {
    crosvm / "aarch64/src/lib.rs": ("reserve_irq(AARCH64_VMWDT_IRQ)",),
    crosvm / "hypervisor/src/gunyah/mod.rs": (
        "GUNYAH IRQFD add:",
        "GUNYAH IRQFD add failed:",
        "create_cma_compat_mem_fd",
    ),
    crosvm / "hypervisor/src/gunyah/gunyah_sys.rs": (
        "GH_ANDROID_CREATE_CMA_COMPAT_MEM_FD",
        "0x20",
    ),
    crosvm / "src/crosvm/sys/linux.rs": (
        "GUNYAH CMA: backing non-protected guest RAM with contiguous memory",
        "create_gunyah_cma_guest_memory",
        "&cfg.file_backed_mappings_ram",
    ),
    crosvm / "vm_memory/src/guest_memory.rs": (
        "new_with_options_and_file_fds",
        "libc::dup(*fd)",
    ),
}
for path, tokens in post_checks.items():
    require_tokens(path, tokens, "post-patch crosvm source")

print(
    "Applied Android 16 r4 crosvm/Gunyah patch chain: IRQ15 reservation + IRQFD logging + "
    "THP preconditioning + bounded-backing compatibility ioctl/GUP path"
)
