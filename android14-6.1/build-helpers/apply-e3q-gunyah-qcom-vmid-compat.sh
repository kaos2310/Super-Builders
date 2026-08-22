#!/usr/bin/env bash
set -euo pipefail

KERNEL_TREE="${1:?usage: apply-e3q-gunyah-qcom-vmid-compat.sh <kernel-tree>}"
BASE_COMMIT="f314a3274b567352a2ad17a76b1c5229b0e9c241"
TMP_DIR="$(mktemp -d -t e3q-qcom-vmid-base.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT

BASE_HELPER="$TMP_DIR/apply-e3q-gunyah-qcom-vmid-compat.sh"
curl --fail --location --silent --show-error --retry 3 --retry-delay 2 \
  "https://raw.githubusercontent.com/kaos2310/Super-Builders/${BASE_COMMIT}/android14-6.1/build-helpers/apply-e3q-gunyah-qcom-vmid-compat.sh" \
  -o "$BASE_HELPER"

test -s "$BASE_HELPER" || { echo 'FATAL: pinned e3q QCOM baseline helper is empty' >&2; exit 1; }
bash -n "$BASE_HELPER"

# The pinned helper is the runtime-proven SCM/VMID implementation. Keep the
# functional path intact and deliberately do not inject pr_info()/pr_err()
# diagnostics: gunyah_qcom must not gain the debug-only _printk import.
for token in \
  'static u16 qcom_scm_map_vmid(u16 vmid)' \
  'gh_rm_get_vmid(rm, &self_vmid)' \
  'src = BIT_ULL(qcom_scm_map_vmid(self_vmid));' \
  'new_perms[n].vmid = qcom_scm_map_vmid(vmid);' \
  'src |= BIT_ULL(qcom_scm_map_vmid(vmid));'; do
  grep -qF "$token" "$BASE_HELPER" || {
    echo "FATAL: pinned e3q QCOM baseline missing expected VMID token: $token" >&2
    exit 1
  }
done

bash "$BASE_HELPER" "$KERNEL_TREE"

QCOM_SRC="$KERNEL_TREE/drivers/virt/gunyah/gunyah_qcom.c"
VM_SRC="$KERNEL_TREE/drivers/virt/gunyah/vm_mgr.c"
VM_HDR="$KERNEL_TREE/drivers/virt/gunyah/vm_mgr.h"
RM_RPC="$KERNEL_TREE/drivers/virt/gunyah/rsc_mgr_rpc.c"
RM_HDR="$KERNEL_TREE/include/linux/gunyah_rsc_mgr.h"
UAPI_HDR="$KERNEL_TREE/include/uapi/linux/gunyah.h"

for file in "$QCOM_SRC" "$VM_SRC" "$VM_HDR" "$RM_RPC" "$RM_HDR" "$UAPI_HDR"; do
  test -s "$file" || { echo "FATAL: missing Gunyah source: $file" >&2; exit 1; }
done

require_fixed() {
  local needle="$1" file="$2" label="$3"
  grep -qF "$needle" "$file" || {
    echo "FATAL: missing ${label}: ${needle} in ${file}" >&2
    exit 1
  }
}

require_absent() {
  local needle="$1" file="$2" label="$3"
  if grep -qF "$needle" "$file"; then
    echo "FATAL: unexpected ${label}: ${needle} in ${file}" >&2
    exit 1
  fi
}

# Fail closed on the proven functional semantics while keeping the strict
# modversion audit meaningful.
require_fixed 'static u16 qcom_scm_map_vmid(u16 vmid)' "$QCOM_SRC" 'SCM VMID mapping helper'
require_fixed 'gh_rm_get_vmid(rm, &self_vmid)' "$QCOM_SRC" 'dynamic RM self-VMID lookup'
require_fixed 'src = BIT_ULL(qcom_scm_map_vmid(self_vmid));' "$QCOM_SRC" 'SCM source VMID mapping'
require_fixed 'new_perms[n].vmid = qcom_scm_map_vmid(vmid);' "$QCOM_SRC" 'SCM destination VMID mapping'
require_fixed 'src |= BIT_ULL(qcom_scm_map_vmid(vmid));' "$QCOM_SRC" 'SCM reclaim VMID mapping'
require_absent 'GH_QCOM_DIAG' "$QCOM_SRC" 'printk-based runtime diagnostics'
require_absent 'GH_QCOM_SCM' "$QCOM_SRC" 'abandoned GH_QCOM_SCM workaround'

# Android 14/6.1 predates the upstream boot-context UAPI used by modern crosvm.
# Runtime evidence on e3q shows SET_BOOT_PC receives ENOTTY with pc=0x80000000
# and payload_offset=0, immediately followed by RM VM_START -> NORESOURCE/-ENODEV.
# Backport the upstream flow without touching memory sharing, MEM_APPEND, IRQFD,
# VCPU resource handling, SCM ownership, or the 8192-entry circuit breaker.
python3 - "$VM_SRC" "$VM_HDR" "$RM_RPC" "$RM_HDR" "$UAPI_HDR" <<'PY'
from pathlib import Path
import sys

vm_path, vmh_path, rpc_path, rmh_path, uapi_path = map(Path, sys.argv[1:])
vm = vm_path.read_text()
vmh = vmh_path.read_text()
rpc = rpc_path.read_text()
rmh = rmh_path.read_text()
uapi = uapi_path.read_text()


def insert_once(text, anchor, addition, label, before=False):
    if addition.strip() in text:
        return text
    count = text.count(anchor)
    if count != 1:
        raise SystemExit(f"FATAL: {label}: expected one anchor {anchor!r}, found {count}")
    if before:
        return text.replace(anchor, addition + anchor, 1)
    return text.replace(anchor, anchor + addition, 1)

# 1) RM RPC opcode + payload + call.
if 'GH_RM_RPC_VM_SET_BOOT_CONTEXT' not in rpc:
    anchor = '#define GH_RM_RPC_VM_GET_VMID 0x56000024\n'
    if anchor not in rpc:
        raise SystemExit('FATAL: RM GET_VMID opcode anchor missing')
    rpc = rpc.replace(anchor, anchor + '#define GH_RM_RPC_VM_SET_BOOT_CONTEXT 0x56000031\n', 1)

if 'struct gh_rm_vm_set_boot_context_req {' not in rpc:
    anchor = 'struct gh_rm_vm_common_vmid_req {\n'
    pos = rpc.find(anchor)
    if pos < 0:
        raise SystemExit('FATAL: RM common VMID request anchor missing')
    end = rpc.find('} __packed;\n', pos)
    if end < 0:
        raise SystemExit('FATAL: RM common VMID request terminator missing')
    end += len('} __packed;\n')
    payload = '''\n/* Call: VM_SET_BOOT_CONTEXT */\nstruct gh_rm_vm_set_boot_context_req {\n\t__le16 vmid;\n\tu8 reg_set;\n\tu8 reg_idx;\n\t__le32 val_low;\n\t__le32 val_high;\n} __packed;\n'''
    rpc = rpc[:end] + payload + rpc[end:]

if 'int gh_rm_set_boot_context(struct gh_rm *rm,' not in rpc:
    anchor = '/**\n * gh_rm_get_hyp_resources() - Retrieve hypervisor resources'
    if anchor not in rpc:
        raise SystemExit('FATAL: gh_rm_get_hyp_resources documentation anchor missing')
    func = '''/**\n * gh_rm_set_boot_context() - Set initial register context for a VM\n * @rm: Handle to a Gunyah resource manager\n * @vmid: VM identifier\n * @reg_set: Register set selector\n * @reg_idx: Register index within the selected set\n * @value: Initial register value\n */\nint gh_rm_set_boot_context(struct gh_rm *rm, u16 vmid, u8 reg_set, u8 reg_idx, u64 value)\n{\n\tstruct gh_rm_vm_set_boot_context_req req = {\n\t\t.vmid = cpu_to_le16(vmid),\n\t\t.reg_set = reg_set,\n\t\t.reg_idx = reg_idx,\n\t\t.val_low = cpu_to_le32(lower_32_bits(value)),\n\t\t.val_high = cpu_to_le32(upper_32_bits(value)),\n\t};\n\n\treturn gh_rm_call(rm, GH_RM_RPC_VM_SET_BOOT_CONTEXT, &req, sizeof(req), NULL, NULL);\n}\n\n'''
    rpc = rpc.replace(anchor, func + anchor, 1)

if 'int gh_rm_set_boot_context(struct gh_rm *rm,' not in rmh:
    anchor = 'int gh_rm_vm_init(struct gh_rm *rm, u16 vmid);\n'
    if anchor not in rmh:
        raise SystemExit('FATAL: RM header vm_init declaration anchor missing')
    rmh = rmh.replace(anchor, anchor + 'int gh_rm_set_boot_context(struct gh_rm *rm, u16 vmid, u8 reg_set, u8 reg_idx, u64 value);\n', 1)

# 2) Userspace ABI. Keep the legacy GH_* naming used by Android 14/6.1 and crosvm.
if 'struct gh_vm_boot_context {' not in uapi:
    start_macro = '#define GH_VM_START'
    pos = uapi.find(start_macro)
    if pos < 0:
        raise SystemExit('FATAL: GH_VM_START UAPI anchor missing')
    block = '''enum gh_vm_boot_context_reg {\n\tREG_SET_X = 0,\n\tREG_SET_PC = 1,\n\tREG_SET_SP = 2,\n};\n\n#define GH_VM_BOOT_CONTEXT_REG_SHIFT 8\n#define GH_VM_BOOT_CONTEXT_REG(reg, idx) \\\n\t((((reg) & 0xff) << GH_VM_BOOT_CONTEXT_REG_SHIFT) | ((idx) & 0xff))\n\nstruct gh_vm_boot_context {\n\t__u32 reg;\n\t__u32 reserved;\n\t__u64 value;\n};\n\n'''
    uapi = uapi[:pos] + block + uapi[pos:]

if 'GH_VM_SET_BOOT_CONTEXT' not in uapi:
    ioctl_type = 'GH_IOCTL_TYPE' if 'GH_IOCTL_TYPE' in uapi else 'GUNYAH_IOCTL_TYPE'
    start_line = next((line for line in uapi.splitlines(True) if line.startswith('#define GH_VM_START')), None)
    if not start_line:
        raise SystemExit('FATAL: GH_VM_START definition missing for boot-context ioctl insertion')
    uapi = uapi.replace(start_line, start_line + f'#define GH_VM_SET_BOOT_CONTEXT _IOW({ioctl_type}, 0xa, struct gh_vm_boot_context)\n', 1)

# 3) Store requested context until VMID exists, then send to RM after VM_INIT.
if '#include <linux/xarray.h>' not in vmh:
    include_anchor = '#include <linux/wait.h>\n'
    if include_anchor not in vmh:
        raise SystemExit('FATAL: vm_mgr.h wait.h include anchor missing')
    vmh = vmh.replace(include_anchor, include_anchor + '#include <linux/xarray.h>\n', 1)

if 'struct xarray boot_context;' not in vmh:
    anchor = '\tstruct list_head resource_tickets;\n'
    if anchor not in vmh:
        raise SystemExit('FATAL: vm_mgr.h resource_tickets anchor missing')
    vmh = vmh.replace(anchor, anchor + '\tstruct xarray boot_context;\n', 1)

if 'xa_init(&ghvm->boot_context);' not in vm:
    anchor = '\tINIT_LIST_HEAD(&ghvm->resource_tickets);\n'
    if anchor not in vm:
        raise SystemExit('FATAL: gh_vm_alloc resource_tickets anchor missing')
    vm = vm.replace(anchor, anchor + '\txa_init(&ghvm->boot_context);\n', 1)

if 'static long gh_vm_set_boot_context(struct gh_vm *ghvm,' not in vm:
    anchor = 'static int gh_vm_start(struct gh_vm *ghvm)\n'
    if anchor not in vm:
        raise SystemExit('FATAL: gh_vm_start anchor missing')
    helpers = '''static long gh_vm_set_boot_context(struct gh_vm *ghvm,\n\t\t\t\t       struct gh_vm_boot_context *boot_ctx)\n{\n\tu8 reg_set, reg_index;\n\tint ret;\n\n\treg_set = (boot_ctx->reg >> GH_VM_BOOT_CONTEXT_REG_SHIFT) & 0xff;\n\treg_index = boot_ctx->reg & 0xff;\n\n\tswitch (reg_set) {\n\tcase REG_SET_X:\n\t\tif (reg_index > 31)\n\t\t\treturn -EINVAL;\n\t\tbreak;\n\tcase REG_SET_PC:\n\t\tif (reg_index)\n\t\t\treturn -EINVAL;\n\t\tbreak;\n\tcase REG_SET_SP:\n\t\tif (reg_index > 2)\n\t\t\treturn -EINVAL;\n\t\tbreak;\n\tdefault:\n\t\treturn -EINVAL;\n\t}\n\n\tret = down_read_interruptible(&ghvm->status_lock);\n\tif (ret)\n\t\treturn ret;\n\n\tif (ghvm->vm_status != GH_RM_VM_STATUS_NO_STATE) {\n\t\tret = -EINVAL;\n\t\tgoto out;\n\t}\n\n\tret = xa_err(xa_store(&ghvm->boot_context, boot_ctx->reg,\n\t\t\t      (void *)(uintptr_t)boot_ctx->value, GFP_KERNEL));\nout:\n\tup_read(&ghvm->status_lock);\n\treturn ret;\n}\n\nstatic int gh_vm_fill_boot_context(struct gh_vm *ghvm)\n{\n\tunsigned long reg_set, reg_index, id;\n\tvoid *entry;\n\tint ret;\n\n\txa_for_each(&ghvm->boot_context, id, entry) {\n\t\treg_set = (id >> GH_VM_BOOT_CONTEXT_REG_SHIFT) & 0xff;\n\t\treg_index = id & 0xff;\n\t\tret = gh_rm_set_boot_context(ghvm->rm, ghvm->vmid, reg_set, reg_index,\n\t\t\t\t     (u64)(uintptr_t)entry);\n\t\tif (ret)\n\t\t\treturn ret;\n\t}\n\n\treturn 0;\n}\n\n'''
    vm = vm.replace(anchor, helpers + anchor, 1)

if 'ret = gh_vm_fill_boot_context(ghvm);' not in vm:
    anchor = '\tghvm->vm_status = GH_RM_VM_STATUS_READY;\n\n'
    if anchor not in vm:
        raise SystemExit('FATAL: VM READY state anchor missing')
    fill = '''\tret = gh_vm_fill_boot_context(ghvm);\n\tif (ret) {\n\t\tdev_warn(ghvm->parent, "Failed to setup boot context: %d\\n", ret);\n\t\tgoto err;\n\t}\n\n'''
    vm = vm.replace(anchor, anchor + fill, 1)

if 'case GH_VM_SET_BOOT_CONTEXT:' not in vm:
    anchor = '\tcase GH_VM_START: {\n'
    if anchor not in vm:
        raise SystemExit('FATAL: GH_VM_START ioctl switch anchor missing')
    case = '''\tcase GH_VM_SET_BOOT_CONTEXT: {\n\t\tstruct gh_vm_boot_context boot_ctx;\n\n\t\tif (copy_from_user(&boot_ctx, argp, sizeof(boot_ctx)))\n\t\t\treturn -EFAULT;\n\n\t\tr = gh_vm_set_boot_context(ghvm, &boot_ctx);\n\t\tbreak;\n\t}\n'''
    vm = vm.replace(anchor, case + anchor, 1)

if 'xa_destroy(&ghvm->boot_context);' not in vm:
    anchor = '\tgh_rm_put(ghvm->rm);\n'
    if anchor not in vm:
        raise SystemExit('FATAL: gh_vm_free gh_rm_put anchor missing')
    vm = vm.replace(anchor, '\txa_destroy(&ghvm->boot_context);\n' + anchor, 1)

vm_path.write_text(vm)
vmh_path.write_text(vmh)
rpc_path.write_text(rpc)
rmh_path.write_text(rmh)
uapi_path.write_text(uapi)
PY

# Boot-context backport must be complete and must not perturb the runtime-proven
# memory/SCM paths. These checks intentionally fail the build on a partial port.
for token in \
  'GH_RM_RPC_VM_SET_BOOT_CONTEXT 0x56000031' \
  'struct gh_rm_vm_set_boot_context_req {' \
  'int gh_rm_set_boot_context(struct gh_rm *rm,'; do
  require_fixed "$token" "$RM_RPC" 'RM boot-context RPC'
done
require_fixed 'int gh_rm_set_boot_context(struct gh_rm *rm, u16 vmid, u8 reg_set, u8 reg_idx, u64 value);' "$RM_HDR" 'RM boot-context declaration'
for token in \
  'enum gh_vm_boot_context_reg {' \
  'GH_VM_BOOT_CONTEXT_REG_SHIFT 8' \
  'struct gh_vm_boot_context {' \
  'GH_VM_SET_BOOT_CONTEXT'; do
  require_fixed "$token" "$UAPI_HDR" 'boot-context UAPI'
done
for token in \
  'xa_init(&ghvm->boot_context);' \
  'static long gh_vm_set_boot_context(struct gh_vm *ghvm,' \
  'static int gh_vm_fill_boot_context(struct gh_vm *ghvm)' \
  'ret = gh_vm_fill_boot_context(ghvm);' \
  'case GH_VM_SET_BOOT_CONTEXT:' \
  'xa_destroy(&ghvm->boot_context);'; do
  require_fixed "$token" "$VM_SRC" 'VM-manager boot-context path'
done
require_fixed 'struct xarray boot_context;' "$VM_HDR" 'VM boot-context storage'

# Preserve the proven safety/compatibility markers generated earlier in this run.
require_fixed 'mapping->parcel.n_mem_entries > 8192' "$VM_SRC" '8192 mem-share safety guard'
require_fixed 'GH_DIAG mem_share begin' "$VM_SRC" 'memory-share diagnostics'
require_fixed 'GH_RM_RPC_MEM_APPEND' "$RM_RPC" 'RM MEM_APPEND support'
require_fixed 'GH_DIAG rm_append sequence begin' "$RM_RPC" 'RM MEM_APPEND diagnostics'

echo 'e3q Gunyah QCOM VMID path preserved; strict module audit remains printk-clean'
echo 'e3q Gunyah boot-context backport enabled: GH_VM_SET_BOOT_CONTEXT -> RM 0x56000031 before GET_HYP_RESOURCES/VM_START'