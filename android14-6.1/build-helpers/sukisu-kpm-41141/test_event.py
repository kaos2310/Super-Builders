"""Exercise native KernelPatch op 8, including argument forwarding and guards."""
import subprocess
PREFIX=r'''
#include <errno.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#define __user
static int event_calls,legacy_calls;
static const char *event_path,*event_args,*event_name;
static unsigned int kpver;
static const char *get_build_time(void) {return "test";}
static long load_module_path(const char *p,const char *a,void *r) {legacy_calls++;return 11;}
static long load_module_path_event(const char *p,const char *a,const char *e,void *r) {
    event_calls++;event_path=p;event_args=a;event_name=e;return -EIO;
}
static long unload_module(const char *n,void *r) {return 0;}
static long get_module_nums(void) {return 0;}
static long module_control0(const char *n,const char *a,char *b,unsigned long c) {return 0;}
static long list_snapshot(char *b,int c) {return 0;}
static long get_module_info(const char *n,char *b,long c) {return 0;}
'''
CHECKS=r'''
#define CHECK(x) do {if (!(x)) return __LINE__;} while(0)
int main(void) {
    const char *p="/data/adb/kpm/test.kpm",*a="a=1",*e="post-fs-data";
    CHECK(dispatch(SUKISU_KPM_PROBE,0,0,0,0)==2);
    CHECK(dispatch(SUKISU_KPM_LOAD_EVENT,(unsigned long)p,(unsigned long)a,(unsigned long)e,0)==-EIO);
    CHECK(event_calls==1 && event_path==p && event_args==a && event_name==e);
    CHECK(dispatch(SUKISU_KPM_LOAD_EVENT,0,(unsigned long)a,(unsigned long)e,0)==-EINVAL);
    CHECK(dispatch(SUKISU_KPM_LOAD_EVENT,(unsigned long)p,(unsigned long)a,0,0)==-EINVAL);
    CHECK(dispatch(SUKISU_KPM_LOAD_EVENT,(unsigned long)p,(unsigned long)a,(unsigned long)e,1)==-EINVAL);
    CHECK(event_calls==1);
    CHECK(dispatch(SUKISU_KPM_LOAD,(unsigned long)p,(unsigned long)a,0,0)==11 && legacy_calls==1);
    return 0;
}
'''

def test_event(engine_source, defines, extract, work):
    body=extract(engine_source,'dispatch')
    code=defines+PREFIX+body+CHECKS
    variants={'production':code}
    for label,old,new in (
        ('event-op-absent','case SUKISU_KPM_LOAD_EVENT:', 'case 99:'),
        ('wrong-event-forwarding','(const char *)a3, (void *)a4);','(const char *)a2, (void *)a4);')):
        if code.count(old)!=1:raise RuntimeError('KPM event mutation anchor changed: '+label)
        variants[label]=code.replace(old,new)
    results={}
    for label,src in variants.items():
        path=work/(label+'-event');path.with_suffix('.c').write_text(src)
        subprocess.run(['gcc','-std=gnu11','-Werror=implicit-function-declaration',str(path.with_suffix('.c')),'-o',str(path)],check=True)
        rc=subprocess.run([str(path)]).returncode
        if (rc==0)!=(label=='production'):raise RuntimeError('KPM native event test failed: '+label)
        results[label]=rc
    return {'native_event_dispatch_passed':True,'abi_version':2,'negative_controls_rejected':2,'tests':results,'device_tested':False}
