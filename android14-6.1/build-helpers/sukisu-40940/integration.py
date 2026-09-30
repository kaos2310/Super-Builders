#!/usr/bin/env python3
"""Adapt generic SUSFS 2.3 exec hooks to the pinned SukiSU builtin contract."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from configure import PIN, MAIN_PIN, VERSION, FULL

SUSFS_PIN = '24743360ea08d98f6ad72b856851abed8de5854f'

def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f'SUSFS source anchor drift: {old[:85]!r}')
    return text.replace(old, new, 1)

def identity(common, ksu):
    actual = subprocess.check_output(['git', '-C', str(ksu), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != PIN:
        raise RuntimeError('Unexpected SukiSU source pin')
    if '#define SUSFS_VERSION "v2.3.0"' not in (common / 'include/linux/susfs.h').read_text():
        raise RuntimeError('Pinned SUSFS 2.3.0 source required')
    # The native driver is installed through the upstream LSM/task-work path.
    # Its [ksu_driver] ABI is distinct from ReSukiSU's post-exec scoped FD.
    source = (ksu / 'kernel/feature/sucompat.c').read_bytes()
    original = subprocess.check_output(['git', '-C', str(ksu), 'show', f'{PIN}:kernel/feature/sucompat.c'])
    if source != original:
        raise RuntimeError('Native SukiSU sucompat source was changed')
    if 'bool ksu_su_compat_enabled __read_mostly = true;' not in source.decode():
        raise RuntimeError('Expected native SukiSU boolean hook switch')
    if 'anon_inode_getfile("[ksu_driver]"' not in (ksu / 'kernel/supercall/supercall.c').read_text():
        raise RuntimeError('Expected native SukiSU driver ABI')
    if 'ksu_install_fd();' not in (ksu / 'kernel/hook/lsm_hook.c').read_text():
        raise RuntimeError('Native SukiSU LSM driver installation is absent')

def apply(common, ksu):
    identity(common, ksu)
    paths = [common / 'fs/exec.c', common / 'fs/open.c', common / 'fs/stat.c']
    planned = {}
    for path in paths:
        text = path.read_text(encoding='utf-8')
        text = once(text, 'extern struct static_key_true ksu_su_compat_enabled;',
                    'extern bool ksu_su_compat_enabled;')
        if 'static_branch_likely(&ksu_su_compat_enabled)' not in text:
            raise RuntimeError(f'Generic SUSFS hook switch absent in {path}')
        text = text.replace('static_branch_likely(&ksu_su_compat_enabled)', 'READ_ONCE(ksu_su_compat_enabled)')
        planned[path] = text
    path = common / 'fs/exec.c'
    text = planned[path]
    text = once(text, 'extern int ksu_handle_post_execveat_sucompat(int *fd, struct filename **filename_ptr, void *argv,\n\t\t\t\tvoid *envp, int *flags, int *retval);\n', '')
    text = once(text, '#ifdef CONFIG_KSU_SUSFS\n\tbool is_su_session = false;\n#endif // #ifdef CONFIG_KSU_SUSFS\n', '')
    for function in ('ksu_handle_execveat', 'ksu_handle_execveat_sucompat'):
        text = once(text, f'is_su_session = !{function}(&fd, &filename, &argv, &envp, &flags);',
                    f'(void){function}(&fd, &filename, &argv, &envp, &flags);')
    text = once(text, '#ifdef CONFIG_KSU_SUSFS\n\tif (unlikely(is_su_session))\n\t\t(void)ksu_handle_post_execveat_sucompat(&fd, &filename, &argv, &envp, &flags, &retval);\n#endif // #ifdef CONFIG_KSU_SUSFS\n', '')
    planned[path] = text
    # No writes occur until every exact pinned-source anchor passes.
    for path, text in planned.items():
        path.write_text(text, encoding='utf-8', newline='\n')
    verify(common, ksu)

def verify(common, ksu):
    identity(common, ksu)
    for name in ('exec', 'open', 'stat'):
        text = (common / f'fs/{name}.c').read_text()
        if 'extern bool ksu_su_compat_enabled;' not in text or 'READ_ONCE(ksu_su_compat_enabled)' not in text:
            raise RuntimeError(f'Native SukiSU boolean hook bridge missing: {name}')
        if 'static_branch_likely(&ksu_su_compat_enabled)' in text:
            raise RuntimeError('Foreign static-key declaration survived')
    exec_text = (common / 'fs/exec.c').read_text()
    if 'ksu_handle_post_execveat_sucompat' in exec_text or 'is_su_session' in exec_text:
        raise RuntimeError('Foreign post-exec driver contract survived')
    for function in ('ksu_handle_execveat', 'ksu_handle_execveat_sucompat'):
        if f'(void){function}(&fd, &filename, &argv, &envp, &flags);' not in exec_text:
            raise RuntimeError('Native SukiSU pre-exec hook missing')
    print('Verified SukiSU builtin boolean hooks, native pre-exec handling and unchanged [ksu_driver] ABI')

def attest(args):
    verify(args.common, args.ksu)
    config = args.config.read_text()
    required = ('KSU', 'KSU_SUSFS', 'KSU_SUSFS_SUS_MAP', 'KSU_SUSFS_OPEN_REDIRECT',
                'KSU_SUSFS_SUS_KSTAT_REDIRECT', 'KSU_SUSFS_UID_GATED_HIDING', 'ZEROMOUNT', 'BBG')
    for symbol in required:
        if f'CONFIG_{symbol}=y' not in config.splitlines():
            raise RuntimeError(f'Final SukiSU config missing {symbol}')
    image = args.image.read_bytes()
    for marker in (FULL.encode(), b'[ksu_driver]'):
        if marker not in image:
            raise RuntimeError(f'SukiSU compiled image marker missing: {marker!r}')
    symbols = subprocess.check_output(['nm', '--defined-only', str(args.vmlinux)], text=True)
    for symbol in ('ksu_handle_execveat', 'susfs_add_sus_kstat_redirect'):
        matches = re.findall(r'^[0-9a-fA-F]+ [Tt] ' + symbol + r'$', symbols, re.M)
        if len(matches) != 1:
            raise RuntimeError(f'Expected exactly one compiled definition: {symbol}')
    record = dict(sukisu_commit=PIN, version=VERSION, full_version=FULL,
                  version_main_commit=MAIN_PIN, version_main_count=3755, source_branch='builtin',
                  susfs_commit=SUSFS_PIN, susfs_version='v2.3.0',
                  native_driver='[ksu_driver]', image_sha256=hashlib.sha256(image).hexdigest(),
                  runtime_test='not performed')
    args.receipt.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--common', required=True, type=Path)
    p.add_argument('--ksu', required=True, type=Path)
    p.add_argument('--verify-only', action='store_true')
    for name in ('config', 'image', 'vmlinux', 'receipt'):
        p.add_argument('--' + name, type=Path)
    a = p.parse_args()
    (verify if a.verify_only else apply)(a.common.resolve(), a.ksu.resolve())
    if a.receipt:
        attest(a)
