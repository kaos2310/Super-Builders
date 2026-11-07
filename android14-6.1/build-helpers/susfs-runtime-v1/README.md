# SCRUM-6 – SukiSU 41159 and SuSFS Runtime v1

Functional baseline: https://github.com/kaos2310/Super-Builders/actions/runs/42129383180 at 4369dc1ae64d3e98e0b83452118ae15f3e5a5a78.

Requested update: official SukiSU 41159 at fae5788d2984e0c5844e8af96a18c569225d9774 (3974 commits; 40000 + 3974 - 2815). Kernel, UAPI and userspace are byte-identical upstream to the inspected 41155 source; the four intervening commits affect manager UI only. The full kernel/userspace pair is rebuilt at the 41159 pin.

The original workflow inputs are recorded in BASELINE.json and checked by contract.py. DroidSpaces, native KernelPatch/KPM ABI 2, Gunyah adaptive backing/reclaim, ZeroMount, priority UID filtering, ZRAM/BBG/OverlayFS, ptrace/perf patches and the strict Samsung DLKM CRC/KMI gates are retained. CPU/PID limits remain omitted as in the selected run.

Runtime-v1 adds a fixed-size 48-byte GET/SET ABI to the existing SuSFS dispatcher, global-root/init-userns-capability/KSU-domain checks, a generation CAS, and a mutex. All compiled features retain their previous enabled defaults after boot. UID-gating, hidden-name, unicode-filter and symbol-hiding can subsequently be toggled by the compatible SUSFS Console 2.2 APK/helper. UID-gating OFF restores legacy consumer behavior; it does not grant root. Other flags pause only their existing consumer filters; tables and rules remain stored.

The overlay is applied only after the original exact-C and source checks. Original receipt verification is retained: only the exact reversible runtime additions are normalized, and both full overlay source hashes and reconstructed baseline hashes are verified. Unknown or partial overlays fail. Kernel configuration, full link, stock-module CRC, packaged-Image and runtime-function attestations gate artifact production.

Independent local evidence: fresh source replay at the 41159 pin; 57 ARM64 port objects and three runtime objects compiled; original feature/fault tests passed; 16 runtime configurations (1069 assertions), helper/handler integration (56 assertions), and workflow actionlint passed. The helper SHA-256 matches the SUSFS Console 2.2 native helper: 0884eab792eb3a21d0be447cbe62d92b6dde5ec6bd0f9cbe02506e43361dcc28.

This builds artifacts only. No device installation, flash, reboot or runtime root-invisibility claim is part of this change.
