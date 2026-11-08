/* SPDX-License-Identifier: GPL-2.0 */
#ifndef LINUX_SUSFS_RUNTIME_H
#define LINUX_SUSFS_RUNTIME_H
#include <linux/susfs_runtime_abi.h>
#include <linux/types.h>
#ifdef CONFIG_KSU_SUSFS
bool susfs_runtime_enabled(unsigned int bit);
int susfs_runtime_handle(unsigned int command, void __user *argument);
#endif
#endif
