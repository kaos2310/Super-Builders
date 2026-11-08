/* SPDX-License-Identifier: GPL-2.0 */
/* Actual userspace parser/transport against actual kernel handler, host shims. */
#define main kernel_tests_main
#include "test_runtime.c"
#undef main
#define SUSFS_HELPER_TEST 1
static char captured[2048];
static unsigned int captured_size, get_calls, set_calls;
static int transport_mode;
static long call4(long nr, long a, long b, long c, long d) {
    if (nr == 1) {
        CHECK(a == 1 && captured_size + (unsigned int)c < sizeof(captured));
        memcpy(captured+captured_size,(void *)b,(unsigned int)c); captured_size+=(unsigned int)c; captured[captured_size]=0; return c;
    }
    CHECK(nr == 169 && a == 0xdeadbeefU && b == 0xfafafafaU);
    if (c == CMD_SUSFS_RUNTIME_GET) get_calls++; else if (c == CMD_SUSFS_RUNTIME_SET) set_calls++; else CHECK(false);
    if (transport_mode == 1) return 0; /* Old dispatcher silently ignores new commands. */
    if (transport_mode == 2) {
        struct susfs_runtime_request *r=(void *)d; r->error=0; r->generation=1; r->magic=99; return 0;
    }
    return susfs_runtime_handle((unsigned int)c,(void *)d);
}
#include "susfs-runtime.c"
static int invoke(int argc, char **argv) { captured_size=0; captured[0]=0; return runtime_main(argc,argv); }
int main(void) {
    unsigned int start=checks;
    susfs_runtime_mask=15; susfs_runtime_generation=1;
    char *status[]={"tool","status"};
    CHECK(invoke(2,status)==0);
    CHECK(strcmp(captured,"{\"protocol\":\"kaoslab-susfs-runtime\",\"version\":1,\"size\":48,\"supported\":15,\"enabled\":15,\"generation\":1}\n")==0);
    char *off[]={"tool","set","hidden-name","0","1"};
    CHECK(invoke(5,off)==0); CHECK(susfs_runtime_mask==13 && susfs_runtime_generation==2); CHECK(strstr(captured,"\"enabled\":13")!=NULL);
    unsigned int before=set_calls;
    CHECK(invoke(5,off)==75 && set_calls==before); /* stale helper preflight never SETs */
    char *same[]={"tool","set","hidden-name","0","2"};
    CHECK(invoke(5,same)==0 && susfs_runtime_generation==2);
    char *on[]={"tool","set","hidden-name","1","2"};
    CHECK(invoke(5,on)==0 && susfs_runtime_mask==15 && susfs_runtime_generation==3);
    before=set_calls; transport_mode=1; CHECK(invoke(5,on)==95 && set_calls==before);
    transport_mode=2; CHECK(invoke(5,on)==95 && set_calls==before);
    transport_mode=0; domain=false; CHECK(invoke(5,on)==95 && set_calls==before); domain=true;
    char *bad[]={"tool","set","symbol-hiding","1","4294967296"};
    before=get_calls; CHECK(invoke(5,bad)==64 && get_calls==before);
    printf("PASS helper/kernel integration checks=%u\n",checks-start); return 0;
}
