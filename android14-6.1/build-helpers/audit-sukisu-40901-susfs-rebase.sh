#!/bin/bash
set -euo pipefail

MODE="${1:?capture or verify}"
KSU_TREE="${2:?SukiSU Ultra tree}"
STATE_FILE="${3:?state file}"
EXPECTED_HEAD="9fbe8fe8ca90c62c259c5894bf96d02ac31209b9"
EXPECTED_VERSION="40901"

critical=(
  kernel/Kbuild
  kernel/feature/kernel_umount.c
  kernel/feature/sucompat.c
  kernel/hook/syscall_event_bridge.c
  kernel/hook/syscall_hook_manager.c
  kernel/policy/allowlist.c
  kernel/runtime/ksud_integration.c
)

fail() {
  echo "::error::$*"
  exit 1
}

[[ -d "$KSU_TREE/.git" ]] || fail "SukiSU Ultra git tree missing: $KSU_TREE"
[[ "$(git -C "$KSU_TREE" rev-parse HEAD)" == "$EXPECTED_HEAD" ]] || \
  fail "SukiSU Ultra HEAD drifted from $EXPECTED_HEAD"

for rel in "${critical[@]}"; do
  [[ -f "$KSU_TREE/$rel" ]] || fail "Critical SukiSU rebase file missing: $rel"
done

# 40901 identity must remain explicit and reproducible after the release helper.
grep -qx 'KSU_VERSION := 40901' "$KSU_TREE/kernel/Kbuild" || \
  fail "KSU_VERSION is not pinned to 40901"
grep -qx 'KSU_VERSION_FULL := v4.2.0-9fbe8fe8@main' "$KSU_TREE/kernel/Kbuild" || \
  fail "KSU_VERSION_FULL is not pinned to v4.2.0-9fbe8fe8@main"

# Rebase-sensitive SukiSU 40901 semantics. These are intentionally kept from
# SukiSU Ultra instead of replacing the whole files with the upstream KernelSU
# SUSFS 10_enable_susfs_for_ksu.patch.
grep -qF 'new_uid != WEBVIEW_ZYGOTE_UID' "$KSU_TREE/kernel/feature/kernel_umount.c" || \
  fail "WebView zygote umount handling is missing"
grep -qF 'is_isolated_process(new_uid)' "$KSU_TREE/kernel/feature/kernel_umount.c" || \
  fail "isolated-process umount handling is missing"
grep -qF 'ksu_handle_execveat_sucompat' "$KSU_TREE/kernel/feature/sucompat.c" || \
  fail "SukiSU execveat sucompat path is missing"
grep -qF 'ksu_syscall_table[__NR_execveat]' "$KSU_TREE/kernel/feature/sucompat.c" || \
  fail "SukiSU execveat dispatch is missing"
grep -qF 'long __nocfi ksu_hook_execveat' "$KSU_TREE/kernel/hook/syscall_event_bridge.c" || \
  fail "execveat event bridge is missing"
grep -qF 'ksu_execveat_hook_ksud(regs)' "$KSU_TREE/kernel/hook/syscall_event_bridge.c" || \
  fail "ksud execveat bridge is missing"
grep -qF 'ksu_register_syscall_hook(__NR_execveat, ksu_hook_execveat);' "$KSU_TREE/kernel/hook/syscall_hook_manager.c" || \
  fail "execveat hook registration is missing"
grep -qF 'bool ksu_uid_should_umount(uid_t uid)' "$KSU_TREE/kernel/policy/allowlist.c" || \
  fail "allowlist umount policy is missing"
grep -qF 'default_non_root_profile.umount_modules = true;' "$KSU_TREE/kernel/policy/allowlist.c" || \
  fail "default non-root umount policy changed"
grep -qF 'void ksu_handle_execveat_ksud' "$KSU_TREE/kernel/runtime/ksud_integration.c" || \
  fail "ksud execveat integration is missing"
grep -qF 'ksu_stop_ksud_execve_hook();' "$KSU_TREE/kernel/runtime/ksud_integration.c" || \
  fail "first-zygote exec hook shutdown is missing"

case "$MODE" in
  capture)
    mkdir -p "$(dirname "$STATE_FILE")"
    : > "$STATE_FILE"
    for rel in "${critical[@]}"; do
      sha256sum "$KSU_TREE/$rel" >> "$STATE_FILE"
    done
    echo "Captured SukiSU Ultra 40901 SUSFS-rebase baseline for ${#critical[@]} critical files"
    ;;
  verify)
    [[ -s "$STATE_FILE" ]] || fail "SukiSU rebase baseline is missing: $STATE_FILE"
    sha256sum -c "$STATE_FILE"

    # A copied 10_enable patch is evidence that the generic KernelSU patch path
    # has been reintroduced. This build deliberately uses the SukiSU-specific
    # SUSFS bridge instead.
    if find "$KSU_TREE" -type f -name '10_enable_susfs_for_ksu.patch' -print -quit | grep -q .; then
      fail "Generic SUSFS 10_enable_susfs_for_ksu.patch was copied into SukiSU Ultra"
    fi

    echo "Verified SukiSU Ultra 40901 critical files remained bit-identical across SUSFS/ZeroMount integration"
    ;;
  *)
    fail "Unsupported audit mode: $MODE"
    ;;
esac
