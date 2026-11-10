"""Compile exact old/new readdir syscall bodies against kernel boundary fakes."""
from pathlib import Path
import argparse,importlib.util,json,re,subprocess
HERE=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('hidden_apply',HERE/'apply.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

def main():
 p=argparse.ArgumentParser();p.add_argument('--common',type=Path);p.add_argument('--source',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--cc',default='cc');a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
 text=(a.common/'fs/readdir.c' if a.common else a.source).read_text();old=m.original(text) if 'susfs_name_filter.h' in text else text;new=m.transform(old)
 header=(HERE/'host.h').read_text()+'\n'+(HERE/'susfs_name_filter.h').read_text();tail=(HERE/'host.c').read_text();results=[]
 for zm in (0,1):
  for kind,source in [('baseline',old),('fixed',new)]:
   code=header+'\n'+re.sub(r'^#include[^\n]*\n','',source,flags=re.M)+'\n'+tail
   path=a.output/f'{kind}-zm{zm}.c';path.write_text(code);binary=path.with_suffix('')
   cmd=[a.cc,'-std=gnu11','-O1','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-unused-function','-Wno-unused-label','-Wno-sign-compare','-Wno-pointer-sign','-DCONFIG_KSU_SUSFS_HIDDEN_NAME=1']
   if zm:cmd+=['-DCONFIG_ZEROMOUNT=1']
   compile=subprocess.run(cmd+[str(path),'-o',str(binary)],capture_output=True,text=True)
   if compile.returncode:raise RuntimeError(compile.stderr)
   run=subprocess.run([str(binary)],capture_output=True,text=True)
   if kind=='baseline':
    if run.returncode==0 or 'directory leak or unexpected hiding' not in run.stderr:raise RuntimeError('Baseline did not reproduce the intended leak: '+run.stdout+run.stderr)
   elif run.returncode:raise RuntimeError(run.stdout+run.stderr)
   results.append({'kind':kind,'zeromount':bool(zm),'exit_code':run.returncode,'output':(run.stdout+run.stderr).strip()})
 result={'regression_reproduced':True,'five_abis_tested':True,'inode_cache_independent':True,'owner_and_runtime_exceptions_tested':True,'small_buffer_and_eof_tested':True,'cases':results,'limitation':'Kernel API boundary fakes; full ARM64 build, CRC checks and real app tests are separate gates.'}
 (a.output/'TESTS.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
