#!/usr/bin/env python3
"""Execute native SukiSU session code and the reference SUSFS KSTAT/VFS tests."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import uuid
import integration

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
#define KSUD_PATH "/data/adb/ksud"
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
static const char su_path[]=SU_PATH,ksud_path[]=KSUD_PATH;
static int root_ret,allowed,chrooted,root_calls,fd_calls,fd_ret,checks;
static struct { unsigned val; } current_uid(void) { return (typeof(current_uid())){11000}; }
static int ksu_handle_execveat_init(struct filename *f,struct user_arg_ptr *a,struct user_arg_ptr *e) { return -22; }
static bool __ksu_is_allow_uid_for_current(unsigned uid) { return allowed; }
static bool current_chrooted(void) { return chrooted; }
static struct ksu_sulog_pending_event *ksu_sulog_capture_sucompat(const char *f,struct user_arg_ptr *a,int g) { return &event; }
static void ksu_sulog_emit_pending(struct ksu_sulog_pending_event *e,int ret,int g) {}
static int escape_with_root_profile(void) { root_calls++;return root_ret; }
static const char *get_user_arg_ptr(struct user_arg_ptr a,int n) { return "su"; }
static int ksu_install_fd(void) { fd_calls++;return fd_ret; }
@@FUNCTIONS@@
static void post_exec(bool is_su_session,int retval) {
@@POST@@
}
#define CHECK(x) do {checks++;if(!(x))return __LINE__;}while(0)
int test_main(void) {
 struct filename *p=&filename;
 int fd=0,flags=0;
 for(int failure=0;failure<6;failure++) {
  strcpy(filename.name,SU_PATH);root_ret=0;allowed=1;chrooted=root_calls=fd_calls=0;fd_ret=5;
  if(failure==1)allowed=0;
  if(failure==2)chrooted=1;
  if(failure==3)root_ret=-12;
  if(failure==4)strcpy(filename.name,"/system/bin/sh");
  if(failure==5)fd_ret=-24;
  bool session=ksu_handle_execveat_su_session(&fd,&p,&args,&args,&flags);
  CHECK(session==(failure==0||failure==5));
  if(failure==3)CHECK(!strcmp(filename.name,SU_PATH));
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
    for label, old, new in (
        ('failed-exec', 'is_su_session && retval >= 0', 'is_su_session'),
        ('ordinary-exec', 'is_su_session && retval >= 0', 'retval >= 0'),
        ('profile-failure', 'return ret;\n    }\n    memcpy', '(void)0;\n    }\n    memcpy'),
    ):
        if code.count(old) != 1:
            raise RuntimeError(f'Mutation anchor drift: {label}')
        util.compile_run(code.replace(old, new, 1), label, a, root, expect_failure=True)
    util.verify_vfs(a.common)
    kstat = util.compile_run(util.kstat_sources(a.common), 'kstat', a, root)
    record = dict(native=native, kstat=kstat, mutation_rejections=3,
                  vfs_scope_order='passed', runtime_test='not performed')
    (root / 'result.json').write_text(json.dumps(record, indent=2) + '\n')

if __name__ == '__main__':
    main()
