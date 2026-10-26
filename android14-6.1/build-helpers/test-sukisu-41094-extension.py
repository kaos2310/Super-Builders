#!/usr/bin/env python3
"""Exercise the native 41094 extension ioctl with its real UAPI and C handler.

Host mocks cover ABI layout, dispatch, error propagation and pointer width.
They do not establish device behavior or concurrency guarantees.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
PIN = '2ec445ffcb803614ee41ce111b6bad28c67f3347'
spec = importlib.util.spec_from_file_location('uapi41094', HERE / 'sukisu_41094_uapi.py')
uapi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uapi)

PRELUDE = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
#include "uapi/extension.h"
#define __user
typedef uint32_t u32;
typedef uint64_t u64;
_Static_assert(sizeof(struct ksu_extension_cmd) == 32, "extension ABI size");
_Static_assert(offsetof(struct ksu_extension_cmd, value) == 16, "value offset");
_Static_assert(offsetof(struct ksu_extension_cmd, user_ptr) == 24, "pointer offset");
_Static_assert(KSU_EXTENSION_SUSFS == 4 && KSU_EXTENSION_MAX == 6, "native IDs");
_Static_assert(KSU_EXTENSION_VERSION_SPOOF == 5, "native version extension ID");
_Static_assert(sizeof(struct ksu_version_spoof_cmd) == 536, "native version payload");
static bool from_fault, to_fault, mock_supported = true, forced;
static int get_error, set_error, io_error, wipe_error, gets, sets, ios, wipes;
static u64 mock_value = 0x100000001ULL, set_value;
static uintptr_t passed_pointer;
static int copy_from_user(void *d, const void *s, size_t n) {
    if (from_fault) return 1;
    memcpy(d, s, n); return 0;
}
static int copy_to_user(void *d, const void *s, size_t n) {
    if (to_fault) return 1;
    memcpy(d, s, n); return 0;
}
static int ksu_extension_get(u32 id, u64 *v, bool *s) {
    gets++; *v = mock_value; *s = mock_supported; return get_error;
}
static int ksu_extension_set(u32 id, u64 v) {
    sets++; set_value = v; return set_error;
}
static bool ksu_extension_is_forced(u32 id) { return forced; }
static int ksu_extension_ioctl(u32 id, void *p) {
    ios++; passed_pointer = (uintptr_t)p; return io_error;
}
static int ksu_extension_wipe(u32 id) { wipes++; return wipe_error; }
'''

CHECKS = r'''
#define CHECK(x) do { if (!(x)) return __LINE__; } while (0)
int main(void) {
    struct ksu_extension_cmd cmd = {.id = KSU_EXTENSION_SUSFS, .op = KSU_EXTENSION_GET};
    CHECK(KSU_IOCTL_EXTENSION == _IOC(_IOC_READ | _IOC_WRITE, 'K', 300, 32));
    from_fault = true;
    CHECK(do_extension(&cmd) == -EFAULT && gets == 0);
    from_fault = false;
    cmd.id = KSU_EXTENSION_MAX;
    CHECK(do_extension(&cmd) == -EINVAL && gets == 0);
    cmd.id = KSU_EXTENSION_SUSFS;
    CHECK(do_extension(&cmd) == 0 && cmd.value == mock_value && cmd.supported == 1);
    forced = true;
    CHECK(do_extension(&cmd) == 0 && cmd.supported == 129);
    forced = false; mock_supported = false;
    CHECK(do_extension(&cmd) == -EOPNOTSUPP);
    mock_supported = true; get_error = -EIO;
    CHECK(do_extension(&cmd) == -EIO);
    get_error = 0; to_fault = true;
    CHECK(do_extension(&cmd) == -EFAULT);
    to_fault = false;
    cmd.op = KSU_EXTENSION_SET; cmd.value = 0x123456789ULL;
    set_error = -EPERM;
    CHECK(do_extension(&cmd) == -EPERM && sets == 1 && set_value == 0x123456789ULL);
    set_error = 0; forced = true;
    CHECK(do_extension(&cmd) == 0 && cmd.value == mock_value && cmd.supported == 129);
    to_fault = true;
    CHECK(do_extension(&cmd) == -EFAULT);
    to_fault = false;
    cmd.op = KSU_EXTENSION_IO; cmd.user_ptr = 0x123456789ULL; io_error = -EIO;
    CHECK(do_extension(&cmd) == -EIO && ios == 1 && passed_pointer == 0x123456789ULL);
    cmd.op = KSU_EXTENSION_WIPE; wipe_error = -EPERM;
    CHECK(do_extension(&cmd) == -EPERM && wipes == 1);
    return 0;
}
'''


def test(source, cc, work):
    uapi.verify_sources(source)
    dispatch = (source / 'kernel/supercall/dispatch.c').read_text()
    body = uapi.function(dispatch, 'do_extension')
    native = uapi.git(source, 'show', PIN + ':kernel/supercall/dispatch.c').decode()
    if body != uapi.function(native, 'do_extension'):
        raise RuntimeError('Native extension dispatch changed')
    names = uapi.git(source, 'ls-tree', '-r', '--name-only', PIN, '--', 'kernel/extension').decode().splitlines()
    names += ['userspace/ksud/src/extension.rs', 'userspace/ksud/src/extension_id.rs',
              'userspace/ksud/src/temporary_root.rs', 'userspace/ksud/src/version_spoof.rs',
              'kernel/feature/avc_spoof.c', 'kernel/feature/avc_spoof.h',
              'kernel/manager/throne_tracker.c', 'kernel/manager/throne_tracker.h']
    hashes = {}
    for name in names:
        data = (source / name).read_bytes()
        if data != uapi.git(source, 'show', PIN + ':' + name):
            raise RuntimeError('Native extension source changed: ' + name)
        hashes[name] = hashlib.sha256(data).hexdigest()
    init = (source / 'kernel/core/init.c').read_text()
    for token in ('ksu_avc_spoof_init();', 'ksu_avc_spoof_exit();'):
        if init.count(token) != 1:
            raise RuntimeError('Port lost native AVC lifecycle: ' + token)
    if (source / 'kernel/runtime/boot_event.c').read_text().count('ksu_avc_spoof_late_init();') != 1:
        raise RuntimeError('Port lost native AVC boot-completed hook')
    name = 'kernel/policy/allowlist.c'
    rcu = uapi.function((source / name).read_text(), 'ksu_uid_should_umount')
    native_rcu = uapi.function(uapi.git(source, 'show', PIN + ':' + name).decode(), 'ksu_uid_should_umount')
    if rcu != native_rcu:
        raise RuntimeError('Native RCU unmount policy changed')
    hashes['ksu_uid_should_umount'] = hashlib.sha256(rcu.encode()).hexdigest()
    order = [init.index(name + '();') for name in ('ksu_extension_init', 'ksu_extension_register_all', 'ksu_ksud_init')]
    if order != sorted(order) or init.count('ksu_extension_exit();') != 1:
        raise RuntimeError('Port lost native extension lifecycle')
    runtime = (source / 'kernel/runtime/ksud_integration.c').read_text()
    if runtime.count('ksu_extension_apply_forced();') != 1 or not re.search(r'ksu_feature_apply_forced\(\);\s+ksu_extension_apply_forced\(\);', runtime):
        raise RuntimeError('Port lost forced-extension replay at init second stage')
    variants = {'production': body}
    mutations = [
        ('id-guard', 'extension_id >= KSU_EXTENSION_MAX', 'false'),
        ('forced-flag', 'cmd.supported |= KSU_EXTENSION_FLAG_FORCED;', 'cmd.supported |= 0;'),
        ('set-error', 'if (ret)\n            return ret;', 'if (false)\n            return ret;'),
        ('pointer-width', '(uintptr_t)cmd.user_ptr', '(u32)cmd.user_ptr'),
    ]
    for label, before, after in mutations:
        if before not in body:
            raise RuntimeError('Extension mutation anchor changed: ' + label)
        variants[label] = body.replace(before, after)
    results = {}
    for label, function in variants.items():
        src = work / (label + '.c')
        binary = work / label
        src.write_text(PRELUDE + function + CHECKS, encoding='utf-8', newline='\n')
        subprocess.run([cc, '-std=gnu11', '-Wall', '-Werror=implicit-function-declaration', '-I', str(source), str(src), '-o', str(binary)], check=True)
        result = subprocess.run([str(binary)])
        if (result.returncode == 0) != (label == 'production'):
            raise RuntimeError('Extension test/negative control failed: ' + label)
        results[label] = result.returncode
    return {'pin': PIN, 'version': 41094, 'native_sources_sha256': hashes,
            'handler_sha256': hashlib.sha256(body.encode()).hexdigest(),
            'abi_size': 32, 'extension_count': 6, 'lifecycle_preserved': True,
            'native_handler_test_passed': True, 'negative_controls_rejected': 4,
            'tests': results, 'device_runtime_tested': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ksu', type=Path, required=True)
    parser.add_argument('--cc', default='gcc')
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='sukisu41094-extension-') as tmp:
        result = test(args.ksu, args.cc, Path(tmp))
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
