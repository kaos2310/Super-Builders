#!/usr/bin/env python3
"""Execute native SukiSU session code and the reference SUSFS KSTAT/VFS tests."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import uuid
import integration
import uapi4

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('reference_tests', HERE.parent / 'su-session-35187/test.py')
util = importlib.util.module_from_spec(spec)
spec.loader.exec_module(util)

def native_sources(common, ksu):
    su = (ksu / 'kernel/feature/sucompat.c').read_text()
    marker = '\n#else\n__attribute__((hot)) static __always_inline bool __is_su_allowed'
    if su.count(marker) != 1:
        raise RuntimeError('Pinned SukiSU SUSFS/non-SUSFS branch boundary drift')
    su = su.split(marker, 1)[0]
    functions = util.extract(su, 'ksu_handle_execveat_sucompat')
    functions += '\nstatic int ksu_handle_execveat(int *fd, struct filename **p, void *a, void *e, int *f) { return ksu_handle_execveat_sucompat(fd,p,a,e,f); }\n'
    functions += util.extract(su, 'ksu_handle_execveat_su_session')
    exec_text = (common / 'fs/exec.c').read_text()
    post = re.search(r'\tif \(unlikely\(is_su_session && retval >= 0\)\) \{.*?\n\t\}', exec_text, re.S)
    if not post:
        raise RuntimeError('Actual native post-success FD block missing')
    code = r'''
typedef __SIZE_TYPE__ size_t;
typedef __INTPTR_TYPE__ intptr_t;
typedef _Bool bool;
#define true 1
#define false 0
#define NULL ((void *)0)
void *memcpy(void *d,const void *s,size_t n) {char *a=d;const char *b=s;while(n--)*a++=*b++;return d;}
int memcmp(const void *a,const void *b,size_t n) {const unsigned char *x=a,*y=b;while(n--){if(*x!=*y)return *x-*y;x++;y++;}return 0;}
int strcmp(const char *a,const char *b) {while(*a&&*a==*b){a++;b++;}return *a-*b;}
char *strcpy(char *d,const char *s) {char *p=d;while((*p++=*s++));return d;}
#define SU_PATH "/system/bin/su"
#define SH_PATH "/system/bin/sh"
#define KSUD_PATH "/data/adb/ksud"
#define TIF_KSU_DISABLE_ESCAPE_WITH_ROOT 1
#define EPERM 1
#define LOOKUP_FOLLOW 1
#define GFP_KERNEL 0
#define likely(x) (x)
#define unlikely(x) (x)
#define IS_ERR(x) ((intptr_t)(x)<0)
#define IS_ERR_OR_NULL(x) (!(x)||IS_ERR(x))
#define pr_info(...) ((void)0)
#define pr_err(...) ((void)0)
#define pr_warn(...) ((void)0)
#define __user
struct filename { char name[160]; } filename;
struct user_arg_ptr { int unused; } args;
struct ksu_sulog_pending_event { int unused; } event;
struct path {int unused;};
static const char su_path[]=SU_PATH,ksud_path[]=KSUD_PATH,sh_path[]=SH_PATH;
static int root_ret,allowed,chrooted,root_calls,fd_calls,fd_ret,checks,no_privs,path_ret;
static int test_thread_flag(int flag) {return no_privs;}
static int kern_path(const char *name,int flag,struct path *path) {return path_ret;}
static void path_put(struct path *path) {}
static struct { unsigned val; } current_uid(void) { return (typeof(current_uid())){11000}; }
static int ksu_handle_execveat_init(struct filename *f,struct user_arg_ptr *a,struct user_arg_ptr *e) { return -22; }
static bool __ksu_is_allow_uid_for_current(unsigned uid) { return allowed; }
static bool current_chrooted(void) { return chrooted; }
static struct ksu_sulog_pending_event *ksu_sulog_capture_sucompat(const char *f,struct user_arg_ptr *a,int g) { return &event; }
static void ksu_sulog_emit_pending(struct ksu_sulog_pending_event *e,int ret,int g) {}
static int escape_with_root_profile(void) { root_calls++;return root_ret; }
static const char *get_user_arg_ptr(struct user_arg_ptr a,int n) { return "su"; }
static int ksu_install_su_fd(void) { fd_calls++;return fd_ret; }
@@FUNCTIONS@@
static void post_exec(bool is_su_session,int retval) {
@@POST@@
}
#define CHECK(x) do {checks++;if(!(x))return __LINE__;}while(0)
int test_main(void) {
 struct filename *p=&filename;
 int fd=0,flags=0;
 for(int failure=0;failure<8;failure++) {
  strcpy(filename.name,SU_PATH);root_ret=0;allowed=1;chrooted=root_calls=fd_calls=no_privs=path_ret=0;fd_ret=5;
  if(failure==1)allowed=0;
  if(failure==2)chrooted=1;
  if(failure==3)root_ret=-12;
  if(failure==4)strcpy(filename.name,"/system/bin/sh");
  if(failure==5)fd_ret=-24;
  if(failure==6)no_privs=1;
  if(failure==7)path_ret=-2;
  bool session=ksu_handle_execveat_su_session(&fd,&p,&args,&args,&flags);
  CHECK(session==(failure==0||failure==5));
  if(failure==3||failure==6)CHECK(!strcmp(filename.name,SU_PATH));
  if(failure==6)CHECK(root_calls==0);
  if(failure==7)CHECK(!strcmp(filename.name,SH_PATH));
  post_exec(session,-2);CHECK(fd_calls==0);
  post_exec(session,0);CHECK(fd_calls==(session?1:0));
  post_exec(false,0);CHECK(fd_calls==(session?1:0));
 }
 CHECK(!ksu_handle_execveat_su_session(&fd,NULL,&args,&args,&flags));
 p=NULL;CHECK(!ksu_handle_execveat_su_session(&fd,&p,&args,&args,&flags));
 return 0;
}
int test_count(void) {return checks;}
#ifndef WASM_TEST
int printf(const char *,...);
int main(void) {int line=test_main();printf("Native SukiSU exact-C checks: %d; failure line: %d\n",checks,line);return line?1:0;}
#endif
'''
    return code.replace('@@FUNCTIONS@@', functions).replace('@@POST@@', post[0])

def webview_sources(ksu):
    policy = (ksu / 'kernel/policy/allowlist.c').read_text()
    lsm = (ksu / 'kernel/hook/lsm_hook.c').read_text()
    code = (HERE.parent / 'su-session-35187/webview.c.in').read_text()
    code = code.replace('static uid_t manager_uid;', '''static uid_t manager_uid;
#define PER_USER_RANGE 100000
static bool ksu_is_manager_appid_valid(void) {return manager_uid!=0;}
static unsigned ksu_get_manager_appid(void) {return manager_uid;}
static bool is_uid_manager(uid_t uid) {return uid%PER_USER_RANGE==manager_uid;}
''')
    code = code.replace('@@NEXT@@', '''static void disable_seccomp(void) {}
static void ksu_handle_extra_susfs_work(void) {if(!work_pending(&susfs_extra_works))schedule_work(&susfs_extra_works);}
''' + util.extract(lsm, 'handle_zygote_next_setresuid'))
    for key, name in (('VALID','profile_valid'), ('POLICY','ksu_uid_should_umount'), ('PRUNE','ksu_prune_allowlist')):
        code = code.replace(f'@@{key}@@', util.extract(policy, name))
    return code

def driver_sources(ksu):
    read = lambda p: (ksu / p).read_text()
    driver = read('kernel/supercall/supercall.c')
    dispatch = read('kernel/supercall/dispatch.c')
    table = uapi4.extract(dispatch, 'ksu_ioctl_handlers', array=True)
    handlers = set(re.findall(r'\.handler\s*=\s*(\w+)', table)) - {'NULL', 'do_get_info'}
    header = read('kernel/supercall/supercall.h')
    payloads = read('kernel/include/uapi/app_profile.h') + '\n' + read('kernel/include/uapi/supercall.h')
    payloads = re.sub(r'^#include[^\n]*', '', payloads, flags=re.M)
    values = dict(
        UAPI=payloads,
        TYPES='\n'.join(re.findall(r'^typedef .*;$', header, re.M)) + '\n' +
              re.search(r'struct ksu_ioctl_cmd_map \{.*?\};', header, re.S)[0],
        DRIVER=driver[driver.index('#define KSU_DRIVER_PERMISSION_SU_SESSION'):driver.index('static void ksu_install_fd_tw_func(')],
        INFO='const __u32 ksu_uapi4_contract = KERNEL_SU_UAPI_VERSION;\n' + uapi4.extract(dispatch, 'do_get_info'),
        HANDLERS='\n'.join(f'static int {n}(void *p) {{return 123;}}' for n in sorted(handlers)),
        DISPATCH=table + '\n' + uapi4.extract(dispatch, 'ksu_supercall_handle_ioctl'),
    )
    code = (HERE / 'uapi4-driver.c.in').read_text()
    for key, value in values.items():
        if code.count(f'@@{key}@@') != 1:
            raise RuntimeError(f'Driver test template mismatch: {key}')
        code = code.replace(f'@@{key}@@', value)
    return code

def wrapper_sources(ksu):
    # Reuse only the reference API mocks; compile the actual pinned SukiSU
    # function with its credential and cleanup paths inserted verbatim.
    mocks = (HERE.parent / 'su-session-35187/harness.c.in').read_text()
    code = mocks.split('@@PROFILE@@', 1)[0]
    code += mocks[mocks.index('struct inode_security_struct'):mocks.index('@@INSTALL@@')]
    code += mocks[mocks.index('static int wrapper_fault'):mocks.index('@@WRAPPER@@')]
    code += uapi4.extract((ksu / 'kernel/infra/file_wrapper.c').read_text(), 'ksu_install_file_wrapper')
    code += r'''
int test_main(void) {
 for(int f=0;f<=5;f++) {
  wrapper_fault=f==5?0:f;fd_error=f==5?-24:0;
  mock_violation=original_puts=wrapper_puts=wrapper_releases=installs=releases=0;
  override_active=override_calls=revert_calls=0;
  original_inode.i_mode=0620;wrapper_security.sid=0;
  orig_file=(struct file){.f_path={&original_dentry},.inode=&original_inode};
  wrapper_file=(struct file){.f_path={&wrapper_dentry},.inode=&wrapper_inode};
  wrapper_dentry=(struct dentry){0};
  int ret=ksu_install_file_wrapper(1);
  CHECK(ret==(f==0?7:f==1?-EBADF:f==2||f==4?-ENOMEM:f==3?-EPERM:-24));
  CHECK(override_active==0 && override_calls==revert_calls && mock_violation==0);
  CHECK(override_calls==((f==0||f==3||f==4)?1:0));
  CHECK(original_puts==(f==1?0:1));CHECK(installs==(f==0?1:0));
  CHECK(releases==((f==2||f==3||f==4)?1:0));
  CHECK(wrapper_puts==(f==4?1:0));CHECK(wrapper_releases==(f==3?1:0));
  if(f==0) {
   CHECK(wrapper_inode.i_mode==original_inode.i_mode && wrapper_security.sid==42);
   CHECK(wrapper_dentry.d_fsdata==&allocated_path && allocated_path.dentry==&original_dentry);
  }
 }
 return 0;
}
int test_count(void) {return checks;}
#ifndef WASM_TEST
int printf(const char *,...);
int main(void) {int line=test_main();printf("SukiSU exact-C wrapper checks: %d; failure line: %d\n",checks,line);return line?1:0;}
#endif
'''
    return code

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--common', required=True, type=Path)
    p.add_argument('--ksu', required=True, type=Path)
    p.add_argument('--work-dir', required=True, type=Path)
    p.add_argument('--cc', default='gcc')
    a = p.parse_args()
    a.wasm = False
    a.node = None
    integration.verify(a.common, a.ksu)
    root = a.work_dir.resolve() / ('sukisu40940-' + uuid.uuid4().hex)
    root.mkdir(parents=True)
    code = native_sources(a.common, a.ksu)
    native = util.compile_run(code, 'native', a, root)
    driver_code = driver_sources(a.ksu)
    driver = util.compile_run(driver_code, 'uapi4-driver', a, root)
    wrapper_code = wrapper_sources(a.ksu)
    wrapper = util.compile_run(wrapper_code, 'uapi4-wrapper', a, root)
    for label, old, new in (
        ('wrapper-credentials', 'old_cred = override_creds(ksu_cred);', 'old_cred = &live_cred;'),
        ('wrapper-restore', 'revert_creds(old_cred);', '(void)old_cred;'),
    ):
        if wrapper_code.count(old) != 1:
            raise RuntimeError(f'Wrapper mutation anchor drift: {label}')
        util.compile_run(wrapper_code.replace(old, new, 1), label, a, root, expect_failure=True)
    for label, old, new in (
        ('unscoped-driver', 'KSU_DRIVER_PERMISSION_SU_SESSION ? "[ksu_driver_su]"', 'KSU_DRIVER_PERMISSION_SU_SESSION ? "[ksu_driver]"'),
        ('ordinary-fd-permissions', 'ksu_install_fd_with_permissions(O_CLOEXEC, 0)', 'ksu_install_fd_with_permissions(O_CLOEXEC, KSU_DRIVER_PERMISSION_SU_SESSION)'),
        ('unscoped-ioctl', 'ksu_ioctl_handlers[i].allow_su_session && ksu_is_su_session_fd(filp)', 'ksu_is_su_session_fd(filp)'),
        ('uapi-version', 'KERNEL_SU_UAPI_VERSION, 4)', 'KERNEL_SU_UAPI_VERSION, 2)'),
    ):
        if driver_code.count(old) != 1:
            raise RuntimeError(f'UAPI4 mutation anchor drift: {label}')
        util.compile_run(driver_code.replace(old, new, 1), label, a, root, expect_failure=True)
    webview = util.compile_run(webview_sources(a.ksu), 'webview', a, root)
    for label, old, new in (
        ('failed-exec', 'is_su_session && retval >= 0', 'is_su_session'),
        ('ordinary-exec', 'is_su_session && retval >= 0', 'retval >= 0'),
        ('profile-failure', 'return ret;\n    }\n    /* Preserve', '(void)0;\n    }\n    /* Preserve'),
        ('no-new-privileges', 'if (test_thread_flag(TIF_KSU_DISABLE_ESCAPE_WITH_ROOT)) {', 'if (false) {'),
        ('missing-ksud', 'if (kern_path(KSUD_PATH, LOOKUP_FOLLOW, &kpath)) {', 'if (false) {'),
    ):
        if code.count(old) != 1:
            raise RuntimeError(f'Mutation anchor drift: {label}')
        util.compile_run(code.replace(old, new, 1), label, a, root, expect_failure=True)
    util.verify_vfs(a.common)
    kstat = util.compile_run(util.kstat_sources(a.common), 'kstat', a, root)
    record = dict(native=native, uapi4_driver=driver, uapi4_wrapper=wrapper, webview=webview,
                  kstat=kstat, mutation_rejections=11,
                  uapi=4, uapi_reference_commit=uapi4.MAIN_PIN,
                  vfs_scope_order='passed', runtime_test='not performed')
    (root / 'result.json').write_text(json.dumps(record, indent=2) + '\n')

if __name__ == '__main__':
    main()
