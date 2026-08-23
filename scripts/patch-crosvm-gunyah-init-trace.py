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
if marker not in text:
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
    target.write_text(text, encoding="utf-8")
    print(
        "Applied Gunyah init_arch tracing: SET_DTB_CONFIG + SET_BOOT_PC + "
        "GH_VM_START with errno diagnostics"
    )
else:
    print(f"Gunyah init tracing already present in {target}")

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
text = target.read_text(encoding="utf-8")
missing = [token for token in checks if token not in text]
if missing:
    fail(f"Gunyah init tracing verification failed: {missing}")

# Diagnostic-only final DTB capture.  The finalized FDT is copied into a named
# anonymous memfd before it is written to GuestMemory.  The raw fd is intentionally
# left open until crosvm exits so a root-side watcher can copy /proc/<pid>/fd/<n>.
# This does not alter the FDT bytes, GuestMemory contents, or Gunyah VM lifecycle.
fdt_target = crosvm / "aarch64/src/fdt.rs"
if not fdt_target.is_file():
    fail(f"AArch64 FDT source missing: {fdt_target}")

fdt_text = fdt_target.read_text(encoding="utf-8")
fdt_marker = 'CString::new("avf-final-dtb")'
if fdt_marker not in fdt_text:
    fdt_old = '''    let fdt_final = fdt.finish()?;

    if let Some(file_path) = dump_device_tree_blob {
'''
    fdt_new = '''    let fdt_final = fdt.finish()?;

    // GUNYAH FDT DIAG: retain an exact copy of the finalized DTB in a named
    // memfd.  The successful raw fd is intentionally not closed; it remains
    // visible as /proc/<crosvm-pid>/fd/* until process exit for external capture.
    #[cfg(target_os = "android")]
    {
        let name = std::ffi::CString::new("avf-final-dtb")
            .expect("static diagnostic memfd name contains no NUL");
        let fd = unsafe { libc::memfd_create(name.as_ptr(), libc::MFD_CLOEXEC) };
        if fd >= 0 {
            let mut offset = 0usize;
            let mut complete = true;
            while offset < fdt_final.len() {
                let remaining = &fdt_final[offset..];
                let written = unsafe {
                    libc::write(
                        fd,
                        remaining.as_ptr() as *const libc::c_void,
                        remaining.len(),
                    )
                };
                if written <= 0 {
                    complete = false;
                    unsafe {
                        libc::close(fd);
                    }
                    break;
                }
                offset += written as usize;
            }
            if complete {
                // Reset the shared file offset so `cat /proc/<pid>/fd/<n>` starts
                // at byte zero.  A raw i32 fd has no Drop implementation, so
                // simply leaving it open retains the capture until crosvm exits.
                unsafe {
                    libc::lseek(fd, 0, libc::SEEK_SET);
                }
            }
        }
    }

    if let Some(file_path) = dump_device_tree_blob {
'''
    fdt_text = replace_once(fdt_text, fdt_old, fdt_new, "final FDT memfd capture")
    fdt_target.write_text(fdt_text, encoding="utf-8")
    print(f"Applied final DTB memfd capture to {fdt_target}")
else:
    print(f"Final DTB memfd capture already present in {fdt_target}")

fdt_text = fdt_target.read_text(encoding="utf-8")
fdt_checks = (
    'CString::new("avf-final-dtb")',
    "libc::memfd_create",
    "libc::write",
    "libc::lseek",
    "GUNYAH FDT DIAG",
)
fdt_missing = [token for token in fdt_checks if token not in fdt_text]
if fdt_missing:
    fail(f"final DTB memfd capture verification failed: {fdt_missing}")
