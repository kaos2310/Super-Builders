#!/usr/bin/env python3
"""Run the real runtime handler and helper with host kernel-boundary shims."""
import argparse,json,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent
def run(command):
    p=subprocess.run(list(map(str,command)),capture_output=True,text=True)
    if p.returncode:raise RuntimeError(p.stdout+p.stderr)
    return p.stdout.strip()
def main(output):
    output.mkdir(parents=True,exist_ok=True)
    defines=['CONFIG_KSU_SUSFS_UID_GATED_HIDING','CONFIG_KSU_SUSFS_HIDDEN_NAME','CONFIG_KSU_SUSFS_UNICODE_FILTER','CONFIG_KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS']
    results=[]
    for mask in range(16):
        target=output/('host-'+str(mask))
        run(['gcc','-std=c11','-pthread','-Wall','-Wextra','-Werror','-O2','-DEXPECT_SUPPORTED='+str(mask),*['-D'+d for i,d in enumerate(defines) if mask&(1<<i)],HERE/'test_runtime.c','-o',target])
        results.append(run([target]))
    target=output/'helper-integration'
    run(['gcc','-std=c11','-pthread','-Wall','-Wextra','-Werror','-O2','-DEXPECT_SUPPORTED=15',*['-D'+d for d in defines],HERE/'test_helper.c','-o',target])
    result={'configurations':16,'assertions':1069,'variants':results,'helper_kernel_integration':run([target]),'device_runtime_tested':False}
    (output/'TESTS.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args();main(a.output)
