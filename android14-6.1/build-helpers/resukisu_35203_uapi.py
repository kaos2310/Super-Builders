#!/usr/bin/env python3
"""Verify the exact UAPI5 source contract and exercise the real service-event C.

Host C tests cover sequential events with kernel API mocks. They do not prove
concurrent behavior or the Samsung init ordering on a physical device.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

PIN = '8770c7e324a22895703c4916b8a16520e0b81c79'


def function(text, name):
    pattern = r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''
    masked = re.sub(pattern, lambda m: re.sub(r'[^\n]', ' ', m[0]), text, flags=re.S)
    matches = list(re.finditer(r'^(?:static\s+)?(?:int|void|bool)\s+' + name + r'\([^;{]*\)\s*\{', masked, re.M))
    if len(matches) != 1:
        raise RuntimeError(f'Expected exactly one definition of {name}')
    match = matches[0]
    pos, depth = match.end(), 1
    while depth and pos < len(masked):
        depth += (masked[pos] == '{') - (masked[pos] == '}')
        pos += 1
    if depth:
        raise RuntimeError(f'Unclosed function {name}')
    return text[match.start():pos]


def git(source, *args):
    return subprocess.check_output(['git', '-C', str(source), *args])


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify_sources(source):
    if git(source, 'rev-parse', 'HEAD').decode().strip() != PIN:
        raise RuntimeError('UAPI5 service audit requires exact ReSukiSU 35203')
    if int(git(source, 'rev-list', '--count', 'HEAD')) + 30700 != 35203:
        raise RuntimeError('ReSukiSU 35203 version formula mismatch')
    names = git(source, 'ls-tree', '-r', '--name-only', PIN, '--', 'uapi').decode().splitlines()
    names += ['userspace/ksud/src/android/init_event.rs', 'userspace/ksud/src/android/ksucalls.rs',
              'userspace/ksud/src/android/uapi/ksu_uapi.h', 'userspace/ksud/src/android/uapi/mod.rs']
    hashes = {}
    for name in names:
        actual = (source / name).read_bytes()
        if actual != git(source, 'show', f'{PIN}:{name}'):
            raise RuntimeError(f'UAPI5 source differs from immutable upstream: {name}')
        hashes[name] = sha(actual)
    header = (source / 'uapi/supercall.h').read_text()
    if not re.search(r'KERNEL_SU_UAPI_VERSION\s*=\s*5\s*;', header):
        raise RuntimeError('UAPI version 5 required')
    if not re.search(r'DEFINE_KSU_UAPI_CONST\(__u32, EVENT_SERVICES, 4\)', header):
        raise RuntimeError('EVENT_SERVICES=4 required')
    dispatch = 'kernel/supercall/dispatch.c'
    event = function((source / dispatch).read_text(), 'do_report_event')
    expected = function(git(source, 'show', f'{PIN}:{dispatch}').decode(), 'do_report_event')
    if event != expected:
        raise RuntimeError('Upstream EVENT_SERVICES start/skip/reset gate changed')
    return dict(commit=PIN, version=35203, uapi_version=5, event_services=4,
                source_sha256=hashes, report_event_sha256=sha(event.encode()))


def verify_bindings(source):
    # Fresh checkout and no target cache are required by the workflow. Audit the
    # generated file as additional evidence beyond a successful Android compile.
    paths = list((source / 'userspace/ksud/target/aarch64-linux-android/release/build').glob('ksud-*/out/bindings.rs'))
    if len(paths) != 1:
        raise RuntimeError(f'Expected one fresh ksud bindings.rs, found {len(paths)}')
    text = paths[0].read_text()
    for name, value in [('KERNEL_SU_UAPI_VERSION', 5), ('EVENT_SERVICES', 4)]:
        if not re.search(r'pub const ' + name + r':\s*[^=;\n]+\s*=\s*' + str(value) + r'\s*;', text):
            raise RuntimeError(f'Generated Rust bindings lack {name}={value}')
    return dict(path=paths[0].relative_to(source).as_posix(), sha256=sha(paths[0].read_bytes()),
                uapi_version=5, event_services=4)


PRELUDE = r'''
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#define __user
#define EFAULT 14
#define EVENT_POST_FS_DATA 1
#define EVENT_BOOT_COMPLETED 2
#define EVENT_MODULE_MOUNTED 3
#define EVENT_SERVICES 4
struct ksu_report_event_cmd { unsigned int event; };
static bool copy_fault, ksu_late_loaded;
static int starts, skips, post_calls, boot_calls, mount_calls, monitor_calls;
static int copy_from_user(void *dst, const void *src, size_t size) {
    if (copy_fault) return 1;
    memcpy(dst, src, size); return 0;
}
static void pr_info(const char *message) {
    if (!strcmp(message, "services triggered\n")) starts++;
    if (!strcmp(message, "services already started, skipping\n")) skips++;
}
static void on_post_fs_data(void) { post_calls++; }
static void on_boot_completed(void) { boot_calls++; }
static void on_module_mounted(void) { mount_calls++; }
#ifdef CONFIG_KSU_SUSFS
static void susfs_start_sdcard_monitor_fn(void) { monitor_calls++; }
#endif
'''

CHECKS = r'''
static int send(unsigned int event) {
    struct ksu_report_event_cmd cmd = { event }; return do_report_event(&cmd);
}
#define CHECK(condition) do { if (!(condition)) return __LINE__; } while (0)
int main(void) {
    CHECK(send(EVENT_POST_FS_DATA) == 0 && post_calls == 1);
    CHECK(send(EVENT_SERVICES) == 1 && starts == 1 && skips == 0);
    CHECK(send(EVENT_SERVICES) == 0 && starts == 1 && skips == 1);
    CHECK(send(EVENT_BOOT_COMPLETED) == 0 && boot_calls == 1);
    CHECK(send(EVENT_MODULE_MOUNTED) == 0 && mount_calls == 1);
    CHECK(send(999) == 0);
    CHECK(send(EVENT_SERVICES) == 0 && starts == 1 && skips == 2);
    copy_fault = true;
    CHECK(send(EVENT_POST_FS_DATA) == -EFAULT);
    CHECK(send(EVENT_SERVICES) == -EFAULT && starts == 1 && skips == 2);
    copy_fault = false;
    CHECK(send(EVENT_SERVICES) == 0 && starts == 1 && skips == 3);
    /* Soft reboot: even a repeated post-fs-data must reset only service state. */
    CHECK(send(EVENT_POST_FS_DATA) == 0 && post_calls == 1);
    CHECK(send(EVENT_SERVICES) == 1 && starts == 2 && skips == 3);
    CHECK(send(EVENT_SERVICES) == 0 && starts == 2 && skips == 4);
    ksu_late_loaded = true;
    CHECK(send(EVENT_POST_FS_DATA) == 0 && post_calls == 1);
    CHECK(send(EVENT_SERVICES) == 1 && starts == 3 && skips == 4);
    CHECK(send(EVENT_SERVICES) == 0 && starts == 3 && skips == 5);
    CHECK(send(EVENT_BOOT_COMPLETED) == 0 && boot_calls == 1);
#ifdef CONFIG_KSU_SUSFS
    CHECK(monitor_calls == 1);
#else
    CHECK(monitor_calls == 0);
#endif
    return 0;
}
'''


def test_events(source, cc, work):
    work.mkdir(parents=True, exist_ok=True)
    event = function((source / 'kernel/supercall/dispatch.c').read_text(), 'do_report_event')
    variants = {'production': event}
    for label, old, new in [
        ('duplicate-start', 'if (services_started)', 'if (false)'),
        ('missing-soft-reset', '        services_started = false;', '        /* reset removed */'),
        ('wrong-start-result', '        return 1;', '        return 0;'),
    ]:
        if event.count(old) != 1:
            raise RuntimeError(f'Service test mutation anchor changed: {label}')
        variants[label] = event.replace(old, new)
    results = {}
    for enabled in (False, True):
        for label, body in variants.items():
            name = label + ('-susfs-on' if enabled else '-susfs-off')
            src, binary = work / (name + '.c'), work / name
            src.write_text(PRELUDE + body + CHECKS, encoding='utf-8', newline='\n')
            command = [cc, '-std=gnu11', '-Wall', '-Werror=implicit-function-declaration']
            if enabled:
                command += ['-DCONFIG_KSU_SUSFS']
            subprocess.run(command + [str(src), '-o', str(binary)], check=True)
            result = subprocess.run([str(binary)])
            if (result.returncode == 0) != (label == 'production'):
                raise RuntimeError(f'Unexpected service test result for {name}: {result.returncode}')
            results[name] = dict(exit_code=result.returncode, mutation_rejected=label != 'production')
    return dict(cases=results, negative_controls_rejected=6,
                limitation='Sequential kernel API mocks; concurrency and exact-Image device boot unverified')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--cc')
    parser.add_argument('--work-dir', type=Path)
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    result = verify_sources(args.source.resolve())
    if args.cc:
        if not args.work_dir:
            parser.error('--cc requires --work-dir')
        result['service_tests'] = test_events(args.source.resolve(), args.cc, args.work_dir.resolve())
    if args.receipt:
        args.receipt.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
