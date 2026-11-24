"""Reviewed Nova 35095 adapter; retain the Samsung manual-hook profile.

This adapter is intentionally bound to one full-history source pin. It keeps
Nova's native SELinux implementation and adds the newest SUS_PATH command to
the existing compatibility port. No compilation or device evidence is reused.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess

PIN = '54d6da4e7e792a7d0e70c4f5ec70f1ac1c32fa2b'
SOURCE_URL = 'https://git.zako.shirkneko.top:20004/shirkneko/SukiSU.git'
TAG = 'v3.0.0-r1'
SUSFS_PIN = 'f76b81f2a6bf98e4029cc0c823c054edbec29803'
SUSFS_BASE = 'a2165b6f875b73e2f87d3c6f12814efac8de061d'
GKI_PATCH_BASE = '9104e6b85a0c5af7b347cb2d52aeb1ff0a3b8fcb72c126422e4ac8a04576b171'
GKI_PATCH_TARGET = 'adaed18bfa298d83c2d768f0433b7c87f418d157e88df0006d2d962dfb8f3144'
CODE, COUNT = 35095, 4099
COMPAT_BASE = '9defbe9f834aac26e70914f716a358ffae3c973e02bda2a39ca7d6c36f410b0b'
COMPAT_NOVA = '5c3ba699fc7a1db821d3b8555218e5e67c47d0ab754606d0385de0bc0be5b3c8'
CERT = '947ae944f3de4ed4c21a7e4f7953ecf351bfa2b36239da37a34111ad29993eef'
PREVIOUS_SUSFS_HEADER = 'b3de6f8bba7b0c2adf63e4fb9777ccb2dc2916790b8fd085e8723e60f6dec25d'
SUSFS_SOURCE_HASHES = {
    'fs/susfs.c': ('eb192f62a9ec70b0c00b0e800d5734a7e51f357bb3d001e10d1e3be9f76e9b0d', '2a8bb10bca2ad5134cd65bf02ef56863795949b1d9cbed603c380b58d9bc61bf'),
    'include/linux/susfs.h': ('1dbe8e9d31211bf07eacf5c28054b7f3bb27d034565b88f1ddff371c356c4dd6', '763a502a37c3ffa3807ba2cab46af31807b8bd87cccb86d12e552d0532a96573'),
    'include/linux/susfs_def.h': ('cb441cb566d009bce20c1f4ce43fa10ce3472daafd0f37e144cdf1be87b3f88e', 'e8a1cee4b41bcdce43998ae337e60fca9888b2f8bea47074fe3b3377220794d8'),
}
UID_GUARD = '\tif (!susfs_uid_gate_current())\n\t\treturn false;\n\n'


def sha(data): return hashlib.sha256(data).hexdigest()


def command(*args):
    return subprocess.check_output(list(map(str, args)), stderr=subprocess.PIPE)


def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Reviewed Nova anchor changed: '+repr(old))
    return text.replace(old, new, 1)


def validate(plan):
    if plan.get('sukisu_family') != 'nova':
        raise RuntimeError('Nova adapter requires an explicit Nova source family')
    expected = {'sukisu_commit': PIN, 'sukisu_code': CODE, 'sukisu_count': COUNT,
                'sukisu_repository': 'shirkneko/SukiSU', 'sukisu_repository_url': SOURCE_URL,
                'sukisu_version_base': 30000, 'sukisu_version_offset': 996,
                'sukisu_version_operator': '+', 'sukisu_tag': TAG,
                'susfs_commit': SUSFS_PIN, 'susfs_release_base': SUSFS_BASE,
                'susfs_version': 'v2.4.0',
                'profile': 'S928BXXU6EZJB-EUX-android14-6.1.162'}
    for key, value in expected.items():
        if plan.get(key) != value:
            raise RuntimeError('Unreviewed Nova source/profile field: '+key)


def prepare_nova_helpers(root, plan):
    if plan.get('sukisu_family') != 'nova':
        return
    validate(plan)
    helpers = Path(root)/'android14-6.1/build-helpers'
    compat = helpers/f'sukisu-{CODE}-susfs/compat.patch'
    current = sha(compat.read_bytes())
    reviewed = Path(__file__).with_name('compat')/'nova-35004.patch'
    if current not in (COMPAT_BASE, COMPAT_NOVA) or sha(reviewed.read_bytes()) != COMPAT_NOVA:
        raise RuntimeError('Nova compatibility patch requires exact reviewed pre/postimages')
    compat.write_bytes(reviewed.read_bytes())
    shutil.copyfile(__file__, helpers/'_center_nova.py')
    wrapper = ('from pathlib import Path\nimport sys\n'
               'sys.path.insert(0,str(Path(__file__).resolve().parent))\n'
               'from _center_nova import configure_main\nconfigure_main()\n')
    (helpers/f'configure-sukisu-{CODE}.py').write_text(wrapper, encoding='utf-8', newline='\n')
    # UAPI6 remains native. Only its version arithmetic changed upstream.
    uapi = helpers/f'sukisu_{CODE}_uapi.py'
    text = uapi.read_text()
    old = f'40000 + int(git(source, \'rev-list\', \'--count\', \'HEAD\')) - 2815 != {CODE}'
    new = f'30000 + int(git(source, \'rev-list\', \'--count\', \'HEAD\')) + 996 != {CODE}'
    if old in text:
        text = once(text, old, new)
    elif text.count(new) != 1:
        raise RuntimeError('Native UAPI source/version assertion changed')
    uapi.write_text(text, encoding='utf-8', newline='\n')
    session = helpers/f'su-session-{CODE}/apply.py'
    text = session.read_text(encoding='utf-8')
    text = once(text, 'version_offset = -2815\n        compiled_version = 40000 + commit_count + version_offset',
                'version_offset = 996\n        compiled_version = 30000 + commit_count + version_offset')
    session.write_text(text, encoding='utf-8', newline='\n')
    # The original release-only macro gate runs before the functional delta.
    # Afterwards verify the independently merged header, not the old header.
    bej = helpers/f'susfs-runtime-{CODE}/release240.py'
    text = bej.read_text()
    anchor = 'def verify(common):\n'
    replacement = ('def verify(common):\n'
                   '    if (common/\'.build-center-susfs-update.json\').exists():\n'
                   '        from importlib.util import module_from_spec, spec_from_file_location\n'
                   '        spec = spec_from_file_location("center_nova_release", Path(__file__).resolve().parents[1] / "_center_nova.py")\n'
                   '        adapter = module_from_spec(spec)\n'
                   '        spec.loader.exec_module(adapter)\n'
                   '        return adapter.verified_release(common)\n')
    if 'return adapter.verified_release(common)' not in text:
        text = once(text, anchor, replacement)
    bej.write_text(text, encoding='utf-8', newline='\n')
    runtime = helpers/f'susfs-runtime-{CODE}/apply.py'
    text = runtime.read_text()
    text = once(text, 'sys.path.insert(0,str(HERE))\n',
                'sys.path.insert(0,str(HERE.parents[0]))\nsys.path.insert(0,str(HERE))\n')
    old = ("    from release240 import EXPECTED\n"
           "    release=json.loads((common/'.susfs-release240.json').read_text())\n"
           "    header=(common/'include/linux/susfs.h').read_bytes()\n"
           "    if sha(header)!=EXPECTED or release['release_header_sha256']!=EXPECTED or b'v2.4.0' not in blob:")
    new = ("    from release240 import verify as verify_release\n"
           "    release=verify_release(common)\n"
           "    header=(common/'include/linux/susfs.h').read_bytes()\n"
           "    if sha(header)!=release['release_header_sha256'] or b'v2.4.0' not in blob:")
    if old in text:
        text = once(text, old, new)
    elif new not in text:
        raise RuntimeError('Runtime packaged Image release assertion changed')
    runtime.write_text(text, encoding='utf-8', newline='\n')
    old = 'full_device_runtime_tested=False)'
    previous = 'full_device_runtime_tested=False,sus_path_uid_filter=attest_sus_path(common,ksu,vmlinux))'
    new = 'full_device_runtime_tested=False,sus_path_uid_filter=attest_sus_path(common,ksu,vmlinux,config))'
    if old in text:
        text = once(text, '    from release240 import verify as verify_release',
                    '    from release240 import verify as verify_release\n    from _center_nova import attest_sus_path')
        text = once(text, old, new)
    elif previous in text:
        text = once(text, previous, new)
    elif new not in text:
        raise RuntimeError('Runtime Image evidence return changed')
    runtime.write_text(text, encoding='utf-8', newline='\n')


def configure(root, verify=False):
    root = Path(root)
    if command('git', '-C', root, 'rev-parse', 'HEAD').decode().strip() != PIN:
        raise RuntimeError(f'Exact Nova {CODE} source required')
    if int(command('git', '-C', root, 'rev-list', '--count', 'HEAD')) != COUNT:
        raise RuntimeError(f'Nova requires full {COUNT}-commit history')
    path = root/'kernel/Kbuild'
    text = path.read_text()
    for name, value in (('VERSION_BASE', '30000'), ('VERSION_OFFSET', '996')):
        if not re.search('^'+name+r'\s*:=\s*'+value+r'\s*$', text, re.M):
            raise RuntimeError('Nova version arithmetic changed')
    settings = {'RELEASE_API_BASE': '', 'KSU_RELEASE_VER': TAG[1:], 'RELEASE_COMMITS': '',
                'LOCAL_COUNT': str(COUNT), 'KSU_VERSION': str(CODE), 'VERSION_TAG': TAG[1:],
                'KSU_VERSION_FULL': f'{TAG}-{CODE}-{PIN[:8]}'}
    for name, value in settings.items():
        pattern = '^'+name+r'\s*:=.*$'
        found = re.findall(pattern, text, re.M)
        expected = name+' := '+value
        if len(found) != 1 or (verify and found[0] != expected):
            raise RuntimeError('Nova Kbuild version identity drift: '+name)
        text = re.sub(pattern, lambda _: expected, text, flags=re.M)
    for value in ('KSU_PACKAGE_NAME ?= com.sukisu.nova\n',
                  'KSU_EXPECTED_SIZE ?= 0x35c', 'KSU_EXPECTED_HASH ?= '+CERT):
        if value not in text:
            raise RuntimeError('Official Nova manager package/signature contract changed')
    # No unshallow/network operation is needed for this verified full checkout.
    shallow = '$(shell cd $(KSU_SRC) 2>/dev/null && [ -f ../.git/shallow ] && $(GIT_BIN) fetch --unshallow 2>/dev/null)'
    if shallow in text:
        if verify:
            raise RuntimeError('Unpinned Kbuild history fetch remains')
        text = once(text, shallow, '# Full source history was verified before Kbuild.')
    if not verify:
        path.write_text(text, encoding='utf-8', newline='\n')
    return {'pin': PIN, 'version': CODE, 'count': COUNT,
            'formula': f'30000 + {COUNT} + 996', 'manager_package': 'com.sukisu.nova',
            'kbuild_sha256': sha(text.encode()), 'device_runtime_tested': False}


def configure_main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    print(json.dumps(configure(args.root, args.verify_only), indent=2))


def definition(text, name):
    """Return a C function, including its optional upstream #if signature."""
    mask = re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
                  lambda m: re.sub(r'[^\n]', ' ', m[0]), text, flags=re.S)
    prefix = r'^(?:__attribute__\s*\(\([^\n]*?\)\)\s*)?(?:static\s+)?(?:inline\s+)?(?:bool|int|void|ssize_t)\s+'
    matches = list(re.finditer(prefix+re.escape(name)+r'\([^;{}\n]*\)\s*(?:#endif[^\n]*\s*)?\{', mask, re.M))
    if len(matches) != 1:
        raise RuntimeError('Expected one Nova/SUSFS function: '+name)
    begin = mask.rfind('\n', 0, matches[0].start())+1
    end, depth = matches[0].end(), 1
    while depth and end < len(mask):
        depth += (mask[end] == '{')-(mask[end] == '}')
        end += 1
    if depth:
        raise RuntimeError('Unbalanced Nova/SUSFS function: '+name)
    return begin, end


def sus_path_guard(text, add):
    begin, end = definition(text, 'susfs_is_inode_sus_path')
    body = text[begin:end]
    if add:
        body = once(body, '\tif (uid < 10000) {', UID_GUARD+'\tif (uid < 10000) {')
    else:
        body = once(body, UID_GUARD, '')
    return text[:begin]+body+text[end:]


def native_susfs_view(data):
    """Manual upstream SELinux type hooks are replaced by native Nova hooks."""
    text = data.decode()
    marker = 'static DEFINE_MUTEX(susfs_mutex_lock_sus_type);'
    if marker not in text:
        return data
    start = text.index(marker)
    if text[:start].endswith('/* selinux hide */\n'):
        start -= len('/* selinux hide */\n')
    end = text.index('/* sus_path */', start)
    return (text[:start]+text[end:]).encode()


def review_native_gki_delta(base, target):
    """Bound the exact upstream VFS delta to this already ported profile.

    New functional SUS_PATH code is carried by fs/susfs.c and both headers.
    In the 50er patch, new setxattr/default/force helpers belong to the manual
    SELinux implementation which this profile replaces with native Nova.
    Remaining changes are include guards (equivalent with all three required
    options built in), hot annotations, and patch context/formatting. Replaying
    the full generic patch would undo the separately audited Samsung VFS port.
    """
    if (sha(base), sha(target)) != (GKI_PATCH_BASE, GKI_PATCH_TARGET):
        raise RuntimeError('Unreviewed generic GKI patch delta for native Nova profile')
    return {'upstream_old_patch_sha256': sha(base), 'upstream_new_patch_sha256': sha(target),
            'manual_selinux_sections_reapplied': False,
            'manual_only_new_helpers': ['susfs_security_context_to_sid_default',
                                        'susfs_security_context_to_sid_force'],
            'native_nova_setxattr_implementation_retained': True,
            'samsung_vfs_port_retained': True,
            'equivalent_include_guards_require': ['CONFIG_KSU_SUSFS=y',
                'CONFIG_KSU_SUSFS_SUS_PATH=y', 'CONFIG_KSU_SUSFS_OPEN_REDIRECT=y'],
            'remaining_nonfunctional_changes': ['hot attributes', 'comments', 'patch offsets and context'],
            'functional_uid_filter_sources': ['fs/susfs.c', 'include/linux/susfs.h',
                                              'include/linux/susfs_def.h']}


def merge_susfs_file(name, local, base, target, merger):
    """Resolve only the reviewed UID-gate/SUS_PATH overlap, fail otherwise."""
    if name not in SUSFS_SOURCE_HASHES:
        return merger(local, base, target)
    if (sha(base), sha(target)) != SUSFS_SOURCE_HASHES[name]:
        raise RuntimeError('Unreviewed official Nova/SUSFS input: '+name)
    if name == 'include/linux/susfs.h':
        if sha(local) != PREVIOUS_SUSFS_HEADER:
            raise RuntimeError('Reviewed enhanced SuSFS header preimage changed')
        text = local.decode()
        # The original port drops the comments on these two #endif lines.
        # Align only those lines with the old upstream spelling so the new
        # declarations can be merged into the same guarded blocks.
        for preceding in ('};', 'void susfs_add_sus_path_loop(void __user **user_info);'):
            end = '\n\n/* sus_mount */\n'
            text = once(text, preceding+'\n#endif'+end,
                        preceding+'\n#endif // #ifdef CONFIG_KSU_SUSFS_SUS_PATH'+end)
        return merger(text.encode(), base, target)
    if name != 'fs/susfs.c':
        return merger(local, base, target)
    old = local.decode()
    ungated = sus_path_guard(old, False)
    # Native integration predates the upstream manual type-list hooks. Do not
    # reintroduce them solely because their comment changed in the new patch.
    if 'static DEFINE_MUTEX(susfs_mutex_lock_sus_type);' not in ungated:
        base, target = native_susfs_view(base), native_susfs_view(target)
    result = merger(ungated.encode(), base, target).decode()
    result = sus_path_guard(result, True)
    latest = target.decode()
    start, end = definition(result, 'susfs_is_inode_sus_path')
    a, b = definition(latest, 'susfs_is_inode_sus_path')
    if result[start:end].replace(UID_GUARD, '', 1) != latest[a:b]:
        raise RuntimeError('SUS_PATH UID-gated consumer differs from reviewed upstream')
    return result.encode()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def verified_release(common):
    common = Path(common)
    update = json.loads((common/'.build-center-susfs-update.json').read_text())
    original = json.loads((common/'.susfs-release240.json').read_text())
    header = (common/'include/linux/susfs.h').read_bytes()
    if (update.get('source_pin') != SUSFS_PIN or update.get('release_base') != SUSFS_BASE
            or update.get('susfs_version') != 'v2.4.0' or update.get('conflicts') != 0
            or original.get('upstream_release_pin') != SUSFS_BASE
            or original.get('release_header_sha256') != PREVIOUS_SUSFS_HEADER
            or sha(header) != update.get('output_sha256', {}).get('include/linux/susfs.h')):
        raise RuntimeError('Merged Nova/SUSFS release identity drift')
    if b'#define SUSFS_VERSION "v2.4.0"' not in header or b'st_susfs_sus_path_uid_filter' not in header:
        raise RuntimeError('Latest SUSFS interface is absent')
    return dict(original, upstream_source_pin=SUSFS_PIN, release_only_change=False,
                release_header_sha256=sha(header))


def attest_sus_path(common, ksu, vmlinux, config):
    verified_release(common)
    for option in ('CONFIG_KSU_SUSFS=y', 'CONFIG_KSU_SUSFS_SUS_PATH=y', 'CONFIG_KSU_SUSFS_OPEN_REDIRECT=y'):
        if option not in config.read_text().splitlines():
            raise RuntimeError('Native GKI delta review requires '+option)
    dispatch = (ksu/'kernel/supercall/dispatch.c').read_text()
    if not re.search(r'case CMD_SUSFS_SET_SUS_PATH_UID_FILTER:\s*\{\s*susfs_set_sus_path_uid_filter\(arg\);\s*return 0;', dispatch):
        raise RuntimeError('Linked SUS_PATH receipt requires the reviewed dispatcher')
    symbols = command('nm', vmlinux).decode()
    required = ('susfs_set_sus_path_uid_filter',)
    source_functions = required+('susfs_parse_sus_path_app_strings', 'susfs_is_uid_allowed_for_sus_path')
    observed = []
    for name in source_functions:
        found = re.search(r'^[0-9a-fA-F]+ [tT] '+name+r'(?:\.llvm\.[0-9]+)?$', symbols, re.M)
        if found:observed.append(name)
        if name in required and not found:
            raise RuntimeError('Latest SUS_PATH implementation missing from linked kernel: '+name)
    source = (common/'fs/susfs.c').read_text()
    hashes = {}
    for name in source_functions:
        begin, end = definition(source, name)
        hashes[name] = sha(source[begin:end].encode())
    tests = json.loads((common/'.susfs-sus-path-tests.json').read_text())
    if tests.get('upstream_pin') != SUSFS_PIN or tests.get('variant_exit_codes', {}).get('production') != 0:
        raise RuntimeError('Current-run SUS_PATH semantic tests are missing')
    for name, expected in tests.get('functions_sha256', {}).items():
        begin, end = definition(source, name)
        if sha(source[begin:end].encode()) != expected:
            raise RuntimeError('SUS_PATH code changed after semantic tests: '+name)
    return {'upstream_pin': SUSFS_PIN, 'command': '0x55554',
            'required_linked_functions': list(required), 'observed_linked_functions': observed,
            'functions_sha256': hashes,
            'package_uid_refresh': True, 'downstream_uid_gate_preserved': True,
            'runtime_is_additive': True, 'semantic_host_test': tests,
            'device_runtime_tested': False}


def test_sus_path(common, cc, work):
    """Compile actual merged consumers plus negative controls with host stubs.

    The stubs model inode flags, UIDs and bitmap reads; these are semantic host
    tests. Kernel compilation, RCU scheduling and device behavior remain
    separate checks, and are never inferred from this result.
    """
    common, work = Path(common), Path(work)
    work.mkdir(parents=True, exist_ok=True)
    source = (common/'fs/susfs.c').read_text()
    functions = {}
    for name in ('susfs_is_inode_sus_path', 'susfs_is_uid_allowed_for_sus_path'):
        begin, end = definition(source, name)
        functions[name] = source[begin:end]
    production = '\n'.join(functions[name] for name in reversed(functions))
    variants = {'production': production,
                'missing-uid-gate': once(production, UID_GUARD, ''),
                'inverted-allowlist': production.replace('likely(!susfs_is_uid_allowed_for_sus_path(uid))',
                                                       'likely(susfs_is_uid_allowed_for_sus_path(uid))'),
                'missing-android-user-normalization': once(production,
                    'uid_t uid = current_uid().val % 100000;', 'uid_t uid = current_uid().val;')}
    if any(value == production for name, value in variants.items() if name != 'production'):
        raise RuntimeError('SUS_PATH semantic negative control was not changed')
    prefix = r'''
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
typedef unsigned int uid_t;
struct kuid_t { uid_t val; };
static uid_t caller_uid;
static bool gate_permit = true;
static struct kuid_t current_uid(void) { return (struct kuid_t){caller_uid}; }
static bool susfs_uid_gate_current(void) __attribute__((unused));
static bool susfs_uid_gate_current(void) { return gate_permit; }
#define likely(value) (value)
#define unlikely(value) (value)
#define SUSFS_LOGE(...) ((void)0)
#define FUSE_SUPER_MAGIC 0x65735546
#define AS_FLAGS_SUS_PATH 3
#define SUSFS_UID_FILTER_MIN_UID 10000
#define SUSFS_UID_FILTER_MAX_UID 19999
struct mapping { unsigned long flags; };
struct super_block { unsigned long s_magic; };
struct inode { struct mapping *i_mapping; struct super_block *i_sb; };
struct fuse_inode { struct inode inode; };
static struct fuse_inode *selected_fuse;
static struct fuse_inode *get_fuse_inode(struct inode *inode) { (void)inode; return selected_fuse; }
struct susfs_sus_path_uid_filter_bitmap { unsigned long bits[157]; };
static struct susfs_sus_path_uid_filter_bitmap *sus_path_uid_filter_bitmap;
static void rcu_read_lock(void) {}
static void rcu_read_unlock(void) {}
#define rcu_dereference(value) (value)
static bool test_bit(unsigned int bit, const unsigned long *bits) {
    return (bits[bit/(8*sizeof(unsigned long))] >> (bit%(8*sizeof(unsigned long)))) & 1UL;
}
'''
    suffix = r'''
static void allow(struct susfs_sus_path_uid_filter_bitmap *bitmap, unsigned int uid) {
    unsigned int bit = uid - SUSFS_UID_FILTER_MIN_UID;
    bitmap->bits[bit/(8*sizeof(unsigned long))] |= 1UL << (bit%(8*sizeof(unsigned long)));
}
int main(void) {
    struct susfs_sus_path_uid_filter_bitmap bitmap = {{0}};
    struct mapping marked = {1UL << AS_FLAGS_SUS_PATH}, plain = {0};
    struct super_block regular = {0}, fuse = {FUSE_SUPER_MAGIC};
    struct inode inode = {&marked, &regular};
    struct fuse_inode fi = {{&marked, &fuse}};
    unsigned int system_uids[] = {0, 1000, 9999, 100000, 109999};
    unsigned int hidden_uids[] = {10024, 19999, 20000, 110024, 210024};
    unsigned int visible_uids[] = {10023, 110023, 210023, 90000, 190000};
    unsigned int i;
    allow(&bitmap, 10023);
    sus_path_uid_filter_bitmap = &bitmap;
    for (i=0; i<sizeof(system_uids)/sizeof(system_uids[0]); i++) {
        caller_uid=system_uids[i]; if (susfs_is_inode_sus_path(&inode)) return 10;
    }
    for (i=0; i<sizeof(hidden_uids)/sizeof(hidden_uids[0]); i++) {
        caller_uid=hidden_uids[i]; if (!susfs_is_inode_sus_path(&inode)) return 11;
    }
    for (i=0; i<sizeof(visible_uids)/sizeof(visible_uids[0]); i++) {
        caller_uid=visible_uids[i]; if (susfs_is_inode_sus_path(&inode)) return 12;
    }
    caller_uid=10024; gate_permit=false;
    if (susfs_is_inode_sus_path(&inode)) return 13;
    gate_permit=true; inode.i_mapping=&plain;
    if (susfs_is_inode_sus_path(&inode)) return 14;
    inode.i_mapping=NULL;
    if (susfs_is_inode_sus_path(&inode)) return 15;
    inode.i_mapping=&marked; inode.i_sb=&fuse; selected_fuse=NULL;
    if (susfs_is_inode_sus_path(&inode)) return 16;
    selected_fuse=&fi;
    if (!susfs_is_inode_sus_path(&inode)) return 17;
    fi.inode.i_mapping=&plain;
    if (susfs_is_inode_sus_path(&inode)) return 18;
    fi.inode.i_mapping=NULL;
    if (susfs_is_inode_sus_path(&inode)) return 19;
    sus_path_uid_filter_bitmap=NULL;
    if (susfs_is_uid_allowed_for_sus_path(10023)) return 20;
    if (!susfs_is_uid_allowed_for_sus_path(90000)) return 21;
    return 0;
}
'''
    outcomes = {}
    for name, text in variants.items():
        cfile, binary = work/(name+'.c'), work/name
        cfile.write_text(prefix+text+suffix, encoding='utf-8', newline='\n')
        command(cc, '-std=c11', '-Wall', '-Wextra', '-Werror', cfile, '-o', binary)
        process = subprocess.run([str(binary.resolve())], capture_output=True)
        outcomes[name] = process.returncode
        if (process.returncode == 0) != (name == 'production'):
            raise RuntimeError('SUS_PATH semantic control failed: '+name)
    result = {'upstream_pin': SUSFS_PIN, 'scope': 'host C semantic tests with kernel API stubs',
              'functions_sha256': {name: sha(text.encode()) for name, text in functions.items()},
              'variant_exit_codes': outcomes, 'allowlist_direction': 'selected app UIDs may see flagged paths',
              'android_user_normalization': True, 'fuse_and_regular_paths': True,
              'preserved_uid_gate': True, 'kernel_compilation_proven': False, 'device_runtime_tested': False}
    (work/'RESULT.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


if __name__ == '__main__':
    configure_main()
