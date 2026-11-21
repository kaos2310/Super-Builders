"""Verify the hosted build's flash package before a companion-only assembly."""
from hashlib import sha256
import json
from pathlib import Path
import sys
from zipfile import ZipFile


package = Path(sys.argv[1])
with ZipFile(package) as archive:
    if archive.testzip():
        raise ValueError('Kernel ZIP integrity check failed')
    for line in archive.read('SHA256SUMS').decode().splitlines():
        expected, name = line.split('  ', 1)
        if expected != sha256(archive.read(name)).hexdigest():
            raise ValueError(f'Kernel ZIP checksum failed for {name}')
    verification = json.loads(archive.read('BUILD-VERIFICATION.json'))
    if (not verification['target_identity_in_image'] or not verification['thinlto_present']
            or verification['strict_symbol_count'] != 2485 or not verification['strict_passed']
            or verification['native_kpm_present'] or verification['enabled_cpu_pid_limits']
            or verification['image_sha256'] != sha256(archive.read('Image')).hexdigest()
            or b'S928BXXU6EZJB' not in archive.read('anykernel.sh')):
        raise ValueError('Kernel archive does not satisfy the EZJB build contract')
print(f'{sha256(package.read_bytes()).hexdigest()}  {package.name}')
