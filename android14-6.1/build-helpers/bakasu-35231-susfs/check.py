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
if 'BAKASU_SUSFS_PREFLIGHT' in text or 'requires CONFIG_KALLSYMS_ALL=y' not in text:
    raise RuntimeError('Independent native port build guard missing')
state=json.loads((args.common/'.bakasu-35231-susfs-port.json').read_text())
if not state['upstream_build_block_lifted'] or state['bakasu_pin']!=port.PIN:
    raise RuntimeError('Independent native port was not approved')
if args.config:
    lines=args.config.read_text().splitlines()
    if 'CONFIG_KALLSYMS_ALL=y' not in lines:raise RuntimeError('Native symbol resolver requires KALLSYMS_ALL')
print('PASS: audited BakaSU35231 native SELinux port; no obsolete manual fake_state hooks')
