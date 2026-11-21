"""Verify the legacy release header or a freshly merged immutable source receipt."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re

UPSTREAM='a2165b6f875b73e2f87d3c6f12814efac8de061d'
EXPECTED='b3de6f8bba7b0c2adf63e4fb9777ccb2dc2916790b8fd085e8723e60f6dec25d'
OLD=b'#define SUSFS_VERSION "v2.3.0"'
NEW=b'#define SUSFS_VERSION "v2.4.0"'
VERSION_MACRO=rb'^#define[ \t]+SUSFS_VERSION[ \t]+"([^"\r\n]+)"[ \t]*\r?$'


def require_version(header,version):
    if (not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+[A-Za-z0-9_.+\-]*',version)
            or re.findall(VERSION_MACRO,header,re.M)!=[version.encode('ascii')]):
        raise RuntimeError('SuSFS header version does not match the immutable plan')


def updated_receipt(common):
    path=common/'.build-center-susfs-update.json'
    if not path.exists():return None
    root=next((p for p in (common,*common.parents) if (p/'.build-center-plan.json').is_file()),None)
    if root is None:raise RuntimeError('Merged release requires the immutable source plan')
    plan=json.loads((root/'.build-center-plan.json').read_text());update=json.loads(path.read_text())
    if (plan.get('profile')!='S928BXXS6EZJ1-EUX-android14-6.1.162'
            or update.get('source_pin')!=plan['susfs_commit'] or update.get('release_base')!=plan['susfs_release_base']
            or update.get('susfs_version')!=plan['susfs_version'] or update.get('conflicts')!=0):
        raise RuntimeError('Merged release source binding changed')
    header=(common/'include/linux/susfs.h').read_bytes()
    digest=hashlib.sha256(header).hexdigest()
    if update.get('effective_source_sha256',{}).get('include/linux/susfs.h')!=digest:
        raise RuntimeError('Merged release header drift')
    require_version(header,plan['susfs_version'])
    return {'susfs_version':plan['susfs_version'],'upstream_release_pin':plan['susfs_commit'],
            'functional_base_pin':plan['susfs_functional_base'],'release_header_sha256':digest,
            'release_only_change':False,'source_update_receipt_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def verify(common):
    receipt=json.loads((common/'.susfs-release240.json').read_text())
    updated=updated_receipt(common)
    if updated is not None:
        if receipt!=updated:raise RuntimeError('Merged release receipt drift')
    elif (hashlib.sha256((common/'include/linux/susfs.h').read_bytes()).hexdigest()!=EXPECTED
          or receipt.get('release_header_sha256')!=EXPECTED or receipt.get('upstream_release_pin')!=UPSTREAM
          or receipt.get('susfs_version')!='v2.4.0'):
        raise RuntimeError('SUSFS 2.4.0 release identity drift')
    return receipt


def apply(common):
    result=updated_receipt(common)
    if result is None:
        header=common/'include/linux/susfs.h';original=header.read_bytes()
        if original.count(NEW)==1 and OLD not in original:raw=original
        elif original.count(OLD)==1 and NEW not in original:raw=original.replace(OLD,NEW)
        else:raise RuntimeError('Unexpected SUSFS version macro')
        if hashlib.sha256(raw).hexdigest()!=EXPECTED:raise RuntimeError('Audited base release header changed')
        if raw!=original:header.write_bytes(raw)
        result={'susfs_version':'v2.4.0','upstream_release_pin':UPSTREAM,
                'functional_base_pin':'5369359dbd10f6dd8cbdd59d1df7b788b29b168c',
                'priority_functional_pin':'5f85e6e7838a54ad363de5749d33361a5da2316b',
                'release_header_sha256':EXPECTED,'release_only_change':True}
    (common/'.susfs-release240.json').write_text(json.dumps(result,indent=2)+'\n')
    verified=verify(common)
    # The initial action exports the legacy functional base. Later source and
    # configuration audits must use the verified effective update identity.
    if not verified['release_only_change'] and os.environ.get('GITHUB_ENV'):
        pin=verified['upstream_release_pin']
        if not re.fullmatch('[0-9a-f]{40}',pin):
            raise RuntimeError('Invalid merged release source pin')
        with Path(os.environ['GITHUB_ENV']).open('a',encoding='utf-8',newline='\n') as output:
            output.write('SUSFS_EXPECTED_VERSION='+verified['susfs_version']+'\n'
                         'SUSFS_PINNED_COMMIT='+pin+'\n')
    return verified


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('common',type=Path);args=parser.parse_args()
    print(json.dumps(apply(args.common),indent=2))
