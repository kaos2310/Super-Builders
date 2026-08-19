#!/usr/bin/env python3
# Full AOSP build wrapper; standalone source-only verification invokes the core helper directly.
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


if not PREP.is_file():
    fail(f"missing dependency preflight helper: {PREP}")
if not CORE.is_file():
    fail(f"missing crosvm patch core helper: {CORE}")
if not MEMORY.is_file():
    fail(f"missing Gunyah memory contiguity helper: {MEMORY}")
if len(sys.argv) < 2:
    fail(f"usage: {Path(sys.argv[0]).name} <path-to-external/crosvm>")

crosvm = Path(sys.argv[1]).resolve()
if not crosvm.is_dir():
    fail(f"crosvm source directory not found: {crosvm}")
if crosvm.name != "crosvm" or crosvm.parent.name != "external":
    fail(f"expected <aosp>/external/crosvm, got: {crosvm}")

aosp_root = crosvm.parent.parent
bionic_bp = aosp_root / "bionic/libc/Android.bp"
require_tokens(
    bionic_bp,
    ('//external/llvm-libc:llvmlibc',),
    "Bionic build definition",
)

# Close dependency projects intentionally omitted from the first minimal sync.
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

# Keep/restore the complete graphics subtree. The workflow already preserves it,
# but this makes the helper safe when invoked from other full-AOSP callers.
hw_interfaces = aosp_root / "hardware/interfaces"
if not (hw_interfaces / ".git").exists():
    fail(f"hardware/interfaces git worktree missing: {hw_interfaces}")
print("Restoring complete frameworks/native graphics HIDL/AIDL/stable-C provider closure")
subprocess.run(
    ["git", "checkout", "HEAD", "--", "graphics", "media/1.0"],
    cwd=hw_interfaces,
    check=True,
)

require_tokens(
    aosp_root / "frameworks/native/libs/ui/Android.bp",
    (
        '"android.hardware.graphics.allocator@2.0"',
        '"android.hardware.graphics.allocator@3.0"',
        '"android.hardware.graphics.allocator@4.0"',
        '"android.hardware.graphics.mapper@2.0"',
        '"android.hardware.graphics.mapper@2.1"',
        '"android.hardware.graphics.mapper@3.0"',
        '"android.hardware.graphics.mapper@4.0"',
        '"libimapper_stablec"',
        '"libimapper_providerutils"',
    ),
    "libui literal graphics dependency model",
)
require_tokens(
    aosp_root / "frameworks/native/libs/gui/Android.bp",
    (
        '"android.hardware.graphics.bufferqueue@1.0"',
        '"android.hardware.graphics.bufferqueue@2.0"',
        '"android.hidl.token@1.0-utils"',
    ),
    "libgui graphics dependency model",
)

provider_checks = {
    aosp_root / "hardware/interfaces/graphics/allocator/2.0/Android.bp": (
        'name: "android.hardware.graphics.allocator@2.0"',
        '"android.hardware.graphics.mapper@2.0"',
    ),
    aosp_root / "hardware/interfaces/graphics/allocator/3.0/Android.bp": (
        'name: "android.hardware.graphics.allocator@3.0"',
        '"android.hardware.graphics.mapper@3.0"',
        '"android.hardware.graphics.common@1.2"',
    ),
    aosp_root / "hardware/interfaces/graphics/allocator/4.0/Android.bp": (
        'name: "android.hardware.graphics.allocator@4.0"',
        '"android.hardware.graphics.mapper@4.0"',
        '"android.hardware.graphics.common@1.2"',
    ),
    aosp_root / "hardware/interfaces/graphics/mapper/stable-c/Android.bp": (
        'name: "libimapper_stablec"',
        'name: "libimapper_providerutils"',
        '"libarect_headers"',
        '"libbase_headers"',
    ),
    aosp_root / "hardware/interfaces/graphics/mapper/2.0/Android.bp": (
        'name: "android.hardware.graphics.mapper@2.0"',
        '"android.hardware.graphics.common@1.0"',
    ),
    aosp_root / "hardware/interfaces/graphics/mapper/2.1/Android.bp": (
        'name: "android.hardware.graphics.mapper@2.1"',
        '"android.hardware.graphics.mapper@2.0"',
        '"android.hardware.graphics.common@1.1"',
    ),
    aosp_root / "hardware/interfaces/graphics/mapper/3.0/Android.bp": (
        'name: "android.hardware.graphics.mapper@3.0"',
        '"android.hardware.graphics.common@1.2"',
    ),
    aosp_root / "hardware/interfaces/graphics/mapper/4.0/Android.bp": (
        'name: "android.hardware.graphics.mapper@4.0"',
        '"android.hardware.graphics.common@1.2"',
    ),
    aosp_root / "hardware/interfaces/graphics/common/1.0/Android.bp": (
        'name: "android.hardware.graphics.common@1.0"',
    ),
    aosp_root / "hardware/interfaces/graphics/common/1.1/Android.bp": (
        'name: "android.hardware.graphics.common@1.1"',
    ),
    aosp_root / "hardware/interfaces/graphics/common/1.2/Android.bp": (
        'name: "android.hardware.graphics.common@1.2"',
    ),
    aosp_root / "hardware/interfaces/graphics/bufferqueue/1.0/Android.bp": (
        'name: "android.hardware.graphics.bufferqueue@1.0"',
        '"android.hardware.media@1.0"',
        '"android.hidl.base@1.0"',
    ),
    aosp_root / "hardware/interfaces/graphics/bufferqueue/2.0/Android.bp": (
        'name: "android.hardware.graphics.bufferqueue@2.0"',
        '"android.hardware.graphics.common@1.2"',
        '"android.hidl.base@1.0"',
    ),
    aosp_root / "hardware/interfaces/media/1.0/Android.bp": (
        'name: "android.hardware.media@1.0"',
        '"android.hardware.graphics.common@1.0"',
    ),
    aosp_root / "system/libhidl/Android.bp": (
        'name: "libhidlbase"',
        'name: "libhidltransport"',
    ),
    aosp_root / "system/libhidl/transport/base/1.0/Android.bp": (
        'name: "android.hidl.base@1.0"',
    ),
    aosp_root / "system/libhidl/transport/token/1.0/utils/Android.bp": (
        'name: "android.hidl.token@1.0-utils"',
    ),
    aosp_root / "system/libhwbinder/Android.bp": (
        'name: "libhwbinder"',
        'name: "libhwbinder-impl-internal"',
    ),
    aosp_root / "system/libfmq/Android.bp": (
        'name: "libfmq-base"',
    ),
}
for path, tokens in provider_checks.items():
    require_tokens(path, tokens, "graphics/HIDL provider")

graphics_root = require_tokens(
    aosp_root / "hardware/interfaces/graphics/Android.bp",
    (
        'name: "android.hardware.graphics.allocator-latest"',
        'name: "android.hardware.graphics.common-latest"',
        'name: "android.hardware.graphics.allocator-ndk_static"',
        'name: "android.hardware.graphics.allocator-ndk_shared"',
        'name: "android.hardware.graphics.common-ndk_static"',
        'name: "android.hardware.graphics.common-ndk_shared"',
    ),
    "graphics Stable-AIDL defaults",
)

alloc_match = re.search(r'"android\.hardware\.graphics\.allocator-V(\d+)"', graphics_root)
common_match = re.search(r'"android\.hardware\.graphics\.common-V(\d+)"', graphics_root)
if not alloc_match or not common_match:
    fail("cannot derive graphics Stable-AIDL latest versions from graphics/Android.bp")
allocator_version = int(alloc_match.group(1))
graphics_common_version = int(common_match.group(1))

allocator_ndk = f"android.hardware.graphics.allocator-V{allocator_version}-ndk"
graphics_common_ndk = f"android.hardware.graphics.common-V{graphics_common_version}-ndk"
for generated in (allocator_ndk, graphics_common_ndk):
    if f'"{generated}"' not in graphics_root:
        fail(f"generated graphics NDK default missing from graphics/Android.bp: {generated}")

require_tokens(
    aosp_root / "hardware/interfaces/graphics/allocator/aidl/Android.bp",
    (
        'name: "android.hardware.graphics.allocator"',
        'frozen: true',
        'ndk: {',
        f'version: "{allocator_version}"',
        '"android.hardware.common-V2"',
        f'"android.hardware.graphics.common-V{graphics_common_version}"',
    ),
    "graphics allocator Stable-AIDL provider",
)
require_tokens(
    aosp_root / "hardware/interfaces/graphics/common/aidl/Android.bp",
    (
        'name: "android.hardware.graphics.common"',
        'ndk: {',
        f'version: "{graphics_common_version}"',
        '"android.hardware.common-V2"',
    ),
    "graphics common Stable-AIDL provider",
)
require_tokens(
    aosp_root / "hardware/interfaces/common/aidl/Android.bp",
    ('name: "android.hardware.common"', 'ndk: {'),
    "hardware common Stable-AIDL provider",
)

require_aidl_snapshot(aosp_root / "hardware/interfaces/common/aidl", "android.hardware.common", 2)
require_aidl_snapshot(
    aosp_root / "hardware/interfaces/graphics/common/aidl",
    "android.hardware.graphics.common",
    graphics_common_version,
)
require_aidl_snapshot(
    aosp_root / "hardware/interfaces/graphics/allocator/aidl",
    "android.hardware.graphics.allocator",
    allocator_version,
)
print(
    "Verified generated Stable-AIDL providers: "
    f"android.hardware.common-V2, {graphics_common_ndk}, {allocator_ndk}"
)

require_tokens(
    aosp_root / "frameworks/native/libs/arect/Android.bp",
    ('name: "libarect_headers"',),
    "libarect_headers provider",
)
require_tokens(
    aosp_root / "system/libbase/Android.bp",
    ('name: "libbase_headers"',),
    "libbase_headers provider",
)

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

print(
    "Verified graphics/HIDL follow-on closure: "
    "legacy allocator/mapper/bufferqueue + stable-C IMapper + "
    f"allocator-V{allocator_version}/graphics-common-V{graphics_common_version} Stable AIDL + "
    "media@1.0 + libhidl/libhwbinder/libfmq"
)

subprocess.run([sys.executable, str(PREP), *sys.argv[1:]], check=True)
runpy.run_path(str(CORE), run_name="__main__")
subprocess.run([sys.executable, str(MEMORY), *sys.argv[1:]], check=True)
if CMA.is_file():
    subprocess.run([sys.executable, str(CMA), *sys.argv[1:]], check=True)
