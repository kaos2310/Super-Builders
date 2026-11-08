/* SPDX-License-Identifier: GPL-2.0 */
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <pthread.h>
#include <stdlib.h>
#include "susfs_runtime_abi.h"
#define SUSFS_RUNTIME_TEST 1
#define __user
#define DEFINE_MUTEX(name) pthread_mutex_t name = PTHREAD_MUTEX_INITIALIZER
#define mutex_lock pthread_mutex_lock
#define mutex_unlock pthread_mutex_unlock
#define READ_ONCE(value) __atomic_load_n(&(value), __ATOMIC_ACQUIRE)
#define WRITE_ONCE(value, next) __atomic_store_n(&(value), (next), __ATOMIC_RELEASE)
#define EXPORT_SYMBOL_GPL(name)
#define BUILD_BUG_ON(condition) _Static_assert(!(condition), "build invariant")
#define GLOBAL_ROOT_UID 0U
#define CAP_SYS_ADMIN 21
static int init_user_ns;
static _Thread_local unsigned int real_uid, effective_uid;
static _Thread_local bool capability = true, domain = true, fail_read, fail_write;
static unsigned int current_uid(void) { return real_uid; }
static unsigned int current_euid(void) { return effective_uid; }
static bool uid_eq(unsigned int a, unsigned int b) { return a == b; }
static bool ns_capable(void *ns, int cap) { return ns == &init_user_ns && cap == CAP_SYS_ADMIN && capability; }
static bool susfs_is_current_ksu_domain(void) { return domain; }
static int copy_from_user(void *out, const void *in, unsigned long size) { if (fail_read) return 1; memcpy(out,in,size); return 0; }
static int copy_to_user(void *out, const void *in, unsigned long size) { if (fail_write) return 1; memcpy(out,in,size); return 0; }
#include "susfs_runtime.inc"

static unsigned int checks;
#define CHECK(condition) do { checks++; if (!(condition)) { fprintf(stderr,"failed line %d: %s\n",__LINE__,#condition); exit(1); } } while (0)
static struct susfs_runtime_request request(void) {
    struct susfs_runtime_request r = {0}; r.magic=SUSFS_RUNTIME_MAGIC; r.version=1; r.size=48; r.error=-95; return r;
}
static struct susfs_runtime_request get(void) {
    struct susfs_runtime_request r=request(); CHECK(susfs_runtime_handle(CMD_SUSFS_RUNTIME_GET,&r)==0); CHECK(r.error==0); return r;
}
struct race { unsigned int mask, expected; int result; };
static void *race_set(void *argument) {
    struct race *race=argument; struct susfs_runtime_request r=request();
    r.mask=race->mask; r.values=0; r.expected_generation=race->expected;
    race->result=susfs_runtime_handle(CMD_SUSFS_RUNTIME_SET,&r); return NULL;
}
int main(void) {
    struct susfs_runtime_request r=get(); CHECK(r.supported==EXPECT_SUPPORTED); CHECK(r.enabled==EXPECT_SUPPORTED); CHECK(r.generation==1);
    real_uid=10000; r=request(); CHECK(susfs_runtime_handle(CMD_SUSFS_RUNTIME_GET,&r)==-EPERM); real_uid=0;
    effective_uid=10000; CHECK(susfs_runtime_handle(CMD_SUSFS_RUNTIME_GET,&r)==-EPERM); effective_uid=0;
    capability=false; CHECK(susfs_runtime_handle(CMD_SUSFS_RUNTIME_GET,&r)==-EPERM); capability=true;
    domain=false; CHECK(susfs_runtime_handle(CMD_SUSFS_RUNTIME_GET,&r)==-EPERM); domain=true;
    fail_read=true; CHECK(susfs_runtime_handle(CMD_SUSFS_RUNTIME_GET,&r)==-EFAULT); fail_read=false;
    r=request(); r.version=2; CHECK(susfs_runtime_handle(CMD_SUSFS_RUNTIME_GET,&r)==-EINVAL);
    r=request(); r.size=47; CHECK(susfs_runtime_handle(CMD_SUSFS_RUNTIME_GET,&r)==-EINVAL);
    r=request(); r.reserved=1; CHECK(susfs_runtime_handle(CMD_SUSFS_RUNTIME_GET,&r)==-EINVAL);
    r=request(); r.enabled=1; CHECK(susfs_runtime_handle(CMD_SUSFS_RUNTIME_GET,&r)==-EINVAL);
    r=request(); r.mask=1; CHECK(susfs_runtime_handle(CMD_SUSFS_RUNTIME_GET,&r)==-EINVAL);
    r=request(); CHECK(susfs_runtime_handle(999,&r)==-EOPNOTSUPP);
    r=request(); CHECK(susfs_runtime_handle(CMD_SUSFS_RUNTIME_SET,&r)==-EINVAL);
    r=request(); r.mask=16; r.expected_generation=1; CHECK(susfs_runtime_handle(CMD_SUSFS_RUNTIME_SET,&r)==-EINVAL);
    r=request(); r.mask=1; r.values=2; r.expected_generation=1; CHECK(susfs_runtime_handle(CMD_SUSFS_RUNTIME_SET,&r)==-EINVAL);
    unsigned int bit=EXPECT_SUPPORTED & (0U-EXPECT_SUPPORTED);
    if (bit) {
        r=request(); r.mask=bit; r.expected_generation=0; CHECK(susfs_runtime_handle(CMD_SUSFS_RUNTIME_SET,&r)==-EAGAIN);
        r=request(); r.mask=bit; r.expected_generation=1; fail_write=true;
        CHECK(susfs_runtime_handle(CMD_SUSFS_RUNTIME_SET,&r)==-EFAULT); fail_write=false;
        r=get(); CHECK(r.enabled==EXPECT_SUPPORTED && r.generation==1);
        pthread_t threads[16]; struct race races[16];
        for (int i=0;i<16;i++) { races[i]=(struct race){bit,1,999}; CHECK(pthread_create(&threads[i],NULL,race_set,&races[i])==0); }
        unsigned int successes=0;
        for (int i=0;i<16;i++) { pthread_join(threads[i],NULL); CHECK(races[i].result==0 || races[i].result==-EAGAIN); successes+=races[i].result==0; }
        CHECK(successes==1); r=get(); CHECK(r.enabled==(EXPECT_SUPPORTED & ~bit) && r.generation==2);
        r=request(); r.mask=bit; r.expected_generation=2; CHECK(susfs_runtime_handle(CMD_SUSFS_RUNTIME_SET,&r)==0); CHECK(r.generation==2);
        r=request(); r.mask=bit; r.values=bit; r.expected_generation=2; CHECK(susfs_runtime_handle(CMD_SUSFS_RUNTIME_SET,&r)==0); CHECK(r.enabled==EXPECT_SUPPORTED && r.generation==3);
        susfs_runtime_generation=0xffffffffU; r=request(); r.mask=bit; r.expected_generation=0xffffffffU;
        CHECK(susfs_runtime_handle(CMD_SUSFS_RUNTIME_SET,&r)==-EOVERFLOW); r=get(); CHECK(r.enabled==EXPECT_SUPPORTED);
        CHECK(susfs_runtime_enabled(bit)); CHECK(!susfs_runtime_enabled(16));
    }
    printf("PASS mask=%u checks=%u\n",EXPECT_SUPPORTED,checks); return 0;
}
