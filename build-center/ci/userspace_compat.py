"""Bounded, recorded fixes for reviewed upstream userspace compilation errors."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess

PIN='ef77212e51c95886192ac066ec7ec28a0108cdee'
CLI='userspace/ksud/src/cli.rs'
PROFILE='userspace/ksud/src/profile.rs'
CALLS=(
    ('crate::profile::set_sepolicy(&package, &policy)', 'crate::profile::set_sepolicy(&package, policy)'),
    ('crate::profile::set_template(&id, &template)', 'crate::profile::set_template(&id, template)'),
)


def digest(data):return hashlib.sha256(data).hexdigest()


def repaired_cli(pin,cli,profile):
    if pin!=PIN:return cli
    for signature in (b'pub fn set_sepolicy(pkg: &str, policy: String) -> Result<()> {',
                      b'pub fn set_template(id: &str, template: String) -> Result<()> {'):
        if profile.count(signature)!=1:raise RuntimeError('Reviewed profile signature changed')
    for before,after in CALLS:
        if cli.count(before.encode())!=1 or after.encode() in cli:
            raise RuntimeError('Reviewed ksud caller changed')
        cli=cli.replace(before.encode(),after.encode())
    return cli


def git(root,*args):
    return subprocess.check_output(['git','-C',str(root),*args])


def prepare(root,pin,receipt,verify_only=False):
    if git(root,'rev-parse','HEAD').decode().strip()!=pin:
        raise RuntimeError('Userspace source pin mismatch')
    originals={name:git(root,'show',pin+':'+name) for name in (CLI,PROFILE)}
    expected=dict(originals)
    expected[CLI]=repaired_cli(pin,originals[CLI],originals[PROFILE])
    # Validate both files and any previous receipt before changing anything.
    for name in originals:
        actual=(root/name).read_bytes()
        if actual!=expected[name] and (verify_only or actual!=originals[name]):
            raise RuntimeError('Userspace compatibility source drift: '+name)
    result={'schema':1,'pin':pin,'repair':'ksud-owned-profile-arguments-v1' if pin==PIN else None,
            'applied':expected[CLI]!=originals[CLI],
            'scope':'Two CLI call arguments only. Kernel, UAPI and dependency locks are unchanged.',
            'files':{name:{'upstream_sha256':digest(originals[name]),'effective_sha256':digest(expected[name])}
                     for name in originals}}
    if verify_only:
        if json.loads(receipt.read_text())!=result:raise RuntimeError('Userspace compatibility receipt drift')
    else:
        if receipt.exists() and json.loads(receipt.read_text())!=result:
            raise RuntimeError('Existing userspace compatibility receipt differs')
        if (root/CLI).read_bytes()!=expected[CLI]:(root/CLI).write_bytes(expected[CLI])
        receipt.parent.mkdir(parents=True,exist_ok=True)
        receipt.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--receipt',type=Path,required=True)
    parser.add_argument('--verify-only',action='store_true')
    args=parser.parse_args()
    plan=json.loads(args.plan.read_text())
    if not isinstance(plan.get('sukisu_commit'),str) or len(plan['sukisu_commit'])!=40:
        raise RuntimeError('Missing immutable source pin')
    prepare(args.source,plan['sukisu_commit'],args.receipt,args.verify_only)
