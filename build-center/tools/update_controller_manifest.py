"""Bind the automatic source contract to the exact workflow and resolver."""
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT.parent / '.github/workflows/build-center.yml'


def manifest():
    return {'schema':2,'workflow':'build-center.yml','source_binding':'source-request-v1',
            'profile':'S928BXXS6EZJ1-EUX-android14-6.1.162','channels':['main','release'],
            'workflow_sha256':hashlib.sha256(WORKFLOW.read_bytes()).hexdigest(),
            'resolver_sha256':hashlib.sha256((ROOT/'ci/check_updates.py').read_bytes()).hexdigest()}


if __name__=='__main__':
    (ROOT/'controller.json').write_text(json.dumps(manifest(),indent=2)+'\n',encoding='utf-8',newline='\n')
    shutil.copyfile(WORKFLOW,ROOT/'integration/.github/workflows/build-center.yml')
    print('Controller manifest and integration workflow synchronized')
