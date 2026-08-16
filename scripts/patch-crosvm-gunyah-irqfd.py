#!/usr/bin/env python3
from pathlib import Path
import os
import subprocess
import sys


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

    # Re-locate after the host edit so subsequent property ranges are always
    # scoped to the exact root crosvm module.
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
        # android-16.0.0_r4 has an explicit com.android.virt-only property, but
        # keep this fallback for nearby revisions where the property is inherited.
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
    print("selective AOSP checkout: ensuring rustc_linker host providers")
    required_projects = []
    if not (aosp_root / "external/sqlite").is_dir():
        required_projects.append("platform/external/sqlite")
    if not (aosp_root / "external/icu").is_dir():
        required_projects.append("platform/external/icu")
    if required_projects:
        subprocess.run(
            ["repo", "sync", "-c", "-j2", "--no-tags", "--no-clone-bundle", "--force-sync", *required_projects],
            cwd=aosp_root,
            check=True,
        )

    sqlite_bps = list((aosp_root / "external/sqlite").rglob("Android.bp"))
    sqlite_text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in sqlite_bps)
    if 'name: "libsqlite"' not in sqlite_text:
        fail("libsqlite provider missing after external/sqlite sync")

    icu_bps = list((aosp_root / "external/icu").rglob("Android.bp"))
    icu_text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in icu_bps)
    for module in ("libicuuc", "libicui18n"):
        if f'name: "{module}"' not in icu_text:
            fail(f"{module} provider missing after external/icu sync")

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
    # AOSP's root crosvm binary supports host variants and, at Android 16 r4,
    # is explicitly APEX-only (com.android.virt). A reduced module_arm64 graph
    # therefore either selects the host linux_glibc_x86_64 variant or exposes no
    # standalone `crosvm` target once host support is disabled.
    #
    # For this CI-only source checkout, keep the AVF APEX variant while also
    # exposing a platform Android64 variant, and disable host support only on
    # the root binary. Build-time host tools/proc-macros remain untouched.
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
