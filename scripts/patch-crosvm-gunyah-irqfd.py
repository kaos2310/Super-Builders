#!/usr/bin/env python3
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        fail(f"expected exactly one {label} anchor, found {count}")
    return text.replace(old, new, 1)


def find_root_crosvm_rust_binary(lines: list[str]) -> tuple[int, int]:
    matches = []
    for start, line in enumerate(lines):
        if line.strip() != "rust_binary {":
            continue
        depth = 0
        end = None
        for idx in range(start, len(lines)):
            depth += lines[idx].count("{")
            depth -= lines[idx].count("}")
            if depth == 0:
                end = idx
                break
        if end is None:
            fail(f"unterminated rust_binary block starting at line {start + 1}")
        block = lines[start : end + 1]
        if any(entry.strip() == 'name: "crosvm",' for entry in block):
            matches.append((start, end))
    if len(matches) != 1:
        fail(f"expected exactly one root crosvm rust_binary block, found {len(matches)}")
    return matches[0]


def line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    return "\n"


def make_root_crosvm_device_platform_available(android_bp: str) -> str:
    lines = android_bp.splitlines(keepends=True)
    start, end = find_root_crosvm_rust_binary(lines)

    host_lines = [
        idx
        for idx in range(start, end + 1)
        if lines[idx].strip() in ("host_supported: true,", "host_supported: false,")
    ]
    if len(host_lines) != 1:
        fail(
            "expected exactly one host_supported property in root crosvm "
            f"rust_binary block, found {len(host_lines)}"
        )
    host_idx = host_lines[0]
    host_indent = lines[host_idx][: len(lines[host_idx]) - len(lines[host_idx].lstrip())]
    newline = line_ending(lines[host_idx])
    lines[host_idx] = f"{host_indent}host_supported: false,{newline}"

    start, end = find_root_crosvm_rust_binary(lines)
    apex_starts = [
        idx
        for idx in range(start, end + 1)
        if lines[idx].lstrip().startswith("apex_available:")
    ]
    if len(apex_starts) > 1:
        fail(
            "expected at most one apex_available property in root crosvm "
            f"rust_binary block, found {len(apex_starts)}"
        )

    if apex_starts:
        apex_start = apex_starts[0]
        apex_indent = lines[apex_start][: len(lines[apex_start]) - len(lines[apex_start].lstrip())]
        newline = line_ending(lines[apex_start])
        bracket_depth = 0
        apex_end = None
        for idx in range(apex_start, end + 1):
            bracket_depth += lines[idx].count("[")
            bracket_depth -= lines[idx].count("]")
            if bracket_depth == 0:
                apex_end = idx
                break
        if apex_end is None:
            fail("unterminated apex_available property in root crosvm rust_binary block")
    else:
        apex_start = host_idx + 1
        apex_end = host_idx
        apex_indent = host_indent
        newline = line_ending(lines[host_idx])

    platform_apex = [
        f"{apex_indent}apex_available: [{newline}",
        f'{apex_indent}    "//apex_available:platform",{newline}',
        f'{apex_indent}    "com.android.virt",{newline}',
        f"{apex_indent}],{newline}",
    ]
    lines[apex_start : apex_end + 1] = platform_apex
    return "".join(lines)


def verify_root_crosvm_device_platform(android_bp: str) -> None:
    lines = android_bp.splitlines(keepends=True)
    start, end = find_root_crosvm_rust_binary(lines)
    block = "".join(lines[start : end + 1])
    required = (
        "host_supported: false,",
        '"//apex_available:platform"',
        '"com.android.virt"',
    )
    missing = [entry for entry in required if entry not in block]
    if missing:
        fail(f"root crosvm device/platform verification failed; missing {missing}")
    if "host_supported: true," in block:
        fail("root crosvm device/platform verification failed; host support still enabled")


def manifest_project_map(aosp_root: Path) -> dict[str, str]:
    candidates = (
        Path("/tmp/aosp-manifest.xml"),
        aosp_root / ".repo/manifests/default.xml",
        aosp_root / ".repo/manifest.xml",
    )
    manifest = next((path for path in candidates if path.is_file()), None)
    if manifest is None:
        fail("cannot locate AOSP manifest for dependency closure")
    tree = ET.parse(manifest)
    mapping: dict[str, str] = {}
    for project in tree.getroot().iter("project"):
        name = project.get("name")
        path = project.get("path") or name
        if name and path:
            mapping[path] = name
    if not mapping:
        fail(f"AOSP manifest contains no project mappings: {manifest}")
    return mapping


def sync_native_dependency_closure(aosp_root: Path) -> None:
    # Build the native Android closure up-front instead of letting
    # ALLOW_MISSING_DEPENDENCIES surface one provider per Ninja run.
    required_paths = (
        "external/sqlite",
        "external/icu",
        "external/gwp_asan",
        "external/scudo",
        "external/dtc",
        "external/libcxx",
        "external/libcxxabi",
        "external/compiler-rt",
        "external/selinux",
        "external/vulkan-headers",
        "external/libpng",
        "external/libyuv",
        "external/libjpeg-turbo",
        "external/flatbuffers",
        "hardware/libhardware",
        "system/libhidl",
        "system/libfmq",
        "system/libvintf",
        "system/libufdt",
        "system/libprocinfo",
        "system/librustutils",
        "system/unwinding",
        "system/media",
    )
    optional_paths = (
        "external/minigbm",
        "system/libhwbinder",
        "system/libziparchive",
        "system/memory/libdmabufheap",
        "system/memory/libion",
        "system/memory/libmeminfo",
        "system/memory/libmemtrack",
    )

    project_map = manifest_project_map(aosp_root)
    absent_from_manifest = [path for path in required_paths if path not in project_map]
    if absent_from_manifest:
        fail(f"required dependency projects absent from AOSP manifest: {absent_from_manifest}")

    selected_paths = list(required_paths)
    selected_paths.extend(path for path in optional_paths if path in project_map)
    to_sync = [
        project_map[path]
        for path in selected_paths
        if not (aosp_root / path).is_dir()
    ]
    if to_sync:
        print("syncing native crosvm dependency closure:")
        for project in to_sync:
            print(f"  {project}")
        subprocess.run(
            [
                "repo",
                "sync",
                "-c",
                "-j2",
                "--no-tags",
                "--no-clone-bundle",
                "--force-sync",
                *to_sync,
            ],
            cwd=aosp_root,
            check=True,
        )

    still_missing = [path for path in required_paths if not (aosp_root / path).is_dir()]
    if still_missing:
        fail(f"native dependency projects still missing after repo sync: {still_missing}")
    print(f"native dependency closure present: {len(selected_paths)} projects")


def project_defines_module(project: Path, module: str) -> bool:
    pattern = re.compile(r'\bname\s*:\s*"' + re.escape(module) + r'"')
    for bp in project.rglob("Android.bp"):
        try:
            text = bp.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if pattern.search(text):
            return True
    return False


def validate_native_dependency_modules(aosp_root: Path) -> None:
    checks = {
        "external/gwp_asan": ("gwp_asan_headers", "gwp_asan"),
        "external/scudo": ("libscudo",),
        "external/dtc": ("libfdt",),
        "system/libhidl": ("libhidlbase",),
        "system/unwinding": ("libunwindstack",),
        "external/selinux": ("libselinux",),
        "system/core": ("libprocessgroup",),
        "frameworks/native": ("libnativewindow",),
    }
    failures = []
    for relative, modules in checks.items():
        project = aosp_root / relative
        if not project.is_dir():
            failures.append(f"{relative}: project missing")
            continue
        for module in modules:
            if not project_defines_module(project, module):
                failures.append(f"{relative}: module {module} not defined")
    if failures:
        fail("native dependency preflight failed: " + "; ".join(failures))
    print(
        "verified native providers: gwp_asan/scudo/libfdt/libhidlbase/"
        "libunwindstack/libselinux/libprocessgroup/libnativewindow"
    )


def install_aaudio_abi_stub(aosp_root: Path) -> None:
    # libandroid_audio links to libaaudio on Android. Building frameworks/av
    # would pull a large product/audio graph, so use the AOSP NDK ARM64 ABI
    # stub for link-time only. The produced crosvm still records DT_NEEDED
    # libaaudio.so and resolves against the device's real system library.
    ndk = aosp_root / "prebuilts/ndk"
    if not ndk.is_dir():
        fail(f"NDK prebuilts missing: {ndk}")

    candidates = [
        path
        for path in ndk.rglob("libaaudio.so")
        if "aarch64-linux-android" in path.as_posix()
    ]
    if not candidates:
        fail("cannot find ARM64 libaaudio.so ABI stub under prebuilts/ndk")

    def api_rank(path: Path) -> tuple[int, str]:
        parts = path.parts
        api = -1
        for part in parts:
            if part.isdigit():
                api = max(api, int(part))
        return api, path.as_posix()

    source = max(candidates, key=api_rank)
    out = aosp_root / "local-crosvm-ndk-stubs"
    libdir = out / "lib64"
    libdir.mkdir(parents=True, exist_ok=True)
    dest = libdir / "libaaudio.so"
    shutil.copy2(source, dest)
    bp = out / "Android.bp"
    bp.write_text(
        """// Generated CI-only ARM64 AAudio ABI provider for crosvm.
cc_prebuilt_library_shared {
    name: "libaaudio",
    compile_multilib: "64",
    arch: {
        arm64: {
            srcs: ["lib64/libaaudio.so"],
        },
    },
    stl: "none",
    strip: {
        none: true,
    },
    check_elf_files: false,
    installable: false,
    apex_available: [
        "//apex_available:platform",
        "com.android.virt",
    ],
}
""",
        encoding="utf-8",
    )
    if not dest.is_file() or not bp.is_file():
        fail("failed to install local libaaudio ABI provider")
    if not project_defines_module(out, "libaaudio"):
        fail("generated libaaudio ABI provider is not discoverable")
    print(f"installed ARM64 libaaudio ABI provider from {source.relative_to(aosp_root)}")


def restore_pruned_hardware_interface_inputs(aosp_root: Path) -> None:
    project = aosp_root / "hardware/interfaces"
    if not project.is_dir():
        fail(f"hardware interfaces project missing: {project}")

    required_paths = (
        "current.txt",
        "Android.bp",
        "common/aidl",
        "graphics/Android.bp",
        "graphics/common/1.0",
        "graphics/common/1.1",
        "graphics/common/1.2",
        "graphics/common/aidl",
    )
    restored = []
    for relative in required_paths:
        path = project / relative
        if path.exists():
            continue
        result = subprocess.run(
            ["git", "checkout", "HEAD", "--", relative],
            cwd=project,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            fail(
                f"cannot restore required hardware/interfaces path {relative}: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        if not path.exists():
            fail(f"restored path is still missing: hardware/interfaces/{relative}")
        restored.append(relative)

    required_files = (
        "current.txt",
        "Android.bp",
        "common/aidl/Android.bp",
        "graphics/Android.bp",
        "graphics/common/1.0/Android.bp",
        "graphics/common/1.1/Android.bp",
        "graphics/common/1.2/Android.bp",
        "graphics/common/aidl/Android.bp",
    )
    missing_files = [relative for relative in required_files if not (project / relative).is_file()]
    if missing_files:
        fail(f"hardware/interfaces graphics preflight missing files: {missing_files}")

    current_txt = (project / "current.txt").read_text(encoding="utf-8", errors="ignore")
    if "android.hardware.graphics.common@1.0" not in current_txt:
        fail("hardware/interfaces/current.txt lacks graphics.common@1.0 HIDL hashes")

    hidl_markers = {
        "graphics/common/1.0/Android.bp": "android.hardware.graphics.common@1.0",
        "graphics/common/1.1/Android.bp": "android.hardware.graphics.common@1.1",
        "graphics/common/1.2/Android.bp": "android.hardware.graphics.common@1.2",
    }
    for relative, marker in hidl_markers.items():
        text = (project / relative).read_text(encoding="utf-8", errors="ignore")
        if marker not in text:
            fail(f"{relative} lacks expected HIDL module marker {marker}")

    aidl_text = (project / "graphics/common/aidl/Android.bp").read_text(
        encoding="utf-8", errors="ignore"
    )
    for marker in ('name: "android.hardware.graphics.common"', "host_supported: true"):
        if marker not in aidl_text:
            fail(f"graphics common AIDL definition lacks required marker: {marker}")

    api_root = project / "graphics/common/aidl/aidl_api/android.hardware.graphics.common"
    if not (api_root / "current").is_dir():
        fail(f"missing graphics common Stable AIDL current dump: {api_root / 'current'}")
    frozen_versions = sorted(
        int(path.name)
        for path in api_root.iterdir()
        if path.is_dir() and path.name.isdigit()
    )
    if not frozen_versions:
        fail("graphics common Stable AIDL has no frozen versions")

    if restored:
        print("restored pruned hardware/interfaces inputs: " + ", ".join(restored))
    print(
        "verified hardware/interfaces graphics inputs: current.txt + "
        "HIDL 1.0/1.1/1.2 + Stable AIDL"
    )


root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
aosp_root = root.parent.parent
arch_path = root / "aarch64/src/lib.rs"
gunyah_path = root / "hypervisor/src/gunyah/mod.rs"
android_bp_path = root / "Android.bp"

if not arch_path.is_file():
    fail(f"missing {arch_path}")
if not gunyah_path.is_file():
    fail(f"missing {gunyah_path}")
if not android_bp_path.is_file():
    fail(f"missing {android_bp_path}")

selective_aosp_checkout = (aosp_root / ".repo").is_dir()

if selective_aosp_checkout:
    print("selective AOSP checkout: completing native Android dependency closure")
    sync_native_dependency_closure(aosp_root)
    restore_pruned_hardware_interface_inputs(aosp_root)
    validate_native_dependency_modules(aosp_root)
    install_aaudio_abi_stub(aosp_root)

    sqlite_bps = list((aosp_root / "external/sqlite").rglob("Android.bp"))
    sqlite_text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in sqlite_bps)
    if 'name: "libsqlite"' not in sqlite_text:
        fail("libsqlite provider missing after dependency closure")

    icu_bps = list((aosp_root / "external/icu").rglob("Android.bp"))
    icu_text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in icu_bps)
    for module in ("libicuuc", "libicui18n"):
        if f'name: "{module}"' not in icu_text:
            fail(f"{module} provider missing after dependency closure")

    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a", encoding="utf-8") as env_file:
            env_file.write("WITH_DEXPREOPT=false\n")
        print("GitHub Actions: WITH_DEXPREOPT=false")
else:
    print("standalone crosvm checkout: skipping AOSP-only build settings")

arch = arch_path.read_text(encoding="utf-8", errors="ignore")
gunyah = gunyah_path.read_text(encoding="utf-8", errors="ignore")
android_bp = android_bp_path.read_text(encoding="utf-8", errors="ignore")

if selective_aosp_checkout:
    android_bp = make_root_crosvm_device_platform_available(android_bp)
    verify_root_crosvm_device_platform(android_bp)

if "const AARCH64_IRQ_BASE: u32 = 4;" not in arch:
    fail("AARCH64_IRQ_BASE is not 4")
if "const AARCH64_VMWDT_IRQ: u32 = 15;" not in arch:
    fail("AARCH64_VMWDT_IRQ is not 15")
if "reserve_irq(AARCH64_VMWDT_IRQ)" in arch:
    fail("VMWDT IRQ reservation is already present")

arch_anchor = "        let has_bios = matches!(components.vm_image, VmImage::Bios(_));\n"
arch_replacement = (
    "        // IRQ 15 is fixed for the ARM64 virtual watchdog. Reserve it before\n"
    "        // PCI/platform devices consume dynamically allocated IRQs starting at 4.\n"
    "        if !system_allocator.reserve_irq(AARCH64_VMWDT_IRQ) {\n"
    "            return Err(Error::AllocateIrq);\n"
    "        }\n\n" + arch_anchor
)
arch = replace_once(arch, arch_anchor, arch_replacement, "build_vm/has_bios")

for required_import in ("use base::info;", "use base::warn;"):
    if required_import not in gunyah:
        fail(f"required logging import missing: {required_import}")

if "GUNYAH IRQFD add:" in gunyah or "GUNYAH IRQFD add failed:" in gunyah:
    fail("Gunyah IRQFD diagnostic logging is already present")

register_anchor = (
    "    pub fn register_irqfd(&self, label: u32, evt: &Event, level: bool) -> Result<()> {\n"
    "        let gh_fn_irqfd_arg = gh_fn_irqfd_arg {\n"
)
register_replacement = (
    "    pub fn register_irqfd(&self, label: u32, evt: &Event, level: bool) -> Result<()> {\n"
    "        info!(\n"
    "            \"GUNYAH IRQFD add: label={} level={} fd={}\",\n"
    "            label,\n"
    "            level,\n"
    "            evt.as_raw_descriptor()\n"
    "        );\n\n"
    "        let gh_fn_irqfd_arg = gh_fn_irqfd_arg {\n"
)
gunyah = replace_once(gunyah, register_anchor, register_replacement, "register_irqfd")

failure_anchor = (
    "        } else {\n"
    "            errno_result()\n"
    "        }\n"
    "    }\n\n"
    "    pub fn unregister_irqfd"
)
failure_replacement = (
    "        } else {\n"
    "            warn!(\n"
    "                \"GUNYAH IRQFD add failed: label={} level={} fd={} ret={}\",\n"
    "                label,\n"
    "                level,\n"
    "                evt.as_raw_descriptor(),\n"
    "                ret\n"
    "            );\n"
    "            errno_result()\n"
    "        }\n"
    "    }\n\n"
    "    pub fn unregister_irqfd"
)
gunyah = replace_once(gunyah, failure_anchor, failure_replacement, "register_irqfd failure")

arch_path.write_text(arch, encoding="utf-8")
gunyah_path.write_text(gunyah, encoding="utf-8")
if selective_aosp_checkout:
    android_bp_path.write_text(android_bp, encoding="utf-8")
    verify_root_crosvm_device_platform(
        android_bp_path.read_text(encoding="utf-8", errors="ignore")
    )
    print("verified: root crosvm host_supported=false + platform/com.android.virt")
    print("=== Android.bp root crosvm CI diff ===")
    subprocess.run(["git", "diff", "--", "Android.bp"], cwd=root, check=True)

print(f"patched: {arch_path}")
print(f"patched: {gunyah_path}")
if selective_aosp_checkout:
    print(f"patched: {android_bp_path} (root crosvm Android platform device variant enabled)")
