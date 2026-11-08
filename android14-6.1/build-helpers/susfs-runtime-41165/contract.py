#!/usr/bin/env python3
"""Preserve run 42129383180 inputs, with only the two requested extensions."""
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
state=json.loads((HERE/'BASELINE.json').read_text())
text=(ROOT/'.github/workflows/run-sukisu-41165-kpm-strict.yml').read_text()
section=text.split('  strict-gate:\n',1)[1].split('    with:\n',1)[1]
actual={}
for line in section.splitlines():
    if line.startswith('#'):break
    if line.strip() and not line.lstrip().startswith('#'):
        key,_,value=line.strip().partition(':');actual[key]=value.strip().strip('"')
expected=dict(state['base_inputs'],sukisu_commit='d7d042816b82b200c25b3a93dcc158ba0307cabf',resukisu_version_code='41165',susfs_runtime_setters='true')
if actual!=expected:raise RuntimeError('Build options drifted from the explicitly selected baseline')
print('PASS: baseline inputs retained; SukiSU41165 + runtime-v1 only')
