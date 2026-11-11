"""Select a reviewed Kbuild patch refresh for one exact official source pin.

Upstream added preinit runner linker flags after the audited 41165 template.
The existing manual-hook profile removes that runner block. Refreshing its
deletion hunk preserves the audited postimage without fuzzy patch application.
"""
from pathlib import Path
import hashlib
import re

SOURCE_PIN = '3af6085d0d26e73ffd1a3e7b34362435dcfb5a03'
REVIEWED_PINS = {
    SOURCE_PIN: (41176, 3991),
    '1c9cca42f8049227d4eea20ab3979db3c5662a7d': (41178, 3993),
}
BASE_FRAGMENT_SHA256 = '9077757358943819e7f2ff8833678983cd91afc0a215396e534a72cb682fd98c'
FIXED_FRAGMENT_SHA256 = '822bbc66db146efc304ad9fee0cbd0ec1f764fae96578d284ba74a5e30d14a15'
KBUILD_HEADER = b'diff --git a/kernel/Kbuild b/kernel/Kbuild\n'


def adapt_compat_patch(patch, plan):
    """Change only Kbuild's patch section; reject unreviewed inputs."""
    mapping = REVIEWED_PINS.get(plan['sukisu_commit'])
    if mapping is None:
        return patch
    if (plan['sukisu_code'], plan['sukisu_count']) != mapping:
        raise RuntimeError('Kbuild refresh requires an exact reviewed SukiSU source/version mapping')
    parts = re.split(rb'(?=^diff --git )', patch, flags=re.M)
    matches = [i for i, part in enumerate(parts) if part.startswith(KBUILD_HEADER)]
    if len(matches) != 1:
        raise RuntimeError('Expected exactly one audited Kbuild compatibility section')
    index = matches[0]
    actual = hashlib.sha256(parts[index]).hexdigest()
    fixed = Path(__file__).with_name('compat').joinpath('kbuild-41176.patch').read_bytes()
    if hashlib.sha256(fixed).hexdigest() != FIXED_FRAGMENT_SHA256:
        raise RuntimeError('Reviewed 41176 Kbuild fragment identity changed')
    if actual == FIXED_FRAGMENT_SHA256:
        return patch
    if actual != BASE_FRAGMENT_SHA256:
        raise RuntimeError('Audited baseline Kbuild fragment changed; explicit compatibility review required')
    parts[index] = fixed
    return b''.join(parts)
