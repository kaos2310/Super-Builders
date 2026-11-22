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
    from .kbuild_compat import SOURCE_PIN as KBUILD_REFRESH_PIN, adapt_compat_patch
else:
    from firmware_profile import prepare as prepare_firmware
    from kbuild_compat import SOURCE_PIN as KBUILD_REFRESH_PIN, adapt_compat_patch

OLD_PIN = 'd7d042816b82b200c25b3a93dcc158ba0307cabf'
OLD_CODE = '41165'


def validate(plan):
    for key in ('sukisu_commit', 'susfs_commit', 'baseline_commit', 'susfs_release_base', 'susfs_functional_base'):
        if not re.fullmatch('[0-9a-f]{40}', plan.get(key, '')):
            raise ValueError('Invalid immutable pin: '+key)
    count, code = plan['sukisu_count'], plan['sukisu_code']
    if type(count) is not int or type(code) is not int or code != 40000+count-2815 or count < 2815:
        raise ValueError('Invalid source/version mapping')
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
    shutil.copytree(Path(__file__).with_name('hidden_names'), helper / 'susfs-hidden-name-readdir',
                    ignore=shutil.ignore_patterns('__pycache__'))
    port = helper / f'sukisu-{code}-susfs'
    if pin == KBUILD_REFRESH_PIN:
        compat = port / 'compat.patch'
        compat.write_bytes(adapt_compat_patch(compat.read_bytes(), plan))
        print('Refreshed the exact 41176 Kbuild preinit deletion hunk; audited build profile retained')
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
    (helper / f'configure-sukisu-{code}.py').write_text(
        (helper / f'configure-sukisu-{code}.py').read_text().replace(
            "'KSU_VERSION_FULL':'v4.3.0-r2-", "'KSU_VERSION_FULL':'"+plan['sukisu_tag']+'-').replace(
            "'VERSION_TAG':'4.3.0-r1'", "'VERSION_TAG':'"+plan['sukisu_tag'].removeprefix('v')+"'"), encoding='utf-8')
    marker.write_text(json.dumps(plan, indent=2)+'\n', encoding='utf-8')
    print(f'Prepared SukiSU {code} at {pin}; historical compilation evidence was not reused')


if __name__ == '__main__':
    p = argparse.ArgumentParser();p.add_argument('root', type=Path);p.add_argument('--plan-env', default='CENTER_PLAN')
    a = p.parse_args();prepare(a.root, json.loads(os.environ[a.plan_env]))
