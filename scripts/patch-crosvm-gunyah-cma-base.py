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

root = Path(sys.argv[1]).resolve()
if not root.is_dir():
    fail(f"crosvm source directory not found: {root}")

sys_rs = root / "hypervisor/src/gunyah/gunyah_sys.rs"
gunyah_rs = root / "hypervisor/src/gunyah/mod.rs"
guest_rs = root / "vm_memory/src/guest_memory.rs"
linux_rs = root / "src/crosvm/sys/linux.rs"
for path in (sys_rs, gunyah_rs, guest_rs, linux_rs):
    if not path.is_file():
        fail(f"required crosvm source missing: {path}")

marker = "GUNYAH CMA: backing non-protected guest RAM with contiguous memory"
if marker in linux_rs.read_text(encoding="utf-8"):
    print("Experimental Gunyah CMA guest-memory backport already present")
    raise SystemExit(0)

# 1) Custom compatibility allocator ioctl. This is intentionally NOT the later
# upstream GH_ANDROID_CREATE_CMA_MEM_FD ABI: the e3q 6.1 kernel exposes the
# compatibility allocator on /dev/gunyah to preserve existing AVF device policy.
text = sys_rs.read_text(encoding="utf-8")
anchor = '''ioctl_iow_nr!(
    GH_VM_ANDROID_SET_AUTH_TYPE,
    GH_ANDROID_IOCTL_TYPE,
    0x16,
    gunyah_auth_desc
);
'''
addition = anchor + '''ioctl_iow_nr!(
    GH_ANDROID_CREATE_CMA_COMPAT_MEM_FD,
    GH_ANDROID_IOCTL_TYPE,
    0x20,
    u64
);
'''
text = replace_once(text, anchor, addition, "gunyah_sys CMA compat ioctl")
sys_rs.write_text(text, encoding="utf-8")

# 2) Ask /dev/gunyah for an anonymous mmap-able CMA backing fd.
text = gunyah_rs.read_text(encoding="utf-8")
anchor = '''    pub fn new() -> Result<Gunyah> {
        Gunyah::new_with_path(&PathBuf::from("/dev/gunyah"))
    }
'''
addition = anchor + '''
    /// Allocate physically contiguous userspace backing from the Samsung e3q
    /// Android 14/6.1 Gunyah compatibility allocator.
    pub fn create_cma_compat_mem_fd(&self, size: u64) -> Result<SafeDescriptor> {
        // SAFETY: the kernel copies exactly one u64 size value from this pointer.
        let ret = unsafe { ioctl_with_ref(self, GH_ANDROID_CREATE_CMA_COMPAT_MEM_FD, &size) };
        if ret < 0 {
            return errno_result();
        }
        // SAFETY: a non-negative ioctl return is a newly allocated owned fd.
        Ok(unsafe { SafeDescriptor::from_raw_descriptor(ret) })
    }
'''
text = replace_once(text, anchor, addition, "Gunyah CMA compat allocator method")
gunyah_rs.write_text(text, encoding="utf-8")

# 3) Extend GuestMemory internally with an optional map of already-open backing
# fds. Crucially, MemoryRegionOptions is NOT changed and options.file_backed
# remains None for these regions. Therefore GunyahVm::new continues to call
# GH_VM_SET_USER_MEM_REGION and the Samsung 6.1 kernel continues through its
# existing pin_user_pages() -> physical-run -> RM parcel path.
text = guest_rs.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''    pub fn new_with_options(
        ranges: &[(GuestAddress, u64, MemoryRegionOptions)],
    ) -> Result<GuestMemory> {
''',
    '''    fn new_with_options_internal(
        ranges: &[(GuestAddress, u64, MemoryRegionOptions)],
        direct_file_fds: Option<&std::collections::BTreeMap<GuestAddress, RawDescriptor>>,
    ) -> Result<GuestMemory> {
''',
    "GuestMemory internal constructor",
)

anchor = '''            let size = usize::try_from(range.1)
                .map_err(|_| Error::MemoryRegionTooLarge(range.1 as u128))?;
            if let Some(file_backed) = &range.2.file_backed {
'''
replacement = '''            let size = usize::try_from(range.1)
                .map_err(|_| Error::MemoryRegionTooLarge(range.1 as u128))?;

            #[cfg(any(target_os = "android", target_os = "linux"))]
            if let Some(fd) = direct_file_fds.and_then(|fds| fds.get(&range.0)) {
                use std::os::fd::FromRawFd;
                let dup_fd = unsafe { libc::dup(*fd) };
                if dup_fd < 0 {
                    return Err(Error::FiledBackedOpenFailed(std::io::Error::last_os_error()));
                }
                // SAFETY: dup() returned a new fd owned by this File.
                let file = unsafe { File::from_raw_fd(dup_fd) };
                let mapping = MemoryMappingBuilder::new(size)
                    .from_file(&file)
                    .offset(0)
                    .align(range.2.align)
                    .protection(base::Protection::read_write())
                    .build()
                    .map_err(Error::FiledBackedMemoryMappingFailed)?;
                regions.push(MemoryRegion {
                    mapping,
                    guest_base: range.0,
                    shared_obj: BackingObject::File(Arc::new(file)),
                    obj_offset: 0,
                    options: range.2.clone(),
                });
                continue;
            }

            if let Some(file_backed) = &range.2.file_backed {
'''
text = replace_once(text, anchor, replacement, "GuestMemory direct-fd mapping")

state_field_candidates = (
    "use_dontneed_locked",
    "use_punchhole_locked",
)
state_fields = [name for name in state_field_candidates if f"            {name}: false," in text]
if len(state_fields) != 1:
    fail(f"GuestMemory policy-state field: expected exactly one candidate, found {state_fields}")
state_field = state_fields[0]

anchor = '''        Ok(GuestMemory {
            regions: Arc::from(regions),
            locked: false,
            __STATE_FIELD__: false,
        })
    }

    /// Creates a container for guest memory regions.
    /// Valid memory regions are specified as a Vec of (Address, Size) tuples sorted by Address.
    pub fn new(ranges: &[(GuestAddress, u64)]) -> Result<GuestMemory> {
'''.replace("__STATE_FIELD__", state_field)
replacement = '''        Ok(GuestMemory {
            regions: Arc::from(regions),
            locked: false,
            __STATE_FIELD__: false,
        })
    }

    /// Creates guest memory using the normal shm/path-backed behavior.
    pub fn new_with_options(
        ranges: &[(GuestAddress, u64, MemoryRegionOptions)],
    ) -> Result<GuestMemory> {
        Self::new_with_options_internal(ranges, None)
    }

    /// Linux/Android-only constructor for regions whose host backing fd already
    /// exists. The fd is duplicated and MemoryRegionOptions remains unchanged.
    #[cfg(any(target_os = "android", target_os = "linux"))]
    pub fn new_with_options_and_file_fds(
        ranges: &[(GuestAddress, u64, MemoryRegionOptions)],
        direct_file_fds: &std::collections::BTreeMap<GuestAddress, RawDescriptor>,
    ) -> Result<GuestMemory> {
        Self::new_with_options_internal(ranges, Some(direct_file_fds))
    }

    /// Creates a container for guest memory regions.
    /// Valid memory regions are specified as a Vec of (Address, Size) tuples sorted by Address.
    pub fn new(ranges: &[(GuestAddress, u64)]) -> Result<GuestMemory> {
'''.replace("__STATE_FIELD__", state_field)
text = replace_once(text, anchor, replacement, "GuestMemory public constructors")
guest_rs.write_text(text, encoding="utf-8")

# 4) For non-protected Gunyah only, allocate primary GuestMemoryRegion backing
# from CMA. Do not set options.file_backed: retaining None is what selects the
# existing GH_VM_SET_USER_MEM_REGION path in GunyahVm::new.
text = linux_rs.read_text(encoding="utf-8")
anchor = '''use vm_memory::MemoryPolicy;
use vm_memory::MemoryRegionOptions;
'''
addition = '''use vm_memory::MemoryPolicy;
use vm_memory::MemoryRegionOptions;
use vm_memory::MemoryRegionPurpose;
'''
text = replace_once(text, anchor, addition, "linux.rs MemoryRegionPurpose import")

anchor = '''    Ok(guest_mem)
}

#[cfg(all(target_arch = "aarch64", feature = "geniezone"))]
fn run_gz'''
helper = '''    Ok(guest_mem)
}

#[cfg(all(any(target_arch = "arm", target_arch = "aarch64"), feature = "gunyah"))]
fn create_gunyah_cma_guest_memory(
    cfg: &Config,
    components: &VmComponents,
    arch_memory_layout: &<Arch as LinuxArch>::ArchMemoryLayout,
    gunyah: &hypervisor::gunyah::Gunyah,
) -> Result<GuestMemory> {
    let guest_mem_layout = Arch::guest_memory_layout(components, arch_memory_layout, gunyah)
        .context("failed to create Gunyah guest memory layout")?;
    let guest_mem_layout =
        punch_holes_in_guest_mem_layout_for_mappings(guest_mem_layout, &cfg.file_backed_mappings);

    // GUNYAH CMA: backing non-protected guest RAM with contiguous memory.
    let mut cma_fds = Vec::new();
    let mut direct_file_fds = BTreeMap::new();
    for (guest_addr, size, options) in guest_mem_layout.iter() {
        if options.purpose != MemoryRegionPurpose::GuestMemoryRegion {
            continue;
        }
        if options.file_backed.is_some() {
            bail!("Gunyah CMA primary RAM unexpectedly has file_backed options");
        }

        let cma_fd = gunyah
            .create_cma_compat_mem_fd(*size)
            .with_context(|| format!(
                "failed to allocate Gunyah CMA backing for guest RAM {:#x}+{:#x}",
                guest_addr.offset(),
                size
            ))?;
        info!(
            "GUNYAH CMA: guest RAM {:#x}+{:#x} fd={} uses contiguous host backing",
            guest_addr.offset(),
            size,
            cma_fd.as_raw_descriptor()
        );
        direct_file_fds.insert(*guest_addr, cma_fd.as_raw_descriptor());
        cma_fds.push(cma_fd);
    }

    if cma_fds.is_empty() {
        bail!("Gunyah CMA path found no GuestMemoryRegion to back");
    }

    let mut guest_mem = GuestMemory::new_with_options_and_file_fds(
        &guest_mem_layout,
        &direct_file_fds,
    )
    .context("failed to create CMA-backed Gunyah guest memory")?;

    let mut mem_policy = MemoryPolicy::empty();
    if components.hugepages {
        mem_policy |= MemoryPolicy::USE_HUGEPAGES;
    }
    if cfg.lock_guest_memory {
        mem_policy |= MemoryPolicy::LOCK_GUEST_MEMORY;
    }
    // Match Android 17 r1 create_guest_memory(): without a jailed balloon
    // process, locked mappings must be reclaimed with punch-hole semantics.
    if cfg.jail_config.is_none() {
        mem_policy |= MemoryPolicy::USE_PUNCHHOLE_LOCKED;
    }
    guest_mem.set_memory_policy(mem_policy);

    if cfg.unmap_guest_memory_on_fork {
        guest_mem.use_dontfork().context("use_dontfork failed")?;
    }

    // GuestMemory now owns duplicate descriptors and mapped VMAs.
    drop(cma_fds);
    Ok(guest_mem)
}

#[cfg(all(target_arch = "aarch64", feature = "geniezone"))]
fn run_gz'''
text = replace_once(text, anchor, helper, "Gunyah CMA guest-memory constructor")

# The THP comparison patch, when present, leaves this exact guest_mem line.
# Replace only that line so its preceding Gunyah-only setup remains harmless.
anchor = '''    let guest_mem = create_guest_memory(&cfg, &components, &arch_memory_layout, &gunyah)?;
'''
replacement = '''    let guest_mem = if cfg.protection_type.isolates_memory() {
        create_guest_memory(&cfg, &components, &arch_memory_layout, &gunyah)?
    } else {
        create_gunyah_cma_guest_memory(&cfg, &components, &arch_memory_layout, &gunyah)?
    };
'''
text = replace_once(text, anchor, replacement, "run_gunyah CMA selection")
linux_rs.write_text(text, encoding="utf-8")

checks = {
    sys_rs: ("GH_ANDROID_CREATE_CMA_COMPAT_MEM_FD", "0x20"),
    gunyah_rs: (
        "pub fn create_cma_compat_mem_fd",
        "GH_ANDROID_CREATE_CMA_COMPAT_MEM_FD",
        "GH_VM_SET_USER_MEM_REGION",
    ),
    guest_rs: (
        "new_with_options_and_file_fds",
        "direct_file_fds.and_then",
        "libc::dup(*fd)",
        "options: range.2.clone()",
    ),
    linux_rs: (
        marker,
        "create_gunyah_cma_guest_memory",
        "MemoryRegionPurpose::GuestMemoryRegion",
        "direct_file_fds.insert(*guest_addr, cma_fd.as_raw_descriptor())",
    ),
}
for path, tokens in checks.items():
    data = path.read_text(encoding="utf-8")
    missing = [token for token in tokens if token not in data]
    if missing:
        fail(f"post-patch verification failed for {path}: {missing}")

# Critical invariant: CMA-backed primary RAM must NOT select the later
# GH_VM_ANDROID_MAP_CMA_MEM branch in GunyahVm::new.
linux_data = linux_rs.read_text(encoding="utf-8")
helper_start = linux_data.index("fn create_gunyah_cma_guest_memory(")
helper_end = linux_data.index("fn run_gz", helper_start)
helper_text = linux_data[helper_start:helper_end]
if "options.file_backed =" in helper_text:
    fail("CMA helper must leave MemoryRegionOptions.file_backed unchanged")

print(
    "Applied experimental e3q Gunyah CMA backing: primary non-protected RAM uses "
    "CMA file mappings while Gunyah retains GH_VM_SET_USER_MEM_REGION/GUP semantics"
)
