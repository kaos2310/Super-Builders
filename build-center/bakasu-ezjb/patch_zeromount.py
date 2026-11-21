"""Rebuild the reference ZeroMount ZIP with a checked native prop-watch endpoint."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
REFERENCE = ROOT.parent / 'nova35004-20261120' / 'release'
REFERENCE_SHA = '6adf97a62b3bec57c0357bc08ff93e0096f42d2ea42bc2e3952b6d695cc91e70'
NATIVE = 'bin/arm64-v8a/zm-native-core'
ADAPTER = 'bin/zm-brene76'
CHECKSUMS = ('SHA256SUMS', 'COMPAT-SHA256SUMS')


def digest(data):
    return sha256(data).hexdigest()


def replace_once(data, before, after):
    if data.count(before) != 1:
        raise ValueError(f'Missing or ambiguous patch anchor: {before!r}')
    return data.replace(before, after, 1)


def patch_adapter(data):
    data = replace_once(data, b'$BINDIR/arm64-v8a/zeromount}', b'$BINDIR/arm64-v8a/zm-native-core}')
    guard = b'''require_native_core() {
    local identity machine
    if [ -f "$NATIVE" ] && [ -x "$NATIVE" ] && [ ! -L "$NATIVE" ]; then
        identity=$(LC_ALL=C od -An -tx1 -N6 "$NATIVE" 2>/dev/null) &&
        machine=$(LC_ALL=C od -An -tx1 -j18 -N2 "$NATIVE" 2>/dev/null) &&
        [ "$(printf '%s' "$identity" | tr -d '[:space:]')" = 7f454c460201 ] &&
        [ "$(printf '%s' "$machine" | tr -d '[:space:]')" = b700 ] && return 0
    fi
    printf 'BRENE76: expected a native AArch64 executable at %s\\n' "$NATIVE" >&2
    return 65
}

'''
    data = replace_once(data, b'property_pass() {', guard + b'property_pass() {')
    return replace_once(data, b'1:) property_pass;; 2:--repeat) while',
                        b'1:) require_native_core && property_pass;; '
                        b'2:--repeat) require_native_core || exit $?; while')


def verify_sums(members):
    for name in CHECKSUMS:
        seen = set()
        for line in members[name].decode().splitlines():
            checksum, member = line.split('  ', 1)
            if member in seen or digest(members[member]) != checksum:
                raise ValueError(f'{name} mismatch for {member}')
            seen.add(member)
        if seen != set(members).difference(CHECKSUMS):
            raise ValueError(f'{name} does not cover all payload members')


def main(source, output):
    if digest(source.read_bytes()) != REFERENCE_SHA:
        raise ValueError('Unexpected reference ZeroMount ZIP')
    with zipfile.ZipFile(source) as archive:
        entries = archive.infolist()
        members = {item.filename: archive.read(item) for item in entries}
        if len(entries) != len(members):
            raise ValueError('Duplicate reference members')
    core = members[NATIVE]
    if core[:6] != b'\x7fELF\x02\x01' or core[18:20] != b'\xb7\x00':
        raise ValueError('Reference native core does not match Android AArch64')
    members[ADAPTER] = patch_adapter(members[ADAPTER])
    members['module.prop'] = replace_once(members['module.prop'], b'.runtime-addon1\nversionCode=2026112001',
                                         b'.runtime-addon1.propwatchfix1\nversionCode=2026112101')
    proof = json.loads(members['BRENE76-INTEGRATION.json'])
    proof['changed_files_sha256'][ADAPTER] = digest(members[ADAPTER])
    members['BRENE76-INTEGRATION.json'] = (json.dumps(proof, indent=2) + '\n').encode()
    manifest = json.loads(members['build-manifest.json'])
    manifest['revision'] += '-propwatchfix1'
    if isinstance(manifest['brene_integration'], dict):
        manifest['brene_integration'] = proof
    manifest['prop_watch_fix'] = {
        'reference_zip_sha256': REFERENCE_SHA,
        'adapter_sha256': digest(members[ADAPTER]),
        'default_executable': NATIVE,
        'native_core_sha256': digest(core),
        'reject_shell_alias': True,
        'android_runtime_tested': False,
    }
    members['build-manifest.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    payload = sorted(set(members).difference(CHECKSUMS))
    for name in CHECKSUMS:
        members[name] = ''.join(f'{digest(members[p])}  {p}\n' for p in payload).encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    pending = output.with_suffix('.zip.part')
    with zipfile.ZipFile(pending, 'w') as archive:
        for info in entries:
            archive.writestr(info, members[info.filename], compresslevel=9)
    with zipfile.ZipFile(pending) as archive:
        if archive.testzip():
            raise ValueError('Output ZIP failed CRC verification')
        verify_sums({name: archive.read(name) for name in archive.namelist()})
    pending.replace(output)
    print(digest(output.read_bytes()), output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=next(REFERENCE.glob('ZeroMount*.zip')))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    main(args.source, args.output)
