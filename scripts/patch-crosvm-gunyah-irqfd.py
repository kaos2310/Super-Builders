#!/usr/bin/env python3
from pathlib import Path
import os
import shutil
import subprocess
import sys


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        fail(f"expected exactly one {label} anchor, found {count}")
    return text.replace(old, new, 1)


root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
aosp_root = root.parent.parent
arch_path = root / "aarch64/src/lib.rs"
gunyah_path = root / "hypervisor/src/gunyah/mod.rs"

if not arch_path.is_file():
    fail(f"missing {arch_path}")
if not gunyah_path.is_file():
    fail(f"missing {gunyah_path}")

# The full build workflow uses a selective AOSP repo checkout. Some Soong
# analysis paths still require metadata/tooling projects that are not direct
# crosvm source dependencies. Keep those build-only concerns out of the
# standalone patch verifier by acting only when a real repo checkout exists.
if (aosp_root / ".repo").is_dir():
    repo = shutil.which("repo")
    if not repo:
        fail("repo launcher not found in AOSP checkout")

    # The workflow historically synced packages/modules/Virtualization only
    # because the final device uses com.android.virt. Building the standalone
    # crosvm binary does not require AVF's Java framework/bootclasspath modules.
    # Leaving that tree visible makes Soong analyze framework-virtualization and
    # drags in Error Prone, dex2oat and bootclasspath-fragment requirements that
    # are unrelated to the crosvm binary target. Remove only the worktree from
    # this partial checkout; repo metadata remains untouched.
    virtualization_dir = aosp_root / "packages/modules/Virtualization"
    if virtualization_dir.is_dir():
        print("excluding non-crosvm AVF Java build graph: packages/modules/Virtualization")
        shutil.rmtree(virtualization_dir)
    if virtualization_dir.exists():
        fail(f"failed to exclude {virtualization_dir}")

    # Error Prone is needed by remaining Java modules. Protobuf's linker-safe
    # notls variants inherit their com.android.runtime APEX availability from
    # absl_notls_defaults in external/abseil-cpp; without that defaults module,
    # ALLOW_MISSING_DEPENDENCIES can hide the missing source while losing the
    # inherited apex_available metadata and later fail bionic's runtime APEX.
    error_prone_bp = aosp_root / "external/error_prone/Android.bp"
    abseil_bp = aosp_root / "external/abseil-cpp/Android.bp"
    projects = []
    if not error_prone_bp.is_file():
        projects.append("platform/external/error_prone")
    if not abseil_bp.is_file():
        projects.append("platform/external/abseil-cpp")

    if projects:
        print("syncing required AOSP project(s): " + " ".join(projects))
        subprocess.run(
            [
                repo,
                "sync",
                "-c",
                "-j4",
                "--no-tags",
                "--no-clone-bundle",
                "--force-sync",
                *projects,
            ],
            cwd=aosp_root,
            check=True,
        )

    if not error_prone_bp.is_file():
        fail(f"missing {error_prone_bp} after dependency sync")
    if not abseil_bp.is_file():
        fail(f"missing {abseil_bp} after dependency sync")

    abseil_text = abseil_bp.read_text(encoding="utf-8", errors="ignore")
    if 'name: "absl_notls_defaults"' not in abseil_text:
        fail("absl_notls_defaults definition missing after dependency sync")
    if '"com.android.runtime"' not in abseil_text:
        fail("absl_notls_defaults source lacks com.android.runtime APEX availability")
    print("verified Abseil notls defaults for com.android.runtime")

    # This is a native crosvm-only target. Keep product dexpreopt disabled now
    # that AVF's bootclasspath fragment has intentionally been excluded, which
    # also prevents the unrelated global dex_bootjars/dex2oat dependency.
    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a", encoding="utf-8") as env_file:
            env_file.write("WITH_DEXPREOPT=false\n")
        print("GitHub Actions: WITH_DEXPREOPT=false")
else:
    print("standalone crosvm checkout: skipping AOSP-only dependency handling")

arch = arch_path.read_text(encoding="utf-8", errors="ignore")
gunyah = gunyah_path.read_text(encoding="utf-8", errors="ignore")

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
    "        }\n"
    "\n"
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
    "        );\n"
    "\n"
    "        let gh_fn_irqfd_arg = gh_fn_irqfd_arg {\n"
)
gunyah = replace_once(gunyah, register_anchor, register_replacement, "register_irqfd")

failure_anchor = (
    "        } else {\n"
    "            errno_result()\n"
    "        }\n"
    "    }\n"
    "\n"
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
    "    }\n"
    "\n"
    "    pub fn unregister_irqfd"
)
gunyah = replace_once(gunyah, failure_anchor, failure_replacement, "register_irqfd failure")

arch_path.write_text(arch, encoding="utf-8")
gunyah_path.write_text(gunyah, encoding="utf-8")

print(f"patched: {arch_path}")
print(f"patched: {gunyah_path}")
