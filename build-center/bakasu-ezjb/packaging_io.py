"""Validation and deterministic ZIP writing for the EZJB release assets."""
from hashlib import sha256
from pathlib import PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


def digest(data):
    return sha256(data).hexdigest()


def write_zip(output, members, entries):
    output.parent.mkdir(parents=True, exist_ok=True)
    pending = output.with_suffix('.part')
    with ZipFile(pending, 'w', compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, raw in sorted(members.items()):
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or '\\' in name:
                raise ValueError(f'Unsafe archive member {name}')
            info = ZipInfo(name, (2026, 11, 21, 0, 0, 0))
            mode = 0o100755 if name == 'ksu_susfs' else 0o100644
            info.create_system = 3
            info.external_attr = entries[name].external_attr if name in entries else mode << 16
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, raw)
    with ZipFile(pending) as archive:
        if archive.testzip() or set(archive.namelist()) != members.keys():
            raise ValueError('Package validation failed')
        for hashes in ('SHA256SUMS', 'COMPAT-SHA256SUMS'):
            if hashes not in members:
                continue
            for line in archive.read(hashes).decode().splitlines():
                expected, name = line.split('  ', 1)
                if digest(archive.read(name)) != expected:
                    raise ValueError(f'{hashes} mismatch for {name}')
    pending.replace(output)
