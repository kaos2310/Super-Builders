# Guard6.13 native SUSFS 2.4 compatibility

This is a bounded compatibility patch to the exact independently tested native
core with SHA-256 `1a0b25246a54746ebe89fb210ffbc8217f6227d9f5a04e964630e50228bea036`.
It is **not a native source rebuild**. The complete historical Guard6.13 source
was unavailable; the official SUSFS 2.4 release delta changes its version macro
and module metadata, with unchanged command numbers and LP64 structures.

The existing strict version predicate encodes `v2.3.0` and `2.3.0` in AArch64
MOV/MOVK instructions, rather than an ordinary data string. Exactly two MOVK
immediates change the digit `3` to `4`. Three read-only display-label bytes also
change. All remaining ELF bytes are identical, including every branch/call,
register/shift/opcode, relocation, import, struct layout and feature mechanism.
Unknown versions continue to fail closed. Native historical build identifiers
and the historical audited source commit remain preserved as provenance.

Usage:

```text
python apply.py INPUT_ELF OUTPUT_ELF --receipt FILE
python test.py
```

`VERIFICATION.json` records seven executions of the real AArch64 native program
on Android. A ptrace parent substitutes only the version-query response in the
child process. A separate kernel-enforced seccomp filter permits only the three
SUSFS read commands, rejects kernel writes, file write opens, ioctl, clone and
ptrace, and tests 131,085 filter cases before executing the core. The original
accepts 2.3 and rejects 2.4/2.5. The patched core accepts 2.4 (with and without
`v`) and rejects 2.3/2.5; all 14 advertised features and LP64 layouts are intact.
No installed module, configuration or kernel was modified by these tests.

The simulated read responses prove the native strict version gate and read ABI.
They do not prove a boot of the new 2.4 kernel, every possible write operation,
or the complete module lifecycle. Those remain separate validation steps.
