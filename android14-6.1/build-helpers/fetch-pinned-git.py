#!/usr/bin/env python3
"""Retry a bounded exact-commit fetch; never substitute a branch or another pin."""
from pathlib import Path
import argparse,re,subprocess,time
def fetch(repo,pin,attempts=4,delay=10):
    if not re.fullmatch('[0-9a-f]{40}',pin):raise RuntimeError('An exact commit SHA is required')
    for attempt in range(1,attempts+1):
        print(f'Pinned fetch attempt {attempt}/{attempts}: {pin}',flush=True)
        try:
            result=subprocess.run(['git','-C',str(repo),'fetch','--depth=1','--no-tags','origin',pin],timeout=90)
            success=result.returncode==0
        except subprocess.TimeoutExpired:
            success=False
        if success:break
        if attempt==attempts:raise RuntimeError('Pinned fetch failed after bounded retries')
        time.sleep(delay*attempt)
    actual=subprocess.check_output(['git','-C',str(repo),'rev-parse','FETCH_HEAD'],text=True).strip()
    if actual!=pin:raise RuntimeError('Fetched commit differs from required pin')
    print('PASS: exact fetched commit verified',flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',type=Path,required=True);p.add_argument('--commit',required=True);a=p.parse_args();fetch(a.repo,a.commit)
