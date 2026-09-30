#!/usr/bin/env python3
"""Carry the reference profile, WebView and su-session guarantees into SukiSU."""
import subprocess
from configure import PIN

PATHS = ('kernel/feature/sucompat.c', 'kernel/policy/app_profile.c',
         'kernel/policy/allowlist.c', 'kernel/hook/lsm_hook.c', 'kernel/include/ksu.h')

def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f'Native SukiSU feature source anchor drift: {old[:90]!r}')
    return text.replace(old, new, 1)

def expected(ksu):
    files = {p: subprocess.check_output(['git', '-C', str(ksu), 'show', f'{PIN}:{p}']).decode() for p in PATHS}
    p = 'kernel/include/ksu.h'
    files[p] = once(files[p], '#define KERNEL_SU_VERSION KSU_VERSION\n',
                    '#define KERNEL_SU_VERSION KSU_VERSION\n#define WEBVIEW_ZYGOTE_UID 1053\n')
    p = 'kernel/policy/app_profile.c'
    files[p] = once(files[p], '    if (set_cred_ucounts(cred)) {\n        goto out_abort_creds;\n    }',
                    '    ret = set_cred_ucounts(cred);\n    if (ret) {\n        goto out_abort_creds;\n    }')
    p = 'kernel/policy/allowlist.c'
    anchor = '    if (profile->allow_su) {\n        if (profile->rp_config.profile.groups_count > KSU_MAX_GROUPS) {'
    files[p] = once(files[p], anchor, '''    /* WebView is a non-root system-service profile, including after pruning. */
    if (profile->curr_uid == WEBVIEW_ZYGOTE_UID &&
        (profile->allow_su || strcmp(profile->key, "webview_zygote") != 0))
        return false;

''' + anchor)
    if 'uid == KSU_APP_PROFILE_PRESERVE_UID || uid == WEBVIEW_ZYGOTE_UID' not in files[p]:
        raise RuntimeError('Native SukiSU WebView prune preservation missing')
    p = 'kernel/hook/lsm_hook.c'
    marker = 'static int handle_zygote_next_setresuid(uid_t ruid) {'
    prefix, suffix = files[p].split(marker)
    anchor = '    // - Check if spawned process is normal user app and needs to be umounted\n'
    suffix = once(suffix, anchor, '''    /* UID 1053 is outside is_appuid(); honor its persisted non-root profile. */
    if (unlikely(ruid == WEBVIEW_ZYGOTE_UID)) {
        susfs_set_current_proc_no_su();
        if (ksu_uid_should_umount(ruid)) {
            susfs_set_current_proc_umounted();
            susfs_set_current_proc_umounted_for_zygote_next();
            goto do_susfs_work;
        }
        return 0;
    }

''' + anchor)
    files[p] = prefix + marker + suffix
    p = 'kernel/feature/sucompat.c'
    old = '''    memcpy((void *)filename->name, ksud_path, sizeof(ksud_path));

    pending_sucompat = ksu_sulog_capture_sucompat(filename->name, (struct user_arg_ptr*)argv_user, GFP_KERNEL);

    ret = escape_with_root_profile();
    if (ret)
        pr_err("escape_with_root_profile() failed: %d\\n", ret);
'''
    new = '''    pending_sucompat = ksu_sulog_capture_sucompat(filename->name, (struct user_arg_ptr*)argv_user, GFP_KERNEL);

    if (test_thread_flag(TIF_KSU_DISABLE_ESCAPE_WITH_ROOT)) {
        ksu_sulog_emit_pending(pending_sucompat, -EPERM, GFP_KERNEL);
        return -EPERM;
    }
    ret = escape_with_root_profile();
    if (ret) {
        pr_err("escape_with_root_profile() failed: %d\\n", ret);
        ksu_sulog_emit_pending(pending_sucompat, ret, GFP_KERNEL);
        return ret;
    }
    /* Preserve the reference fallback without creating a ksud session. */
    struct path kpath;
    if (kern_path(KSUD_PATH, LOOKUP_FOLLOW, &kpath)) {
        memcpy((void *)filename->name, sh_path, sizeof(sh_path));
        ksu_sulog_emit_pending(pending_sucompat, 0, GFP_KERNEL);
        return 0;
    }
    path_put(&kpath);
    memcpy((void *)filename->name, ksud_path, sizeof(ksud_path));
'''
    files[p] = once(files[p], old, new)
    anchor = '''    return ksu_handle_execveat_sucompat(fd, filename_ptr, argv, envp,
                        flags);
}
'''
    wrapper = '''
/* Explicit success decision for the generic SUSFS exec bridge. The FD remains
 * SukiSU's native [ksu_driver] ABI and is installed only after successful exec. */
bool ksu_handle_execveat_su_session(int *fd, struct filename **filename_ptr,
                                   void *argv, void *envp, int *flags)
{
    bool was_su;
    int ret;
    if (!filename_ptr || IS_ERR_OR_NULL(*filename_ptr))
        return false;
    was_su = !strcmp((*filename_ptr)->name, SU_PATH);
    ret = ksu_handle_execveat(fd, filename_ptr, argv, envp, flags);
    return was_su && !ret && !strcmp((*filename_ptr)->name, KSUD_PATH);
}
'''
    files[p] = once(files[p], anchor, anchor + wrapper)
    return files

def apply(ksu):
    files = expected(ksu)
    for path, text in files.items():
        original = subprocess.check_output(['git', '-C', str(ksu), 'show', f'{PIN}:{path}'])
        actual = (ksu / path).read_bytes()
        if actual not in (original, text.encode()):
            raise RuntimeError(f'Unexpected source before native feature port: {path}')
    for path, text in files.items():
        (ksu / path).write_text(text, encoding='utf-8', newline='\n')

def verify(ksu):
    for path, text in expected(ksu).items():
        if (ksu / path).read_bytes() != text.encode():
            raise RuntimeError(f'Native SukiSU feature contract drift: {path}')
