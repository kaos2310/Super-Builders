/* SPDX-License-Identifier: GPL-2.0 */
/* Included by fs/susfs.c; existing authorization and consumer rules remain. */
#ifndef SUSFS_RUNTIME_TEST
#include <linux/susfs_runtime.h>
#include <linux/capability.h>
#include <linux/user_namespace.h>
#endif

#ifdef CONFIG_KSU_SUSFS_UID_GATED_HIDING
#define RT_HAVE_UID SUSFS_RT_UID_GATE
#else
#define RT_HAVE_UID 0U
#endif
#ifdef CONFIG_KSU_SUSFS_HIDDEN_NAME
#define RT_HAVE_NAME SUSFS_RT_HIDDEN_NAME
#else
#define RT_HAVE_NAME 0U
#endif
#ifdef CONFIG_KSU_SUSFS_UNICODE_FILTER
#define RT_HAVE_UNICODE SUSFS_RT_UNICODE
#else
#define RT_HAVE_UNICODE 0U
#endif
#ifdef CONFIG_KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS
#define RT_HAVE_SYMBOLS SUSFS_RT_SYMBOLS
#else
#define RT_HAVE_SYMBOLS 0U
#endif
#define RT_SUPPORTED (RT_HAVE_UID | RT_HAVE_NAME | RT_HAVE_UNICODE | RT_HAVE_SYMBOLS)

static DEFINE_MUTEX(susfs_runtime_lock);
static unsigned int susfs_runtime_mask = RT_SUPPORTED;
static unsigned int susfs_runtime_generation = 1U;

bool susfs_runtime_enabled(unsigned int bit)
{
    return (READ_ONCE(susfs_runtime_mask) & bit) != 0;
}
EXPORT_SYMBOL_GPL(susfs_runtime_enabled);

int susfs_runtime_handle(unsigned int command, void __user *argument)
{
    struct susfs_runtime_request request;
    unsigned int next_mask, next_generation;
    int result = 0;

    BUILD_BUG_ON(sizeof(request) != SUSFS_RUNTIME_SIZE);
    /* Real/effective global root, init-userns capability and the su domain. */
    if (!uid_eq(current_uid(), GLOBAL_ROOT_UID) ||
        !uid_eq(current_euid(), GLOBAL_ROOT_UID) ||
        !ns_capable(&init_user_ns, CAP_SYS_ADMIN) ||
        !susfs_is_current_ksu_domain())
        return -EPERM;
    if (copy_from_user(&request, argument, sizeof(request)))
        return -EFAULT;
    if (request.magic != SUSFS_RUNTIME_MAGIC ||
        request.version != SUSFS_RUNTIME_VERSION ||
        request.size != sizeof(request) || request.reserved || request.reserved2 ||
        request.supported || request.enabled || request.generation)
        return -EINVAL;
    if (command != CMD_SUSFS_RUNTIME_GET && command != CMD_SUSFS_RUNTIME_SET)
        return -EOPNOTSUPP;
    if (command == CMD_SUSFS_RUNTIME_GET &&
        (request.mask || request.values || request.expected_generation))
        return -EINVAL;
    if (command == CMD_SUSFS_RUNTIME_SET &&
        (!request.mask || (request.mask & ~RT_SUPPORTED) ||
         (request.values & ~request.mask)))
        return -EINVAL;

    mutex_lock(&susfs_runtime_lock);
    next_mask = susfs_runtime_mask;
    next_generation = susfs_runtime_generation;
    if (command == CMD_SUSFS_RUNTIME_SET) {
        if (request.expected_generation != next_generation) {
            result = -EAGAIN;
            goto unlock;
        }
        next_mask = (next_mask & ~request.mask) | request.values;
        if (next_mask != susfs_runtime_mask) {
            if (next_generation == 0xffffffffU) {
                result = -EOVERFLOW;
                goto unlock;
            }
            next_generation++;
        }
    }
    request.supported = RT_SUPPORTED;
    request.enabled = next_mask;
    request.generation = next_generation;
    request.error = 0;
    /* An unwritable response buffer must never commit a state change. */
    if (copy_to_user(argument, &request, sizeof(request))) {
        result = -EFAULT;
        goto unlock;
    }
    WRITE_ONCE(susfs_runtime_mask, next_mask);
    susfs_runtime_generation = next_generation;
unlock:
    mutex_unlock(&susfs_runtime_lock);
    return result;
}
EXPORT_SYMBOL_GPL(susfs_runtime_handle);
