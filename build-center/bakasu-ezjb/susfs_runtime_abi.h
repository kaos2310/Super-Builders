/* SPDX-License-Identifier: GPL-2.0 */
#ifndef SUSFS_RUNTIME_ABI_H
#define SUSFS_RUNTIME_ABI_H
#ifdef __KERNEL__
#include <linux/types.h>
#else
typedef unsigned int __u32;
typedef int __s32;
#endif
#define SUSFS_RUNTIME_MAGIC 0x53525431U
#define SUSFS_RUNTIME_VERSION 1U
#define SUSFS_RUNTIME_SIZE 48U
#define CMD_SUSFS_RUNTIME_GET 0x60040U
#define CMD_SUSFS_RUNTIME_SET 0x60041U
#define SUSFS_RT_UID_GATE 1U
#define SUSFS_RT_HIDDEN_NAME 2U
#define SUSFS_RT_UNICODE 4U
#define SUSFS_RT_SYMBOLS 8U
#define SUSFS_RT_ALL 15U
struct susfs_runtime_request {
    __u32 magic, version, size;
    __u32 supported, enabled;
    __u32 mask, values, expected_generation;
    __u32 generation, reserved;
    __s32 error;
    __u32 reserved2;
};
#endif
