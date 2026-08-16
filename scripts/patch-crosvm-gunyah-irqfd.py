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
    matches: list[tuple[int, int]] = []
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
        depth = 0
        apex_end = None
        for idx in range(apex_start, end + 1):
            depth += lines[idx].count("[")
            depth -= lines[idx].count("]")
            if depth == 0:
                apex_end = idx
                break
        if apex_end is None:
            fail("unterminated apex_available property in root crosvm rust_binary block")
    else:
        apex_start = host_idx + 1
        apex_end = host_idx
        apex_indent = host_indent
        newline = line_ending(lines[host_idx])

    lines[apex_start : apex_end + 1] = [
        f"{apex_indent}apex_available: [{newline}",
        f'{apex_indent}    "//apex_available:platform",{newline}',
        f'{apex_indent}    "com.android.virt",{newline}',
        f"{apex_indent}],{newline}",
    ]
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
    mapping: dict[str, str] = {}
    for project in ET.parse(manifest).getroot().iter("project"):
        name = project.get("name")
        path = project.get("path") or name
        if name and path:
            mapping[path] = name
    if not mapping:
        fail(f"AOSP manifest contains no project mappings: {manifest}")
    return mapping


def repo_sync(aosp_root: Path, projects: list[str], jobs: int = 2) -> None:
    if not projects:
        return
    subprocess.run(
        [
            "repo",
            "sync",
            "-c",
            f"-j{jobs}",
            "--no-tags",
            "--no-clone-bundle",
            "--force-sync",
            *projects,
        ],
        cwd=aosp_root,
        check=True,
    )


def sync_native_dependency_closure(aosp_root: Path) -> None:
    # Native providers that are either direct crosvm Android dependencies or
    # common transitive requirements of bionic/graphics/HIDL in this reduced tree.
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
    absent = [path for path in required_paths if path not in project_map]
    if absent:
        fail(f"required dependency projects absent from AOSP manifest: {absent}")

    selected = list(required_paths)
    selected.extend(path for path in optional_paths if path in project_map)
    to_sync = [project_map[path] for path in selected if not (aosp_root / path).is_dir()]
    if to_sync:
        print("syncing native crosvm dependency closure:")
        for project in to_sync:
            print(f"  {project}")
        repo_sync(aosp_root, to_sync)

    missing = [path for path in required_paths if not (aosp_root / path).is_dir()]
    if missing:
        fail(f"native dependency projects still missing after repo sync: {missing}")
    print(f"native dependency closure present: {len(selected)} projects")


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
    failures: list[str] = []
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


def newest_aosp_clang(aosp_root: Path) -> Path:
    clang_root = aosp_root / "prebuilts/clang/host/linux-x86"
    candidates = [path for path in clang_root.glob("clang-r*/bin/clang") if path.is_file()]
    if not candidates:
        stable = clang_root / "clang-stable/bin/clang"
        if stable.is_file():
            return stable
        fail(f"cannot find AOSP clang under {clang_root}")

    def rank(path: Path) -> tuple[int, str]:
        match = re.search(r"clang-r(\d+)", path.as_posix())
        return (int(match.group(1)) if match else -1, path.as_posix())

    return max(candidates, key=rank)


def install_aaudio_abi_stub(aosp_root: Path) -> None:
    """Create a CI-only Android ARM64 libaaudio link provider.

    crosvm's android_audio Soong module links Android targets against libaaudio.
    The full frameworks/av graph is intentionally not part of this reduced build,
    so transiently sync the exact-tag AAudio symbol map, generate a minimal ARM64
    ELF exporting that ABI, then remove frameworks/av before Soong scans the tree.
    The prebuilt is installable:false; it exists only to satisfy the build link.
    """
    av_dir = aosp_root / "frameworks/av"
    if av_dir.is_dir() and project_defines_module(av_dir, "libaaudio"):
        print("using real frameworks/av libaaudio provider")
        return

    project_map = manifest_project_map(aosp_root)
    av_project = project_map.get("frameworks/av")
    if not av_project:
        fail("frameworks/av is absent from the AOSP manifest; cannot derive AAudio ABI")

    synced_here = not av_dir.is_dir()
    if synced_here:
        print("syncing transient frameworks/av for exact-tag AAudio ABI map")
        repo_sync(aosp_root, [av_project], jobs=1)

    try:
        maps = sorted(av_dir.rglob("libaaudio.map.txt"))
        if not maps:
            fail("frameworks/av contains no libaaudio.map.txt")
        preferred = av_dir / "media/libaaudio/src/libaaudio.map.txt"
        map_path = preferred if preferred.is_file() else maps[0]
        map_text = map_path.read_text(encoding="utf-8", errors="strict")
        symbols = sorted(
            set(re.findall(r"^\s*(AAudio[A-Za-z0-9_]+)\s*;", map_text, flags=re.MULTILINE))
        )
        if len(symbols) < 20:
            fail(f"AAudio ABI map yielded only {len(symbols)} exported symbols: {map_path}")
        print(f"AAudio ABI map: {map_path.relative_to(aosp_root)} ({len(symbols)} symbols)")
    finally:
        if synced_here and av_dir.exists():
            shutil.rmtree(av_dir)
            print("removed transient frameworks/av checkout before Soong scan")

    out = aosp_root / "local-crosvm-aaudio-stub"
    if out.exists():
        shutil.rmtree(out)
    libdir = out / "lib64"
    libdir.mkdir(parents=True)
    source = out / "aaudio_abi_stub.c"
    source.write_text(
        "#define EXPORT __attribute__((visibility(\"default\")))\n\n"
        + "\n".join(f"EXPORT void {symbol}(void) {{}}" for symbol in symbols)
        + "\n",
        encoding="utf-8",
    )
    dest = libdir / "libaaudio.so"
    clang = newest_aosp_clang(aosp_root)
    subprocess.run(
        [
            str(clang),
            "--target=aarch64-linux-android26",
            "-shared",
            "-fPIC",
            "-fno-stack-protector",
            "-nostdlib",
            "-Wl,-soname,libaaudio.so",
            "-Wl,--build-id=none",
            "-o",
            str(dest),
            str(source),
        ],
        cwd=aosp_root,
        check=True,
    )

    file_desc = subprocess.check_output(["file", "-b", str(dest)], text=True).strip()
    if not re.search(r"AArch64|ARM aarch64|ARM64", file_desc, flags=re.IGNORECASE):
        fail(f"generated libaaudio has wrong architecture: {file_desc}")
    dynamic = subprocess.check_output(["readelf", "-d", str(dest)], text=True)
    if "SONAME" not in dynamic or "libaaudio.so" not in dynamic:
        fail("generated libaaudio is missing SONAME libaaudio.so")
    dynsym = subprocess.check_output(["readelf", "-Ws", str(dest)], text=True)
    must_export = (
        "AAudio_createStreamBuilder",
        "AAudioStreamBuilder_openStream",
        "AAudioStream_requestStart",
    )
    missing_exports = [symbol for symbol in must_export if symbol not in dynsym]
    if missing_exports:
        fail(f"generated libaaudio is missing required exports: {missing_exports}")

    bp = out / "Android.bp"
    bp.write_text(
        """// Generated CI-only ARM64 AAudio ABI link provider for crosvm.
cc_prebuilt_library_shared {
    name: "libaaudio",
    visibility: ["//visibility:public"],
    compile_multilib: "64",
    arch: {
        arm64: {
            srcs: ["lib64/libaaudio.so"],
        },
    },
    system_shared_libs: [],
    stl: "none",
    strip: {
        none: true,
    },
    check_elf_files: false,
    installable: false,
    min_sdk_version: "26",
    apex_available: [
        "//apex_available:platform",
        "com.android.virt",
    ],
}
""",
        encoding="utf-8",
    )
    if not project_defines_module(out, "libaaudio"):
        fail("generated libaaudio Soong provider is not discoverable")
    print(f"generated ARM64 libaaudio link provider with {len(symbols)} exact-tag exports")


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
    restored: list[str] = []
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
    missing = [relative for relative in required_files if not (project / relative).is_file()]
    if missing:
        fail(f"hardware/interfaces graphics preflight missing files: {missing}")

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
    frozen = sorted(
        int(path.name) for path in api_root.iterdir() if path.is_dir() and path.name.isdigit()
    )
    if not frozen:
        fail("graphics common Stable AIDL has no frozen versions")

    if restored:
        print("restored pruned hardware/interfaces inputs: " + ", ".join(restored))
    print(
        "verified hardware/interfaces graphics inputs: current.txt + "
        "HIDL 1.0/1.1/1.2 + Stable AIDL"
    )


def validate_sqlite_icu(aosp_root: Path) -> None:
    sqlite_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (aosp_root / "external/sqlite").rglob("Android.bp")
    )
    if 'name: "libsqlite"' not in sqlite_text:
        fail("libsqlite provider missing after dependency closure")

    icu_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (aosp_root / "external/icu").rglob("Android.bp")
    )
    for module in ("libicuuc", "libicui18n"):
        if f'name: "{module}"' not in icu_text:
            fail(f"{module} provider missing after dependency closure")


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    aosp_root = root.parent.parent
    arch_path = root / "aarch64/src/lib.rs"
    gunyah_path = root / "hypervisor/src/gunyah/mod.rs"
    android_bp_path = root / "Android.bp"

    for path in (arch_path, gunyah_path, android_bp_path):
        if not path.is_file():
            fail(f"missing {path}")

    selective_aosp_checkout = (aosp_root / ".repo").is_dir()
    if selective_aosp_checkout:
        print("selective AOSP checkout: completing native Android dependency closure")
        sync_native_dependency_closure(aosp_root)
        restore_pruned_hardware_interface_inputs(aosp_root)
        validate_native_dependency_modules(aosp_root)
        install_aaudio_abi_stub(aosp_root)
        validate_sqlite_icu(aosp_root)
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
        "        }\n\n"
        + arch_anchor
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


if __name__ == "__main__":
    main()
