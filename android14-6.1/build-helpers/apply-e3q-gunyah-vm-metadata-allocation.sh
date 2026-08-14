#!/usr/bin/env bash
set -euo pipefail

KERNEL_TREE="${1:?usage: apply-e3q-gunyah-vm-metadata-allocation.sh <kernel-tree>}"
MEM_TARGET="$KERNEL_TREE/drivers/virt/gunyah/vm_mgr_mm.c"
VM_TARGET="$KERNEL_TREE/drivers/virt/gunyah/vm_mgr.c"
IRQ_TARGET="$KERNEL_TREE/drivers/virt/gunyah/gunyah_irqfd.c"

test -f "$MEM_TARGET" || {
  echo "FATAL: Gunyah VM memory manager not found: $MEM_TARGET" >&2
  exit 1
}
test -f "$IRQ_TARGET" || {
  echo "FATAL: Gunyah IRQFD driver not found: $IRQ_TARGET" >&2
  exit 1
}
test -f "$VM_TARGET" || {
  echo "FATAL: Gunyah VM manager not found: $VM_TARGET" >&2
  exit 1
}

python3 - "$MEM_TARGET" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
source = path.read_text()

if "int gh_vm_mem_alloc(" not in source:
    raise SystemExit(f"FATAL: gh_vm_mem_alloc() not found in {path}")

pages_old = re.compile(
    r"mapping->pages\s*=\s*kcalloc\(\s*mapping->npages\s*,\s*"
    r"sizeof\(\*mapping->pages\)\s*,\s*GFP_KERNEL_ACCOUNT\s*\);"
)
entries_old = re.compile(
    r"parcel->mem_entries\s*=\s*kcalloc\(\s*parcel->n_mem_entries\s*,\s*"
    r"sizeof\(parcel->mem_entries\[0\]\)\s*,\s*GFP_KERNEL_ACCOUNT\s*\);"
)

pages_new = (
    "mapping->pages = kvcalloc(mapping->npages, sizeof(*mapping->pages),\n"
    "\t\t\t\t  GFP_KERNEL_ACCOUNT);"
)
entries_new = (
    "parcel->mem_entries = kvcalloc(parcel->n_mem_entries,\n"
    "\t\t\t\t      sizeof(parcel->mem_entries[0]),\n"
    "\t\t\t\t      GFP_KERNEL_ACCOUNT);"
)

already_patched = (
    pages_old.search(source) is None
    and entries_old.search(source) is None
    and "mapping->pages = kvcalloc(" in source
    and "parcel->mem_entries = kvcalloc(" in source
)

if not already_patched:
    source, pages_count = pages_old.subn(pages_new, source)
    source, entries_count = entries_old.subn(entries_new, source)
    if pages_count != 1 or entries_count != 1:
        raise SystemExit(
            "FATAL: unexpected Gunyah allocation layout: "
            f"pages={pages_count}, mem_entries={entries_count}"
        )

if "#include <linux/slab.h>" not in source:
    marker = "#include <linux/mm.h>\n"
    if source.count(marker) != 1:
        raise SystemExit("FATAL: cannot place explicit linux/slab.h include")
    source = source.replace(marker, marker + "#include <linux/slab.h>\n", 1)

pages_free_count = source.count("kfree(mapping->pages);")
if pages_free_count:
    if pages_free_count != 2:
        raise SystemExit(
            f"FATAL: expected two mapping->pages frees, found {pages_free_count}"
        )
    source = source.replace("kfree(mapping->pages);", "kvfree(mapping->pages);")

entries_free_count = source.count("kfree(mapping->parcel.mem_entries);")
if entries_free_count:
    if entries_free_count != 1:
        raise SystemExit(
            "FATAL: expected one parcel mem_entries free, "
            f"found {entries_free_count}"
        )
    source = source.replace(
        "kfree(mapping->parcel.mem_entries);",
        "kvfree(mapping->parcel.mem_entries);",
    )

checks = {
    "pages kvcalloc": source.count("mapping->pages = kvcalloc(") == 1,
    "mem_entries kvcalloc": source.count("parcel->mem_entries = kvcalloc(") == 1,
    "pages kvfree": source.count("kvfree(mapping->pages);") == 2,
    "mem_entries kvfree": source.count("kvfree(mapping->parcel.mem_entries);") == 1,
    "legacy pages allocation removed": pages_old.search(source) is None,
    "legacy entries allocation removed": entries_old.search(source) is None,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("FATAL: incomplete Gunyah metadata fix: " + ", ".join(failed))

path.write_text(source)
print(f"Applied fragmentation-safe Gunyah VM metadata allocation fix to {path}")
PY

grep -qF 'mapping->pages = kvcalloc(' "$MEM_TARGET"
grep -qF 'parcel->mem_entries = kvcalloc(' "$MEM_TARGET"
test "$(grep -cF 'kvfree(mapping->pages);' "$MEM_TARGET")" -eq 2
test "$(grep -cF 'kvfree(mapping->parcel.mem_entries);' "$MEM_TARGET")" -eq 1

python3 - "$MEM_TARGET" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
source = path.read_text()

if "GH_DIAG mem_alloc enter" not in source:
    replacements = {
        "\tu16 vmid;\n\n\tif (!region->memory_size":
            "\tu16 vmid;\n\n"
            "\tpr_info(\"GH_DIAG mem_alloc enter label=%u lend=%u size=%llu gpa=%#llx uaddr=%#llx\\n\",\n"
            "\t\tregion->label, (unsigned int)lend,\n"
            "\t\t(unsigned long long)region->memory_size,\n"
            "\t\t(unsigned long long)region->guest_phys_addr,\n"
            "\t\t(unsigned long long)region->userspace_addr);\n\n"
            "\tif (!region->memory_size",
        "\tpinned = pin_user_pages_fast(region->userspace_addr, mapping->npages,\n"
        "\t\t\t\t\tgup_flags, mapping->pages);\n":
            "\tpr_info(\"GH_DIAG mem_alloc pin begin label=%u npages=%lu\\n\",\n"
            "\t\tregion->label, (unsigned long)mapping->npages);\n"
            "\tpinned = pin_user_pages_fast(region->userspace_addr, mapping->npages,\n"
            "\t\t\t\t\tgup_flags, mapping->pages);\n"
            "\tpr_info(\"GH_DIAG mem_alloc pin end label=%u pinned=%d expected=%lu\\n\",\n"
            "\t\tregion->label, pinned, (unsigned long)mapping->npages);\n",
        "\tlist_add(&mapping->list, &ghvm->memory_mappings);\n":
            "\tpr_info(\"GH_DIAG mem_alloc ready label=%u npages=%lu entries=%u share=%u\\n\",\n"
            "\t\tparcel->label, (unsigned long)mapping->npages,\n"
            "\t\tparcel->n_mem_entries, (unsigned int)mapping->share_type);\n"
            "\tlist_add(&mapping->list, &ghvm->memory_mappings);\n",
        "unlock:\n\tmutex_unlock(&ghvm->mm_lock);\n\treturn ret;\n":
            "unlock:\n"
            "\tpr_info(\"GH_DIAG mem_alloc fail label=%u ret=%d\\n\", region->label, ret);\n"
            "\tmutex_unlock(&ghvm->mm_lock);\n"
            "\treturn ret;\n",
    }
    for old, new in replacements.items():
        if source.count(old) != 1:
            raise SystemExit(f"FATAL: cannot place Gunyah memory diagnostic marker: {old!r}")
        source = source.replace(old, new, 1)

checks = {
    "mem alloc entry": source.count("GH_DIAG mem_alloc enter") == 1,
    "pin begin": source.count("GH_DIAG mem_alloc pin begin") == 1,
    "pin end": source.count("GH_DIAG mem_alloc pin end") == 1,
    "mem ready": source.count("GH_DIAG mem_alloc ready") == 1,
    "mem fail": source.count("GH_DIAG mem_alloc fail") == 1,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("FATAL: incomplete Gunyah memory diagnostics: " + ", ".join(failed))

path.write_text(source)
print(f"Applied Gunyah memory diagnostic markers to {path}")
PY

python3 - "$VM_TARGET" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
source = path.read_text()

if "GH_DIAG vm_start enter" not in source:
    replacements = {
        "\tdown_write(&ghvm->status_lock);\n\tif (ghvm->vm_status != GH_RM_VM_STATUS_NO_STATE) {":
            "\tdown_write(&ghvm->status_lock);\n"
            "\tpr_info(\"GH_DIAG vm_start enter status=%u mappings_empty=%u\\n\",\n"
            "\t\t(unsigned int)ghvm->vm_status,\n"
            "\t\t(unsigned int)list_empty(&ghvm->memory_mappings));\n"
            "\tif (ghvm->vm_status != GH_RM_VM_STATUS_NO_STATE) {",
        "\tret = gh_rm_alloc_vmid(ghvm->rm, 0);\n":
            "\tpr_info(\"GH_DIAG alloc_vmid begin\\n\");\n"
            "\tret = gh_rm_alloc_vmid(ghvm->rm, 0);\n"
            "\tpr_info(\"GH_DIAG alloc_vmid end ret=%d\\n\", ret);\n",
        "\t\tswitch (mapping->share_type) {\n":
            "\t\tpr_info(\"GH_DIAG mem_share begin vmid=%u label=%u type=%u entries=%u\\n\",\n"
            "\t\t\tghvm->vmid, mapping->parcel.label,\n"
            "\t\t\t(unsigned int)mapping->share_type,\n"
            "\t\t\tmapping->parcel.n_mem_entries);\n"
            "\t\tswitch (mapping->share_type) {\n",
        "\t\tif (ret) {\n\t\t\tdev_warn(ghvm->parent, \"Failed to %s parcel %d: %d\\n\",":
            "\t\tpr_info(\"GH_DIAG mem_share end vmid=%u label=%u ret=%d handle=%u\\n\",\n"
            "\t\t\tghvm->vmid, mapping->parcel.label, ret, mapping->parcel.mem_handle);\n"
            "\t\tif (ret) {\n"
            "\t\t\tdev_warn(ghvm->parent, \"Failed to %s parcel %d: %d\\n\",",
        "\tret = gh_rm_vm_configure(ghvm->rm, ghvm->vmid, ghvm->auth, mem_handle,\n":
            "\tpr_info(\"GH_DIAG vm_configure begin vmid=%u auth=%u handle=%u dtb_offset=%llu dtb_size=%llu\\n\",\n"
            "\t\tghvm->vmid, (unsigned int)ghvm->auth, mem_handle,\n"
            "\t\t(unsigned long long)dtb_offset,\n"
            "\t\t(unsigned long long)ghvm->dtb_config.size);\n"
            "\tret = gh_rm_vm_configure(ghvm->rm, ghvm->vmid, ghvm->auth, mem_handle,\n",
        "\tif (ret) {\n\t\tdev_warn(ghvm->parent, \"Failed to configure VM: %d\\n\", ret);":
            "\tpr_info(\"GH_DIAG vm_configure end vmid=%u ret=%d\\n\", ghvm->vmid, ret);\n"
            "\tif (ret) {\n"
            "\t\tdev_warn(ghvm->parent, \"Failed to configure VM: %d\\n\", ret);",
        "\tret = gh_rm_vm_init(ghvm->rm, ghvm->vmid);\n":
            "\tpr_info(\"GH_DIAG vm_init begin vmid=%u\\n\", ghvm->vmid);\n"
            "\tret = gh_rm_vm_init(ghvm->rm, ghvm->vmid);\n"
            "\tpr_info(\"GH_DIAG vm_init end vmid=%u ret=%d\\n\", ghvm->vmid, ret);\n",
        "\tret = gh_rm_get_hyp_resources(ghvm->rm, ghvm->vmid, &resources);\n":
            "\tpr_info(\"GH_DIAG hyp_resources begin vmid=%u\\n\", ghvm->vmid);\n"
            "\tret = gh_rm_get_hyp_resources(ghvm->rm, ghvm->vmid, &resources);\n"
            "\tpr_info(\"GH_DIAG hyp_resources end vmid=%u ret=%d entries=%u\\n\",\n"
            "\t\tghvm->vmid, ret, ret ? 0 : le32_to_cpu(resources->n_entries));\n",
        "\t\tgh_vm_add_resource(ghvm, ghrsc);\n":
            "\t\tpr_info(\"GH_DIAG resource add begin index=%d type=%u label=%u capid=%llu\\n\",\n"
            "\t\t\ti, (unsigned int)ghrsc->type, ghrsc->rm_label,\n"
            "\t\t\t(unsigned long long)ghrsc->capid);\n"
            "\t\tgh_vm_add_resource(ghvm, ghrsc);\n"
            "\t\tpr_info(\"GH_DIAG resource add end index=%d type=%u label=%u\\n\",\n"
            "\t\t\ti, (unsigned int)ghrsc->type, ghrsc->rm_label);\n",
        "\tret = gh_rm_vm_start(ghvm->rm, ghvm->vmid);\n":
            "\tpr_info(\"GH_DIAG rm_vm_start begin vmid=%u\\n\", ghvm->vmid);\n"
            "\tret = gh_rm_vm_start(ghvm->rm, ghvm->vmid);\n"
            "\tpr_info(\"GH_DIAG rm_vm_start end vmid=%u ret=%d\\n\", ghvm->vmid, ret);\n",
        "err:\n\t/* gh_vm_free will handle releasing resources and reclaiming memory */":
            "err:\n"
            "\tpr_info(\"GH_DIAG vm_start exit-error vmid=%u status=%u ret=%d\\n\",\n"
            "\t\tghvm->vmid, (unsigned int)ghvm->vm_status, ret);\n"
            "\t/* gh_vm_free will handle releasing resources and reclaiming memory */",
    }
    for old, new in replacements.items():
        if source.count(old) != 1:
            raise SystemExit(f"FATAL: cannot place Gunyah VM diagnostic marker: {old!r}")
        source = source.replace(old, new, 1)

checks = {
    "vm start": source.count("GH_DIAG vm_start enter") == 1,
    "vmid": source.count("GH_DIAG alloc_vmid begin") == 1,
    "memory share": source.count("GH_DIAG mem_share begin") == 1,
    "configure": source.count("GH_DIAG vm_configure begin") == 1,
    "init": source.count("GH_DIAG vm_init begin") == 1,
    "resources": source.count("GH_DIAG hyp_resources begin") == 1,
    "resource population": source.count("GH_DIAG resource add begin") == 1,
    "hypervisor start": source.count("GH_DIAG rm_vm_start begin") == 1,
    "error exit": source.count("GH_DIAG vm_start exit-error") == 1,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("FATAL: incomplete Gunyah VM diagnostics: " + ", ".join(failed))

path.write_text(source)
print(f"Applied Gunyah VM-start diagnostic markers to {path}")
PY

python3 - "$IRQ_TARGET" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
source = path.read_text()

if "struct gh_irqfd_group" in source:
    checks = {
        "single shared resource ticket": source.count(
            "gh_vm_add_resource_ticket(f->ghvm, &group->ticket);"
        ) == 1,
        "grouped duplicate irqfds": "list_add(&irqfd->group_list, &group->irqfds);" in source,
        "mixed semantics fallback": "Gunyah irqfd label %u is shared by edge and level sources; using edge-compatible semantics" in source,
        "wait queue removed on unbind": "eventfd_ctx_remove_wait_queue(irqfd->ctx, &irqfd->wait, &cnt);" in source,
        "irqfd diagnostics": source.count("GH_DIAG irqfd populate") == 1,
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise SystemExit("FATAL: incomplete grouped Gunyah IRQFD fix: " + ", ".join(failed))
    print(f"Grouped Gunyah IRQFD compatibility fix already present in {path}")
    raise SystemExit(0)

if source.count("struct gh_irqfd {") != 1:
    raise SystemExit(f"FATAL: unexpected gh_irqfd structure layout in {path}")

include_marker = "#include <linux/module.h>\n"
if source.count(include_marker) != 1:
    raise SystemExit("FATAL: cannot place explicit linux/mutex.h include")
source = source.replace(include_marker, include_marker + "#include <linux/mutex.h>\n", 1)

struct_pattern = re.compile(
    r"struct gh_irqfd \{.*?\n\};\n\n"
    r"(?=static int irqfd_wakeup)",
    re.S,
)
struct_replacement = r'''struct gh_irqfd_group {
	struct list_head list;
	struct list_head irqfds;
	struct gh_vm *ghvm;
	struct gh_resource *ghrsc;
	struct gh_vm_resource_ticket ticket;
	bool level;
	bool mixed;
};

struct gh_irqfd {
	struct gh_vm_function_instance *f;
	struct gh_irqfd_group *group;
	struct list_head group_list;

	bool level;

	struct eventfd_ctx *ctx;
	wait_queue_entry_t wait;
	poll_table pt;
};

static LIST_HEAD(gh_irqfd_groups);
static DEFINE_MUTEX(gh_irqfd_groups_lock);

static struct gh_irqfd_group *gh_irqfd_find_group(struct gh_vm *ghvm, u32 label)
{
	struct gh_irqfd_group *group;

	list_for_each_entry(group, &gh_irqfd_groups, list) {
		if (group->ghvm == ghvm && group->ticket.label == label)
			return group;
	}

	return NULL;
}

'''
source, count = struct_pattern.subn(lambda _: struct_replacement, source, count=1)
if count != 1:
    raise SystemExit("FATAL: failed to replace gh_irqfd structure")

wakeup_pattern = re.compile(
    r"static int irqfd_wakeup\(.*?\n\}\n\n"
    r"(?=static void irqfd_ptable_queue_proc)",
    re.S,
)
wakeup_replacement = r'''static int irqfd_wakeup(wait_queue_entry_t *wait, unsigned int mode, int sync, void *key)
{
	struct gh_irqfd *irqfd = container_of(wait, struct gh_irqfd, wait);
	struct gh_resource *ghrsc = READ_ONCE(irqfd->group->ghrsc);
	__poll_t flags = key_to_poll(key);
	int ret = 0;

	if (flags & EPOLLIN) {
		if (ghrsc) {
			ret = gh_hypercall_bell_send(ghrsc->capid, 1, NULL);
			if (ret)
				pr_err_ratelimited("Failed to inject interrupt %d: %d\n",
						irqfd->group->ticket.label, ret);
		} else
			pr_err_ratelimited("Premature injection of interrupt\n");
	}

	return 0;
}

'''
source, count = wakeup_pattern.subn(lambda _: wakeup_replacement, source, count=1)
if count != 1:
    raise SystemExit("FATAL: failed to replace irqfd_wakeup()")

populate_pattern = re.compile(
    r"static bool gh_irqfd_populate\(.*?\n\}\n\n"
    r"static void gh_irqfd_unpopulate\(.*?\n\}\n\n"
    r"(?=static long gh_irqfd_bind)",
    re.S,
)
populate_replacement = r'''static bool gh_irqfd_populate(struct gh_vm_resource_ticket *ticket, struct gh_resource *ghrsc)
{
	struct gh_irqfd_group *group = container_of(ticket, struct gh_irqfd_group, ticket);
	int ret;

	if (READ_ONCE(group->ghrsc)) {
		pr_warn("irqfd%d already got a Gunyah resource. Check if multiple resources with same label were configured.\n",
			group->ticket.label);
		return false;
	}

	WRITE_ONCE(group->ghrsc, ghrsc);
	pr_info("GH_DIAG irqfd populate label=%u capid=%llu level=%u mixed=%u\n",
		group->ticket.label, (unsigned long long)ghrsc->capid,
		(unsigned int)group->level, (unsigned int)group->mixed);
	if (group->level) {
		/* Configure the shared bell as level triggered only when every
		 * source registered for this label uses level semantics.
		 *
		 * A shared edge/level label must retain the default edge-compatible
		 * bell behaviour.  Enabling the automatic acknowledgement mask for
		 * such a mixed label can wedge affected Gunyah implementations while
		 * the VM resources are being populated.
		 */
		ret = gh_hypercall_bell_set_mask(ghrsc->capid, 1, 1);
		if (ret)
			pr_warn("irq %d couldn't be set as level triggered. Might cause IRQ storm if asserted\n",
				group->ticket.label);
	}

	return true;
}

static void gh_irqfd_unpopulate(struct gh_vm_resource_ticket *ticket, struct gh_resource *ghrsc)
{
	struct gh_irqfd_group *group = container_of(ticket, struct gh_irqfd_group, ticket);

	if (WARN_ON(READ_ONCE(group->ghrsc) != ghrsc))
		return;

	WRITE_ONCE(group->ghrsc, NULL);
}

'''
source, count = populate_pattern.subn(lambda _: populate_replacement, source, count=1)
if count != 1:
    raise SystemExit("FATAL: failed to replace Gunyah IRQFD resource callbacks")

bind_pattern = re.compile(
    r"static long gh_irqfd_bind\(.*?\n\}\n\n"
    r"(?=static void gh_irqfd_unbind)",
    re.S,
)
bind_replacement = r'''static long gh_irqfd_bind(struct gh_vm_function_instance *f)
{
	struct gh_fn_irqfd_arg *args = f->argp;
	struct gh_irqfd_group *group;
	struct gh_irqfd *irqfd;
	__poll_t events;
	struct fd fd;
	long r;

	if (f->arg_size != sizeof(*args))
		return -EINVAL;

	/* All other flag bits are reserved for future use */
	if (args->flags & ~GH_IRQFD_FLAGS_LEVEL)
		return -EINVAL;

	irqfd = kzalloc(sizeof(*irqfd), GFP_KERNEL);
	if (!irqfd)
		return -ENOMEM;

	irqfd->f = f;
	f->data = irqfd;

	fd = fdget(args->fd);
	if (!fd.file) {
		kfree(irqfd);
		return -EBADF;
	}

	irqfd->ctx = eventfd_ctx_fileget(fd.file);
	if (IS_ERR(irqfd->ctx)) {
		r = PTR_ERR(irqfd->ctx);
		goto err_fdput;
	}

	irqfd->level = args->flags & GH_IRQFD_FLAGS_LEVEL;
	init_waitqueue_func_entry(&irqfd->wait, irqfd_wakeup);
	init_poll_funcptr(&irqfd->pt, irqfd_ptable_queue_proc);

	mutex_lock(&gh_irqfd_groups_lock);
	group = gh_irqfd_find_group(f->ghvm, args->label);
	if (!group) {
		group = kzalloc(sizeof(*group), GFP_KERNEL);
		if (!group) {
			r = -ENOMEM;
			goto err_unlock;
		}

		INIT_LIST_HEAD(&group->irqfds);
		group->ghvm = f->ghvm;
		group->level = irqfd->level;
		group->ticket.resource_type = GH_RESOURCE_TYPE_BELL_TX;
		group->ticket.label = args->label;
		group->ticket.owner = THIS_MODULE;
		group->ticket.populate = gh_irqfd_populate;
		group->ticket.unpopulate = gh_irqfd_unpopulate;

		r = gh_vm_add_resource_ticket(f->ghvm, &group->ticket);
		if (r) {
			kfree(group);
			goto err_unlock;
		}
		list_add(&group->list, &gh_irqfd_groups);
	} else if (!group->mixed && irqfd->level != group->level) {
		/* crosvm can share one guest IRQ between edge and level sources.
		 * Decide the common bell mode before resource population.  Changing
		 * the acknowledgement mask after assignment would be unsafe.
		 */
		if (READ_ONCE(group->ghrsc)) {
			pr_warn("Gunyah irqfd label %u cannot mix edge and level sources after resource assignment\n",
				args->label);
			r = -EBUSY;
			goto err_unlock;
		}

		group->mixed = true;
		group->level = false;
		pr_warn("Gunyah irqfd label %u is shared by edge and level sources; using edge-compatible semantics\n",
			args->label);
	}

	irqfd->group = group;
	list_add(&irqfd->group_list, &group->irqfds);
	mutex_unlock(&gh_irqfd_groups_lock);

	events = vfs_poll(fd.file, &irqfd->pt);
	if (events & EPOLLIN)
		pr_warn("Premature injection of interrupt\n");
	fdput(fd);

	return 0;

err_unlock:
	mutex_unlock(&gh_irqfd_groups_lock);
	eventfd_ctx_put(irqfd->ctx);
err_fdput:
	fdput(fd);
	kfree(irqfd);
	return r;
}

'''
source, count = bind_pattern.subn(lambda _: bind_replacement, source, count=1)
if count != 1:
    raise SystemExit("FATAL: failed to replace gh_irqfd_bind()")

unbind_pattern = re.compile(
    r"static void gh_irqfd_unbind\(.*?\n\}\n\n"
    r"(?=static bool gh_irqfd_compare)",
    re.S,
)
unbind_replacement = r'''static void gh_irqfd_unbind(struct gh_vm_function_instance *f)
{
	struct gh_irqfd *irqfd = f->data;
	struct gh_irqfd_group *group = irqfd->group;
	bool free_group = false;
	u64 cnt;

	eventfd_ctx_remove_wait_queue(irqfd->ctx, &irqfd->wait, &cnt);

	mutex_lock(&gh_irqfd_groups_lock);
	list_del(&irqfd->group_list);
	if (list_empty(&group->irqfds)) {
		list_del(&group->list);
		gh_vm_remove_resource_ticket(group->ghvm, &group->ticket);
		free_group = true;
	}
	mutex_unlock(&gh_irqfd_groups_lock);

	if (free_group)
		kfree(group);
	eventfd_ctx_put(irqfd->ctx);
	kfree(irqfd);
}

'''
source, count = unbind_pattern.subn(lambda _: unbind_replacement, source, count=1)
if count != 1:
    raise SystemExit("FATAL: failed to replace gh_irqfd_unbind()")

checks = {
    "single shared resource ticket": source.count(
        "gh_vm_add_resource_ticket(f->ghvm, &group->ticket);"
    ) == 1,
    "grouped duplicate irqfds": source.count(
        "list_add(&irqfd->group_list, &group->irqfds);"
    ) == 1,
    "per-instance resource ticket removed": "&irqfd->ticket" not in source,
    "mixed semantics fallback": source.count(
        "Gunyah irqfd label %u is shared by edge and level sources; using edge-compatible semantics"
    ) == 1,
    "wait queue removed on unbind": source.count(
        "eventfd_ctx_remove_wait_queue(irqfd->ctx, &irqfd->wait, &cnt);"
    ) == 1,
    "irqfd diagnostics": source.count("GH_DIAG irqfd populate") == 1,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("FATAL: incomplete grouped Gunyah IRQFD fix: " + ", ".join(failed))

path.write_text(source)
print(f"Applied grouped Gunyah IRQFD compatibility fix to {path}")
PY

grep -qF 'struct gh_irqfd_group {' "$IRQ_TARGET"
grep -qF 'list_add(&irqfd->group_list, &group->irqfds);' "$IRQ_TARGET"
grep -qF 'using edge-compatible semantics' "$IRQ_TARGET"
test "$(grep -cF 'gh_vm_add_resource_ticket(f->ghvm, &group->ticket);' "$IRQ_TARGET")" -eq 1
test "$(grep -cF 'eventfd_ctx_remove_wait_queue(irqfd->ctx, &irqfd->wait, &cnt);' "$IRQ_TARGET")" -eq 1
grep -qF 'GH_DIAG mem_alloc enter' "$MEM_TARGET"
grep -qF 'GH_DIAG vm_start enter' "$VM_TARGET"
grep -qF 'GH_DIAG rm_vm_start begin' "$VM_TARGET"
grep -qF 'GH_DIAG irqfd populate' "$IRQ_TARGET"
