#!/usr/bin/env python3
"""Pin SukiSU's builtin source and its independently counted main version."""
import argparse
import re
import subprocess
from pathlib import Path

PIN = 'b20dee702035af09cb2ecb5f35443bbc1747f3e6'
MAIN_PIN = '7fbbb1f12e2410b69c8ebf958be84f165b8d0c93'
VERSION = 40940
FULL = 'v4.2.0-40940-b20dee70@builtin'

def configure(root, verify=False):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()
    if git('rev-parse', 'HEAD') != PIN:
        raise RuntimeError('Unexpected SukiSU builtin source commit')
    if int(git('rev-list', '--count', MAIN_PIN)) != 3755 or 40000 + 3755 - 2815 != VERSION:
        raise RuntimeError('SukiSU immutable main version formula mismatch')
    path = root / 'kernel/Makefile'
    text = path.read_text(encoding='utf-8')
    assignments = {'KSU_GITHUB_VER': '4.2.0', 'GITHUB_COMMITS': '3755', 'LOCAL_COUNT': '3755',
                   'KSU_VERSION': str(VERSION), 'KSU_VERSION_FULL': FULL}
    for name, value in assignments.items():
        pattern = r'^' + name + r'\s*:=.*$'
        if len(re.findall(pattern, text, re.M)) != 1:
            raise RuntimeError(f'Missing or ambiguous SukiSU version assignment: {name}')
        if verify:
            if f'{name} := {value}' not in text:
                raise RuntimeError(f'SukiSU pinned version drift: {name}')
        else:
            text = re.sub(pattern, f'{name} := {value}', text, count=1, flags=re.M)
    if not verify:
        path.write_text(text, encoding='utf-8', newline='\n')
    print(f'SukiSU builtin commit: {PIN}; main version reference: {MAIN_PIN}')
    print(f'SukiSU main commit count: 3755; version: {VERSION}; full version: {FULL}')

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('--verify-only', action='store_true')
    a = p.parse_args()
    configure(a.source.resolve(), a.verify_only)
