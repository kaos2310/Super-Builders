#!/usr/bin/env python3
"""Compile the actual filter, parser and worker with host kernel-API mocks.

Tests validate sequential transactions and fault paths, not device concurrency.
"""
from pathlib import Path
import argparse,hashlib,json,re,subprocess,tempfile
import apply as port

PREFIX=r'''
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <errno.h>
#include <stdarg.h>
#include <ctype.h>
#define __user
#define __rcu
#define GFP_KERNEL 0
#define __GFP_ZERO 0
#define SUSFS_LOGE(...) ((void)0)
#define SUSFS_LOGI(...) ((void)0)
#define BITS_TO_LONGS(n) (((n)+63)/64)
#define DEFINE_MUTEX(n) int n
#define mutex_lock(x) ((void)0)
#define mutex_unlock(x) ((void)0)
#define lockdep_is_held(x) 1
#define rcu_dereference_protected(p,l) (p)
#define rcu_dereference(p) (p)
#define rcu_assign_pointer(p,v) ((p)=(v))
#define likely(x) (x)
#define IS_ERR(x) ((uintptr_t)(x)>=(uintptr_t)-4095)
struct rcu_head { int unused; };
static int grace_periods,copy_fault,domain_fault,restores,alloc_count,fail_alloc,thread_count,thread_fault;
static void synchronize_rcu(void) {grace_periods++;}
#define kfree_rcu(p,f) free(p)
#define kfree(p) free(p)
#define kvfree(p) free(p)
static void *zalloc(size_t n,int flags) {alloc_count++;return fail_alloc==alloc_count?NULL:calloc(1,n);}
#define kzalloc zalloc
#define kvmalloc zalloc
typedef struct {int counter;} atomic_t;
#define ATOMIC_INIT(n) {n}
static int atomic_cmpxchg(atomic_t *a,int old,int value) {int prev=a->counter;if(prev==old)a->counter=value;return prev;}
static void atomic_set(atomic_t *a,int v) {a->counter=v;}
static void *kthread_run(int(*fn)(void*),void *data,const char *name) {thread_count++;return thread_fault?(void*)-ENOMEM:(void*)1;}
static int copy_from_user(void *d,const void *s,size_t n) {if(copy_fault)return 1;memcpy(d,s,n);return 0;}
static int copy_to_user(void *d,const void *s,size_t n) {memcpy(d,s,n);return 0;}
static void set_bit(unsigned bit,unsigned long *bits) {bits[bit/64]|=1UL<<(bit%64);}
static int test_bit(unsigned bit,unsigned long *bits) {return !!(bits[bit/64]&(1UL<<(bit%64)));}
static char *strim(char *s) {while(isspace((unsigned char)*s))s++;char *e=s+strlen(s);while(e>s&&isspace((unsigned char)e[-1]))*--e=0;return s;}
static int scnprintf(char *out,size_t n,const char *fmt,...) {va_list ap;va_start(ap,fmt);int ret=vsnprintf(out,n,fmt,ap);va_end(ap);return ret;}
struct cred {int unused;};static struct cred mock_cred;
static struct cred *susfs_switch_to_ksu_domain(void) {return domain_fault?NULL:&mock_cred;}
static void susfs_restore_creds(struct cred *c) {restores++;}
static unsigned one_uid=10001,two_uid=11002;static int one_missing;
struct path {unsigned uid;};struct kstat {unsigned uid;};
#define LOOKUP_FOLLOW 0
#define STATX_BASIC_STATS 0
static int init_user_ns;
static int kern_path(const char *name,int flags,struct path *p) {
 if(!strcmp(name,"/data/data/com.one")&&!one_missing)p->uid=one_uid;
 else if(!strcmp(name,"/data/data/com.two"))p->uid=two_uid;
 else if(!strcmp(name,"/data/data/com.big"))p->uid=20000;
 else return -ENOENT;
 return 0;
}
static int vfs_getattr(struct path *p,struct kstat *st,int mask,int flags) {st->uid=p->uid;return 0;}
static void path_put(struct path *p) {}
static unsigned from_kuid(int *ns,unsigned uid) {return uid;}
'''

CHECKS=r'''
#define CHECK(x) do { if(!(x)){fprintf(stderr,"line %d: %s\n",__LINE__,#x);return 1;} } while(0)
static int set_list(const char *list) {
 struct st_susfs_priority_uid_filter info={0};strcpy(info.app_strings,list);info.err=123;
 void *p=&info;susfs_set_priority_uid_filter(&p);return info.err;
}
int main(void) {
 CHECK(!susfs_is_priority_uid_filtered(10001));
 CHECK(set_list(" com.one ,, com.two ")==0);
 CHECK(grace_periods==1 && restores==1 && susfs_is_priority_uid_filtered(10001) && susfs_is_priority_uid_filtered(11002));
 CHECK(susfs_is_priority_uid_filtered(110001) && !susfs_is_priority_uid_filtered(9999) && !susfs_is_priority_uid_filtered(20000));
 CHECK(set_list("com.two")==0 && !susfs_is_priority_uid_filtered(10001) && susfs_is_priority_uid_filtered(11002));
 CHECK(set_list("com.one,com.missing")==-ENOENT && !susfs_is_priority_uid_filtered(10001) && susfs_is_priority_uid_filtered(11002));
 CHECK(set_list("../etc")==-EINVAL && set_list("com.big")==-EINVAL && set_list("")==-EINVAL);
 CHECK(!susfs_is_valid_app_name(".") && !susfs_is_valid_app_name("..") && !susfs_is_valid_app_name("com/one") && !susfs_is_valid_app_name("com;one"));
 struct st_susfs_priority_uid_filter bad;memset(&bad,'x',sizeof(bad));void *p=&bad;
 susfs_set_priority_uid_filter(&p);CHECK(bad.err==-EINVAL);
 copy_fault=1;CHECK(set_list("com.one")==-EFAULT);copy_fault=0;
 domain_fault=1;CHECK(set_list("com.one")==-EINVAL);domain_fault=0;
 for(int i=1;i<=3;i++){alloc_count=0;fail_alloc=i;CHECK(set_list("com.one")==-ENOMEM && susfs_is_priority_uid_filtered(11002));}fail_alloc=0;
 CHECK(set_list("com.one,com.two")==0);one_uid=10042;two_uid=11043;
 int before=grace_periods;CHECK(susfs_priority_app_strings_worker(NULL)==0);
 CHECK(grace_periods==before+1 && susfs_is_priority_uid_filtered(10042) && susfs_is_priority_uid_filtered(11043) && !susfs_is_priority_uid_filtered(10001));
 one_missing=1;CHECK(susfs_priority_app_strings_worker(NULL)==0 && !susfs_is_priority_uid_filtered(10042) && susfs_is_priority_uid_filtered(11043));
 susfs_parse_priority_app_strings();CHECK(thread_count==1 && susfs_priority_app_strings_running.counter==1);
 susfs_parse_priority_app_strings();CHECK(thread_count==1);
 susfs_priority_app_strings_worker(NULL);thread_fault=1;susfs_parse_priority_app_strings();CHECK(susfs_priority_app_strings_running.counter==0);
 CHECK(set_list(" , , ")==0 && !susfs_is_priority_uid_filtered(11043));
 return 0;
}
'''

def test(common,ksu):
    state=port.verify(common,ksu)
    text=(common/'fs/susfs.c').read_text()
    section=text[text.index('/* priority uid filter */'):text.index('/* susfs avc log spoofing */')]
    defs=(common/'include/linux/susfs_def.h').read_text()
    constants='\n'.join(line for line in defs.splitlines() if re.match(r'#define (?:SUSFS_PRIORITY_UID_FILTER_|SUSFS_APP_STR_BUF_SIZE)',line))+'\n'
    header=(common/'include/linux/susfs.h').read_text()
    struct=re.search(r'struct st_susfs_priority_uid_filter \{.*?\n\};',header,re.S)[0]
    code=PREFIX+constants+struct+'\n'+section+CHECKS
    variants={'production':code}
    for name,old,new in (
        ('multiuser-normalization','uid % 100000','uid'),
        ('rcu-grace-period','synchronize_rcu();','((void)0);'),
        ('transaction-on-error','if (err)\n\t\tgoto out_free_new_bitmap;','if (false)\n\t\tgoto out_free_new_bitmap;'),
        ('missing-reentrancy-guard','if (atomic_cmpxchg(&susfs_priority_app_strings_running, 0, 1))','if (false)'),
        ('unterminated-input',"if (!memchr(info->app_strings, '\\0', sizeof(info->app_strings)))",'if (false)'),
    ):
        if old not in code:raise RuntimeError('Filter mutation anchor changed: '+name)
        # The unterminated mutation is checked statically rather than executing unsafe strlen.
        if name=='unterminated-input':continue
        variants[name]=code.replace(old,new)
    results={}
    with tempfile.TemporaryDirectory(prefix='susfs-priority-') as tmp:
        for name,value in variants.items():
            src=Path(tmp)/(name+'.c');binary=Path(tmp)/name;src.write_text(value)
            subprocess.run(['gcc','-std=gnu11','-Werror=implicit-function-declaration',str(src),'-o',str(binary)],check=True)
            p=subprocess.run([str(binary)],capture_output=True,text=True)
            if (p.returncode==0)!=(name=='production'):raise RuntimeError('Filter semantic control failed '+name+': '+p.stderr)
            results[name]=p.returncode
    return {'priority_filter_semantics_passed':True,'negative_controls_rejected':4,'tests':results,'upstream_commit':state['upstream_commit'],'all_four_syscall_hooks_verified':True,'package_refresh_after_throne_verified':True,'replacement_and_failed_transaction_tested':True,'reinstall_uninstall_refresh_tested':True,'allocation_copy_domain_faults_tested':True,'concurrency_tested':False,'device_tested':False}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--common',type=Path,required=True);p.add_argument('--ksu',type=Path,required=True);p.add_argument('--receipt',type=Path);a=p.parse_args();result=test(a.common,a.ksu)
    if a.receipt:a.receipt.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
