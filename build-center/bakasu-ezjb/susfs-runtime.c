/* SPDX-License-Identifier: GPL-2.0 */
/* Freestanding Android arm64 executable: no linker/interpreter/libc dependency. */
#include "susfs_runtime_abi.h"
_Static_assert(sizeof(struct susfs_runtime_request) == SUSFS_RUNTIME_SIZE, "ABI size");

#ifdef SUSFS_HELPER_TEST
#define NR_WRITE 1
#define NR_EXIT 60
#define NR_REBOOT 169
#elif defined(__aarch64__)
static long call4(long nr, long a, long b, long c, long d)
{
    register long x8 __asm__("x8") = nr;
    register long x0 __asm__("x0") = a;
    register long x1 __asm__("x1") = b;
    register long x2 __asm__("x2") = c;
    register long x3 __asm__("x3") = d;
    __asm__ volatile("svc #0" : "+r"(x0) : "r"(x8), "r"(x1), "r"(x2), "r"(x3) : "memory");
    return x0;
}
#define NR_WRITE 64
#define NR_EXIT 93
#define NR_REBOOT 142
__asm__(".global _start\n_start:\n mov x0, sp\n bl runtime_entry\n brk #0\n");
#elif defined(__x86_64__)
static long call4(long nr, long a, long b, long c, long d)
{
    register long r10 __asm__("r10") = d;
    long result;
    __asm__ volatile("syscall" : "=a"(result) : "a"(nr), "D"(a), "S"(b), "d"(c), "r"(r10) : "rcx", "r11", "memory");
    return result;
}
#define NR_WRITE 1
#define NR_EXIT 60
#define NR_REBOOT 169
__asm__(".global _start\n_start:\n mov %rsp,%rdi\n and $-16,%rsp\n call runtime_entry\n ud2\n");
#else
#error Unsupported architecture
#endif

static unsigned int length(const char *s) { unsigned int n = 0; while (s[n]) n++; return n; }
static int equal(const char *a, const char *b) { while (*a && *a == *b) { a++; b++; } return *a == *b; }
static void put(const char *s) {
    unsigned int left = length(s);
    while (left) { long n = call4(NR_WRITE, 1, (long)s, left, 0); if (n == -4) continue; if (n <= 0) return; s += n; left -= (unsigned int)n; }
}
static void number(__u32 value) { char text[11]; unsigned int n = 10; text[n] = 0; do { text[--n] = '0' + value % 10; value /= 10; } while (value); put(text + n); }
static int parse(const char *s, __u32 *value) {
    __u32 n = 0;
    if (!*s) return 0;
    while (*s) { unsigned int digit = (unsigned int)(*s++ - '0'); if (digit > 9 || n > (0xffffffffU - digit) / 10) return 0; n = n * 10 + digit; }
    *value = n; return 1;
}
static unsigned int feature(const char *name) {
    if (equal(name, "uid-gating")) return SUSFS_RT_UID_GATE;
    if (equal(name, "hidden-name")) return SUSFS_RT_HIDDEN_NAME;
    if (equal(name, "unicode-filter")) return SUSFS_RT_UNICODE;
    if (equal(name, "symbol-hiding")) return SUSFS_RT_SYMBOLS;
    return 0;
}
static int exchange(__u32 command, struct susfs_runtime_request *request) {
    request->magic = SUSFS_RUNTIME_MAGIC; request->version = SUSFS_RUNTIME_VERSION;
    request->size = SUSFS_RUNTIME_SIZE; request->error = -95;
    long rc = call4(NR_REBOOT, 0xdeadbeefU, 0xfafafafaU, command, (long)request);
    if (rc != 0 || request->error != 0 || request->magic != SUSFS_RUNTIME_MAGIC ||
        request->version != SUSFS_RUNTIME_VERSION || request->size != SUSFS_RUNTIME_SIZE ||
        (request->supported & ~SUSFS_RT_ALL) || (request->enabled & ~request->supported) ||
        request->reserved || request->reserved2 || !request->generation) return 0;
    return 1;
}
int runtime_main(long argc, char **argv) {
    struct susfs_runtime_request state = {0};
    __u32 bit = 0, enabled = 0, generation = 0;
    int setting = argc == 5 && equal(argv[1], "set");
    if (!(argc == 2 && equal(argv[1], "status")) && !setting) {
        put("usage: susfs-runtime status | set uid-gating|hidden-name|unicode-filter|symbol-hiding 0|1 EXPECTED_GENERATION\n"); return 64;
    }
    if (setting && (!(bit = feature(argv[2])) || !parse(argv[3], &enabled) || enabled > 1 || !parse(argv[4], &generation) || !generation)) {
        put("invalid runtime setting\n"); return 64;
    }
    if (!exchange(CMD_SUSFS_RUNTIME_GET, &state)) {
        put("runtime ABI v1 unavailable or access denied; no setter issued\n"); return 95;
    }
    if (setting) {
        if (!(state.supported & bit) || state.generation != generation) { put("unsupported feature or stale generation; no setter issued\n"); return 75; }
        struct susfs_runtime_request update = {0};
        update.mask = bit; update.values = enabled ? bit : 0; update.expected_generation = generation;
        if (!exchange(CMD_SUSFS_RUNTIME_SET, &update)) { put("runtime update unconfirmed; read status before another attempt\n"); return 75; }
        if ((update.enabled & bit) != update.values || (update.enabled & ~bit) != (state.enabled & ~bit)) {
            put("unexpected runtime response\n"); return 75;
        }
        state = update;
    }
    put("{\"protocol\":\"kaoslab-susfs-runtime\",\"version\":1,\"size\":48,\"supported\":"); number(state.supported);
    put(",\"enabled\":"); number(state.enabled); put(",\"generation\":"); number(state.generation); put("}\n"); return 0;
}
__attribute__((noreturn)) void runtime_entry(long *stack) {
    int code = runtime_main(stack[0], (char **)(stack + 1));
    call4(NR_EXIT, code, 0, 0, 0); __builtin_unreachable();
}
