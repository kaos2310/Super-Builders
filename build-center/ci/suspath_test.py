"""Exact-C checks for the new SUS_PATH bitmap, UID gate and native dispatcher."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess


def definition(source,name):
    masked=re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
                  lambda m:re.sub(r'[^\n]',' ',m[0]),source,flags=re.S)
    matches=list(re.finditer(r'^(?:__attribute__\(\(hot\)\)\s+)?(?:static\s+)?(?:bool|void|int)\s+'
                            +re.escape(name)+r'\([^;{}]*?\)\s*\{',masked,re.M))
    if len(matches)!=1:raise RuntimeError('Expected one SUS_PATH definition: '+name)
    match=matches[0];pos=match.end();depth=1
    while depth and pos<len(masked):depth+=(masked[pos]=='{')-(masked[pos]=='}');pos+=1
    if depth:raise RuntimeError('Unbalanced SUS_PATH function')
    return source[match.start():pos]


PREFIX=r'''
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>
#define CONFIG_KSU_SUSFS_UID_GATED_HIDING 1
#define CONFIG_KSU_SUSFS_SUS_PATH 1
#define SUSFS_RT_UID_GATE 1
#define __rcu
#define likely(x) (x)
#define unlikely(x) (x)
#define SUSFS_LOGE(...) ((void)0)
#define SUSFS_LOGI(...) ((void)0)
#define BITS_TO_LONGS(n) (((n)+63)/64)
#define FUSE_SUPER_MAGIC 0x65735546
#define AS_FLAGS_SUS_PATH 1
static unsigned int mock_uid;
typedef struct { unsigned int val; } kuid_t;
static kuid_t current_uid(void) { return (kuid_t){mock_uid}; }
static bool runtime_enabled=true;
static bool susfs_runtime_enabled(unsigned int bit) { return runtime_enabled; }
struct rcu_head { int unused; };
static int rcu_depth;
static void rcu_read_lock(void) { ++rcu_depth; }
static void rcu_read_unlock(void) { --rcu_depth; }
#define rcu_dereference(x) (x)
static bool test_bit(unsigned int bit,const unsigned long *bits) { return !!(bits[bit/64] & (1UL<<(bit%64))); }
struct address_space { unsigned long flags; };
struct super_block { unsigned long s_magic; };
struct inode { struct address_space *i_mapping; struct super_block *i_sb; unsigned long i_ino; };
struct fuse_inode { struct inode inode; };
static struct fuse_inode mock_fuse;
static bool fuse_exists=true;
static struct fuse_inode *get_fuse_inode(struct inode *inode) { return fuse_exists?&mock_fuse:NULL; }
'''

CHECKS=r'''
#define CHECK(x) do { if(!(x)){fprintf(stderr,"line %d: %s\n",__LINE__,#x);return 1;} } while(0)
int main(void) {
 struct address_space mapping={1UL<<AS_FLAGS_SUS_PATH};
 struct super_block sb={0};struct inode inode={&mapping,&sb,42};
 static struct susfs_sus_path_uid_filter_bitmap bitmap={0};
 sus_path_uid_filter_bitmap=&bitmap;
 mock_uid=10001;CHECK(susfs_is_inode_sus_path(&inode));CHECK(rcu_depth==0);
 bitmap.bits[(10002-SUSFS_UID_FILTER_MIN_UID)/64]|=1UL<<((10002-SUSFS_UID_FILTER_MIN_UID)%64);
 mock_uid=10002;CHECK(!susfs_is_inode_sus_path(&inode));CHECK(rcu_depth==0);
 mock_uid=110001;CHECK(susfs_is_inode_sus_path(&inode));CHECK(rcu_depth==0);
 mock_uid=110002;CHECK(!susfs_is_inode_sus_path(&inode));CHECK(rcu_depth==0);
 mock_uid=0;CHECK(!susfs_is_inode_sus_path(&inode));
 mock_uid=1000;CHECK(!susfs_is_inode_sus_path(&inode));
 mock_uid=100000;CHECK(!susfs_is_inode_sus_path(&inode));
 mock_uid=(unsigned int)-1;CHECK(!susfs_is_inode_sus_path(&inode));
 mock_uid=90001;CHECK(!susfs_is_inode_sus_path(&inode));
 mock_uid=10001;mapping.flags=0;CHECK(!susfs_is_inode_sus_path(&inode));
 mapping.flags=1UL<<AS_FLAGS_SUS_PATH;inode.i_mapping=NULL;CHECK(!susfs_is_inode_sus_path(&inode));
 inode.i_mapping=&mapping;sb.s_magic=FUSE_SUPER_MAGIC;mock_fuse.inode=inode;
 CHECK(susfs_is_inode_sus_path(&inode));CHECK(rcu_depth==0);
 fuse_exists=false;CHECK(!susfs_is_inode_sus_path(&inode));
 fuse_exists=true;mock_fuse.inode.i_mapping=NULL;CHECK(!susfs_is_inode_sus_path(&inode));
 runtime_enabled=false;mock_uid=0;CHECK(!susfs_is_inode_sus_path(&inode));
 CHECK(rcu_depth==0);return 0;
}
'''


def test(common,ksu,output):
    output.mkdir(parents=True,exist_ok=True)
    defs=(common/'include/linux/susfs_def.h').read_text()
    if 'CMD_SUSFS_SET_SUS_PATH_UID_FILTER' not in defs:return {'feature_present':False}
    source=(common/'fs/susfs.c').read_text()
    functions={name:definition(source,name) for name in ('susfs_is_inode_sus_path','susfs_is_uid_allowed_for_sus_path')}
    constants='\n'.join(re.search(r'^#define '+name+r' .*$',defs,re.M)[0] for name in
                        ('SUSFS_UID_FILTER_MIN_UID','SUSFS_UID_FILTER_MAX_UID','SUSFS_UID_FILTER_UID_NUM','SUSFS_UID_FILTER_BITMAP_LEN'))+'\n'
    structure=re.search(r'^struct susfs_sus_path_uid_filter_bitmap \{.*?^\};',source,re.S|re.M)[0]
    header=re.sub(r'^#include[^\n]*\n','',(common/'include/linux/susfs_uid_gate.h').read_text(),flags=re.M)
    code=PREFIX+header+constants+structure+'\nstatic struct susfs_sus_path_uid_filter_bitmap *sus_path_uid_filter_bitmap;\n'
    code+=functions['susfs_is_uid_allowed_for_sus_path']+'\n'+functions['susfs_is_inode_sus_path']+CHECKS
    variants={'production':code}
    for name,old,new in [('multiuser','current_uid().val % 100000','current_uid().val'),
                         ('uid-gate','if (!susfs_uid_gate_current())','if (false)'),
                         ('bitmap','test_bit(uid - SUSFS_UID_FILTER_MIN_UID, bitmap->bits)','false'),
                         ('rcu','rcu_read_unlock();','((void)0);')]:
        if old not in code:raise RuntimeError('SUS_PATH negative-control anchor changed: '+name)
        variants[name]=code.replace(old,new)
    results={}
    for name,value in variants.items():
        path=output/(name+'.c');path.write_text(value);binary=path.with_suffix('')
        compile=subprocess.run(['cc','-std=gnu11','-O1','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-unused-function',str(path),'-o',str(binary)],capture_output=True,text=True)
        if compile.returncode:raise RuntimeError(compile.stderr)
        run=subprocess.run([str(binary)],capture_output=True,text=True)
        if (run.returncode==0)!=(name=='production'):raise RuntimeError('SUS_PATH semantic control failed: '+name+' '+run.stderr)
        results[name]=run.returncode
    dispatch=(ksu/'kernel/supercall/dispatch.c').read_text()
    case=re.search(r'#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n    case CMD_SUSFS_SET_SUS_PATH_UID_FILTER: \{.*?\n#endif',dispatch,re.S)[0]
    for enabled in (0,1):
        text=('#define CMD_SUSFS_SET_SUS_PATH_UID_FILTER 0x55554\n'+('#define CONFIG_KSU_SUSFS_SUS_PATH 1\n' if enabled else '')+
              'static int calls;static void susfs_set_sus_path_uid_filter(void **arg){++calls;}\n'
              'static int dispatch(unsigned int cmd,void **arg){switch(cmd){\n'+case+'\ndefault:return -25;}}\n'+
              f'int main(void){{void *arg=0;int result=dispatch(0x55554,&arg);return result!={0 if enabled else -25}||calls!={enabled};}}\n')
        path=output/f'dispatch-{enabled}.c';path.write_text(text);binary=path.with_suffix('')
        subprocess.run(['cc','-std=gnu11',str(path),'-o',str(binary)],check=True)
        subprocess.run([str(binary)],check=True)
    result={'feature_present':True,'exact_suspath_c_passed':True,'negative_controls_rejected':4,'native_dispatch_configurations':2,
            'multiuser_bitmap_uid_gate_fuse_and_invalid_uid_tested':True,'rcu_balanced':True,
            'functions_sha256':{name:hashlib.sha256(value.encode()).hexdigest() for name,value in functions.items()},
            'results':results,'kernel_boundary_fakes':True,'device_runtime_tested':False}
    (output/'TESTS.json').write_text(json.dumps(result,indent=2)+'\n');return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--common',type=Path,required=True);parser.add_argument('--ksu',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(test(args.common,args.ksu,args.output),indent=2))
