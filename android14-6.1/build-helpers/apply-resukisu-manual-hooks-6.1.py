#!/usr/bin/env python3
"""Apply ReSukiSU 35154 Manual Hook integration to Android 14 / Linux 6.1."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def die(msg: str) -> None:
    raise SystemExit(f"ERROR: {msg}")


def load(path: Path) -> str:
    if not path.is_file():
        die(f"missing source file: {path}")
    return path.read_text(encoding="utf-8")


def save(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        die(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


def patch_exec(common: Path) -> None:
    path = common / "fs/exec.c"
    text = load(path)

    decl = """#ifdef CONFIG_KSU_MANUAL_HOOK
__attribute__((hot))
extern int ksu_handle_execveat(int *fd, struct filename **filename_ptr,
				void *argv, void *envp, int *flags);
__attribute__((hot))
extern int ksu_handle_post_execveat(int *fd, struct filename **filename_ptr,
				void *argv, void *envp, int *flags, int *retval);
#endif

"""

    marker = "static int do_execveat_common(int fd, struct filename *filename,"
    if "extern int ksu_handle_execveat(" not in text:
        if marker not in text:
            die("fs/exec.c: do_execveat_common declaration not found")
        text = text.replace(marker, decl + marker, 1)

    if "ksu_handle_execveat(&fd, &filename, &argv, &envp, &flags);" not in text:
        # Android 14 / Linux 6.1 has a full do_execveat_common() body. Insert
        # after its local declarations and immediately before filename validation.
        pat = re.compile(
            r"(static int do_execveat_common\(int fd, struct filename \*filename,\n"
            r"\s*struct user_arg_ptr argv,\n"
            r"\s*struct user_arg_ptr envp,\n"
            r"\s*int flags\)\n"
            r"\{.*?\n\s*int retval;\n)(\s*\n\s*if \(IS_ERR\(filename\)\))",
            re.DOTALL,
        )
        repl = (
            r"\1\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
            r"\tksu_handle_execveat(&fd, &filename, &argv, &envp, &flags);\n"
            r"#endif\n\2"
        )
        text, n = pat.subn(repl, text, count=1)
        if n != 1:
            die("fs/exec.c: modern do_execveat_common pre-hook anchor not found")

    if "ksu_handle_post_execveat(&fd, &filename, &argv, &envp, &flags, &retval);" not in text:
        pat = re.compile(
            r"(\nout_ret:\n"
            r"(?:\s*if \(filename\)\n\s*)?"
            r"\s*putname\(filename\);\n)"
            r"(\s*return retval;)",
            re.MULTILINE,
        )
        repl = (
            r"\1#ifdef CONFIG_KSU_MANUAL_HOOK\n"
            r"\tksu_handle_post_execveat(&fd, &filename, &argv, &envp, &flags, &retval);\n"
            r"#endif\n\2"
        )
        text, n = pat.subn(repl, text, count=1)
        if n != 1:
            die("fs/exec.c: modern do_execveat_common out_ret post-hook anchor not found")

    save(path, text)
    print("manual-hook: integrated execveat + post-execveat into modern do_execveat_common")


def patch_open(common: Path) -> None:
    path = common / "fs/open.c"
    text = load(path)

    if "extern int ksu_handle_faccessat(" not in text:
        marker = "SYSCALL_DEFINE3(faccessat, int, dfd, const char __user *, filename, int, mode)"
        decl = """#ifdef CONFIG_KSU_MANUAL_HOOK
__attribute__((hot))
extern int ksu_handle_faccessat(int *dfd, const char __user **filename_user,
				int *mode, int *flags);
#endif

"""
        if marker not in text:
            die("fs/open.c: faccessat syscall not found")
        text = text.replace(marker, decl + marker, 1)

    if "ksu_handle_faccessat(&dfd, &filename, &mode, NULL);" not in text:
        pat = re.compile(
            r"(SYSCALL_DEFINE3\(faccessat, int, dfd, const char __user \*, filename, int, mode\)\n\{\n)"
        )
        repl = r"\1#ifdef CONFIG_KSU_MANUAL_HOOK\n\tksu_handle_faccessat(&dfd, &filename, &mode, NULL);\n#endif\n"
        text, n = pat.subn(repl, text, count=1)
        if n != 1:
            die("fs/open.c: faccessat body anchor not found")

    if "SYSCALL_DEFINE4(faccessat2" in text and "ksu_handle_faccessat(&dfd, &filename, &mode, &flags);" not in text:
        pat = re.compile(
            r"(SYSCALL_DEFINE4\(faccessat2, int, dfd, const char __user \*, filename, int, mode,\n"
            r"\s*int, flags\)\n\{\n)"
        )
        repl = r"\1#ifdef CONFIG_KSU_MANUAL_HOOK\n\tksu_handle_faccessat(&dfd, &filename, &mode, &flags);\n#endif\n"
        text, n = pat.subn(repl, text, count=1)
        if n != 1:
            die("fs/open.c: faccessat2 body anchor not found")

    save(path, text)
    print("manual-hook: integrated faccessat/faccessat2")


def patch_stat(common: Path) -> None:
    path = common / "fs/stat.c"
    text = load(path)

    if "extern int ksu_handle_stat(" not in text:
        marker = "#if !defined(__ARCH_WANT_STAT64) || defined(__ARCH_WANT_SYS_NEWFSTATAT)"
        decl = """#ifdef CONFIG_KSU_MANUAL_HOOK
__attribute__((hot))
extern int ksu_handle_stat(int *dfd, const char __user **filename_user,
				int *flags);
extern void ksu_handle_newfstat_ret(unsigned int *fd,
				struct stat __user **statbuf_ptr);
#if defined(__ARCH_WANT_STAT64) || defined(__ARCH_WANT_COMPAT_STAT64)
extern void ksu_handle_fstat64_ret(unsigned long *fd,
				struct stat64 __user **statbuf_ptr);
#endif
#endif

"""
        if marker not in text:
            die("fs/stat.c: stat declaration marker not found")
        text = text.replace(marker, decl + marker, 1)

    # newfstatat
    if "ksu_handle_stat(&dfd, &filename, &flag);" not in text:
        pat = re.compile(
            r"(SYSCALL_DEFINE4\(newfstatat, int, dfd, const char __user \*, filename,\n"
            r"\s*struct stat __user \*, statbuf, int, flag\)\n"
            r"\{.*?\n\s*int error;\n)",
            re.DOTALL,
        )
        repl = r"\1\n#ifdef CONFIG_KSU_MANUAL_HOOK\n\tksu_handle_stat(&dfd, &filename, &flag);\n#endif\n"
        text, n = pat.subn(repl, text, count=1)
        if n != 1:
            die("fs/stat.c: newfstatat anchor not found")

    # native fstat return path
    if "ksu_handle_newfstat_ret(&fd, &statbuf);" not in text:
        pat = re.compile(
            r"(SYSCALL_DEFINE2\(newfstat, unsigned int, fd, struct stat __user \*, statbuf\).*?"
            r"\n\s*if \(!error\)\n\s*error = cp_new_stat\(&stat, statbuf\);\n)",
            re.DOTALL,
        )
        repl = r"\1\n#ifdef CONFIG_KSU_MANUAL_HOOK\n\tksu_handle_newfstat_ret(&fd, &statbuf);\n#endif\n"
        text, n = pat.subn(repl, text, count=1)
        if n != 1:
            die("fs/stat.c: newfstat return anchor not found")

    # 32-bit/compat fstat64 path, if present.
    if "SYSCALL_DEFINE2(fstat64" in text and "ksu_handle_fstat64_ret(&fd, &statbuf);" not in text:
        pat = re.compile(
            r"(SYSCALL_DEFINE2\(fstat64, unsigned long, fd, struct stat64 __user \*, statbuf\).*?"
            r"\n\s*if \(!error\)\n\s*error = cp_new_stat64\(&stat, statbuf\);\n)",
            re.DOTALL,
        )
        repl = (
            r"\1\n#if defined(CONFIG_KSU_MANUAL_HOOK) && "
            r"(defined(__ARCH_WANT_STAT64) || defined(__ARCH_WANT_COMPAT_STAT64))\n"
            r"\tksu_handle_fstat64_ret(&fd, &statbuf);\n#endif\n"
        )
        text, n = pat.subn(repl, text, count=1)
        if n != 1:
            die("fs/stat.c: fstat64 return anchor not found")

    # fstatat64 exists on some compat configurations and must receive the same
    # pathname rewrite when present.
    if "SYSCALL_DEFINE4(fstatat64" in text and text.count("ksu_handle_stat(&dfd, &filename, &flag);") < 2:
        pat = re.compile(
            r"(SYSCALL_DEFINE4\(fstatat64, int, dfd, const char __user \*, filename,.*?"
            r"\n\s*int error;\n)",
            re.DOTALL,
        )
        repl = r"\1\n#ifdef CONFIG_KSU_MANUAL_HOOK\n\tksu_handle_stat(&dfd, &filename, &flag);\n#endif\n"
        text, n = pat.subn(repl, text, count=1)
        if n != 1:
            die("fs/stat.c: fstatat64 anchor not found")

    save(path, text)
    print("manual-hook: integrated stat/newfstat/fstat64 paths")


def patch_reboot(common: Path) -> None:
    path = common / "kernel/reboot.c"
    text = load(path)

    sig = "SYSCALL_DEFINE4(reboot, int, magic1, int, magic2, unsigned int, cmd,"
    if "extern int ksu_handle_sys_reboot(" not in text:
        pos = text.find(sig)
        if pos < 0:
            die("kernel/reboot.c: reboot syscall not found")
        decl = """#ifdef CONFIG_KSU_MANUAL_HOOK
extern int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd,
				 void __user **arg);
#endif

"""
        text = text[:pos] + decl + text[pos:]

    if "ksu_handle_sys_reboot(magic1, magic2, cmd, &arg);" not in text:
        pat = re.compile(
            r"(SYSCALL_DEFINE4\(reboot, int, magic1, int, magic2, unsigned int, cmd,\n"
            r"\s*void __user \*, arg\)\n"
            r"\{.*?\n\s*int ret = 0;\n)",
            re.DOTALL,
        )
        repl = r"\1\n#ifdef CONFIG_KSU_MANUAL_HOOK\n\tksu_handle_sys_reboot(magic1, magic2, cmd, &arg);\n#endif\n"
        text, n = pat.subn(repl, text, count=1)
        if n != 1:
            die("kernel/reboot.c: reboot body anchor not found")

    save(path, text)
    print("manual-hook: integrated reboot")


def verify(common: Path) -> None:
    checks = {
        "fs/exec.c": (
            "ksu_handle_execveat(&fd, &filename, &argv, &envp, &flags);",
            "ksu_handle_post_execveat(&fd, &filename, &argv, &envp, &flags, &retval);",
        ),
        "fs/open.c": ("ksu_handle_faccessat(&dfd, &filename, &mode, NULL);",),
        "fs/stat.c": (
            "ksu_handle_stat(&dfd, &filename, &flag);",
            "ksu_handle_newfstat_ret(&fd, &statbuf);",
            "ksu_handle_fstat64_ret",
        ),
        "kernel/reboot.c": ("ksu_handle_sys_reboot(magic1, magic2, cmd, &arg);",),
    }
    for rel, needles in checks.items():
        text = load(common / rel)
        for needle in needles:
            if needle not in text:
                die(f"verification failed: {needle!r} missing from {rel}")

    incompatible = {
        "fs/read_write.c": "ksu_vfs_read_hook",
        "security/selinux/hooks.c": "is_ksu_transition",
        "security/security.c": "ksu_handle_rename",
    }
    for rel, needle in incompatible.items():
        path = common / rel
        if path.is_file() and needle in load(path):
            die(f"manual-hook incompatible marker present: {needle} in {rel}")

    print("manual-hook: ReSukiSU 35154 Android 14 / Linux 6.1 core hooks verified")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--common", type=Path, required=True)
    args = ap.parse_args()
    common = args.common.resolve()

    patch_exec(common)
    patch_open(common)
    patch_stat(common)
    patch_reboot(common)
    verify(common)


if __name__ == "__main__":
    main()
