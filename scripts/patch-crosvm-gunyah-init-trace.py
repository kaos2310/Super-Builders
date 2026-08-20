#!/usr/bin/env python3
from pathlib import Path
import sys


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        fail(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


if len(sys.argv) != 2:
    fail(f"usage: {Path(sys.argv[0]).name} <path-to-external/crosvm>")

crosvm = Path(sys.argv[1]).resolve()
target = crosvm / "hypervisor/src/gunyah/aarch64.rs"
if not target.is_file():
    fail(f"Gunyah AArch64 source missing: {target}")

text = target.read_text(encoding="utf-8")
marker = "GUNYAH INIT: SET_DTB_CONFIG begin"
if marker in text:
    print(f"Gunyah init tracing already present in {target}")
    raise SystemExit(0)

old = '''        self.set_dtb_config(fdt_address, fdt_size)?;

        // Gunyah sets the PC to the payload entry point for protected VMs without firmware.
        // It needs to be 0 as Gunyah assumes it to be kernel start.
        if self.hv_cfg.protection_type.isolates_memory()
            && !self.hv_cfg.protection_type.runs_firmware()
            && payload_offset != 0
        {
            bail!("Payload offset must be zero");
        }

        if let Err(e) = self.set_boot_pc(payload_entry_address.offset()) {
            if e.errno() == ENOTTY {
                // GH_VM_SET_BOOT_CONTEXT ioctl is not supported, but returning success
                // for backward compatibility when the offset is zero.
                if payload_offset != 0 {
                    bail!("Payload offset must be zero");
                }
            } else {
                return Err(e).context("set_boot_pc failed");
            }
        }

        self.start()?;
'''

new = '''        error!(
            "GUNYAH INIT: begin payload={:#x} payload_offset={:#x} fdt={:#x} fdt_size={:#x} dtb_obj_offset={:#x} payload_obj_offset={:#x}",
            payload_entry_address.offset(),
            payload_offset,
            fdt_address.offset(),
            fdt_size,
            dtb_obj_offset,
            payload_obj_offset,
        );

        error!(
            "GUNYAH INIT: SET_DTB_CONFIG begin fdt={:#x} size={:#x}",
            fdt_address.offset(),
            fdt_size,
        );
        if let Err(e) = self.set_dtb_config(fdt_address, fdt_size) {
            error!(
                "GUNYAH INIT: SET_DTB_CONFIG FAILED errno={} error={:?}",
                e.errno(),
                e,
            );
            return Err(e).context("set_dtb_config failed");
        }
        error!("GUNYAH INIT: SET_DTB_CONFIG OK");

        // Gunyah sets the PC to the payload entry point for protected VMs without firmware.
        // It needs to be 0 as Gunyah assumes it to be kernel start.
        if self.hv_cfg.protection_type.isolates_memory()
            && !self.hv_cfg.protection_type.runs_firmware()
            && payload_offset != 0
        {
            bail!("Payload offset must be zero");
        }

        error!(
            "GUNYAH INIT: SET_BOOT_PC begin pc={:#x} payload_offset={:#x}",
            payload_entry_address.offset(),
            payload_offset,
        );
        match self.set_boot_pc(payload_entry_address.offset()) {
            Ok(()) => {
                error!("GUNYAH INIT: SET_BOOT_PC OK");
            }
            Err(e) if e.errno() == ENOTTY => {
                error!(
                    "GUNYAH INIT: SET_BOOT_PC ENOTTY fallback payload_offset={:#x}",
                    payload_offset,
                );
                // GH_VM_SET_BOOT_CONTEXT ioctl is not supported, but returning success
                // for backward compatibility when the offset is zero.
                if payload_offset != 0 {
                    bail!("Payload offset must be zero");
                }
            }
            Err(e) => {
                error!(
                    "GUNYAH INIT: SET_BOOT_PC FAILED errno={} error={:?}",
                    e.errno(),
                    e,
                );
                return Err(e).context("set_boot_pc failed");
            }
        }

        error!("GUNYAH INIT: GH_VM_START begin");
        if let Err(e) = self.start() {
            error!(
                "GUNYAH INIT: GH_VM_START FAILED errno={} error={:?}",
                e.errno(),
                e,
            );
            return Err(e).context("GH_VM_START failed");
        }
        error!("GUNYAH INIT: GH_VM_START OK");
'''

text = replace_once(text, old, new, "Gunyah init_arch trace")

checks = (
    "GUNYAH INIT: begin payload=",
    "GUNYAH INIT: SET_DTB_CONFIG begin",
    "GUNYAH INIT: SET_DTB_CONFIG FAILED errno=",
    "GUNYAH INIT: SET_DTB_CONFIG OK",
    "GUNYAH INIT: SET_BOOT_PC begin",
    "GUNYAH INIT: SET_BOOT_PC FAILED errno=",
    "GUNYAH INIT: SET_BOOT_PC ENOTTY fallback",
    "GUNYAH INIT: GH_VM_START begin",
    "GUNYAH INIT: GH_VM_START FAILED errno=",
    "GUNYAH INIT: GH_VM_START OK",
)
missing = [token for token in checks if token not in text]
if missing:
    fail(f"Gunyah init tracing verification failed: {missing}")

target.write_text(text, encoding="utf-8")
print(
    "Applied Gunyah init_arch tracing: SET_DTB_CONFIG + SET_BOOT_PC + "
    "GH_VM_START with errno diagnostics"
)
