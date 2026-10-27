#!/usr/bin/env python3
"""Read-only gate after downstream transforms and before flash packaging."""
from pathlib import Path
import argparse,hashlib,json
import apply as port

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--common',type=Path,required=True)
parser.add_argument('--ksu',type=Path,required=True)
parser.add_argument('--config',type=Path)
args=parser.parse_args()
proof=json.loads((port.HERE/'PREFLIGHT.json').read_text())
if proof['port_sha256']!=hashlib.sha256((port.HERE/'apply.py').read_bytes()).hexdigest():
    raise RuntimeError('Independent port evidence changed')
port.verify(args.common,args.ksu)
text=(args.ksu/'kernel/tools/susfs_compat.mk').read_text()
original=port.run('git','-C',args.ksu,'show',port.PIN+':kernel/tools/susfs_compat.mk').decode()
if text!=original or '$(error Please wait susfs update.)' in text:
    raise RuntimeError('Exact upstream SUSFS compatibility Makefile required')
state=json.loads((args.common/'.bakasu-35252-susfs-port.json').read_text())
if not state['native_port_approved'] or state['bakasu_pin']!=port.PIN:
    raise RuntimeError('Independent native port was not approved')
if args.config:
    lines=args.config.read_text().splitlines()
    if 'CONFIG_KALLSYMS_ALL=y' not in lines:raise RuntimeError('Native symbol resolver requires KALLSYMS_ALL')
print('PASS: audited BakaSU35252 native SELinux port; no obsolete manual fake_state hooks')
