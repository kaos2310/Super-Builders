"""Prepare ephemeral copies of the audited builder for one immutable source pair.

Names are migrated with their references. Historical preflight evidence is
discarded; the full build and existing semantic/CRC gates create fresh evidence.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
if __package__:
    from .firmware_profile import prepare as prepare_firmware
    from .kbuild_compat import REVIEWED_PINS as KBUILD_REFRESH_PINS, adapt_compat_patch
    from .susfs_helpers import prepare as prepare_susfs_helpers
    from .versioning import validate_mapping
    from .helper_identity import prepare as prepare_identity_helpers
else:
    from firmware_profile import prepare as prepare_firmware
    from kbuild_compat import REVIEWED_PINS as KBUILD_REFRESH_PINS, adapt_compat_patch
    from susfs_helpers import prepare as prepare_susfs_helpers
    from versioning import validate_mapping
    from helper_identity import prepare as prepare_identity_helpers

OLD_PIN = 'd7d042816b82b200c25b3a93dcc158ba0307cabf'
OLD_CODE = '41165'


def validate(plan):
    for key in ('sukisu_commit', 'susfs_commit', 'baseline_commit', 'susfs_release_base', 'susfs_functional_base'):
        if not re.fullmatch('[0-9a-f]{40}', plan.get(key, '')):
            raise ValueError('Invalid immutable pin: '+key)
    count, code = plan['sukisu_count'], plan['sukisu_code']
    validate_mapping(plan)
    if 'sukisu_repository' in plan and (plan.get('sukisu_repository_id')!=957055748
            or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',plan['sukisu_repository'])):
        raise ValueError('Invalid official SukiSU repository identity')
    reviewed = KBUILD_REFRESH_PINS.get(plan['sukisu_commit'])
    if reviewed is not None and (code, count) != reviewed:
        raise ValueError('Invalid reviewed source/version mapping')
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+(?:[\w.+-]*)', plan['susfs_version']):
        raise ValueError('Invalid SuSFS version')
    if plan['profile'] != 'S928BXXS6EZJ1-EUX-android14-6.1.162':
        raise ValueError('Only the audited S928B/EZJ1 profile is supported')
    if not re.fullmatch(r'v[\w.+-]+', plan['sukisu_tag']):
        raise ValueError('Invalid SukiSU tag')


def prepare(root, plan):
    validate(plan)
    root = root.resolve()
    marker = root / '.build-center-plan.json'
    if marker.exists():
        if json.loads(marker.read_text()) != plan:
            raise ValueError('Workspace already belongs to another source pair')
        return
    helper = root / 'android14-6.1/build-helpers'
    if not (helper / 'sukisu-41165-susfs/apply.py').is_file():
        raise ValueError('Audited 41165 builder is missing')
    prepare_firmware(root, plan)
    code, pin = str(plan['sukisu_code']), plan['sukisu_commit']
    def migrate(text):
        text=text.replace(OLD_PIN, pin).replace(OLD_PIN[:8], pin[:8])
        text=re.sub(r'(?<![0-9a-f])41165(?![0-9a-f])',code,text)
        return re.sub(r'(?<![0-9a-f])3980(?![0-9a-f])',str(plan['sukisu_count']),text)
    # Only these audited source/helper surfaces are involved in the new build.
    for base in (helper, root / '.github/workflows'):
        for path in list(base.rglob('*')):
            if path.is_file() and not path.is_symlink():
                try:
                    original = path.read_text(encoding='utf-8')
                except UnicodeError:
                    continue
                changed = migrate(original)
                if changed != original:
                    path.write_text(changed, encoding='utf-8', newline='\n')
        for path in sorted(base.rglob('*'), key=lambda p: len(p.parts), reverse=True):
            if OLD_CODE in path.name and code != OLD_CODE:
                path.rename(path.with_name(path.name.replace(OLD_CODE, code)))
    # Replace the historical evidence gate with a live source-preparation gate.
    # All semantic tests and full kernel compilation still execute afterwards.
    shutil.copyfile(Path(__file__).with_name('runtime.py'), helper / '_center_runtime.py')
    shutil.copyfile(Path(__file__).with_name('versioning.py'), helper / '_center_versioning.py')
    shutil.copyfile(Path(__file__).with_name('suspath_test.py'), helper / '_center_suspath_test.py')
    adapter=helper/'_center_kbuild_compat'
    (adapter/'compat').mkdir(parents=True)
    shutil.copyfile(Path(__file__).with_name('kbuild_compat.py'),adapter/'kbuild_compat.py')
    shutil.copyfile(Path(__file__).with_name('compat')/'kbuild-41176.patch',adapter/'compat/kbuild-41176.patch')
    if pin=='b2d01e8bcea80139be9076c63dcc9a6694691d72':
        shutil.copyfile(Path(__file__).with_name('lock_compat.py'),helper/'_center_lock_compat.py')
        lock_wrapper=("from pathlib import Path\nimport argparse,json\nimport _center_lock_compat as impl\n"
            +f"PIN={pin!r}\n"
            +"def upstream(root,path):return impl.upstream(root,PIN,path)\n"
            +"def verify(root):return impl.verify(root,PIN)\n"
            +"def apply(root):return impl.apply(root,PIN)\n"
            +"if __name__=='__main__':\n"
            +"    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('--verify-only',action='store_true');a=p.parse_args()\n"
            +"    print(json.dumps(verify(a.source) if a.verify_only else apply(a.source),indent=2))\n")
        (helper/f'sukisu_{code}_lock.py').write_text(lock_wrapper,encoding='utf-8',newline='\n')
    shutil.copytree(Path(__file__).with_name('hidden_names'), helper / 'susfs-hidden-name-readdir',
                    ignore=shutil.ignore_patterns('__pycache__'))
    port = helper / f'sukisu-{code}-susfs'
    if pin in KBUILD_REFRESH_PINS:
        compat = port / 'compat.patch'
        compat.write_bytes(adapt_compat_patch(compat.read_bytes(), plan))
        print(f'Refreshed the exact {code} Kbuild preinit deletion hunk; audited build profile retained')
    wrapper = "from pathlib import Path\nimport sys\nsys.path.insert(0,str(Path(__file__).resolve().parents[1]))\nfrom _center_runtime import {}\n{}()\n"
    (port / 'apply.py').write_text(wrapper.format('port_apply', 'port_apply'), encoding='utf-8')
    (port / 'check.py').write_text(wrapper.format('port_check', 'port_check'), encoding='utf-8')
    (port / 'PREFLIGHT.json').write_text(json.dumps({
        'schema': 1, 'pin': pin, 'susfs_pin': plan['susfs_commit'],
        'stage': 'source_preparation', 'historical_evidence_reused': False,
        'full_kernel_link_tested': False, 'stock_module_crc_compatibility_tested': False,
        'device_runtime_tested': False,
        'scope': 'Fresh semantic tests, full ARM64 build and strict CRC gates are required in this run.'
    }, indent=2)+'\n', encoding='utf-8')
    for proof in helper.rglob('PREFLIGHT.json'):
        if proof != port / 'PREFLIGHT.json' and str(code) in str(proof):
            proof.write_text(json.dumps({'stage':'not_reused','historical_evidence_reused':False,
                'scope':'New execution evidence is recorded by the current CI run.'}, indent=2)+'\n', encoding='utf-8')
    identity=("from pathlib import Path\nimport argparse\nfrom _center_versioning import configure_identity\n"
              +f"PLAN={plan!r}\n"
              +"def configure(root,verify=False):return configure_identity(root,PLAN,verify)\n"
              +"if __name__=='__main__':\n"
              +"    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('--verify-only',action='store_true');a=p.parse_args()\n"
              +"    configure(a.source,a.verify_only);print('PASS: immutable upstream kernel version and official manager identity')\n")
    (helper/f'configure-sukisu-{code}.py').write_text(identity,encoding='utf-8',newline='\n')
    prepare_identity_helpers(helper,code,plan)
    prepare_susfs_helpers(helper,code,plan)
    marker.write_text(json.dumps(plan, indent=2)+'\n', encoding='utf-8')
    print(f'Prepared SukiSU {code} at {pin}; historical compilation evidence was not reused')


if __name__ == '__main__':
    p = argparse.ArgumentParser();p.add_argument('root', type=Path);p.add_argument('--plan-env', default='CENTER_PLAN')
    a = p.parse_args();prepare(a.root, json.loads(os.environ[a.plan_env]))
