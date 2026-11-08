/* Read-only SUSFS gate tracer. Changes child response memory, never kernel state. */
#define _GNU_SOURCE
#include <sys/ptrace.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <sys/uio.h>
#include <stdint.h>
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <stddef.h>
#include <fcntl.h>
#include <sys/prctl.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <linux/audit.h>
#include <asm/unistd.h>
_Static_assert(__NR_reboot==142,"AArch64 reboot number");
_Static_assert(__NR_clone==220,"AArch64 clone number");

#define LD_NR BPF_STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,nr))
#define LD_ARG(N) BPF_STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,args[N]))
#define DENY BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ERRNO|EPERM)
#define ALLOW BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ALLOW)
#define READ_SYSCALL(N) BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,N,0,1), ALLOW
static uint32_t simulate_filter(const struct sock_filter *code,unsigned count,struct seccomp_data *data) {
 uint32_t a=0;
 for(unsigned pc=0;pc<count;pc++) {
  struct sock_filter i=code[pc];
  switch(i.code) {
   case BPF_LD|BPF_W|BPF_ABS:
    if(i.k+4>sizeof(*data))return 0;memcpy(&a,(char*)data+i.k,4);break;
   case BPF_ALU|BPF_AND|BPF_K:a&=i.k;break;
   case BPF_JMP|BPF_JEQ|BPF_K:pc+=a==i.k?i.jt:i.jf;break;
   case BPF_JMP|BPF_JGT|BPF_K:pc+=a>i.k?i.jt:i.jf;break;
   case BPF_RET|BPF_K:return i.k;
   default:return 0;
  }
 }
 return 0;
}
static void filter_tests(const struct sock_filter *code,unsigned count) {
 struct seccomp_data d={.arch=AUDIT_ARCH_AARCH64,.nr=142,.args={0xDEADBEEF,0xFAFAFAFA,0}};
 unsigned tests=0;
 for(unsigned c=0x50000;c<0x70000;c++) {
  d.args[2]=c;int expected=(c==0x555e1||c==0x555e2||c==0x555e3);
  int allowed=simulate_filter(code,count,&d)==SECCOMP_RET_ALLOW;
  if(allowed!=expected)_exit(123);tests++;
 }
 d.nr=56;
 for(unsigned f=0;f<4;f++) {
  d.args[2]=f;
  if((simulate_filter(code,count,&d)==SECCOMP_RET_ALLOW)!=(f==0))_exit(123);tests++;
 }
 int blocked[]={29,117,220,271,38,40,34,35,37};
 for(unsigned n=0;n<sizeof(blocked)/sizeof(blocked[0]);n++) {
  d.nr=blocked[n];if(simulate_filter(code,count,&d)==SECCOMP_RET_ALLOW)_exit(123);tests++;
 }
 fprintf(stderr,"FILTER_SELFTEST cases=%u reboot=142 readonly_commands=3 denied_writes=1\n",tests);
}
static void readonly_filter(void) {
 struct sock_filter code[]={
  BPF_STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,arch)),
  BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,AUDIT_ARCH_AARCH64,1,0),DENY,
  LD_NR,
  /* Kernel-enforced SUSFS read whitelist, independent of the ptrace guard. */
  BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,142,0,10),
  LD_ARG(0), BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,0xDEADBEEF,0,6),
  LD_ARG(1), BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,0xFAFAFAFA,0,4),
  LD_ARG(2),
  BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,0x555e1,3,0),
  BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,0x555e2,2,0),
  BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,0x555e3,1,0),DENY,ALLOW,
  LD_NR,
  /* openat accepts read-only opens; no creation/truncation/appending. */
  BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,56,0,5),LD_ARG(2),
  BPF_STMT(BPF_ALU|BPF_AND|BPF_K,O_ACCMODE|O_CREAT|O_TRUNC|O_APPEND|(O_TMPFILE & ~O_DIRECTORY)),
  BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,0,1,0),DENY,ALLOW,LD_NR,
  /* Writes are limited to inherited stdin/stdout/stderr, never opened files. */
  BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,64,0,4),LD_ARG(0),
  BPF_JUMP(BPF_JMP|BPF_JGT|BPF_K,2,0,1),DENY,ALLOW,LD_NR,
  BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,66,0,4),LD_ARG(0),
  BPF_JUMP(BPF_JMP|BPF_JGT|BPF_K,2,0,1),DENY,ALLOW,LD_NR,
  READ_SYSCALL(17),READ_SYSCALL(23),READ_SYSCALL(25),READ_SYSCALL(43),READ_SYSCALL(44),READ_SYSCALL(48),
  READ_SYSCALL(57),READ_SYSCALL(62),READ_SYSCALL(63),READ_SYSCALL(65),
  READ_SYSCALL(67),READ_SYSCALL(72),READ_SYSCALL(73),READ_SYSCALL(78),READ_SYSCALL(79),READ_SYSCALL(80),
  READ_SYSCALL(93),READ_SYSCALL(94),READ_SYSCALL(96),READ_SYSCALL(98),
  READ_SYSCALL(99),READ_SYSCALL(101),READ_SYSCALL(113),READ_SYSCALL(115),
  READ_SYSCALL(120),READ_SYSCALL(121),READ_SYSCALL(123),READ_SYSCALL(124),
  READ_SYSCALL(132),READ_SYSCALL(134),READ_SYSCALL(135),READ_SYSCALL(139),
  READ_SYSCALL(160),READ_SYSCALL(163),READ_SYSCALL(167),
  READ_SYSCALL(172),READ_SYSCALL(173),READ_SYSCALL(174),READ_SYSCALL(175),
  READ_SYSCALL(176),READ_SYSCALL(177),READ_SYSCALL(178),
  READ_SYSCALL(214),READ_SYSCALL(215),READ_SYSCALL(216),READ_SYSCALL(221),
  READ_SYSCALL(222),READ_SYSCALL(226),READ_SYSCALL(233),READ_SYSCALL(261),
  READ_SYSCALL(278),READ_SYSCALL(291),DENY
 };
 filter_tests(code,sizeof(code)/sizeof(code[0]));
 struct sock_fprog prog={sizeof(code)/sizeof(code[0]),code};
 if(prctl(PR_SET_NO_NEW_PRIVS,1,0,0,0)<0 || prctl(PR_SET_SECCOMP,SECCOMP_MODE_FILTER,&prog)<0) {
  perror("readonly-seccomp");_exit(125);
 }
}

struct arm64_regs { uint64_t r[31], sp, pc, pstate; };
static void fail(const char *text) { perror(text); exit(125); }
static void regs(pid_t pid,struct arm64_regs *r,int write) {
 struct iovec v={r,sizeof(*r)};
 if(ptrace(write?PTRACE_SETREGSET:PTRACE_GETREGSET,pid,(void*)1,&v)<0)fail("regset");
 if(v.iov_len!=sizeof(*r))fail("regset-size");
}
static void copy_bytes(pid_t pid,uintptr_t addr,void *buffer,size_t length,int write) {
 unsigned char *out=buffer;
 for(size_t pos=0;pos<length;pos+=sizeof(long)) {
  size_t n=length-pos<sizeof(long)?length-pos:sizeof(long);
  errno=0;long word=ptrace(PTRACE_PEEKDATA,pid,(void*)(addr+pos),0);
  if(word==-1 && errno)fail("peekdata");
  if(write) {
   memcpy(&word,out+pos,n);
   if(ptrace(PTRACE_POKEDATA,pid,(void*)(addr+pos),(void*)word)<0)fail("pokedata");
  } else memcpy(out+pos,&word,n);
 }
}
int main(int argc,char **argv) {
 if(argc!=3 || strlen(argv[2])>=16) return 124;
 pid_t pid=fork();if(pid<0)fail("fork");
 if(!pid) {
  if(ptrace(PTRACE_TRACEME,0,0,0)<0)fail("traceme");
  raise(SIGSTOP);readonly_filter();
  execl(argv[1],argv[1],"susfs-compat","--check",(char*)0);fail("exec");
 }
 int status,entry=1,blocked=0;unsigned queries=0,features=0,variant=0,denied=0;
 uint64_t command=0,address=0,syscall_nr=0;
 if(waitpid(pid,&status,0)<0)fail("wait-initial");
 if(ptrace(PTRACE_SETOPTIONS,pid,0,(void*)(PTRACE_O_TRACESYSGOOD|PTRACE_O_TRACEEXEC|PTRACE_O_EXITKILL))<0)fail("options");
 while(1) {
  if(ptrace(PTRACE_SYSCALL,pid,0,0)<0)fail("syscall");
  if(waitpid(pid,&status,0)<0)fail("wait");
  if(WIFEXITED(status)) {
   fprintf(stderr,"TRACE_RESULT {\"exit\":%d,\"version_queries\":%u,\"feature_queries\":%u,\"variant_queries\":%u,\"denied_mutations\":%u,\"response_version\":\"%s\"}\n",WEXITSTATUS(status),queries,features,variant,denied,argv[2]);
   return WEXITSTATUS(status);
  }
  if(WIFSIGNALED(status))return 128+WTERMSIG(status);
  if(!WIFSTOPPED(status))continue;
  int sig=WSTOPSIG(status);
  if(sig==(SIGTRAP|0x80)) {
   struct arm64_regs r;regs(pid,&r,0);
   if(entry) {
    syscall_nr=r.r[8];
    command=0;address=0;blocked=0;
    if(r.r[8]==142) { /* AArch64 reboot: ALL commands blocked except the 3 reads. */
     if(r.r[0]==0xDEADBEEF && r.r[1]==0xFAFAFAFA &&
       (r.r[2]==0x555e1 || r.r[2]==0x555e2 || r.r[2]==0x555e3)) {
      command=r.r[2];address=r.r[3];
     } else {r.r[8]=UINT64_MAX;regs(pid,&r,1);blocked=1;denied++;}
    }
    /* This diagnostic command does not need ioctls or process execution. */
    if(r.r[8]==29 || r.r[8]==220) {r.r[8]=UINT64_MAX;regs(pid,&r,1);blocked=1;denied++;}
   } else {
    if((int64_t)r.r[0]==-EPERM)fprintf(stderr,"READONLY_DENIED syscall=%llu\n",(unsigned long long)syscall_nr);
    if(blocked) {r.r[0]=(uint64_t)-EPERM;regs(pid,&r,1);}
    if(command==0x555e1) {
     unsigned char info[20];copy_bytes(pid,address,info,sizeof(info),0);
     int err;memcpy(&err,info+16,4);
     if(err || (int64_t)r.r[0]<0)fail("real-version-query");
     memset(info,0,16);memcpy(info,argv[2],strlen(argv[2]));copy_bytes(pid,address,info,sizeof(info),1);queries++;
    }
    if(command==0x555e2)features++;
    if(command==0x555e3)variant++;
   }
   entry=!entry;
  } else if(sig!=SIGTRAP && sig!=SIGSTOP) {
   /* Fail closed: never continue an unexpected child signal silently. */
   kill(pid,SIGKILL);waitpid(pid,&status,0);return 126;
  }
 }
}
