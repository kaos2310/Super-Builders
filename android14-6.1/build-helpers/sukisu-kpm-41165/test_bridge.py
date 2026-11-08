#!/usr/bin/env python3
"""Host tests of native SukiSU/KP framing with mocked kernel calls, not device tests."""
from pathlib import Path
import argparse,hashlib,json,re,subprocess,tempfile
import build_and_patch as integration
def function(text,name):
    pat=r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''
    masked=re.sub(pat,lambda m:re.sub(r'[^\n]',' ',m[0]),text,flags=re.S)
    hits=list(re.finditer(r'^(?:static\s+)?(?:long|int|void)\s+(?:__nocfi\s+)?'+name+r'\([^;{]*\)\s*\{',masked,re.M))
    if len(hits)!=1:raise RuntimeError('Expected one native function '+name)
    m=hits[0];i=m.end();depth=1
    while depth and i<len(masked):depth+=(masked[i]=='{')-(masked[i]=='}');i+=1
    if depth:raise RuntimeError('Unclosed native function '+name)
    return text[m.start():i]
PREFIX=r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32; typedef uint64_t u64;
#define CONFIG_ARM64 1
#define CONFIG_KPM 1
#define __nocfi
#define PSR_MODE_EL1h 5
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define processor_mode(p) ((p)->pstate & 15)
struct pt_regs { unsigned long regs[31]; unsigned long sp,pc,pstate; };
typedef struct {unsigned long arg0; long ret; int skip_origin;} hook_fargs1_t;
static bool engine_ready, missing;
static int calls;
static unsigned long seen_op,seen_arg;
static long dispatch(unsigned long op,unsigned long a1,unsigned long a2,unsigned long a3,unsigned long a4) {
    calls++;seen_op=op;seen_arg=a1;return op==SUKISU_KPM_PROBE?SUKISU_KPM_ABI_VERSION:7;
}
'''
MIDDLE=r'''
static long mock_truncate(const struct pt_regs *regs) {
    hook_fargs1_t args={.arg0=(unsigned long)regs,.ret=-EFAULT};
    if(engine_ready)before_supercall(&args,NULL);
    return args.ret;
}
static void *find_kernel_symbol_exact(const char *name) { return missing?NULL:(void *)mock_truncate; }
'''
CHECKS=r'''
#define CHECK(x) do{if(!(x))return __LINE__;}while(0)
int main(void) {
    u64 value=99;
    missing=true;CHECK(sukisu_kpm_bridge(0,0,0,0,0)==-EOPNOTSUPP);
    missing=false;engine_ready=false;
    CHECK(sukisu_kpm_bridge(SUKISU_KPM_NUM,0,0,0,0)==-EOPNOTSUPP);
    CHECK(ksu_extension_kpm_get(0,&value)==0 && value==0);
    engine_ready=true;
    CHECK(ksu_extension_kpm_get(0,&value)==0 && value==1);
    CHECK(sukisu_kpm_bridge(SUKISU_KPM_NUM,0x123456789UL,0,0,0)==7);
    CHECK(seen_op==SUKISU_KPM_NUM && seen_arg==0x123456789UL);
    struct pt_regs r={.pstate=0};
    r.regs[0]=SUKISU_KPM_SUPERCALL_MAGIC;r.regs[6]=SUKISU_KPM_SUPERCALL_MAGIC2;
    r.regs[7]=SUKISU_KPM_SUPERCALL_MAGIC3;r.regs[8]=SUKISU_KPM_ABI_VERSION;
    hook_fargs1_t args={.arg0=(unsigned long)&r,.ret=-22};int before=calls;
    before_supercall(&args,NULL);CHECK(!args.skip_origin && args.ret==-22 && calls==before);
    r.pstate=PSR_MODE_EL1h;r.regs[6]=0;
    before_supercall(&args,NULL);CHECK(args.skip_origin && args.ret==-EPROTO && calls==before);
    r.regs[6]=SUKISU_KPM_SUPERCALL_MAGIC2;r.regs[8]=0;
    before_supercall(&args,NULL);CHECK(args.ret==-EPROTO && calls==before);
    r.regs[8]=SUKISU_KPM_ABI_VERSION;r.regs[9]=1;
    before_supercall(&args,NULL);CHECK(args.ret==-EPROTO && calls==before);
    r.regs[9]=0;before_supercall(&args,NULL);CHECK(args.ret==SUKISU_KPM_ABI_VERSION && calls==before+1);
    return 0;
}
'''
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--engine',type=Path,required=True);p.add_argument('--ksu',type=Path,required=True);p.add_argument('--receipt',type=Path,required=True);a=p.parse_args()
    if integration.git(a.engine,'rev-parse','HEAD')!=integration.ENGINE_PIN or integration.git(a.ksu,'rev-parse','HEAD')!=integration.SUKISU_PIN:raise RuntimeError('Source pair mismatch')
    kp=a.engine/'kernel/patch/sukisu/sukisu.c';su=a.ksu/'kernel/extension/kpm/kpm.c';ext=a.ksu/'kernel/extension/kpm.c'
    paths=[(a.engine,'kernel/patch/sukisu/sukisu.c'),(a.engine,'kernel/patch/sukisu/supercall.h'),(a.ksu,'kernel/extension/kpm/kpm.c'),(a.ksu,'kernel/extension/kpm/bridge.h'),(a.ksu,'kernel/extension/kpm.c')]
    hashes={}
    for root,name in paths:
        data=(root/name).read_bytes()
        if data!=subprocess.check_output(['git','-C',str(root),'show','HEAD:'+name]):raise RuntimeError('Native KPM source changed: '+name)
        hashes[str(root.name)+'/'+name]=hashlib.sha256(data).hexdigest()
    headers=[(a.ksu/'kernel/extension/kpm/bridge.h').read_text(),(a.engine/'kernel/patch/sukisu/supercall.h').read_text()]
    def constants(text):return {k:int(v.rstrip('ULul'),0) for k,v in re.findall(r'^#define\s+(SUKISU_KPM_\w+)\s+([0-9a-fxA-FX]+(?:UL)?)\s*$',text,re.M)}
    left,right=map(constants,headers)
    if len(left.keys()&right.keys())<6 or any(left[k]!=right[k] for k in left.keys()&right.keys()):raise RuntimeError('Native framing constants differ')
    defines='\n'.join('#define '+k+' '+str(v)+'UL' for k,v in right.items())+'\n'
    engine=function(kp.read_text(),'before_supercall');bridge=function(su.read_text(),'sukisu_kpm_bridge');get=function(ext.read_text(),'ksu_extension_kpm_get')
    production=defines+PREFIX+engine+MIDDLE+bridge+get+CHECKS
    changes=[('el0-boundary','!regs || processor_mode(regs) != PSR_MODE_EL1h','!regs'),('reserved-registers','if (regs->regs[i]) return;','if (false) return;'),('probe-required','if (fn(&regs) != SUKISU_KPM_ABI_VERSION)','if (false)'),('pointer-width','regs.regs[2] = a1;','regs.regs[2] = (u32)a1;')]
    variants={'production':production}
    for name,old,new in changes:
        if production.count(old)!=1:raise RuntimeError('Mutation anchor changed: '+name)
        variants[name]=production.replace(old,new)
    from test_event import test_event
    with tempfile.TemporaryDirectory(prefix='kpm-bridge-') as tmp:
        event_tests=test_event(kp.read_text(),defines,function,Path(tmp))
        for name,src in variants.items():
            path=Path(tmp)/name;path.with_suffix('.c').write_text(src)
            subprocess.run(['gcc','-std=gnu11','-Werror=implicit-function-declaration',str(path.with_suffix('.c')),'-o',str(path)],check=True)
            rc=subprocess.run([str(path)]).returncode
            if (rc==0)!=(name=='production'):raise RuntimeError('Native bridge/negative control failed: '+name)
    # The full native recovery may retain only these bounded PAC->NOP changes.
    original=b'\0'*4+(0xd503233f).to_bytes(4,'little')+b'\0'*4
    restored=b'\0'*4+(0xd503201f).to_bytes(4,'little')+b'\0'*4
    assert len(integration.audit_restore(original,restored,4,4))==1
    for wrong in (restored[:8]+b'xxxx',restored[:4]+b'xxxx'+restored[8:]):
        try:integration.audit_restore(original,wrong,4,4)
        except RuntimeError:pass
        else:raise RuntimeError('Unexpected image transform was accepted')
    result={'event_tests':event_tests,'sukisu_pin':integration.SUKISU_PIN,'engine_pin':integration.ENGINE_PIN,'abi_constants_match':True,'native_functions_tested':True,'negative_controls_rejected':4,'unexpected_image_changes_rejected':2,'source_sha256':hashes,'device_tested':False}
    a.receipt.parent.mkdir(parents=True,exist_ok=True);a.receipt.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
