/* SPDX-License-Identifier: GPL-2.0 */
#ifndef _LINUX_SUSFS_NAME_FILTER_H
#define _LINUX_SUSFS_NAME_FILTER_H

#ifndef SUSFS_NAME_FILTER_TEST
#include <linux/dcache.h>
#include <linux/fs.h>
#include <linux/rcupdate.h>
#include <linux/seqlock.h>
#include <linux/susfs.h>
#include <linux/susfs_def.h>
#endif

/* Match the Android/data and Android/obb scope of the existing stat/access
 * consumers. Name lookup remains in susfs_is_hidden_name(), including its
 * runtime switch, UID gate, RCU table and owner exception. No inode lookup is
 * needed, so uncached directory entries and FUSE names follow the same rule.
 */
static inline bool susfs_hidden_name_dir(struct file *file)
{
	struct dentry *dir, *parent;
	unsigned int sequence, length;
	bool match;

	if (!susfs_is_current_proc_umounted_app())
		return false;
	if (!file || !(dir = file->f_path.dentry))
		return false;

	/* rename_lock gives one consistent parent/name snapshot. RCU protects
	 * parent dentries and external name storage while a rename is retried.
	 */
	rcu_read_lock();
	do {
		sequence = read_seqbegin(&rename_lock);
		parent = READ_ONCE(dir->d_parent);
		length = READ_ONCE(dir->d_name.len);
		match = parent && parent != dir &&
			((length == 4 && !memcmp(dir->d_name.name, "data", 4)) ||
			 (length == 3 && !memcmp(dir->d_name.name, "obb", 3))) &&
			READ_ONCE(parent->d_name.len) == 7 &&
			!memcmp(parent->d_name.name, "Android", 7);
	} while (read_seqretry(&rename_lock, sequence));
	rcu_read_unlock();
	return match;
}
#endif
