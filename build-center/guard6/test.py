"""Exercise original menu, real bridge contracts, installer state and full ZIP."""
from pathlib import Path,PurePosixPath
import copy,json,os,subprocess,sys,tempfile,zipfile
from package import arguments,package,validate

def run(*args):
    result=subprocess.run(list(map(str,args)),capture_output=True,text=True)
    if result.returncode:raise RuntimeError('Guard6 check failed: '+result.stdout+result.stderr)
    print(result.stdout+result.stderr,flush=True)


def verify_prop_watch(archive, root):
    def executable(name, body):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body.replace(b'#!/system/bin/sh\n', b'#!/bin/sh\n', 1))
        path.chmod(0o755)
        return path

    entry = executable('bin/zm', archive.read('bin/zm'))
    for name in ('bin/zm-brene75', 'bin/zm-brene76', 'bin/arm64-v8a/zeromount'):
        executable(name, archive.read(name))
    executable('bin/arm64-v8a/zm-native-core', b'''#!/bin/sh
case "$*" in
    'prop-watch') echo native-pass;;
    'config get brene.prop_spoofing') echo false;;
    *) exit 64;;
esac
''')
    executable('bin/zm-patch-policy', b'#!/bin/sh\necho "$*" >> "$TEST_POLICY_LOG"\necho true\n')
    executable('commands/getprop', b'#!/bin/sh\necho "$TEST_BOOT"\n')
    executable('commands/date', b'#!/bin/sh\necho 2026 11 21\n')
    executable('commands/sleep', b'#!/bin/sh\nkill -TERM "$PPID"\n')
    env = {key: value for key, value in os.environ.items() if not key.startswith('ZM')}
    policy_log = root / 'policy.log'
    env.update(PATH=f'{root}/commands:/usr/bin:/bin', TEST_BOOT='1',
               TEST_POLICY_LOG=str(policy_log), ZM71_EXTERNAL_FLAG=str(root / 'no-owner'))

    def watcher(*args, **overrides):
        result = subprocess.run([entry, 'prop-watch', *args], env=env | overrides,
                                capture_output=True, text=True, timeout=5)
        return result.returncode, result.stdout, result.stderr

    if watcher() != (0, 'native-pass\n', ''):
        raise RuntimeError('Public prop-watch failed to call the native endpoint exactly once')
    if policy_log.read_text().splitlines() != ['get spoof_os_security_patch_level_property']:
        raise RuntimeError('Existing property policy was bypassed')
    if watcher('--repeat') != (-15, 'native-pass\n', ''):
        raise RuntimeError('Repeating prop-watch failed its first pass')
    if watcher(TEST_BOOT='0') != (0, '', ''):
        raise RuntimeError('Prop-watch ran before boot completed')
    alias = str(root / 'bin/arm64-v8a/zeromount')
    for args in ((), ('--repeat',)):
        status, output, error = watcher(*args, ZM71_NATIVE=alias)
        if status != 65 or output or 'recursive prop-watch dispatch refused' not in error:
            raise RuntimeError('Prop-watch did not stop a recursive alias dispatch')
    print('PASS prop-watch native endpoint, existing property policy, boot gate and recursive alias guard')


if __name__=='__main__':
    args=arguments().parse_args();helpers=args.helpers.resolve();plan=json.loads(args.plan.read_text())
    validate(plan,helpers)
    for changes in ({'sukisu_code':41179},{'susfs_commit':'f'*40},{'profile':'wrong'}):
        changed=copy.deepcopy(plan);changed.update(changes)
        try:validate(changed,helpers)
        except RuntimeError:pass
        else:raise RuntimeError('Wrong source/profile was accepted')
    run('node',Path(__file__).resolve().parents[1]/'brene76/test.mjs')
    run(sys.executable,'-B',Path(__file__).resolve().parents[1]/'brene76/test.py')
    run(sys.executable,'-B',Path(__file__).resolve().parents[1]/'brene76/test_overlay.py','--helpers',helpers)
    run('node',helpers/f'zeromount-ui-{plan["sukisu_code"]}/test.mjs')
    run(sys.executable,'-B',helpers/f'zeromount-package-{plan["sukisu_code"]}/test_install.py')
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary);source=root/'base';source.mkdir()
        with zipfile.ZipFile(helpers/f'zeromount-package-{plan["sukisu_code"]}/module-base.zip') as archive:
            for name in archive.namelist():
                path=PurePosixPath(name)
                if path.is_absolute() or '..' in path.parts or '\\' in name:raise RuntimeError('Unsafe baseline')
                target=source/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.read(name))
        run(sys.executable,'-B',helpers/f'zeromount-ui-{plan["sukisu_code"]}/test.py',source)
        result=package(helpers,plan,args.runtime_helper,root/'output',args.susfs_tool)
        with zipfile.ZipFile(root/'output'/result['zip_name']) as archive:
            verify_prop_watch(archive, root/'prop-watch')
            for line in archive.read('COMPAT-SHA256SUMS').decode().splitlines():
                digest,name=line.split('  ',1)
                from package import sha
                if sha(archive.read(name))!=digest:raise RuntimeError('Installed-member checksum mismatch')
    print('PASS Guard6.13/BRENE76 original controls, additive Runtime, installer persistence, source pair and complete package')
