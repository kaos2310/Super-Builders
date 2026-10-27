"""Exercise the unmodified native ABI negotiation and capability validation C."""
import subprocess
from pathlib import Path
from sukisu_41096_uapi import function, git

PREFIX = r'''
#include <stdbool.h>
#include <stdint.h>
#include <errno.h>
#include <stddef.h>
#include "uapi/extension.h"
typedef uint32_t u32; typedef uint64_t u64;
#define __user
#define pr_err(...) ((void)0)
#define pr_warn(...) ((void)0)
#define mutex_lock(x) ((void)0)
#define mutex_unlock(x) ((void)0)
'''
CHECKS = r'''
static int fail_get;
static int getter(u32 id, u64 *v) { *v = 55; return fail_get ? -EIO : 0; }
static int setter(u32 id, u64 v) { return 0; }
#define CHECK(x) do { if (!(x)) return __LINE__; } while (0)
int main(void) {
    struct ksu_extension_handler_ops ops = {.get=getter,.set=setter};
    struct ksu_extension_handler h = {.extension_id=0, .name="mock", .ops=&ops,
        .caps=KSU_EXTENSION_FLAG_STICKY | KSU_EXTENSION_FLAG_PERSIST, .min_api_version=1};
    CHECK(extension_handler_validate(&h)==0);
    CHECK(extension_api_allowed(&h,0) && extension_api_allowed(&h,1));
    h.min_api_version=2; CHECK(!extension_api_allowed(&h,0) && !extension_api_allowed(&h,1));
    CHECK(extension_api_allowed(&h,2) && extension_handler_validate(&h)==-EINVAL);
    h.min_api_version=1; h.caps |= KSU_FEATURE_FLAG_SUPPORTED;
    CHECK(extension_handler_validate(&h)==-EINVAL); h.caps &= ~KSU_FEATURE_FLAG_SUPPORTED;
    h.caps |= KSU_EXTENSION_FLAG_FORCED; CHECK(extension_handler_validate(&h)==-EINVAL);
    h.caps &= ~KSU_EXTENSION_FLAG_FORCED; ops.set=NULL;
    CHECK(extension_handler_validate(&h)==-EINVAL);
    h.caps=KSU_EXTENSION_FLAG_PERSIST; CHECK(extension_handler_validate(&h)==-EINVAL);
    h.caps=KSU_EXTENSION_FLAG_REBOOT; CHECK(extension_handler_validate(&h)==0);
    extension_handlers[0]=&h; u64 value=999; u32 caps=999;
    CHECK(ksu_extension_get(0,0,&value,&caps)==0 && value==55 && caps==17);
    fail_get=1; CHECK(ksu_extension_get(0,1,&value,&caps)==-EIO && caps==0);
    fail_get=0; h.min_api_version=2; value=999; caps=999;
    CHECK(ksu_extension_get(0,1,&value,&caps)==0 && !value && !caps);
    extension_handlers[0]=NULL; value=999; caps=999;
    CHECK(ksu_extension_get(0,1,&value,&caps)==0 && !value && !caps);
    CHECK(ksu_extension_get(KSU_EXTENSION_MAX,1,&value,&caps)==-EINVAL);
    return 0;
}
'''

def test_capabilities(source, cc, work):
    text=(source/'kernel/extension/extension.c').read_text()
    header=(source/'kernel/extension/extension.h').read_text()
    structs=header[header.index('struct ksu_extension_handler;'):header.index('int ksu_register_extension_handler(')]
    names=('extension_api_allowed','extension_handler_validate','ksu_extension_get')
    native=git(source,'show','HEAD:kernel/extension/extension.c').decode()
    bodies=[]
    for name in names:
        body=function(text,name)
        if body!=function(native,name):raise RuntimeError('Native capability code changed: '+name)
        bodies.append(body)
    code=PREFIX+structs+'\nstatic const struct ksu_extension_handler *extension_handlers[KSU_EXTENSION_MAX];\n'+'\n'.join(bodies)+CHECKS
    variants={'production':code}
    for label,old,new in (
        ('legacy-api','u32 caller = caller_api_version ? caller_api_version : 1;','u32 caller = caller_api_version;'),
        ('persist-validation','(handler->caps & KSU_EXTENSION_FLAG_PERSIST) && !has_setter','false'),
        ('capability-loss','KSU_FEATURE_FLAG_SUPPORTED | handler->caps','KSU_FEATURE_FLAG_SUPPORTED')):
        if code.count(old)!=1:raise RuntimeError('Capability mutation anchor changed: '+label)
        variants[label]=code.replace(old,new)
    results={}
    for label,code in variants.items():
        src=work/(label+'-caps.c');binary=work/(label+'-caps');src.write_text(code)
        subprocess.run([cc,'-std=gnu11','-Werror=implicit-function-declaration','-I',str(source),str(src),'-o',str(binary)],check=True)
        rc=subprocess.run([str(binary)]).returncode
        if (rc==0)!=(label=='production'):raise RuntimeError('Capability test failed: '+label)
        results[label]=rc
    return {'extension_api_version':1,'legacy_api_zero_maps_to_one':True,'native_get_and_registration_validated':True,'negative_controls_rejected':3,'tests':results,'device_tested':False}
