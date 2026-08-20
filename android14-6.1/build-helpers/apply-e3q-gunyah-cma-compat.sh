#!/usr/bin/env bash
set -euo pipefail

KERNEL_TREE="${1:?usage: apply-e3q-gunyah-cma-compat.sh <kernel-tree>}"
GUNYAH_DIR="$KERNEL_TREE/drivers/virt/gunyah"
MAKEFILE="$GUNYAH_DIR/Makefile"
VM_MGR="$GUNYAH_DIR/vm_mgr.c"
VM_HDR="$GUNYAH_DIR/vm_mgr.h"
UAPI="$KERNEL_TREE/include/uapi/linux/gunyah.h"
CMA_SRC="$GUNYAH_DIR/cma_compat.c"

for f in "$MAKEFILE" "$VM_MGR" "$VM_HDR" "$UAPI"; do
  test -f "$f" || { echo "FATAL: required Gunyah source missing: $f" >&2; exit 1; }
done

cat > "$CMA_SRC" <<'EOF'
// SPDX-License-Identifier: GPL-2.0-only
/*
 * Samsung e3q / Android 14-6.1 Gunyah CMA compatibility allocator.
 *
 * Allocate physically contiguous pages from the existing global CMA area and
 * expose them through an anonymous mmap-able fd. crosvm maps that fd as normal
 * userspace guest RAM. The existing Samsung 6.1 GH_VM_SET_USER_MEM_REGION ->
 * pin_user_pages() path therefore remains unchanged, while the resulting RM
 * parcel should collapse to a single physical extent.
 */
#define pr_fmt(fmt) "gh_cma_compat: " fmt

#include <linux/anon_inodes.h>
#include <linux/dma-contiguous.h>
#include <linux/file.h>
#include <linux/fs.h>
#include <linux/mm.h>
#include <linux/module.h>
#include <linux/sizes.h>
#include <linux/slab.h>
#include <linux/uaccess.h>
#include <linux/vmalloc.h>

#include <uapi/linux/gunyah.h>

struct gh_cma_compat_buffer {
	struct page *base;
	u64 size;
	unsigned long nr_pages;
};

static bool gh_cma_compat_release_pages(struct gh_cma_compat_buffer *buf)
{
	if (!buf || !buf->base)
		return true;

	/* Max accepted size is 512 MiB, so nr_pages is safely representable as int. */
	return dma_release_from_contiguous(NULL, buf->base, (int)buf->nr_pages);
}

static int gh_cma_compat_release(struct inode *inode, struct file *file)
{
	struct gh_cma_compat_buffer *buf = file->private_data;

	if (!buf)
		return 0;

	if (buf->base && !gh_cma_compat_release_pages(buf))
		pr_err("CMA release failed base_pfn=%#lx pages=%lu\n",
		       page_to_pfn(buf->base), buf->nr_pages);
	else if (buf->base)
		pr_info("released base_pfn=%#lx pages=%lu bytes=%llu\n",
			page_to_pfn(buf->base), buf->nr_pages,
			(unsigned long long)buf->size);

	kfree(buf);
	return 0;
}

static int gh_cma_compat_mmap(struct file *file, struct vm_area_struct *vma)
{
	struct gh_cma_compat_buffer *buf = file->private_data;
	unsigned long len = vma->vm_end - vma->vm_start;
	unsigned long nr_pages = PAGE_ALIGN(len) >> PAGE_SHIFT;
	struct page **pages;
	unsigned long i;
	int ret;

	if (!buf || !buf->base)
		return -EINVAL;
	if (vma->vm_pgoff != 0)
		return -EINVAL;
	if (!len || len > buf->size || nr_pages > buf->nr_pages)
		return -EINVAL;

	pages = kvmalloc_array(nr_pages, sizeof(*pages), GFP_KERNEL);
	if (!pages)
		return -ENOMEM;

	for (i = 0; i < nr_pages; i++)
		pages[i] = nth_page(buf->base, i);

	file_accessed(file);
	ret = vm_map_pages_zero(vma, pages, nr_pages);
	kvfree(pages);
	if (ret)
		pr_err("mmap failed base_pfn=%#lx pages=%lu ret=%d\n",
		       page_to_pfn(buf->base), nr_pages, ret);
	else
		pr_info("mapped base_pfn=%#lx pages=%lu bytes=%lu\n",
			page_to_pfn(buf->base), nr_pages, len);
	return ret;
}

static const struct file_operations gh_cma_compat_fops = {
	.owner = THIS_MODULE,
	.llseek = no_llseek,
	.mmap = gh_cma_compat_mmap,
	.release = gh_cma_compat_release,
};

long gh_cma_compat_create_mem_fd(unsigned long arg)
{
	struct gh_cma_compat_buffer *buf;
	struct file *file;
	u64 size;
	unsigned long nr_pages;
	int fd;

	if (copy_from_user(&size, (void __user *)arg, sizeof(size)))
		return -EFAULT;
	if (!size || !PAGE_ALIGNED(size) || size > SZ_512M)
		return -EINVAL;

	nr_pages = (unsigned long)(size >> PAGE_SHIFT);
	if (!nr_pages)
		return -EINVAL;

	buf = kzalloc(sizeof(*buf), GFP_KERNEL_ACCOUNT);
	if (!buf)
		return -ENOMEM;

	buf->size = size;
	buf->nr_pages = nr_pages;
	/*
	 * align=0 requests any contiguous run of nr_pages from CMA. Requiring
	 * get_order(size) would additionally require a 256 MiB RAM block to start
	 * on a 256 MiB boundary, which is unnecessary for the Gunyah parcel.
	 */
	buf->base = dma_alloc_from_contiguous(NULL, nr_pages, 0, false);
	if (!buf->base) {
		pr_err("allocation failed bytes=%llu pages=%lu\n",
		       (unsigned long long)size, nr_pages);
		kfree(buf);
		return -ENOMEM;
	}

	fd = get_unused_fd_flags(O_CLOEXEC);
	if (fd < 0)
		goto err_release;

	file = anon_inode_getfile("[gunyah-cma-compat]", &gh_cma_compat_fops,
				  buf, O_RDWR);
	if (IS_ERR(file)) {
		fd = PTR_ERR(file);
		goto err_put_fd;
	}

	fd_install(fd, file);
	pr_info("allocated fd=%d base_pfn=%#lx pages=%lu bytes=%llu\n",
		fd, page_to_pfn(buf->base), nr_pages,
		(unsigned long long)size);
	return fd;

err_put_fd:
	put_unused_fd(fd);
err_release:
	if (!gh_cma_compat_release_pages(buf))
		pr_err("CMA release after fd failure failed base_pfn=%#lx pages=%lu\n",
		       page_to_pfn(buf->base), buf->nr_pages);
	kfree(buf);
	return fd;
}
EOF

python3 - "$MAKEFILE" "$VM_HDR" "$VM_MGR" "$UAPI" <<'PY'
from pathlib import Path
import re
import sys

makefile, hdr, vm, uapi = map(Path, sys.argv[1:])

# Makefile: tolerate Samsung/AOSP object ordering. Append to the one gunyah-y
# line that contains vm_mgr_mm.o rather than requiring it to be the final token.
text = makefile.read_text()
if "cma_compat.o" not in text:
    lines = text.splitlines(keepends=True)
    candidates = [
        i for i, line in enumerate(lines)
        if re.match(r"^\s*gunyah-y\s*\+=", line) and "vm_mgr_mm.o" in line
    ]
    if len(candidates) != 1:
        raise SystemExit(
            f"FATAL: expected one Gunyah composite-object line containing vm_mgr_mm.o, found {len(candidates)}"
        )
    i = candidates[0]
    newline = "\n" if lines[i].endswith("\n") else ""
    lines[i] = lines[i].rstrip("\n").rstrip() + " cma_compat.o" + newline
    text = "".join(lines)
makefile.write_text(text)

# Header: tolerate whitespace/wrapping differences while requiring one canonical
# gh_dev_vm_mgr_ioctl declaration.
text = hdr.read_text()
proto = "long gh_cma_compat_create_mem_fd(unsigned long arg);"
if proto not in text:
    pat = re.compile(
        r"(?m)^(?P<decl>\s*long\s+gh_dev_vm_mgr_ioctl\s*\(\s*struct\s+gh_rm\s*\*\s*rm\s*,\s*"
        r"unsigned\s+int\s+cmd\s*,\s*unsigned\s+long\s+arg\s*\)\s*;\s*)$"
    )
    matches = list(pat.finditer(text))
    if len(matches) != 1:
        raise SystemExit(
            f"FATAL: expected one gh_dev_vm_mgr_ioctl declaration, found {len(matches)}"
        )
    m = matches[0]
    insertion = m.group("decl").rstrip() + "\n" + proto
    text = text[:m.start()] + insertion + text[m.end():]
hdr.write_text(text)

# UAPI: nr 0x20 is deliberately outside the Android r4 VM ioctl range in this
# tree. Match the Android ioctl type independent of spacing/comment layout.
text = uapi.read_text()
macro = "GH_ANDROID_CREATE_CMA_COMPAT_MEM_FD"
if macro not in text:
    pat = re.compile(r"(?m)^\s*#\s*define\s+GH_ANDROID_IOCTL_TYPE\s+'A'\s*$")
    matches = list(pat.finditer(text))
    if len(matches) != 1:
        raise SystemExit(
            f"FATAL: expected one GH_ANDROID_IOCTL_TYPE 'A' definition, found {len(matches)}"
        )
    m = matches[0]
    addition = (
        m.group(0)
        + "\n\n/* Samsung e3q Android 14/6.1 CMA-backed userspace RAM compatibility. */\n"
        + "#define GH_ANDROID_CREATE_CMA_COMPAT_MEM_FD \\\n"
        + "\t_IOW(GH_ANDROID_IOCTL_TYPE, 0x20, __u64)"
    )
    text = text[:m.start()] + addition + text[m.end():]
uapi.write_text(text)

# /dev/gunyah dispatcher: find the function semantically rather than requiring
# an exact single-line signature.
text = vm.read_text()
case = "case GH_ANDROID_CREATE_CMA_COMPAT_MEM_FD:"
if case not in text:
    pat = re.compile(
        r"long\s+gh_dev_vm_mgr_ioctl\s*\(\s*struct\s+gh_rm\s*\*\s*rm\s*,\s*"
        r"unsigned\s+int\s+cmd\s*,\s*unsigned\s+long\s+arg\s*\)\s*\{",
        re.MULTILINE,
    )
    matches = list(pat.finditer(text))
    if len(matches) != 1:
        raise SystemExit(
            f"FATAL: expected one gh_dev_vm_mgr_ioctl definition, found {len(matches)}"
        )
    start = matches[0].end()
    switch = re.search(r"\bswitch\s*\(\s*cmd\s*\)\s*\{", text[start:])
    if not switch:
        raise SystemExit("FATAL: gh_dev_vm_mgr_ioctl switch(cmd) not found")
    switch_end = start + switch.end()
    text = text[:switch_end] + (
        "\n\tcase GH_ANDROID_CREATE_CMA_COMPAT_MEM_FD:\n"
        "\t\treturn gh_cma_compat_create_mem_fd(arg);"
    ) + text[switch_end:]
vm.write_text(text)
PY

# Fail closed before invoking the kernel build.
grep -qF 'cma_compat.o' "$MAKEFILE"
grep -qF 'long gh_cma_compat_create_mem_fd(unsigned long arg);' "$VM_HDR"
grep -qF 'GH_ANDROID_CREATE_CMA_COMPAT_MEM_FD' "$UAPI"
grep -qF '_IOW(GH_ANDROID_IOCTL_TYPE, 0x20, __u64)' "$UAPI"
grep -qF 'case GH_ANDROID_CREATE_CMA_COMPAT_MEM_FD:' "$VM_MGR"
grep -qF 'dma_alloc_from_contiguous(NULL, nr_pages, 0, false)' "$CMA_SRC"
grep -qF 'dma_release_from_contiguous(NULL, buf->base, (int)buf->nr_pages)' "$CMA_SRC"
grep -qF 'vm_map_pages_zero' "$CMA_SRC"

# Never relax the memory parcel safety guard as part of the CMA fix.
grep -qF 'mapping->parcel.n_mem_entries > 8192' "$VM_MGR"
grep -qF 'ret = -E2BIG;' "$VM_MGR"

echo 'e3q Gunyah CMA compat verified: robust anchors, normal GUP path, 8192 guard retained'
