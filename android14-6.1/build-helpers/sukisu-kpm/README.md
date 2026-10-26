# S928B EZIF / SukiSU 41094 native KPM profile

This profile enables CONFIG_KPM=y and retains the exact SukiSU 41094 source
2ec445ffcb803614ee41ce111b6bad28c67f3347. It adds the official KernelPatch
engine 40ce8bea970e25fac9926a220730cf5a2331e3d9, built from source using
Arm GNU 12.2.rel1. The compiler archive is pinned to the official SHA-256.
The existing native extension ioctl, manager/root authorization and userspace
remain paired. CPU/PID limits and native preinit remain disabled.

The standard 41094 source was prepared in run 40367656492; that run was still
in progress when KPM preparation began. Its complete result is not claimed here.
The last separately verified successful full strict baseline was 39293074011.
The KPM run repeats all userspace, configuration, strict KMI, Samsung stock
module CRC, source, Image and packaging gates. None is bypassed for KPM.

Independent local checks compile 52 AArch64 kernel/SELinux objects, replay
194 kernel/UAPI sources and link the SukiSU subtree without unresolved ksu_
symbols. The effective configuration audit checks 54 settings, including KPM.
Native SukiSU and KernelPatch bridge functions are exercised with kernel mocks:
matching framing constants, missing engine, probe rejection, EL0 fall-through,
malformed kernel frames, reserved registers and full-width arguments. Four
fault mutations and two unexpected Image transformations are rejected.
These are host/static tests, not device, module loading or concurrency tests.

The engine and Linux patch tool were built and tested on a separate local
DZDP Linux 6.1.162 kernel fixture. Final EZIF transformation must pass in CI.
KernelPatch changes the entry/header and appends its engine. Its native patcher
also converts PAC instructions to NOPs within one declared 8 KiB mapping range.
Native unpatch does not restore those instructions. The integration records
every such instruction, rejects all other recovery differences and proves that
normalizing only the recorded instructions recovers the original bytes.
The original Image is retained separately as Original.Image in the KPM audit
artifact; it is not placed in the flash ZIP. Use that original for exact recovery.

The engine is applied only after compiled-kernel ABI/CRC gates. All existing
config, UIDGate, SUSFS and package checks then run against the transformed Image.
KPM-IMAGE.json binds original and final Image hashes, the exact engine build and
the transformation evidence. The final ZIP is created only after verifying this
receipt again. A generated per-image internal key is passed by pipe; it is not
written to arguments, logs or reports. No device has been flashed or tested.
