/* Actual f76b81f2 SUS_PATH consumers plus the retained UIDGate. */
__attribute__((hot)) bool susfs_is_inode_sus_path(struct inode *inode)
{
	uid_t uid = current_uid().val % 100000;
	struct fuse_inode *fi = NULL;

	if (!susfs_uid_gate_current())
		return false;

	if (uid < 10000) {
		return false;
	}

	if (!inode->i_mapping) {
		SUSFS_LOGE("inode->i_mapping is NULL\n");
		return false;
	}

	if (inode->i_sb->s_magic == FUSE_SUPER_MAGIC) {
		fi = get_fuse_inode(inode);
		if (!fi || !fi->inode.i_mapping) {
			SUSFS_LOGE("fi || fi->inode.i_mapping is NULL\n");
			return false;
		}

		if (unlikely(test_bit(AS_FLAGS_SUS_PATH, &fi->inode.i_mapping->flags) &&
			likely(!susfs_is_uid_allowed_for_sus_path(uid))))
		{
			//SUSFS_LOGI("hiding path with ino '%lu'\n", inode->i_ino);
			return true;
		}
		return false;
	}

	if (unlikely(test_bit(AS_FLAGS_SUS_PATH, &inode->i_mapping->flags) &&
		likely(!susfs_is_uid_allowed_for_sus_path(uid))))
	{
		//SUSFS_LOGI("hiding path with ino '%lu'\n", inode->i_ino);
		return true;
	}

	return false;
}

bool susfs_is_uid_allowed_for_sus_path(uid_t uid) {
	struct susfs_sus_path_uid_filter_bitmap *bitmap;

	if (uid >= 90000)
		return true;

	if (uid < SUSFS_UID_FILTER_MIN_UID ||
		uid > SUSFS_UID_FILTER_MAX_UID)
		return false;

	rcu_read_lock();
	bitmap = rcu_dereference(sus_path_uid_filter_bitmap);
	if (likely(bitmap)) {
		if (test_bit(uid - SUSFS_UID_FILTER_MIN_UID, bitmap->bits)) {
			rcu_read_unlock();
			return true;
		}
	}

	rcu_read_unlock();
	return false;
}
