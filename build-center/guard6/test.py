"""Exercise original menu, real bridge contracts, installer state and full ZIP."""
from pathlib import Path,PurePosixPath
import copy,json,subprocess,sys,tempfile,zipfile
from package import arguments,package,validate

def run(*args):
    result=subprocess.run(list(map(str,args)),capture_output=True,text=True)
    if result.returncode:raise RuntimeError('Guard6 check failed: '+result.stdout+result.stderr)
    print(result.stdout+result.stderr,flush=True)

if __name__=='__main__':
    args=arguments().parse_args();helpers=args.helpers.resolve();plan=json.loads(args.plan.read_text())
    validate(plan,helpers)
    code=plan['sukisu_code']
    different_susfs=('0' if plan['susfs_commit'][0]!='0' else '1')+plan['susfs_commit'][1:]
    for changes in ({'sukisu_code':code+1},{'susfs_commit':different_susfs},{'profile':'wrong'}):
        changed=copy.deepcopy(plan);changed.update(changes)
        try:validate(changed,helpers)
        except RuntimeError:pass
        else:raise RuntimeError('Wrong source/profile was accepted')
    run('node',helpers/f'zeromount-ui-{code}/test.mjs')
    run(sys.executable,'-B',helpers/f'zeromount-package-{code}/test_install.py')
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary);source=root/'base';source.mkdir()
        with zipfile.ZipFile(helpers/f'zeromount-package-{code}/module-base.zip') as archive:
            for name in archive.namelist():
                path=PurePosixPath(name)
                if path.is_absolute() or '..' in path.parts or '\\' in name:raise RuntimeError('Unsafe baseline')
                target=source/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.read(name))
        run(sys.executable,'-B',helpers/f'zeromount-ui-{code}/test.py',source)
        result=package(helpers,plan,args.runtime_helper,root/'output')
        with zipfile.ZipFile(root/'output'/result['zip_name']) as archive:
            for line in archive.read('COMPAT-SHA256SUMS').decode().splitlines():
                digest,name=line.split('  ',1)
                from package import sha
                if sha(archive.read(name))!=digest:raise RuntimeError('Installed-member checksum mismatch')
    print('PASS Guard6.13/BRENE75 original controls, additive Runtime, installer persistence, source pair and complete package')
