# HIDDEN_NAME directory enumeration correction

The existing name policy is used by stat/access but was absent from directory
enumeration. This correction invokes the same runtime-controlled, owner-aware
policy before a name is copied into a userspace directory buffer.

The opened directory must be Android/data or Android/obb and the caller must be
an umounted app process. Native and compat getdents/readdir callbacks are covered.
No inode-cache lookup is required for name filtering. Names outside this scope,
unregistered names, the owner app, system/root callers and the disabled runtime
switch retain their previous behavior. Dot entries and directory offsets are
preserved, including an all-hidden remainder and small userspace buffers.

The apply helper validates all insertion anchors. It keeps the existing
ZeroMount guard that prevents injection for these umounted app processes.
The kernel source and generated header are hashed before the full build and
rechecked against the packaged Image receipt. Samsung KMI/CRC gates still apply.

Run `python3 test.py --common /path/to/common --output /path/to/test-output`.
The test compiles the actual readdir syscall implementations against kernel API
boundary fakes. The original source must reproduce the directory leak; the fixed
source must pass all five ABIs with ZeroMount both enabled and disabled. This
does not replace a full ARM64 build or actual Android app verification.

## Partial reads with ZeroMount

The first directory-filter revision reset `buf->error` while validating a
trailing hidden entry. With ZeroMount enabled, this could take its EOF branch
before the visible bytes already written to the userspace buffer were counted.
Revision v2 keeps name-validation errors in a local variable and preserves the
existing callback error state when an entry is skipped. The tests replay v1 as
a negative control and cover hidden-last entries, visible dot prefixes, small
buffers, and EOF for every directory ABI.
