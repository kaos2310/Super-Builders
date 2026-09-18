#!/usr/bin/env python3
"""
Apply the ReSukiSU manual-hook integration required by ReSukiSU 35154
to the Android 14 / Linux 6.1 common kernel tree.

This helper intentionally patches only the core hooks that ReSukiSU's
kernel/tools/manual_hook_check.mk requires when CONFIG_KSU_MANUAL_HOOK=y.
The setuid, init-rc and input hooks stay on ReSukiSU's 6.1 auto-hook paths.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def read(path: Path) -> str:
    if not path.is_file():
        die(f"required source file is missing: {path}")
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def sub_once(text: str, pattern: re.Pattern[str], replacement: str, label: str) -> str:
    text, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        die(f"{label}: expected exactly one source match, got {count}")
    return text


def patch_exec(common: Path) -> None:
    path = common / "fs/exec.c"
    text = read(path)

    if (
        "ksu_handle_execveat(&fd, &filename, &argv, &envp, &flags);" in text
        and "ksu_handle_post_execveat(&fd, &filename, &argv, &envp, &flags, &retval);" in text
    ):
        print("manual-hook: fs/exec.c already integrated")
        return

    pattern = re.compile(
        r"static int do_execveat_common\(int fd, struct filename \*filename,\n"
        r"\s*struct user_arg_ptr argv,\n"
        r"\s*struct user_arg_ptr envp,\n"
        r"\s*int flags\)\n"
        r"\{\n"
        r"\s*return __do_execve_file\(fd, filename, argv, envp, flags, NULL\);\n"
        r"\}",
        re.MULTILINE,
    )

    replacement = """#ifdef CONFIG_KSU_MANUAL_HOOK
__attribute__((hot))
extern int ksu_handle_execveat(int *fd, struct filename **filename_ptr,
				void *argv, void *envp, int *flags);
__attribute__((hot))
extern int ksu_handle_post_execveat(int *fd, struct filename **filename_ptr,
				void *argv, void *envp, int *flags, int *retval);
#endif

static int do_execveat_common(int fd, struct filename *filename,
			      struct user_arg_ptr argv,
			      struct user_arg_ptr envp,
			      int flags)
{
#ifdef CONFIG_KSU_MANUAL_HOOK
	int retval;

	ksu_handle_execveat(&fd, &filename, &argv, &envp, &flags);
	retval = __do_execve_file(fd, filename, argv, envp, flags, NULL);
	ksu_handle_post_execveat(&fd, &filename, &argv, &envp, &flags, &retval);

	return retval;
#else
	return __do_execve_file(fd, filename, argv, envp, flags, NULL);
#endif
}"""

    text = sub_once(text, pattern, replacement, "fs/exec.c do_execveat_common")
    write(path, text)
    print("manual-hook: integrated execveat + post-execveat")


def patch_open(common: Path) -> None:
    path = common / "fs/open.c"
    text = read(path)

    if "ksu_handle_faccessat(&dfd, &filename, &mode, NULL);" not in text:
        pattern = re.compile(
            r"SYSCALL_DEFINE3\(faccessat, int, dfd, const char __user \*, filename, int, mode\)\n"
            r"\{\n"
            r"\s*return do_faccessat\(dfd, filename, mode, 0\);\n"
            r"\}",
            re.MULTILINE,
        )
        replacement = """#ifdef CONFIG_KSU_MANUAL_HOOK
__attribute__((hot))
extern int ksu_handle_faccessat(int *dfd, const char __user **filename_user,
				int *mode, int *flags);
#endif

SYSCALL_DEFINE3(faccessat, int, dfd, const char __user *, filename, int, mode)
{
#ifdef CONFIG_KSU_MANUAL_HOOK
	ksu_handle_faccessat(&dfd, &filename, &mode, NULL);
#endif
	return do_faccessat(dfd, filename, mode, 0);
}"""
        text = sub_once(text, pattern, replacement, "fs/open.c faccessat")
        print("manual-hook: integrated faccessat")
    else:
        print("manual-hook: faccessat already integrated")

    # Linux 6.1 exposes faccessat2 as well. ReSukiSU's checker only requires
    # faccessat, but applying the same path rewrite here keeps both user APIs
    # behaviorally aligned.
    if "SYSCALL_DEFINE4(faccessat2" in text and "ksu_handle_faccessat(&dfd, &filename, &mode, &flags);" not in text:
        pattern2 = re.compile(
            r"SYSCALL_DEFINE4\(faccessat2, int, dfd, const char __user \*, filename, int, mode,\n"
            r"\s*int, flags\)\n"
            r"\{\n"
            r"\s*return do_faccessat\(dfd, filename, mode, flags\);\n"
            r"\}",
            re.MULTILINE,
        )
        replacement2 = """SYSCALL_DEFINE4(faccessat2, int, dfd, const char __user *, filename, int, mode,
		int, flags)
{
#ifdef CONFIG_KSU_MANUAL_HOOK
	ksu_handle_faccessat(&dfd, &filename, &mode, &flags);
#endif
	return do_faccessat(dfd, filename, mode, flags);
}"""
        text = sub_once(text, pattern2, replacement2, "fs/open.c faccessat2")
        print("manual-hook: integrated faccessat2")

    write(path, text)


def patch_function_call(
    text: str,
    header_pattern: str,
    call_anchor: str,
    call_block: str,
    label: str,
    required: bool = True,
) -> tuple[str, bool]:
    function_re = re.compile(
        rf"(?P<body>{header_pattern}\n\{{.*?\n\}})",
        re.MULTILINE | re.DOTALL,
    )
    match = function_re.search(text)
    if not match:
        if required:
            die(f"{label}: function not found")
        return text, False

    body = match.group("body")
    if call_block.strip() in body:
        return text, True
    if call_anchor not in body:
        die(f"{label}: call anchor not found")

    body_new = body.replace(call_anchor, call_anchor + call_block, 1)
    text = text[: match.start("body")] + body_new + text[match.end("body") :]
    return text, True


def patch_stat(common: Path) -> None:
    path = common / "fs/stat.c"
    text = read(path)

    if "extern int ksu_handle_stat(" not in text:
        marker = "#if !defined(__ARCH_WANT_STAT64) || defined(__ARCH_WANT_SYS_NEWFSTATAT)"
        if marker not in text:
            die("fs/stat.c: declaration insertion marker not found")
        declarations = """#ifdef CONFIG_KSU_MANUAL_HOOK
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
        text = text.replace(marker, declarations + marker, 1)
        print("manual-hook: added stat/fstat declarations")

    # Hook every syscall path in this file that passes the user pathname to
    # vfs_fstatat(). On 6.1 this covers native newfstatat and, when built,
    # the stat64 compatibility path.
    if "ksu_handle_stat(&dfd, &filename, &flag);" not in text:
        line_re = re.compile(
            r"(?m)^(?P<indent>[ \t]*)error = vfs_fstatat\(dfd, filename, &stat, flag\);$"
        )

        def add_stat_call(match: re.Match[str]) -> str:
            indent = match.group("indent")
            return (
                f"#ifdef CONFIG_KSU_MANUAL_HOOK\n"
                f"{indent}ksu_handle_stat(&dfd, &filename, &flag);\n"
                f"#endif\n"
                f"{match.group(0)}"
            )

        text, count = line_re.subn(add_stat_call, text)
        if count < 1:
            die("fs/stat.c: no vfs_fstatat syscall path found")
        print(f"manual-hook: integrated stat path at {count} vfs_fstatat call(s)")

    newfstat_header = (
        r"SYSCALL_DEFINE2\(newfstat, unsigned int, fd, struct stat __user \*, statbuf\)"
    )
    text, _ = patch_function_call(
        text,
        newfstat_header,
        "\t\terror = cp_new_stat(&stat, statbuf);",
        """
#ifdef CONFIG_KSU_MANUAL_HOOK
	ksu_handle_newfstat_ret(&fd, &statbuf);
#endif""",
        "fs/stat.c newfstat",
        required=True,
    )

    fstat64_header = (
        r"SYSCALL_DEFINE2\(fstat64, unsigned long, fd, struct stat64 __user \*, statbuf\)"
    )
    text, has_fstat64 = patch_function_call(
        text,
        fstat64_header,
        "\t\terror = cp_new_stat64(&stat, statbuf);",
        """
#ifdef CONFIG_KSU_MANUAL_HOOK
	ksu_handle_fstat64_ret(&fd, &statbuf);
#endif""",
        "fs/stat.c fstat64",
        required=False,
    )
    if has_fstat64:
        print("manual-hook: integrated fstat64 return path")
    else:
        print("manual-hook: fstat64 syscall not present in this 6.1 source; declaration retained for checker/compat")

    write(path, text)
    print("manual-hook: integrated native newfstat return path")


def patch_reboot(common: Path) -> None:
    path = common / "kernel/reboot.c"
    text = read(path)

    if "ksu_handle_sys_reboot(magic1, magic2, cmd, &arg);" in text:
        print("manual-hook: reboot already integrated")
        return

    syscall_marker = (
        "SYSCALL_DEFINE4(reboot, int, magic1, int, magic2, unsigned int, cmd,\n"
        "\t\tvoid __user *, arg)"
    )
    if syscall_marker not in text:
        # Samsung formatting can use spaces instead of the canonical tabs.
        match = re.search(
            r"SYSCALL_DEFINE4\(reboot, int, magic1, int, magic2, unsigned int, cmd,\n"
            r"\s*void __user \*, arg\)",
            text,
        )
        if not match:
            die("kernel/reboot.c: reboot syscall signature not found")
        syscall_marker = match.group(0)

    declarations = """#ifdef CONFIG_KSU_MANUAL_HOOK
extern int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd,
				 void __user **arg);
#endif

"""
    text = text.replace(syscall_marker, declarations + syscall_marker, 1)

    pattern = re.compile(
        r"(SYSCALL_DEFINE4\(reboot, int, magic1, int, magic2, unsigned int, cmd,\n"
        r"\s*void __user \*, arg\)\n"
        r"\{.*?\n\s*int ret = 0;)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        die("kernel/reboot.c: reboot body anchor not found")

    replacement = match.group(1) + """

#ifdef CONFIG_KSU_MANUAL_HOOK
	ksu_handle_sys_reboot(magic1, magic2, cmd, &arg);
#endif"""
    text = text[: match.start()] + replacement + text[match.end() :]
    write(path, text)
    print("manual-hook: integrated reboot")


def verify(common: Path) -> None:
    checks = {
        common / "fs/exec.c": [
            "ksu_handle_execveat(&fd, &filename, &argv, &envp, &flags);",
            "ksu_handle_post_execveat(&fd, &filename, &argv, &envp, &flags, &retval);",
        ],
        common / "fs/open.c": [
            "ksu_handle_faccessat(&dfd, &filename, &mode, NULL);",
        ],
        common / "fs/stat.c": [
            "ksu_handle_stat(&dfd, &filename, &flag);",
            "ksu_handle_newfstat_ret(&fd, &statbuf);",
            "ksu_handle_fstat64_ret",
        ],
        common / "kernel/reboot.c": [
            "ksu_handle_sys_reboot(magic1, magic2, cmd, &arg);",
        ],
    }
    for path, needles in checks.items():
        text = read(path)
        for needle in needles:
            if needle not in text:
                die(f"verification failed: {needle!r} missing from {path}")

    incompatible = {
        common / "fs/read_write.c": "ksu_vfs_read_hook",
        common / "security/selinux/hooks.c": "is_ksu_transition",
        common / "security/security.c": "ksu_handle_rename",
    }
    for path, needle in incompatible.items():
        if path.is_file() and needle in read(path):
            die(f"ReSukiSU manual-hook incompatible marker present: {needle} in {path}")

    print("manual-hook: required ReSukiSU 35154 core hooks verified")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--common", required=True, type=Path)
    args = parser.parse_args()
    common = args.common.resolve()

    patch_exec(common)
    patch_open(common)
    patch_stat(common)
    patch_reboot(common)
    verify(common)


if __name__ == "__main__":
    main()
