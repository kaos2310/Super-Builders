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

# The partial AOSP checkout used by CI does not otherwise need the whole
# system/hardware tree, but frozen soundtrigger AIDL validation requires
# android.media.soundtrigger.types from system/hardware/interfaces.
media_aidl_bp = aosp_root / "system/hardware/interfaces/media/Android.bp"
if not media_aidl_bp.is_file():
    repo = shutil.which("repo")
    if not repo:
        fail("repo launcher not found while system/hardware/interfaces is missing")
    print("syncing required AOSP project: platform/system/hardware/interfaces")
    subprocess.run(
        [
            repo,
            "sync",
            "-c",
            "-j4",
            "--no-tags",
            "--no-clone-bundle",
            "--force-sync",
            "platform/system/hardware/interfaces",
        ],
        cwd=aosp_root,
        check=True,
    )

if not media_aidl_bp.is_file():
    fail(f"missing {media_aidl_bp} after dependency sync")
if 'name: "android.media.soundtrigger.types"' not in media_aidl_bp.read_text():
    fail("android.media.soundtrigger.types definition missing after dependency sync")

# This workflow builds only the native crosvm binary. A full Android product
# dexpreopt graph is unnecessary and, in a selective checkout, can pull in the
# ART dex2oat toolchain solely while Soong analyzes dex_bootjars. Persist the
# supported Make variable for the following GitHub Actions build step.
github_env = os.environ.get("GITHUB_ENV")
if github_env:
    with open(github_env, "a", encoding="utf-8") as env_file:
        env_file.write("WITH_DEXPREOPT=false\n")
    print("GitHub Actions: WITH_DEXPREOPT=false")

arch = arch_path.read_text()
gunyah = gunyah_path.read_text()

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

arch_path.write_text(arch)
gunyah_path.write_text(gunyah)

print(f"patched: {arch_path}")
print(f"patched: {gunyah_path}")
