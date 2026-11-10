/* SPDX-License-Identifier: GPL-2.0 */
/* Kernel boundary fakes for compiling the exact fs/readdir.c implementation. */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#define loff_t int64_t
typedef uint64_t u64;
typedef uint32_t compat_ulong_t;
typedef int32_t compat_long_t;
#define __user
#define EXPORT_SYMBOL(x)
#define __ARCH_WANT_OLD_READDIR 1
#define CONFIG_COMPAT 1
#define CONFIG_KSU_SUSFS_SUS_PATH 1
#define SUSFS_NAME_FILTER_TEST 1
#define PATH_MAX 4096
#define MAY_READ 4
#define ZEROMOUNT_MAGIC_POS ((loff_t)1 << 60)
#define ALIGN(v,a) (((v)+(a)-1)&~((a)-1))
#define unlikely(x) (x)
#define READ_ONCE(x) (x)
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define unsafe_put_user(v,p,label) do { *(p)=(v); } while(0)
#define unsafe_copy_to_user(p,s,n,label) do { memcpy(p,s,n); } while(0)
#define put_user(v,p) ({ *(p)=(v); 0; })
#define copy_to_user(p,s,n) ({ memcpy(p,s,n); 0; })
#define SYSCALL_DEFINE3(n,t,a,u,b,v,c) long sys_##n(t a,u b,v c)
#define COMPAT_SYSCALL_DEFINE3(n,t,a,u,b,v,c) long compat_sys_##n(t a,u b,v c)
struct super_block { int unused; };
struct inode { struct super_block *i_sb; int i_rwsem; bool dead; };
struct qstr { const char *name; unsigned int len; };
struct dentry { struct qstr d_name; struct dentry *d_parent; };
struct path { struct dentry *dentry; };
struct dir_context;
typedef bool (*filldir_t)(struct dir_context *,const char *,int,loff_t,u64,unsigned int);
struct dir_context { filldir_t actor;loff_t pos; };
struct file;
struct file_operations { int (*iterate_shared)(struct file *,struct dir_context *);int (*iterate)(struct file *,struct dir_context *); };
struct file { struct inode *f_inode;struct path f_path;loff_t f_pos;struct file_operations *f_op; };
struct fd { struct file *file; };
struct linux_dirent64 { u64 d_ino;int64_t d_off;unsigned short d_reclen;unsigned char d_type;char d_name[]; };
static struct file *open_file;
static unsigned int test_uid=10155;
static bool marked=true,name_enabled=true;
static int current_storage,rename_lock,rcu_depth,rename_retry;
#define current (&current_storage)
static struct { unsigned int val; } current_uid(void) { __typeof__(current_uid()) x={test_uid};return x; }
static bool susfs_is_current_proc_umounted_app(void) { return marked&&test_uid%100000>=10000; }
static bool susfs_is_hidden_name(const char *name,int length,unsigned int uid) {
 const char registered[]="com.kaoslab.susfstarget";
 return name_enabled&&uid!=10252&&length==(int)sizeof(registered)-1&&!memcmp(name,registered,sizeof(registered)-1);
}
static void rcu_read_lock(void){rcu_depth++;}
static void rcu_read_unlock(void){rcu_depth--;}
static unsigned int read_seqbegin(int *lock){(void)lock;return 0;}
static bool read_seqretry(int *lock,unsigned int seq){(void)lock;(void)seq;if(rename_retry){rename_retry--;return true;}return false;}
static struct inode *file_inode(struct file *file){return file->f_inode;}
static int security_file_permission(struct file *file,int mode){(void)file;(void)mode;return 0;}
static int down_read_killable(int *lock){(void)lock;return 0;}
static int down_write_killable(int *lock){(void)lock;return 0;}
static void inode_unlock(struct inode *node){(void)node;}
static void inode_unlock_shared(struct inode *node){(void)node;}
static void fsnotify_access(struct file *file){(void)file;}
static void file_accessed(struct file *file){(void)file;}
#define IS_DEADDIR(inode) ((inode)->dead)
static struct fd fdget_pos(unsigned int fd){struct fd f={fd==7?open_file:NULL};return f;}
static void fdput_pos(struct fd f){(void)f;}
static bool signal_pending(int *task){(void)task;return false;}
static bool user_write_access_begin(void *p,size_t n){return p&&n<4096;}
static void user_write_access_end(void){}
static struct inode *ilookup(struct super_block *sb,u64 ino){(void)sb;(void)ino;return NULL;}
static bool susfs_is_inode_sus_path(struct inode *inode){(void)inode;return false;}
static void iput(struct inode *inode){(void)inode;}
static void zeromount_inject_dents64(struct file*f,void**p,int*c,loff_t*o){(void)f;(void)p;(void)c;(void)o;}
static void zeromount_inject_dents(struct file*f,void**p,int*c,loff_t*o){(void)f;(void)p;(void)c;(void)o;}
