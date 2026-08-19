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

# 1) Add an experimental allocator ioctl on the existing /dev/gunyah descriptor.
#    0x20 is deliberately outside the Android Gunyah VM ioctls used by this r4 tree (0x11..0x16).
text = sys_rs.read_text(encoding="utf-8")
anchor = '''ioctl_iow_nr!(
    GH_VM_ANDROID_SET_AUTH_TYPE,
    GH_ANDROID_IOCTL_TYPE,
    0x16,
    gunyah_auth_desc
);
'''
addition = anchor + '''ioctl_iow_nr!(
    GH_ANDROID_CREATE_CMA_MEM_FD,
    GH_ANDROID_IOCTL_TYPE,
    0x20,
    u64
);
'''
text = replace_once(text, anchor, addition, "gunyah_sys allocator ioctl")
sys_rs.write_text(text, encoding="utf-8")

# 2) Teach the Gunyah hypervisor object to ask the kernel for a CMA-backed anonymous fd.
text = gunyah_rs.read_text(encoding="utf-8")
anchor = '''    pub fn new() -> Result<Gunyah> {
        Gunyah::new_with_path(&PathBuf::from("/dev/gunyah"))
    }
'''
addition = anchor + '''
    /// Allocate one physically contiguous guest-memory backing object from the
    /// Android Gunyah CMA compatibility ioctl. The returned fd owns the CMA pages.
    pub fn create_cma_mem_fd(&self, size: u64) -> Result<SafeDescriptor> {
        // SAFETY: GH_ANDROID_CREATE_CMA_MEM_FD only reads the u64 size argument and
        // returns either a new owned file descriptor or a negative errno.
        let ret = unsafe { ioctl_with_ref(self, GH_ANDROID_CREATE_CMA_MEM_FD, &size) };
        if ret < 0 {
            return errno_result();
        }
        // SAFETY: a non-negative return value is a new fd transferred to this process.
        Ok(unsafe { SafeDescriptor::from_raw_descriptor(ret) })
    }
'''
text = replace_once(text, anchor, addition, "Gunyah CMA allocator method")
gunyah_rs.write_text(text, encoding="utf-8")

# 3) Allow a GuestMemory file-backed region to consume an already-open descriptor.
#    This avoids reopening an anon-inode through /proc/self/fd and keeps the fd lifetime explicit.
text = guest_rs.read_text(encoding="utf-8")
anchor = '''pub struct MemoryRegionOptions {
    /// Some hypervisors (presently: Gunyah) need explicit knowledge about
    /// which memory region is used for protected firwmare, static swiotlb,
    /// or general purpose guest memory.
    pub purpose: MemoryRegionPurpose,
    /// Alignment for the mapping of this region. This intends to be used for
    /// arm64 KVM support where a block alignment is required for transparent
    /// huge-pages support
    pub align: u64,
    /// Backing file params.
    pub file_backed: Option<FileBackedMappingParameters>,
}
'''
addition = '''pub struct MemoryRegionOptions {
    /// Some hypervisors (presently: Gunyah) need explicit knowledge about
    /// which memory region is used for protected firwmare, static swiotlb,
    /// or general purpose guest memory.
    pub purpose: MemoryRegionPurpose,
    /// Alignment for the mapping of this region. This intends to be used for
    /// arm64 KVM support where a block alignment is required for transparent
    /// huge-pages support
    pub align: u64,
    /// Backing file params.
    pub file_backed: Option<FileBackedMappingParameters>,
    /// Optional already-open backing fd. Linux/Android only; used by the
    /// experimental Gunyah CMA path so anon-inode memory never needs a pathname.
    #[cfg(any(target_os = "android", target_os = "linux"))]
    pub file_backed_fd: Option<RawDescriptor>,
}
'''
text = replace_once(text, anchor, addition, "MemoryRegionOptions fd field")
anchor = '''    pub fn file_backed(mut self, params: FileBackedMappingParameters) -> Self {
        self.file_backed = Some(params);
        self
    }
'''
addition = anchor + '''
    #[cfg(any(target_os = "android", target_os = "linux"))]
    pub fn file_backed_fd(mut self, fd: RawDescriptor) -> Self {
        self.file_backed_fd = Some(fd);
        self
    }
'''
text = replace_once(text, anchor, addition, "MemoryRegionOptions fd builder")
anchor = '''            if let Some(file_backed) = &range.2.file_backed {
                assert_eq!(usize::try_from(file_backed.size).unwrap(), size);
                let file = file_backed.open().map_err(Error::FiledBackedOpenFailed)?;
                let mapping = MemoryMappingBuilder::new(size)
'''
addition = '''            if let Some(file_backed) = &range.2.file_backed {
                assert_eq!(usize::try_from(file_backed.size).unwrap(), size);
                #[cfg(any(target_os = "android", target_os = "linux"))]
                let file = if let Some(fd) = range.2.file_backed_fd {
                    use std::os::fd::FromRawFd;
                    let dup_fd = unsafe { libc::dup(fd) };
                    if dup_fd < 0 {
                        return Err(Error::FiledBackedOpenFailed(std::io::Error::last_os_error()));
                    }
                    // SAFETY: dup() returned a new fd owned by this File.
                    unsafe { File::from_raw_fd(dup_fd) }
                } else {
                    file_backed.open().map_err(Error::FiledBackedOpenFailed)?
                };
                #[cfg(windows)]
                let file = file_backed.open().map_err(Error::FiledBackedOpenFailed)?;
                let mapping = MemoryMappingBuilder::new(size)
'''
text = replace_once(text, anchor, addition, "GuestMemory fd-backed open")
guest_rs.write_text(text, encoding="utf-8")

# 4) Create primary non-protected Gunyah RAM from CMA fds while retaining the existing
#    file-backed-region -> GH_VM_ANDROID_MAP_CMA_MEM path in hypervisor/src/gunyah/mod.rs.
text = linux_rs.read_text(encoding="utf-8")
anchor = '''use vm_memory::MemoryPolicy;
use vm_memory::MemoryRegionOptions;
'''
addition = '''use vm_memory::MemoryPolicy;
use vm_memory::MemoryRegionOptions;
use vm_memory::MemoryRegionPurpose;
'''
text = replace_once(text, anchor, addition, "linux.rs MemoryRegionPurpose import")

# Insert a Gunyah-specific memory constructor directly after the generic constructor.
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
    let mut guest_mem_layout =
        punch_holes_in_guest_mem_layout_for_mappings(guest_mem_layout, &cfg.file_backed_mappings);

    // GUNYAH CMA: backing non-protected guest RAM with contiguous memory.
    // The SafeDescriptors are kept alive until GuestMemory duplicates each fd.
    let mut cma_fds = Vec::new();
    for (guest_addr, size, options) in guest_mem_layout.iter_mut() {
        if options.purpose != MemoryRegionPurpose::GuestMemoryRegion {
            continue;
        }

        let cma_fd = gunyah
            .create_cma_mem_fd(*size)
            .with_context(|| format!(
                "failed to allocate Gunyah CMA backing for guest RAM {:#x}+{:#x}",
                guest_addr.offset(),
                size
            ))?;
        info!(
            "GUNYAH CMA: guest RAM {:#x}+{:#x} fd={} uses contiguous backing",
            guest_addr.offset(),
            size,
            cma_fd.as_raw_descriptor()
        );

        options.file_backed = Some(FileBackedMappingParameters {
            path: PathBuf::new(),
            address: guest_addr.offset(),
            size: *size,
            offset: 0,
            writable: true,
            sync: false,
            align: false,
            ram: true,
        });
        options.file_backed_fd = Some(cma_fd.as_raw_descriptor());
        cma_fds.push(cma_fd);
    }

    if cma_fds.is_empty() {
        bail!("Gunyah CMA path found no GuestMemoryRegion to back");
    }

    let mut guest_mem = GuestMemory::new_with_options(&guest_mem_layout)
        .context("failed to create CMA-backed Gunyah guest memory")?;

    let mut mem_policy = MemoryPolicy::empty();
    if cfg.lock_guest_memory {
        mem_policy |= MemoryPolicy::LOCK_GUEST_MEMORY;
    }
    guest_mem.set_memory_policy(mem_policy);

    if cfg.unmap_guest_memory_on_fork {
        guest_mem.use_dontfork().context("use_dontfork failed")?;
    }

    // GuestMemory owns duplicated file descriptors from this point onward.
    drop(cma_fds);
    Ok(guest_mem)
}

#[cfg(all(target_arch = "aarch64", feature = "geniezone"))]
fn run_gz'''
text = replace_once(text, anchor, helper, "Gunyah CMA guest-memory constructor")

anchor = '''    let arch_memory_layout =
        Arch::arch_memory_layout(&components).context("failed to create arch memory layout")?;
    let guest_mem = create_guest_memory(&cfg, &components, &arch_memory_layout, &gunyah)?;
'''
replacement = '''    let arch_memory_layout =
        Arch::arch_memory_layout(&components).context("failed to create arch memory layout")?;
    let guest_mem = if cfg.protection_type.isolates_memory() {
        create_guest_memory(&cfg, &components, &arch_memory_layout, &gunyah)?
    } else {
        create_gunyah_cma_guest_memory(&cfg, &components, &arch_memory_layout, &gunyah)?
    };
'''
text = replace_once(text, anchor, replacement, "run_gunyah CMA selection")
linux_rs.write_text(text, encoding="utf-8")

# Fail closed if any of the key pieces disappeared during source drift.
checks = {
    sys_rs: (
        "GH_ANDROID_CREATE_CMA_MEM_FD",
        "0x20",
    ),
    gunyah_rs: (
        "pub fn create_cma_mem_fd",
        "GH_ANDROID_CREATE_CMA_MEM_FD",
        "GH_VM_ANDROID_MAP_CMA_MEM",
    ),
    guest_rs: (
        "pub file_backed_fd: Option<RawDescriptor>",
        "libc::dup(fd)",
    ),
    linux_rs: (
        marker,
        "create_gunyah_cma_guest_memory",
        "MemoryRegionPurpose::GuestMemoryRegion",
        "file_backed_fd = Some(cma_fd.as_raw_descriptor())",
    ),
}
for path, tokens in checks.items():
    data = path.read_text(encoding="utf-8")
    missing = [token for token in tokens if token not in data]
    if missing:
        fail(f"post-patch verification failed for {path}: {missing}")

print(
    "Applied experimental Gunyah CMA guest-memory backport: non-protected primary RAM "
    "uses kernel-provided contiguous fd backing and existing GH_VM_ANDROID_MAP_CMA_MEM"
)
