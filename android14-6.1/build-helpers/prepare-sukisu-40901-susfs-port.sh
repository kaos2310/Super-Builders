#!/bin/bash
set -euo pipefail

KSU_ROOT="${1:?SukiSU Ultra tree}"
EXPECTED_PIN="9fbe8fe8ca90c62c259c5894bf96d02ac31209b9"
MARKER="$KSU_ROOT/.sukisu-ultra-source-pin"

[[ -f "$MARKER" ]] || { echo "::error::Missing SukiSU Ultra source marker"; exit 1; }
[[ "$(tr -d '[:space:]' < "$MARKER")" == "$EXPECTED_PIN" ]] || {
  echo "::error::Unexpected SukiSU Ultra source marker"
  exit 1
}

python3 - "$KSU_ROOT" <<'PY'
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])

def read(rel):
    p = root / rel
    if not p.is_file():
        raise SystemExit(f"Missing SukiSU source: {rel}")
    return p, p.read_text(encoding="utf-8")

def write(rel, text):
    (root / rel).write_text(text, encoding="utf-8")

def replace_once(text, old, new, label):
    if new in text:
        return text
    if text.count(old) != 1:
        raise SystemExit(f"Expected one {label} anchor, found {text.count(old)}")
    return text.replace(old, new, 1)

# 1) Define only the SUSFS base feature switches. Enhanced-only switches remain
# owned by the existing enhanced-SUSFS patch in fs/Kconfig.
p, text = read("kernel/Kconfig")
if "config KSU_SUSFS\n" not in text:
    block = r'''
menu "KernelSU - SUSFS"

config KSU_SUSFS
	bool "KernelSU addon - SUSFS"
	depends on KSU
	depends on THREAD_INFO_IN_TASK
	default y

config KSU_SUSFS_SUS_PATH
	bool "SUSFS suspicious path hiding"
	depends on KSU_SUSFS
	default y

config KSU_SUSFS_SUS_MOUNT
	bool "SUSFS suspicious mount hiding"
	depends on KSU_SUSFS
	default y

config KSU_SUSFS_SUS_KSTAT
	bool "SUSFS kstat spoofing"
	depends on KSU_SUSFS
	default y

config KSU_SUSFS_SPOOF_UNAME
	bool "SUSFS uname spoofing"
	depends on KSU_SUSFS
	default y

config KSU_SUSFS_ENABLE_LOG
	bool "SUSFS kernel logging support"
	depends on KSU_SUSFS
	default y

config KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS
	bool "Hide KSU/SUSFS symbols from kallsyms"
	depends on KSU_SUSFS
	default y

config KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG
	bool "SUSFS cmdline/bootconfig spoofing"
	depends on KSU_SUSFS
	default y

config KSU_SUSFS_OPEN_REDIRECT
	bool "SUSFS open redirect"
	depends on KSU_SUSFS
	default y

config KSU_SUSFS_SUS_MAP
	bool "SUSFS mmap hiding"
	depends on KSU_SUSFS
	default y

endmenu
'''
    text = replace_once(text, "\nendmenu\n", "\n" + block + "\nendmenu\n", "KernelSU endmenu")
    write("kernel/Kconfig", text)

# 2) Initialize SUSFS without replacing SukiSU Ultra's modern hook stack.
p, text = read("kernel/core/init.c")
if "#include <linux/susfs.h>" not in text:
    text = replace_once(text, "#include <linux/moduleparam.h>\n", "#include <linux/moduleparam.h>\n#include <linux/susfs.h>\n", "core init include")
if "    susfs_init();\n" not in text:
    text = replace_once(
        text,
        "    ksu_syscall_hook_init();\n\n",
        "    ksu_syscall_hook_init();\n\n#ifdef CONFIG_KSU_SUSFS\n    susfs_init();\n#endif\n\n",
        "SUSFS init",
    )
write("kernel/core/init.c", text)

# 3) Add a SukiSU-native SUSFS reboot ABI. Keep SukiSU's existing reboot kprobe
# for KSU_INSTALL_MAGIC2; non-SUSFS calls return -EINVAL and continue normally.
p, text = read("kernel/supercall/dispatch.c")
if "#include <linux/susfs.h>" not in text:
    text = replace_once(text, "#include <linux/thread_info.h>\n", "#include <linux/thread_info.h>\n#include <linux/susfs.h>\n", "dispatch SUSFS include")
if "int ksu_handle_susfs_cmd(unsigned int cmd, void __user **arg)" not in text:
    anchor = "static int do_nuke_ext4_sysfs(void __user *arg)\n"
    dispatcher = r'''int ksu_handle_susfs_cmd(unsigned int cmd, void __user **arg)
{
    switch (cmd) {
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
    case CMD_SUSFS_ADD_SUS_PATH: {
        susfs_add_sus_path(arg);
        return 0;
    }
    case CMD_SUSFS_ADD_SUS_PATH_LOOP: {
        susfs_add_sus_path_loop(arg);
        return 0;
    }
#endif
#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
    case CMD_SUSFS_HIDE_SUS_MNTS_FOR_NON_SU_PROCS: {
        susfs_set_hide_sus_mnts_for_non_su_procs(arg);
        return 0;
    }
#endif
#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT
    case CMD_SUSFS_ADD_SUS_KSTAT: {
        susfs_add_sus_kstat(arg);
        return 0;
    }
    case CMD_SUSFS_UPDATE_SUS_KSTAT: {
        susfs_update_sus_kstat(arg);
        return 0;
    }
    case CMD_SUSFS_ADD_SUS_KSTAT_STATICALLY: {
        susfs_add_sus_kstat(arg);
        return 0;
    }
#endif
#ifdef CONFIG_KSU_SUSFS_SPOOF_UNAME
    case CMD_SUSFS_SET_UNAME: {
        susfs_set_uname(arg);
        return 0;
    }
#endif
#ifdef CONFIG_KSU_SUSFS_ENABLE_LOG
    case CMD_SUSFS_ENABLE_LOG: {
        susfs_enable_log(arg);
        return 0;
    }
#endif
#ifdef CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG
    case CMD_SUSFS_SET_CMDLINE_OR_BOOTCONFIG: {
        susfs_set_cmdline_or_bootconfig(arg);
        return 0;
    }
#endif
#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
    case CMD_SUSFS_ADD_OPEN_REDIRECT: {
        susfs_add_open_redirect(arg);
        return 0;
    }
#endif
#ifdef CONFIG_KSU_SUSFS_SUS_MAP
    case CMD_SUSFS_ADD_SUS_MAP: {
        susfs_add_sus_map(arg);
        return 0;
    }
#endif
    case CMD_SUSFS_ENABLE_AVC_LOG_SPOOFING: {
        susfs_set_avc_log_spoofing(arg);
        return 0;
    }
    case CMD_SUSFS_SHOW_ENABLED_FEATURES: {
        susfs_get_enabled_features(arg);
        return 0;
    }
    case CMD_SUSFS_SHOW_VARIANT: {
        susfs_show_variant(arg);
        return 0;
    }
    case CMD_SUSFS_SHOW_VERSION: {
        susfs_show_version(arg);
        return 0;
    }
    default:
        return -EINVAL;
    }
}

int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd, void __user **arg)
{
    if (magic1 != KSU_INSTALL_MAGIC1)
        return -EINVAL;
    if (magic2 == SUSFS_MAGIC && current_uid().val == 0)
        return ksu_handle_susfs_cmd(cmd, arg);
    return -EINVAL;
}

'''
    text = replace_once(text, anchor, dispatcher + anchor, "supercall dispatcher insertion")
write("kernel/supercall/dispatch.c", text)

# 4) Start SUSFS sdcard monitoring on boot-completed while preserving SukiSU's
# existing throne/SELinux-hide logic.
p, text = read("kernel/runtime/boot_event.c")
if "#include <linux/susfs.h>" not in text:
    text = replace_once(text, "#include <linux/printk.h>\n", "#include <linux/printk.h>\n#include <linux/susfs.h>\n", "boot event include")
if "    susfs_start_sdcard_monitor_fn();\n" not in text:
    text = replace_once(
        text,
        "    ksu_selinux_hide_drop_backup_if_unused();\n",
        "    ksu_selinux_hide_drop_backup_if_unused();\n#ifdef CONFIG_KSU_SUSFS\n    susfs_start_sdcard_monitor_fn();\n#endif\n",
        "boot-completed monitor",
    )
write("kernel/runtime/boot_event.c", text)

# 5) Mark processes that follow SukiSU's existing umount policy. Do not replace
# kernel_umount.c; this preserves the 40901 WebView/isolated-process semantics.
p, text = read("kernel/hook/setuid_hook.c")
if "#include <linux/susfs_def.h>" not in text:
    text = replace_once(text, "#include <linux/uidgid.h>\n", "#include <linux/uidgid.h>\n#include <linux/susfs_def.h>\n", "setuid SUSFS include")
mark = r'''
#ifdef CONFIG_KSU_SUSFS
    if ((is_appuid(new_uid) || new_uid == WEBVIEW_ZYGOTE_UID || is_isolated_process(new_uid)) &&
        (ksu_uid_should_umount(new_uid) || is_isolated_process(new_uid)) && is_zygote(current_cred()))
        susfs_set_current_proc_umounted();
#endif
'''
if "susfs_set_current_proc_umounted();" not in text:
    text = replace_once(text, "    ksu_handle_umount(old_uid, new_uid);\n", "    ksu_handle_umount(old_uid, new_uid);\n" + mark, "setuid SUSFS mark")
write("kernel/hook/setuid_hook.c", text)

# 6) Export SukiSU's existing SELinux-hide state required by the SUSFS kernel
# hooks instead of replacing the implementation with the generic KSU patch.
p, text = read("kernel/feature/selinux_hide.c")
for old, new in (
    ("static bool ksu_selinux_hide_enabled __read_mostly = false;", "bool ksu_selinux_hide_enabled __read_mostly = false;"),
    ("static bool ksu_selinux_hide_running __read_mostly = false;", "bool ksu_selinux_hide_running __read_mostly = false;"),
    ("static struct selinux_state fake_state;", "struct selinux_state fake_state;"),
    ("static DEFINE_STATIC_KEY_FALSE(fake_status_initialize_key);", "DEFINE_STATIC_KEY_FALSE(fake_status_initialize_key);"),
    ("static struct page *fake_status = NULL;", "struct page *fake_status = NULL;"),
    ("static void initialize_fake_status()", "void initialize_fake_status()"),
):
    text = text.replace(old, new)
write("kernel/feature/selinux_hide.c", text)

# 7) Provide the SID bridge used by SUSFS AVC/zygote logic and refresh it after
# KernelSU policy installation.
p, text = read("kernel/selinux/selinux.c")
if "u32 susfs_ksu_sid __read_mostly" not in text:
    text += r'''

#ifdef CONFIG_KSU_SUSFS
#define KERNEL_INIT_DOMAIN "u:r:init:s0"
#define KERNEL_ZYGOTE_DOMAIN "u:r:zygote:s0"
#define KERNEL_PRIV_APP_DOMAIN "u:r:priv_app:s0:c512,c768"

u32 susfs_ksu_sid __read_mostly;
u32 susfs_init_sid __read_mostly;
u32 susfs_zygote_sid __read_mostly;
u32 susfs_priv_app_sid __read_mostly;

static void susfs_set_sid(const char *ctx, u32 *sid)
{
    int err = security_secctx_to_secid(ctx, strlen(ctx), sid);
    if (err)
        pr_err("SUSFS SID lookup failed for %s: %d\n", ctx, err);
}

bool susfs_is_sid_equal(const struct cred *cred, u32 sid)
{
    const struct task_security_struct *tsec = selinux_cred(cred);
    return tsec && tsec->sid == sid;
}

u32 susfs_get_sid_from_name(const char *ctx)
{
    u32 sid = 0;
    if (ctx)
        susfs_set_sid(ctx, &sid);
    return sid;
}

u32 susfs_get_current_sid(void)
{
    return current_sid();
}

bool susfs_is_current_zygote_domain(void) { return current_sid() == susfs_zygote_sid; }
bool susfs_is_current_ksu_domain(void) { return current_sid() == susfs_ksu_sid; }
bool susfs_is_current_init_domain(void) { return current_sid() == susfs_init_sid; }

void susfs_set_batch_sid(void)
{
    susfs_set_sid(KERNEL_ZYGOTE_DOMAIN, &susfs_zygote_sid);
    susfs_set_sid(KERNEL_SU_CONTEXT, &susfs_ksu_sid);
    susfs_set_sid(KERNEL_INIT_DOMAIN, &susfs_init_sid);
    susfs_set_sid(KERNEL_PRIV_APP_DOMAIN, &susfs_priv_app_sid);
}
#endif
'''
write("kernel/selinux/selinux.c", text)

p, text = read("kernel/selinux/selinux.h")
if "void susfs_set_batch_sid(void);" not in text:
    decl = r'''
#ifdef CONFIG_KSU_SUSFS
bool susfs_is_sid_equal(const struct cred *cred, u32 sid);
u32 susfs_get_sid_from_name(const char *ctx);
u32 susfs_get_current_sid(void);
void susfs_set_batch_sid(void);
bool susfs_is_current_zygote_domain(void);
bool susfs_is_current_ksu_domain(void);
bool susfs_is_current_init_domain(void);
#endif
'''
    text = replace_once(text, "\n#endif\n", "\n" + decl + "\n#endif\n", "selinux header end")
write("kernel/selinux/selinux.h", text)

p, text = read("kernel/selinux/rules.c")
if "    susfs_set_batch_sid();\n" not in text:
    text = replace_once(
        text,
        "    reset_avc_cache();\n",
        "    reset_avc_cache();\n#ifdef CONFIG_KSU_SUSFS\n    susfs_set_batch_sid();\n#endif\n",
        "SUSFS SID refresh",
    )
write("kernel/selinux/rules.c", text)

print("Prepared SukiSU Ultra 40901 native SUSFS ABI/lifecycle port")
PY

# Guard the seven rebase-sensitive 40901 semantics before the generic FS patch.
grep -qF 'new_uid != WEBVIEW_ZYGOTE_UID' "$KSU_ROOT/kernel/feature/kernel_umount.c"
grep -qF 'ksu_handle_execveat_sucompat' "$KSU_ROOT/kernel/feature/sucompat.c"
grep -qF 'long __nocfi ksu_hook_execveat' "$KSU_ROOT/kernel/hook/syscall_event_bridge.c"
grep -qF 'ksu_register_syscall_hook(__NR_execveat, ksu_hook_execveat);' "$KSU_ROOT/kernel/hook/syscall_hook_manager.c"
grep -qF 'bool ksu_uid_should_umount(uid_t uid)' "$KSU_ROOT/kernel/policy/allowlist.c"
grep -qF 'void ksu_handle_execveat_ksud' "$KSU_ROOT/kernel/runtime/ksud_integration.c"

echo "SukiSU Ultra 40901 SUSFS pre-port verified"
