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
 * This deliberately does NOT backport the Android 6.12 Gunyah binding layer.
 * Instead, it allocates physically contiguous pages from the existing global
 * CMA area and exposes them through an anonymous mmap-able fd. crosvm maps
 * that fd as ordinary userspace guest RAM, so the existing 6.1
 * GH_VM_SET_USER_MEM_REGION -> pin_user_pages() path sees one contiguous PFN
 * run and creates a one-entry RM memory parcel.
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
	size_t size;
};

static int gh_cma_compat_release(struct inode *inode, struct file *file)
{
	struct gh_cma_compat_buffer *buf = file->private_data;
	size_t count;

	if (!buf)
		return 0;

	count = PAGE_ALIGN(buf->size) >> PAGE_SHIFT;
	if (buf->base && !dma_release_from_contiguous(NULL, buf->base, count))
		pr_err("CMA release failed base_pfn=%#lx pages=%zu\n",
		       page_to_pfn(buf->base), count);
	else if (buf->base)
		pr_info("released base_pfn=%#lx pages=%zu bytes=%zu\n",
			page_to_pfn(buf->base), count, buf->size);

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
	if (!len || len > buf->size)
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
	size_t count;
	int fd;

	if (copy_from_user(&size, (void __user *)arg, sizeof(size)))
		return -EFAULT;
	if (!size || !PAGE_ALIGNED(size) || size > SZ_512M)
		return -EINVAL;
	if (size > SIZE_MAX)
		return -EOVERFLOW;

	count = size >> PAGE_SHIFT;
	buf = kzalloc(sizeof(*buf), GFP_KERNEL_ACCOUNT);
	if (!buf)
		return -ENOMEM;

	buf->size = size;
	/*
	 * align=0 asks CMA for any physically contiguous run of the requested
	 * page count. Requiring get_order(size) here would unnecessarily require
	 * the 256 MiB guest block to also start on a 256 MiB boundary.
	 */
	buf->base = dma_alloc_from_contiguous(NULL, count, 0, false);
	if (!buf->base) {
		pr_err("allocation failed bytes=%llu pages=%zu\n", size, count);
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
	pr_info("allocated fd=%d base_pfn=%#lx pages=%zu bytes=%llu\n",
		fd, page_to_pfn(buf->base), count, size);
	return fd;

err_put_fd:
	put_unused_fd(fd);
err_release:
	dma_release_from_contiguous(NULL, buf->base, count);
	kfree(buf);
	return fd;
}
EOF

python3 - "$MAKEFILE" "$VM_HDR" "$VM_MGR" "$UAPI" <<'PY'
from pathlib import Path
import re
import sys

makefile, hdr, vm, uapi = map(Path, sys.argv[1:])

text = makefile.read_text()
if "cma_compat.o" not in text:
    pat = re.compile(r"(?m)^(gunyah-y\s*\+=\s*.*\bvm_mgr_mm\.o\s*)$")
    m = pat.search(text)
    if not m:
        raise SystemExit("FATAL: cannot locate Gunyah composite-object line")
    text = text[:m.start()] + m.group(1).rstrip() + " cma_compat.o" + text[m.end():]
makefile.write_text(text)

text = hdr.read_text()
proto = "long gh_cma_compat_create_mem_fd(unsigned long arg);"
if proto not in text:
    anchor = "long gh_dev_vm_mgr_ioctl(struct gh_rm *rm, unsigned int cmd, unsigned long arg);\n"
    if text.count(anchor) != 1:
        raise SystemExit("FATAL: cannot place Gunyah CMA compat prototype")
    text = text.replace(anchor, anchor + proto + "\n", 1)
hdr.write_text(text)

text = uapi.read_text()
macro = "GH_ANDROID_CREATE_CMA_COMPAT_MEM_FD"
if macro not in text:
    anchor = "#define GH_ANDROID_IOCTL_TYPE 'A'\n"
    if text.count(anchor) != 1:
        raise SystemExit("FATAL: GH_ANDROID_IOCTL_TYPE anchor not found")
    addition = (
        anchor
        + "\n/* Samsung e3q Android 14/6.1 CMA-backed userspace RAM compatibility. */\n"
        + "#define GH_ANDROID_CREATE_CMA_COMPAT_MEM_FD \\\n"
        + "\t_IOW(GH_ANDROID_IOCTL_TYPE, 0x20, __u64)\n"
    )
    text = text.replace(anchor, addition, 1)
uapi.write_text(text)

text = vm.read_text()
case = "case GH_ANDROID_CREATE_CMA_COMPAT_MEM_FD:"
if case not in text:
    sig = "long gh_dev_vm_mgr_ioctl(struct gh_rm *rm, unsigned int cmd, unsigned long arg)"
    start = text.find(sig)
    if start < 0:
        raise SystemExit("FATAL: gh_dev_vm_mgr_ioctl not found")
    switch = text.find("switch (cmd) {", start)
    if switch < 0:
        raise SystemExit("FATAL: gh_dev_vm_mgr_ioctl switch not found")
    insert = text.find("\n", switch) + 1
    text = text[:insert] + (
        "\tcase GH_ANDROID_CREATE_CMA_COMPAT_MEM_FD:\n"
        "\t\treturn gh_cma_compat_create_mem_fd(arg);\n"
    ) + text[insert:]
vm.write_text(text)
PY

grep -qF 'cma_compat.o' "$MAKEFILE"
grep -qF 'long gh_cma_compat_create_mem_fd(unsigned long arg);' "$VM_HDR"
grep -qF 'GH_ANDROID_CREATE_CMA_COMPAT_MEM_FD' "$UAPI"
grep -qF 'case GH_ANDROID_CREATE_CMA_COMPAT_MEM_FD:' "$VM_MGR"
grep -qF 'dma_alloc_from_contiguous(NULL, count, 0, false)' "$CMA_SRC"
grep -qF 'vm_map_pages_zero' "$CMA_SRC"
grep -qF 'dma_release_from_contiguous(NULL' "$CMA_SRC"

grep -qF 'mapping->parcel.n_mem_entries > 8192' "$VM_MGR"
grep -qF 'ret = -E2BIG;' "$VM_MGR"

echo 'e3q Gunyah CMA compat verified: /dev/gunyah allocator, normal GUP path, 8192 guard retained'