#!/usr/bin/env python3
"""Apply only the official SUSFS 2.4.0 release macro after functional gates.

Upstream a2165b6 differs from 5f85e6e only in this header macro and module.prop.
The existing audited native SukiSU SELinux integration stays in place.
"""
import argparse, hashlib, json
from pathlib import Path

UPSTREAM = 'a2165b6f875b73e2f87d3c6f12814efac8de061d'
EXPECTED = 'b3de6f8bba7b0c2adf63e4fb9777ccb2dc2916790b8fd085e8723e60f6dec25d'
OLD = b'#define SUSFS_VERSION "v2.3.0"'
NEW = b'#define SUSFS_VERSION "v2.4.0"'

def verify(common):
    header=common/'include/linux/susfs.h'
    receipt=json.loads((common/'.susfs-release240.json').read_text())
    if hashlib.sha256(header.read_bytes()).hexdigest()!=EXPECTED or receipt.get('release_header_sha256')!=EXPECTED or receipt.get('upstream_release_pin')!=UPSTREAM or receipt.get('susfs_version')!='v2.4.0':
        raise RuntimeError('SUSFS 2.4.0 release identity drift')
    return receipt

def apply(common):
    header = common/'include/linux/susfs.h'
    original = header.read_bytes()
    if original.count(NEW) == 1 and OLD not in original:
        result = original
    elif original.count(OLD) == 1 and NEW not in original:
        result = original.replace(OLD, NEW)
    else:
        raise RuntimeError('Unexpected SUSFS version macro')
    digest = hashlib.sha256(result).hexdigest()
    if digest != EXPECTED:
        raise RuntimeError('SUSFS release header differs from independently compiled 2.4.0 header')
    if result != original:
        header.write_bytes(result)
    receipt={'susfs_version':'v2.4.0','upstream_release_pin':UPSTREAM,
             'functional_base_pin':'5369359dbd10f6dd8cbdd59d1df7b788b29b168c',
             'priority_functional_pin':'5f85e6e7838a54ad363de5749d33361a5da2316b',
             'release_header_sha256':digest,'release_only_change':True}
    (common/'.susfs-release240.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('common',type=Path);a=p.parse_args()
    print(json.dumps(apply(a.common),indent=2))
