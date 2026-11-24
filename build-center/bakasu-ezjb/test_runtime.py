"""Exercise the actual staged Runtime-v1 kernel and CLI sources through host shims."""

import argparse
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
FEATURES = ('UID_GATED_HIDING', 'HIDDEN_NAME', 'UNICODE_FILTER', 'HIDE_KSU_SUSFS_SYMBOLS')


def exercise(common, output, filename, mask):
    target = output / f'{Path(filename).stem}-{mask}'
    definitions = [f'-DCONFIG_KSU_SUSFS_{feature}' for index, feature in enumerate(FEATURES)
                   if mask & (1 << index)]
    subprocess.run(['gcc', '-std=c11', '-pthread', '-Wall', '-Wextra', '-Werror', '-O2',
                    '-I', common / 'fs', '-I', common / 'include/linux',
                    f'-DEXPECT_SUPPORTED={mask}', *definitions, HERE / filename, '-o', target], check=True)
    return subprocess.check_output([target], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('common', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cases = [exercise(args.common, args.output, 'test_runtime.c', mask) for mask in range(16)]
    helper = exercise(args.common, args.output, 'test_helper.c', 15)
    checks = sum(int(re.search(r'checks=(\d+)', case)[1]) for case in cases + [helper])
    report = {'configurations': len(cases), 'assertions': checks, 'variants': cases,
              'helper_kernel_integration': helper, 'device_runtime_tested': False}
    result = json.dumps(report, indent=2) + '\n'
    (args.output / 'SUSFS-RUNTIME-TESTS.json').write_text(result, encoding='utf-8')
    print(result, end='')


if __name__ == '__main__':
    main()
