#!/usr/bin/env python3
from pathlib import Path
import sys


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


if len(sys.argv) != 2:
    fail(f"usage: {Path(sys.argv[0]).name} <path-to-external/crosvm>")

crosvm = Path(sys.argv[1]).resolve()
target = crosvm / "src/crosvm/sys/linux.rs"
if not target.is_file():
    fail(f"crosvm Linux runner source missing: {target}")

text = target.read_text(encoding="utf-8")
marker = "GUNYAH MEM: enabling MADV_HUGEPAGE guest RAM"
if marker in text:
    print(f"Gunyah guest-memory contiguity patch already present in {target}")
    raise SystemExit(0)

old = '''    let device_path = device_path.unwrap_or(Path::new(GUNYAH_PATH));
    let gunyah = Gunyah::new_with_path(device_path)
        .with_context(|| format!("failed to open Gunyah device {}", device_path.display()))?;

    let arch_memory_layout =
        Arch::arch_memory_layout(&components).context("failed to create arch memory layout")?;
    let guest_mem = create_guest_memory(&cfg, &components, &arch_memory_layout, &gunyah)?;
'''

new = '''    let device_path = device_path.unwrap_or(Path::new(GUNYAH_PATH));
    let gunyah = Gunyah::new_with_path(device_path)
        .with_context(|| format!("failed to open Gunyah device {}", device_path.display()))?;

    // Samsung's Android 14/6.1 Gunyah VM manager pins ordinary userspace guest RAM and
    // converts the physical layout into an RM memory parcel. On fragmented systems that
    // parcel can exceed the bounded extent count long before a 256 MiB VM can start.
    //
    // Keep the normal Gunyah userspace-memory ABI for now, but request THP compaction for
    // non-protected VMs. This is deliberately scoped to Gunyah and does not alter KVM,
    // GenieZone, Halla, protected-VM semantics, or the kernel's memparcel safety limit.
    let mut components = components;
    if !cfg.protection_type.isolates_memory() && !components.hugepages {
        info!("GUNYAH MEM: enabling MADV_HUGEPAGE guest RAM to reduce physical extents");
        components.hugepages = true;
    }

    let arch_memory_layout =
        Arch::arch_memory_layout(&components).context("failed to create arch memory layout")?;
    let guest_mem = create_guest_memory(&cfg, &components, &arch_memory_layout, &gunyah)?;
'''

count = text.count(old)
if count != 1:
    fail(f"expected exactly one Gunyah guest-memory anchor in {target}, found {count}")

text = text.replace(old, new, 1)

checks = (
    marker,
    "let mut components = components;",
    "!cfg.protection_type.isolates_memory()",
    "components.hugepages = true;",
    "create_guest_memory(&cfg, &components, &arch_memory_layout, &gunyah)?;",
)
missing = [token for token in checks if token not in text]
if missing:
    fail(f"Gunyah guest-memory contiguity verification failed: {missing}")

# Scope guard: the other hypervisor construction paths must remain untouched.
for untouched in ("&gzvm)?;", "&hvm)?;", "&kvm)?;"):
    if untouched not in text:
        fail(f"unexpected crosvm runner layout; missing untouched hypervisor marker: {untouched}")

target.write_text(text, encoding="utf-8")
print(
    "Applied Gunyah non-protected guest-memory contiguity patch: "
    "force MADV_HUGEPAGE while preserving the existing memory ABI"
)
