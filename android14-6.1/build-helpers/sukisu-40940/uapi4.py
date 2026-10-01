#!/usr/bin/env python3
"""Port the real UAPI 3/4 driver contract from immutable SukiSU main to builtin."""
import argparse
import hashlib
import re
import struct
import subprocess
from pathlib import Path
from configure import PIN, MAIN_PIN

PATHS = ('kernel/include/uapi/supercall.h', 'kernel/supercall/supercall.h',
         'kernel/supercall/internal.h', 'kernel/supercall/supercall.c',
         'kernel/supercall/dispatch.c', 'kernel/infra/file_wrapper.c')
SCOPED_COMMANDS = ('KSU_IOCTL_GET_WRAPPER_FD', 'KSU_IOCTL_DISABLE_ESCAPE_TO_ROOT')

def read(ksu, pin, path):
    return subprocess.check_output(['git', '-C', str(ksu), 'show', f'{pin}:{path}']).decode()

def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f'UAPI4 source anchor drift: {old[:85]!r}')
    return text.replace(old, new, 1)

def extract(text, name, array=False):
    # Preserve offsets while excluding braces in C strings and comments.
    mask = re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
                  lambda m: re.sub(r'[^\n]', ' ', m[0]), text, flags=re.S)
    signature = (r'^static const struct ksu_ioctl_cmd_map ' + name + r'\[\]\s*=\s*\{') if array else (
        r'^(?:static\s+)?(?:inline\s+)?(?:int|bool|long|void)\s+' + name + r'\([^;{]*\)\s*\{')
    matches = list(re.finditer(signature, mask, re.M))
    if len(matches) != 1:
        raise RuntimeError(f'Expected one definition: {name}')
    match = matches[0]
    pos, depth = match.end(), 1
    while depth:
        depth += (mask[pos] == '{') - (mask[pos] == '}')
        pos += 1
    if array:
        if text[pos] != ';':
            raise RuntimeError('Unterminated ioctl table')
        pos += 1
    return text[match.start():pos]

def expected(ksu):
    verify_abi(ksu)
    files = {p: read(ksu, PIN, p) for p in PATHS}
    p = PATHS[0]
    files[p] = once(files[p], '// 2: allowlist v4 root profile flag\nDECLARE(__u32, KERNEL_SU_UAPI_VERSION, 2);',
                    '// 2: allowlist v4 root profile flags\n// 3: scoped su-session driver fd\n'
                    '// 4: add KSU_GET_INFO_FLAG_BUNDLED\nDECLARE(__u32, KERNEL_SU_UAPI_VERSION, 4);')
    flag = 'DECLARE(__u32, KSU_GET_INFO_FLAG_PR_BUILD, (1U << 3));'
    files[p] = once(files[p], flag, flag + '\nDECLARE(__u32, KSU_GET_INFO_FLAG_BUNDLED, (1U << 4));')
    p = 'kernel/supercall/supercall.h'
    files[p] = once(files[p], '#include <linux/types.h>', '#include <linux/fs.h>\n#include <linux/types.h>')
    files[p] = once(files[p], '    ksu_perm_check_t perm_check; // Permission check function',
                    '    ksu_perm_check_t perm_check; // Permission check function\n    bool allow_su_session;')
    files[p] = once(files[p], 'int ksu_install_fd(void);',
                    'int ksu_install_fd(void);\nint ksu_install_su_fd(void);\nbool ksu_is_su_session_fd(const struct file *filp);')
    p = 'kernel/supercall/internal.h'
    files[p] = once(files[p], '#include <linux/types.h>', '#include <linux/fs.h>\n#include <linux/types.h>')
    files[p] = once(files[p], 'long ksu_supercall_handle_ioctl(unsigned int cmd, void __user *argp);',
                    'long ksu_supercall_handle_ioctl(const struct file *filp, unsigned int cmd, void __user *argp);')
    p = 'kernel/supercall/supercall.c'
    upstream = read(ksu, MAIN_PIN, p)
    marker = 'static void ksu_install_fd_tw_func('
    if files[p].count(marker) != 1 or upstream.count(marker) != 1:
        raise RuntimeError('Driver task-work boundary drift')
    # Bring over context ownership, names, close-on-exec flags and permissions
    # byte-for-byte; preserve builtin's native SUSFS reboot/task-work entry.
    original = files[p].split(marker)[0]
    prefix = upstream[upstream.index('#define KSU_DRIVER_PERMISSION_SU_SESSION'):upstream.index(marker)]
    files[p] = once(files[p], original, prefix)
    p = 'kernel/supercall/dispatch.c'
    dispatch = read(ksu, MAIN_PIN, p)
    files[p] = once(files[p], 'static int do_grant_root(void __user *arg)',
                    '/* Read by GET_INFO and independently audited in final vmlinux. */\n'
                    'const __u32 ksu_uapi4_contract = KERNEL_SU_UAPI_VERSION;\n\n'
                    'static int do_grant_root(void __user *arg)')
    files[p] = once(files[p], extract(files[p], 'ksu_supercall_handle_ioctl'),
                    extract(dispatch, 'ksu_supercall_handle_ioctl'))
    table = extract(files[p], 'ksu_ioctl_handlers', array=True)
    for command in SCOPED_COMMANDS:
        pattern = re.compile(r'(\{\s*\.cmd = ' + command + r',.*?\.perm_check = \w+)([ \t]*\n    \},)', re.S)
        matches = list(pattern.finditer(table))
        if len(matches) != 1:
            raise RuntimeError(f'Unexpected scoped-command table: {command}')
        table = pattern.sub(lambda m: m[1] + ',\n        .allow_su_session = true' + m[2], table, count=1)
    files[p] = once(files[p], extract(files[p], 'ksu_ioctl_handlers', array=True), table)
    # This exact pipeline is built in, never a bundled or late-loaded LKM.
    # Explicitly derive the flags instead of mislabeling built-in as BUNDLED.
    info = extract(files[p], 'do_get_info')
    info = once(info, 'cmd.uapi_version = KERNEL_SU_UAPI_VERSION;',
                'cmd.uapi_version = READ_ONCE(ksu_uapi4_contract);')
    info = once(info, '    if (is_manager()) {',
                '#ifdef MODULE\n    cmd.flags |= KSU_GET_INFO_FLAG_LKM;\n#endif\n'
                '#ifdef EXPECTED_SIZE2\n    cmd.flags |= KSU_GET_INFO_FLAG_PR_BUILD;\n#endif\n'
                '    /* Builtin: KSU_GET_INFO_FLAG_BUNDLED and LATE_LOAD stay clear. */\n'
                '    if (is_manager()) {')
    files[p] = once(files[p], extract(files[p], 'do_get_info'), info)
    p = 'kernel/infra/file_wrapper.c'
    files[p] = once(files[p], extract(files[p], 'ksu_install_file_wrapper'),
                    extract(read(ksu, MAIN_PIN, p), 'ksu_install_file_wrapper'))
    return files

def verify_abi(ksu):
    # Existing profile, SELinux and event payloads are unchanged in UAPI4.
    for name in ('app_profile.h', 'selinux.h', 'sulog.h'):
        old = read(ksu, PIN, 'kernel/include/uapi/' + name)
        new = read(ksu, MAIN_PIN, 'uapi/' + name)
        if name == 'selinux.h':
            # Upstream changed DECLARE(enum) spelling to static const; compare
            # all names, integer types and values, including every subcommand.
            old_values = {n: (t, v) for t, n, v in re.findall(r'DECLARE\((\w+), (\w+), ([^\n]+)\);', old)}
            new_values = {n: (t, v) for t, n, v in re.findall(r'static const (\w+) (\w+) = ([^\n]+);', new)}
            if not old_values or old_values != new_values:
                raise RuntimeError('SELinux ABI command mismatch')
        elif old != new:
            raise RuntimeError(f'Public ABI payload mismatch: {name}')
    native = read(ksu, PIN, PATHS[0])
    manager = read(ksu, MAIN_PIN, 'uapi/supercall.h')
    old_cmds = dict(re.findall(r'DECLARE\(__u32, (KSU_IOCTL_\w+), ([^\n]+)\);', native))
    new_cmds = dict(re.findall(r'static const __u32 (KSU_IOCTL_\w+) = ([^\n]+);', manager))
    if not old_cmds or any(new_cmds.get(n) != v for n, v in old_cmds.items()):
        raise RuntimeError('Manager/kernel ioctl number or payload size mismatch')
    def layouts(text):
        text = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)
        return {n: re.sub(r'\s+', '', body) for n, body in
                re.findall(r'^struct (\w+) \{(.*?)^};', text, re.M | re.S)}
    old_layouts, new_layouts = layouts(native), layouts(manager)
    if any(new_layouts.get(n) != v for n, v in old_layouts.items()):
        raise RuntimeError('Manager/kernel supercall structure layout mismatch')

def plan(ksu):
    files = expected(ksu)
    for p, text in files.items():
        if (ksu / p).read_bytes() not in (read(ksu, PIN, p).encode(), text.encode()):
            raise RuntimeError(f'Unexpected source before UAPI4 port: {p}')
    return files

def apply(ksu):
    files = plan(ksu)
    for p, text in files.items():
        (ksu / p).write_text(text, encoding='utf-8', newline='\n')
    verify(ksu)

def verify(ksu):
    files = expected(ksu)
    hashes = {}
    for p, text in files.items():
        actual = (ksu / p).read_text()
        if p.endswith('/dispatch.c'):
            if actual.count('const __u32 ksu_uapi4_contract = KERNEL_SU_UAPI_VERSION;') != 1:
                raise RuntimeError('Compiled UAPI4 contract constant is missing')
            # Enhanced SUSFS later changes reboot command cases only.
            for name, array in (('ksu_supercall_handle_ioctl', False), ('ksu_ioctl_handlers', True),
                                ('do_get_info', False), ('do_get_info_legacy', False)):
                scope = extract(actual, name, array)
                if scope != extract(text, name, array):
                    raise RuntimeError(f'UAPI4 dispatcher contract drift: {name}')
                hashes[p + ':' + name] = hashlib.sha256(scope.encode()).hexdigest()
        else:
            if actual != text:
                raise RuntimeError(f'UAPI4 source contract drift: {p}')
            hashes[p] = hashlib.sha256(actual.encode()).hexdigest()
    print('Verified SukiSU UAPI4: scoped su FD, per-file permissions, two scoped ioctls, built-in flags')
    return hashes

def compiled_uapi(path):
    """Read the actual GET_INFO constant from little-endian ARM64 ELF sections."""
    data = path.read_bytes()
    if data[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', data, 18)[0] != 183:
        raise RuntimeError('UAPI attestation requires a little-endian ARM64 ELF')
    offset = struct.unpack_from('<Q', data, 40)[0]
    stride, count = struct.unpack_from('<HH', data, 58)
    if stride != 64 or count == 0:
        raise RuntimeError('Unexpected ELF section table')
    sections = [struct.unpack_from('<IIQQQQIIQQ', data, offset + i * stride) for i in range(count)]
    values = []
    for section in sections:
        if section[1] != 2:  # SHT_SYMTAB
            continue
        if section[9] != 24:
            raise RuntimeError('Unexpected ELF symbol stride')
        strings = sections[section[6]]
        names = data[strings[4]:strings[4] + strings[5]]
        for pos in range(section[4], section[4] + section[5], 24):
            name, info, other, index, value, size = struct.unpack_from('<IBBHQQ', data, pos)
            if names[name:names.find(b'\0', name)] != b'ksu_uapi4_contract':
                continue
            if index >= len(sections) or size != 4:
                raise RuntimeError('Unexpected UAPI contract symbol layout')
            target = sections[index]
            file_offset = target[4] + value - target[3]
            if not target[4] <= file_offset <= target[4] + target[5] - 4:
                raise RuntimeError('UAPI contract symbol exceeds its section')
            values.append(struct.unpack_from('<I', data, file_offset)[0])
    if values != [4]:
        raise RuntimeError(f'Compiled GET_INFO UAPI mismatch: {values}')
    return values[0]

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('ksu', type=Path)
    p.add_argument('--verify-only', action='store_true')
    a = p.parse_args()
    (verify if a.verify_only else apply)(a.ksu.resolve())
