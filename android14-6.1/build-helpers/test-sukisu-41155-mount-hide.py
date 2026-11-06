#!/usr/bin/env python3
"""Exercise exact mount callback selection and seq filtering with kernel mocks."""
from pathlib import Path
import argparse,re,subprocess,tempfile,json
def function(text,name):
    start=text.index('static int __nocfi '+name+'(')
    brace=text.index('{',start);pos=brace+1;depth=1
    # These two bounded functions contain no braces inside strings/comments.
    while depth:
        depth+=(text[pos]=='{')-(text[pos]=='}');pos+=1
    return text[start:pos]
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ksu',required=True,type=Path);p.add_argument('--common',required=True,type=Path);p.add_argument('--receipt',type=Path);a=p.parse_args()
    source=(a.ksu/'kernel/feature/mount_hide.c').read_text()
    for name in ('susfs_show_vfsmnt','susfs_show_mountinfo','susfs_show_vfsstat'):
        assert '"'+name+'"' in source
    native=(a.common/'fs/mount.h').read_text()
    fields=lambda text,name:re.sub(r'\s+','',re.search(r'struct '+name+r'\s*\{(.*?)\};',text,re.S)[1]).split(';')[:3]
    assert fields(native,'proc_mounts')==fields(source,'ksu_proc_mounts'),'private proc_mounts prefix mismatch'
    for name in ('susfs_show_vfsmnt','susfs_show_mountinfo','susfs_show_vfsstat'):
        assert 'mounts_open_common(inode, file, '+name+')' in (a.common/'fs/proc_namespace.c').read_text()
    callback=function(source,'ksu_install_filter');filter_fn=function(source,'ksu_filter_show')
    harness=r'''
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <assert.h>
#define __nocfi
#define pr_warn_once(...) do {} while(0)
struct vfsmount {bool hidden;};
struct seq_file {void *private;char *buf;size_t count;bool overflow;};
struct file {void *private_data;};
typedef int (*ksu_show_fn)(struct seq_file *,struct vfsmount *);
struct ksu_proc_mounts {void *ns;void *root;ksu_show_fn show;};
#define FN(n) static int n(struct seq_file*m,struct vfsmount*v){return 0;}
FN(base1) FN(base2) FN(base3) FN(sus1) FN(sus2) FN(sus3) FN(other)
FN(ksu_show_vfsmnt) FN(ksu_show_mountinfo) FN(ksu_show_vfsstat)
FN(ksu_show_susfs_vfsmnt) FN(ksu_show_susfs_mountinfo) FN(ksu_show_susfs_vfsstat)
static ksu_show_fn ksu_orig_show_vfsmnt=base1,ksu_orig_show_mountinfo=base2,ksu_orig_show_vfsstat=base3;
static ksu_show_fn ksu_orig_susfs_show_vfsmnt=sus1,ksu_orig_susfs_show_mountinfo=sus2,ksu_orig_susfs_show_vfsstat=sus3;
static bool seq_has_overflowed(struct seq_file*m){return m->overflow;}
static bool ksu_region_has_marker(const char*s,size_t len){return len>=6 && memcmp(s,"magisk",6)==0;}
static bool ksu_region_has_mount_list(const char*s,size_t len){return false;}
static bool ksu_mnt_root_hidden(struct vfsmount*v){return v->hidden;}
static int result;
static int render(struct seq_file*m,struct vfsmount*v){m->count+=6;return result;}
CALLBACK
FILTER
int main(void){
 struct ksu_proc_mounts p={0};struct seq_file m={.private=&p};struct file f={.private_data=&m};
 ksu_show_fn bases[]={base1,base2,base3},filters[]={ksu_show_vfsmnt,ksu_show_mountinfo,ksu_show_vfsstat};
 ksu_show_fn sus[]={sus1,sus2,sus3},sus_filters[]={ksu_show_susfs_vfsmnt,ksu_show_susfs_mountinfo,ksu_show_susfs_vfsstat};
 for(int i=0;i<3;i++){
  p.show=bases[i];ksu_install_filter(&f,bases[i],filters[i]);assert(p.show==filters[i]);
  p.show=sus[i];ksu_install_filter(&f,bases[i],filters[i]);
#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
  assert(p.show==sus_filters[i]);
#else
  assert(p.show==sus[i]);
#endif
  p.show=sus[(i+1)%3];ksu_install_filter(&f,bases[i],filters[i]);assert(p.show==sus[(i+1)%3]);
  p.show=other;ksu_install_filter(&f,bases[i],filters[i]);assert(p.show==other);
 }
 struct vfsmount v={0};char buffer[32]="prefixmagisk";m.buf=buffer;m.count=6;
 assert(ksu_filter_show(&m,&v,render)==0 && m.count==6);
 strcpy(buffer,"prefixstock!");m.count=6;ksu_filter_show(&m,&v,render);assert(m.count==12);
 v.hidden=true;m.count=6;ksu_filter_show(&m,&v,render);assert(m.count==6);
 v.hidden=false;strcpy(buffer,"prefixmagisk");m.overflow=true;m.count=6;ksu_filter_show(&m,&v,render);assert(m.count==12);
 m.overflow=false;result=7;m.count=6;assert(ksu_filter_show(&m,&v,render)==7 && m.count==12);
 return 0;
}
'''
    with tempfile.TemporaryDirectory() as d:
        work=Path(d)
        def test(label,callback_text,filter_text,enabled,expected=True):
            c=work/(label+'.c');c.write_text(harness.replace('CALLBACK',callback_text).replace('FILTER',filter_text));exe=work/label
            cmd=['gcc','-Werror=implicit-function-declaration','-o',str(exe),str(c)]+(['-DCONFIG_KSU_SUSFS_SUS_MOUNT'] if enabled else [])
            subprocess.run(cmd,check=True,capture_output=True)
            out=subprocess.run([str(exe)],capture_output=True)
            assert (out.returncode==0)==expected,label
        test('susfs-on',callback,filter_fn,True);test('susfs-off',callback,filter_fn,False)
        test('missing-susfs-branch',callback.replace('p->show == ksu_orig_susfs_show_vfsmnt','p->show == other'),filter_fn,True,False)
        test('cross-file-misclassification',callback.replace('p->show == ksu_orig_susfs_show_vfsmnt','p->show != ksu_orig_susfs_show_vfsmnt'),filter_fn,True,False)
        test('overflow-erasure',callback,filter_fn.replace('if (seq_has_overflowed(m))','if (false)'),True,False)
    report={'callback_modes_passed':2,'negative_controls_rejected':3,'private_proc_mounts_prefix_matches':True,'exact_source_functions_tested':True,'runtime_device_tested':False}
    if a.receipt:a.receipt.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
if __name__=='__main__':main()
