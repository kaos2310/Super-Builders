#!/usr/bin/env python3
"""Verify final KPM Image identity and the paired engine/ABI receipts."""
from pathlib import Path
import argparse,json
import build_and_patch as kpm
p=argparse.ArgumentParser(description=__doc__)
for name in ('image','receipt','abi','config'):p.add_argument('--'+name,type=Path,required=True)
a=p.parse_args();receipt=json.loads(a.receipt.read_text());abi=json.loads(a.abi.read_text())
if receipt['engine']['sukisu_pin']!=kpm.SUKISU_PIN or receipt['engine']['kernelpatch_pin']!=kpm.ENGINE_PIN:raise RuntimeError('KPM source pair drift')
if kpm.sha(a.image)!=receipt['patched_sha256']:raise RuntimeError('Packaged KPM Image hash mismatch')
if receipt.get('normalized_recovery_matches_original') is not True:raise RuntimeError('Missing bounded recovery proof')
if not abi['abi_constants_match'] or not abi['native_functions_tested'] or abi['negative_controls_rejected']!=4 or abi['unexpected_image_changes_rejected']!=2:raise RuntimeError('KPM ABI fault tests missing')
event=abi.get('event_tests',{})
if event.get('abi_version')!=2 or event.get('native_event_dispatch_passed') is not True or event.get('negative_controls_rejected')!=2:raise RuntimeError('KPM ABI 2 event tests missing')
if 'CONFIG_KPM=y' not in a.config.read_text().splitlines():raise RuntimeError('KPM is disabled in packaged configuration')
if receipt['original_sha256']==receipt['patched_sha256']:raise RuntimeError('Engine was not added')
print('PASS: paired native KPM engine, bounded Image transform and CONFIG_KPM=y')
