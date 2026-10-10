#!/usr/bin/env python3
"""Configure and verify DroidSpaces on the Samsung Android 14 / Linux 6.1 tree."""
import argparse
import hashlib
import json
from pathlib import Path
import re

# GKI configuration: Copyright (C) 2026 ravindu644 <droidcasts@protonmail.com>
GUIDE_COMMIT = 'ac38c11fef1402c0db8172ea8187db0401a0bc30'
RESEARCH_COMMIT = 'd1d7478d0abc777ab0cfc4e1d9a902769b8b132a'
PATCH_COMMIT = '1890424779e46c1f3ced182191af28eea7be8c46'
# Linux 6.1 has family-specific REJECT targets, not NETFILTER_XT_TARGET_REJECT.
FEATURES = tuple('''SYSVIPC POSIX_MQUEUE IPC_NS PID_NS DEVTMPFS
NETFILTER_XT_MATCH_ADDRTYPE USER_NS IP6_NF_NAT IP6_NF_TARGET_MASQUERADE
IP_NF_TARGET_REJECT IP6_NF_TARGET_REJECT NETFILTER_XT_TARGET_LOG
NETFILTER_XT_MATCH_RECENT IP_SET IP_SET_HASH_IP IP_SET_HASH_NET NETFILTER_XT_SET
TMPFS_POSIX_ACL TMPFS_XATTR'''.split())
DEPENDENCIES = tuple('''NAMESPACES NET_NS CGROUPS MEMCG TMPFS
NETFILTER NETFILTER_ADVANCED NETFILTER_XTABLES NF_CONNTRACK NF_NAT
IPV6 IP_NF_IPTABLES IP_NF_FILTER IP6_NF_IPTABLES IP6_NF_FILTER'''.split())
RESOURCE_LIMITS = ('CGROUP_SCHED', 'FAIR_GROUP_SCHED', 'CFS_BANDWIDTH', 'CGROUP_PIDS')
# These already-built-in GKI facilities are verified, not enabled or moved
# between fragments. The current upstream runtime checker uses cgroup BPF on
# modern kernels; the legacy CGROUP_DEVICE option is not required here.
RUNTIME_PREREQUISITES = {
    'core': ('SYSCTL', 'UTS_NS', 'PROC_FS', 'SYSFS', 'SECCOMP', 'SECCOMP_FILTER'),
    'cgroups': ('CGROUP_BPF', 'BPF', 'BPF_SYSCALL'),
    'console_and_images': ('EPOLL', 'SIGNALFD', 'UNIX98_PTYS', 'BLK_DEV_LOOP', 'EXT4_FS'),
    'optional_filesystems': ('FUSE_FS', 'OVERLAY_FS'),
    'network': ('TUN', 'VETH', 'BRIDGE', 'IP_NF_NAT', 'IP_NF_TARGET_MASQUERADE',
                'IP6_NF_MANGLE', 'IPV6_MULTIPLE_TABLES', 'IP_ADVANCED_ROUTER',
                'IP_MULTIPLE_TABLES', 'NF_NAT_REDIRECT',
                'NETFILTER_XT_TARGET_MASQUERADE', 'NETFILTER_XT_TARGET_TCPMSS',
                'NF_CT_NETLINK'),
    'configuration_visibility': ('IKCONFIG', 'IKCONFIG_PROC'),
}
ASSIGNMENT = re.compile(r'^(?:CONFIG_(\w+)=(.*)|# CONFIG_(\w+) is not set)$')

def desired(resource_limits):
    values = dict.fromkeys(FEATURES + DEPENDENCIES, 'y')
    if resource_limits:
        values.update(dict.fromkeys(RESOURCE_LIMITS, 'y'))
    else:
        values.update(CFS_BANDWIDTH='n', CGROUP_PIDS='n')
    return values

def parse(text):
    values = {}
    for line in text.splitlines():
        match = ASSIGNMENT.fullmatch(line)
        if match:
            name, value, disabled = match.groups()
            key = name or disabled
            if key in values:
                raise RuntimeError(f'Duplicate configuration for CONFIG_{key}')
            values[key] = value if name else 'n'
    return values

def update(text, values, remove=False):
    lines, seen = [], set()
    for line in text.splitlines():
        match = ASSIGNMENT.fullmatch(line)
        key = (match[1] or match[3]) if match else None
        if key not in values:
            lines.append(line)
        elif not remove and key not in seen:
            lines.append(f'CONFIG_{key}=y' if values[key] == 'y' else f'# CONFIG_{key} is not set')
            seen.add(key)
    if not remove:
        for key, value in values.items():
            if key not in seen:
                lines.append(f'CONFIG_{key}=y' if value == 'y' else f'# CONFIG_{key} is not set')
    return '\n'.join(lines) + '\n'

def deduplicate_identical(text):
    """Normalize repeated source entries without choosing between conflicts."""
    lines, seen, removed = [], {}, {}
    for number, line in enumerate(text.splitlines(), 1):
        match = ASSIGNMENT.fullmatch(line)
        if match:
            name, value, disabled = match.groups()
            key, value = name or disabled, value if name else 'n'
            if key in seen:
                previous, first_line = seen[key]
                if value != previous:
                    raise RuntimeError(f'Conflicting configuration for CONFIG_{key} '
                                       f'at lines {first_line} and {number}')
                removed[key] = removed.get(key, 0) + 1
                continue
            seen[key] = value, number
        lines.append(line)
    return '\n'.join(lines) + '\n', removed

def verify_config(text, resource_limits):
    actual = parse(text)
    missing = [f'CONFIG_{k}={v}' for k,v in desired(resource_limits).items() if actual.get(k) != v]
    if missing:
        raise RuntimeError('DroidSpaces configuration mismatch: ' + ', '.join(missing))
    return actual

def verify_runtime_prerequisites(text):
    actual = parse(text)
    missing = {group: [f'CONFIG_{name}=y' for name in names if actual.get(name) != 'y']
               for group, names in RUNTIME_PREREQUISITES.items()}
    missing = {group: names for group, names in missing.items() if names}
    if missing:
        raise RuntimeError('DroidSpaces runtime prerequisites missing: ' + json.dumps(missing, sort_keys=True))
    return RUNTIME_PREREQUISITES

def verify_padding(common):
    source = (common / 'include/linux/sched.h').read_text(encoding='utf-8')
    # Ignore comments so an unapplied patch or stale commented macro cannot pass.
    clean = re.sub(r'/\*.*?\*/|//[^\n]*', '', source, flags=re.S)
    for pattern in (r'ANDROID_KABI_USE\(6,\s*struct sysv_sem sysvsem\)',
                    r'_ANDROID_KABI_REPLACE\(ANDROID_KABI_RESERVE\(7\);\s*ANDROID_KABI_RESERVE\(8\),\s*struct sysv_shm sysvshm\)'):
        if len(re.findall(pattern, clean)) != 1:
            raise RuntimeError('Mandatory SYSVIPC kABI padding patch missing or ambiguous')
    if re.search(r'^\s*struct sysv_(?:sem|shm)\s+sysv(?:sem|shm);', clean, re.M):
        raise RuntimeError('Unpadded SYSVIPC task_struct fields survived')
    return hashlib.sha256(source.encode()).hexdigest()

def configure(common, defconfig, fragment, resource_limits):
    values = desired(resource_limits)
    definitions = set()
    for path in common.rglob('Kconfig*'):
        if path.is_file():
            definitions.update(re.findall(r'^\s*(?:menu)?config\s+(\w+)', path.read_text(encoding='utf-8', errors='strict'), re.M))
    missing = sorted(set(values) - definitions)
    if missing:
        raise RuntimeError('Required Kconfig definitions missing: ' + ', '.join(missing))
    padding = verify_padding(common)
    # Samsung's source defconfig repeats several unchanged assignments. Apply
    # explicit DroidSpaces overrides first, then collapse only identical
    # remaining entries. Keep the final-config parser strict about duplicates.
    base, base_duplicates = deduplicate_identical(update(defconfig.read_text(encoding='utf-8'), values))
    overlay, fragment_duplicates = deduplicate_identical(update(fragment.read_text(encoding='utf-8'), values, remove=True))
    verify_config(base, resource_limits)
    defconfig.write_text(base, encoding='utf-8', newline='\n')
    fragment.write_text(overlay, encoding='utf-8', newline='\n')
    return {'sched_header_sha256': padding, 'defconfig_sha256': hashlib.sha256(base.encode()).hexdigest(),
            'removed_identical_defconfig_entries': base_duplicates,
            'removed_identical_fragment_entries': fragment_duplicates}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('configure', 'verify'))
    parser.add_argument('--common', type=Path)
    parser.add_argument('--defconfig', type=Path)
    parser.add_argument('--fragment', type=Path)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--resource-limits', action='store_true')
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    if args.mode == 'configure':
        if not all((args.common, args.defconfig, args.fragment)):
            parser.error('configure requires --common, --defconfig and --fragment')
        result = configure(args.common, args.defconfig, args.fragment, args.resource_limits)
    else:
        if not args.config:
            parser.error('verify requires --config')
        final_text = args.config.read_text(encoding='utf-8')
        verify_config(final_text, args.resource_limits)
        verified = verify_runtime_prerequisites(final_text)
        result = {'config_sha256': hashlib.sha256(args.config.read_bytes()).hexdigest(),
                  'verified_runtime_prerequisites': verified}
    result.update(mode=args.mode, resource_limits_requested=args.resource_limits,
                  expected_config=desired(args.resource_limits), guide_commit=GUIDE_COMMIT,
                  runtime_checker_commit=RESEARCH_COMMIT,
                  kabi_patch_commit=PATCH_COMMIT,
                  reject_mapping='IP_NF_TARGET_REJECT + IP6_NF_TARGET_REJECT',
                  full_device_module_rebuild_completed=False,
                  stock_module_compatibility_verified=False, device_boot_verified=False)
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()
