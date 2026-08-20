#!/usr/bin/env python3
from pathlib import Path
import sys
import urllib.request


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


if len(sys.argv) != 2:
    fail(f"usage: {Path(sys.argv[0]).name} <path-to-external/crosvm>")

root = Path(sys.argv[1]).resolve()
linux_rs = root / "src/crosvm/sys/linux.rs"
if not linux_rs.is_file():
    fail(f"crosvm Linux runner source missing: {linux_rs}")

# Keep the already-reviewed CMA/GUP transform immutable and layer only
# Android-16-r4 API corrections on top. This makes CI failures attributable.
BASE_COMMIT = "e1e2092898100ad10aa5fa22d6cc25ffc3771597"
BASE_URL = (
    "https://raw.githubusercontent.com/kaos2310/Super-Builders/"
    f"{BASE_COMMIT}/scripts/patch-crosvm-gunyah-cma-backport.py"
)

marker = "GUNYAH CMA: backing non-protected guest RAM with contiguous memory"
if marker not in linux_rs.read_text(encoding="utf-8"):
    try:
        with urllib.request.urlopen(BASE_URL, timeout=30) as response:
            base_source = response.read().decode("utf-8")
    except Exception as exc:
        fail(f"cannot fetch pinned CMA base transform {BASE_COMMIT}: {exc}")

    namespace = {
        "__name__": "__main__",
        "__file__": BASE_URL,
    }
    try:
        exec(compile(base_source, BASE_URL, "exec"), namespace, namespace)
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise

text = linux_rs.read_text(encoding="utf-8")
try:
    helper_start = text.index("fn create_gunyah_cma_guest_memory(")
    helper_end = text.index("fn run_gz", helper_start)
except ValueError as exc:
    fail(f"cannot locate generated Gunyah CMA helper: {exc}")

helper = text[helper_start:helper_end]

# Android 16 r4 calls this configuration list file_backed_mappings_ram and
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
    fail("Gunyah CMA helper has neither old nor Android-16-r4 file-backed RAM API")

# Preserve the memory policy of create_guest_memory(). The preceding Gunyah
# contiguity patch sets components.hugepages=true for non-protected VMs, so the
# CMA helper must carry that policy through as well.
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
    fail("cannot place USE_HUGEPAGES policy in Gunyah CMA helper")

text = text[:helper_start] + helper + text[helper_end:]
linux_rs.write_text(text, encoding="utf-8")

# Fail closed against the exact r4 API that the AOSP build checks out.
final = linux_rs.read_text(encoding="utf-8")
helper_start = final.index("fn create_gunyah_cma_guest_memory(")
helper_end = final.index("fn run_gz", helper_start)
helper = final[helper_start:helper_end]
checks = {
    "r4 file-backed RAM field": "&cfg.file_backed_mappings_ram" in helper,
    "Result propagation": ")?;" in helper and "punch_holes_in_guest_mem_layout_for_mappings(" in helper,
    "THP policy retained": "MemoryPolicy::USE_HUGEPAGES" in helper,
    "CMA allocator retained": "create_cma_compat_mem_fd" in helper,
    "GUP semantics retained": "options.file_backed =" not in helper,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    fail("Android-16-r4 CMA fixup incomplete: " + ", ".join(failed))

print(
    "Applied Android 16 r4 Gunyah CMA fixup: file_backed_mappings_ram + Result propagation + THP policy"
)
