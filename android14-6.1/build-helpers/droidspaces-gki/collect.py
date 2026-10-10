#!/usr/bin/env python3
"""Collect partial kernel build evidence without treating stock modules as rebuilt."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

root, output = Path(sys.argv[1]), Path(sys.argv[2])
output.mkdir(parents=True, exist_ok=True)
configs, modules, symvers = [], [], []
# Bazel's bazel-out symlink leads to its execution root; include it explicitly.
roots = [root / 'out', root / 'bazel-out', root / 'bazel-bin']
seen = set()
for build in roots:
    if not build.exists():
        continue
    for parent, dirs, files in os.walk(build, followlinks=False):
        for name in files:
            path = Path(parent) / name
            if name not in ('.config', 'Module.symvers') and not name.endswith('.ko'):
                continue
            resolved = path.resolve()
            if resolved in seen or not resolved.is_file():
                continue
            seen.add(resolved)
            relative = str(path.relative_to(root))
            if name.endswith('.ko'):
                modules.append({'path': relative, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
            else:
                target = output / 'outputs' / path.relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                (configs if name == '.config' else symvers).append(relative)
report = dict(resource_limits_requested=sys.argv[3] == 'true',
              configs=configs, symbol_versions=symvers, built_module_candidates=modules,
              stock_vendor_boot_modules=411, stock_vendor_dlkm_modules=351,
              full_device_module_rebuild_completed=False,
              rebuilt_vendor_boot=False, rebuilt_vendor_dlkm=False, rebuilt_system_dlkm=False,
              stock_module_compatibility_verified=False, device_boot_verified=False,
              limitation='This tree has a common-kernel source port, not a complete Samsung external-module and partition build graph.')
(output / 'BUILD-SCOPE.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k != 'built_module_candidates'}, indent=2))
