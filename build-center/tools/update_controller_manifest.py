"""Bind the automatic source contract to the exact workflow and resolver."""
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT.parent / '.github/workflows/build-center.yml'


def canonical_bytes(path):
    # GitHub serves the LF blob. Existing Windows worktrees can still contain
    # CRLF after an eol attribute was introduced, so normalize before binding.
    data=path.read_text(encoding='utf-8').encode('utf-8')
    if path.read_bytes()!=data:
        path.write_bytes(data)
    return data


def manifest():
    return {'schema':2,'workflow':'build-center.yml','source_binding':'source-request-v1',
            'profile':'S928BXXU6EZJB-EUX-android14-6.1.162','channels':['main','release'],
            'source_versions':'kbuild-affine-v1','automatic_builds':True,'kernel_revision':'hidden-name-readdir-v2',
            'workflow_sha256':hashlib.sha256(canonical_bytes(WORKFLOW)).hexdigest(),
            'resolver_sha256':hashlib.sha256(canonical_bytes(ROOT/'ci/check_updates.py')).hexdigest()}


if __name__=='__main__':
    (ROOT/'controller.json').write_text(json.dumps(manifest(),indent=2)+'\n',encoding='utf-8',newline='\n')
    for workflow in WORKFLOW.parent.glob('build-center*.yml'):
        shutil.copyfile(workflow,ROOT/'integration/.github/workflows'/workflow.name)
    print('Controller manifest and integration workflow synchronized')
