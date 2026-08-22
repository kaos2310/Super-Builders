#!/usr/bin/env python3
from pathlib import Path
import runpy
import sys


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


if len(sys.argv) != 2:
    fail(f"usage: {Path(sys.argv[0]).name} <path-to-external/crosvm>")

root = Path(sys.argv[1]).resolve()
linux_rs = root / "src/crosvm/sys/linux.rs"
base_transform = Path(__file__).resolve().with_name("patch-crosvm-gunyah-cma-base.py")
if not linux_rs.is_file():
    fail(f"crosvm Linux runner source missing: {linux_rs}")
if not base_transform.is_file():
    fail(f"pinned local CMA base transform missing: {base_transform}")

marker = "GUNYAH CMA: backing non-protected guest RAM with contiguous memory"
if marker not in linux_rs.read_text(encoding="utf-8"):
    runpy.run_path(str(base_transform), run_name="__main__")

text = linux_rs.read_text(encoding="utf-8")
try:
    helper_start = text.index("fn create_gunyah_cma_guest_memory(")
    helper_end = text.index("fn run_gz", helper_start)
except ValueError as exc:
    fail(f"cannot locate generated Gunyah CMA helper: {exc}")

helper = text[helper_start:helper_end]

# Android 16 r4 names the RAM-backed mapping list file_backed_mappings_ram and
# punch_holes_in_guest_mem_layout_for_mappings() returns Result<...>.
wrong_layout = '''    let guest_mem_layout =
        punch_holes_in_guest_mem_layout_for_mappings(guest_mem_layout, &cfg.file_backed_mappings);
'''
correct_layout = '''    let guest_mem_layout = punch_holes_in_guest_mem_layout_for_mappings(
        guest_mem_layout,
        &cfg.file_backed_mappings_ram,
    )?;
'''
if wrong_layout in helper:
    helper = helper.replace(wrong_layout, correct_layout, 1)
elif "&cfg.file_backed_mappings_ram" not in helper:
    fail("Gunyah backing helper has neither old nor Android-16-r4 file-backed RAM API")

# Match create_guest_memory() memory policy. The preceding Gunyah contiguity
# patch may set components.hugepages=true; preserving this is harmless for the
# custom file mapping and keeps policy behavior consistent.
policy_anchor = '''    let mut mem_policy = MemoryPolicy::empty();
    if cfg.lock_guest_memory || cfg.lock_guest_memory_dontneed {
'''
policy_fixed = '''    let mut mem_policy = MemoryPolicy::empty();
    if components.hugepages {
        mem_policy |= MemoryPolicy::USE_HUGEPAGES;
    }
    if cfg.lock_guest_memory || cfg.lock_guest_memory_dontneed {
'''
if policy_anchor in helper:
    helper = helper.replace(policy_anchor, policy_fixed, 1)
elif "if components.hugepages" not in helper:
    fail("cannot place USE_HUGEPAGES policy in Gunyah backing helper")

text = text[:helper_start] + helper + text[helper_end:]

# Runtime safety policy for SM-S928B/e3q:
# The kernel bounded allocator guarantees the intended <=8192 physical-run
# envelope for guest RAM. Falling back to normal GuestMemory after that
# allocator fails can produce ~40k-54k physical runs on a fragmented phone and
# feed an unsafe long RM/MEM_APPEND sequence. Therefore bounded backing is a
# hard requirement for non-protected Gunyah. Fail closed and leave the host
# stable instead of silently selecting fragmented normal GuestMemory.
plain_selection = '''    let guest_mem = if cfg.protection_type.isolates_memory() {
        create_guest_memory(&cfg, &components, &arch_memory_layout, &gunyah)?
    } else {
        create_gunyah_cma_guest_memory(&cfg, &components, &arch_memory_layout, &gunyah)?
    };
'''
old_fallback = '''    let guest_mem = if cfg.protection_type.isolates_memory() {
        create_guest_memory(&cfg, &components, &arch_memory_layout, &gunyah)?
    } else {
        match create_gunyah_cma_guest_memory(&cfg, &components, &arch_memory_layout, &gunyah) {
            Ok(mem) => mem,
            Err(e) => {
                warn!(
                    "GUNYAH CMA: allocation failed ({:#}); falling back to normal guest memory",
                    e
                );
                create_guest_memory(&cfg, &components, &arch_memory_layout, &gunyah)?
            }
        }
    };
'''
fail_closed = '''    let guest_mem = if cfg.protection_type.isolates_memory() {
        create_guest_memory(&cfg, &components, &arch_memory_layout, &gunyah)?
    } else {
        match create_gunyah_cma_guest_memory(&cfg, &components, &arch_memory_layout, &gunyah) {
            Ok(mem) => {
                info!("GUNYAH CMA: bounded guest backing SUCCESS");
                mem
            }
            Err(e) => {
                warn!(
                    "GUNYAH CMA: bounded guest backing FAILED ({:#}); normal GuestMemory fallback disabled",
                    e
                );
                return Err(e).context(
                    "Gunyah bounded guest backing failed; fragmented normal GuestMemory fallback disabled",
                );
            }
        }
    };
'''

if fail_closed not in text:
    if text.count(old_fallback) == 1:
        text = text.replace(old_fallback, fail_closed, 1)
    elif text.count(plain_selection) == 1:
        text = text.replace(plain_selection, fail_closed, 1)
    else:
        fail(
            "cannot place fail-closed Gunyah bounded-backing selection: "
            f"plain={text.count(plain_selection)} old_fallback={text.count(old_fallback)}"
        )

linux_rs.write_text(text, encoding="utf-8")

final = linux_rs.read_text(encoding="utf-8")
helper_start = final.index("fn create_gunyah_cma_guest_memory(")
helper_end = final.index("fn run_gz", helper_start)
helper = final[helper_start:helper_end]
checks = {
    "r4 file-backed RAM field": "&cfg.file_backed_mappings_ram" in helper,
    "Result propagation": "punch_holes_in_guest_mem_layout_for_mappings(" in helper and ")?;" in helper,
    "memory policy retained": "MemoryPolicy::USE_HUGEPAGES" in helper,
    "custom backing allocator retained": "create_cma_compat_mem_fd" in helper,
    "normal GUP semantics retained": "options.file_backed =" not in helper,
    "bounded success diagnostic": "GUNYAH CMA: bounded guest backing SUCCESS" in final,
    "bounded failure diagnostic": "GUNYAH CMA: bounded guest backing FAILED" in final,
    "normal fallback explicitly disabled": "fragmented normal GuestMemory fallback disabled" in final,
    "old normal fallback removed": "falling back to normal guest memory" not in final,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    fail("Android-16-r4 Gunyah bounded-backing fixup incomplete: " + ", ".join(failed))

print(
    "Applied local Android 16 r4 Gunyah backing fixup: "
    "file_backed_mappings_ram + Result propagation + normal GUP semantics + "
    "FAIL-CLOSED bounded guest backing (normal GuestMemory fallback disabled)"
)
