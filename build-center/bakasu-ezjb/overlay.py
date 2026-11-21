"""Restore the reviewed BakaSU EZJB source overlay onto its exact AOSP base."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile

HERE = Path(__file__).resolve().parent
common = Path(sys.argv[1]).resolve()
listing = json.loads((HERE / 'common-overlay.json').read_text())
assert subprocess.check_output(['git', '-C', common, 'rev-parse', 'HEAD'], text=True).strip() == listing['aosp_common']


def target(name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] == '.git':
        raise ValueError(f'Unexpected source path {name}')
    return common / path


with tarfile.open(HERE / 'common-overlay.tar.xz') as source:
    members = source.getmembers()
    if len(members) != len(listing['files']) or {m.name for m in members} != listing['files'].keys():
        raise ValueError('Source overlay list drift')
    for member in members:
        target(member.name)
        metadata = listing['files'][member.name]
        if (not member.isfile() or member.mode != int(metadata['mode'][-3:], 8) or
                hashlib.sha256(source.extractfile(member).read()).hexdigest() != metadata['sha256']):
            raise ValueError(f'Invalid source overlay member {member.name}')
    for name in listing['delete']:
        target(name).unlink()
    source.extractall(common, filter='data')
