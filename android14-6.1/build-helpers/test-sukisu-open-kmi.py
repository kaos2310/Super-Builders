#!/usr/bin/env python3
"""Exercise the sanitizer/normalizer boundary that broke run 34168189986.

Compile the resulting hook declarations with the host C compiler, and inspect
its preprocessor output with __GENKSYMS__. Full CRC equality remains enforced
by the Samsung DLKM gate on the real kernel build.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
UNICODE = "extern bool susfs_check_unicode_bypass(const char __user *filename);"
BROAD = "#ifdef CONFIG_KSU_SUSFS\n#include <linux/susfs.h>\n#endif\n"
SOURCE = '''#include "internal.h"
#ifdef CONFIG_KSU_SUSFS
#include <linux/susfs_def.h>
#endif
extern bool susfs_is_current_proc_umounted(void);
extern bool susfs_is_hidden_name(const char *name, int namlen, uid_t caller_uid);
extern bool susfs_check_unicode_bypass(const char __user *filename);
#ifdef CONFIG_KSU
extern int ksu_handle_faccessat(void);
#endif
static long do_faccessat(int dfd, const char __user *filename, int mode, int flags)
{
    struct filename *fname = NULL;
    struct path path;
    unsigned int lookup_flags = 0;
    int res;
retry:
    if (res) return res;
    if (susfs_is_hidden_name(filename, 1, 10000)) return -1;
    if (susfs_check_unicode_bypass(filename)) return -1;
    return 0;
}
'''


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sukisu-open-kmi-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.common, self.ksu = self.root / "common", self.root / "KernelSU"
        for relative in ("drivers/input/input.c", "fs/exec.c", "fs/read_write.c",
                         "fs/stat.c", "kernel/sys.c"):
            self.write(self.common / relative, "/* no generic KSU callbacks */\n")
        self.open = self.common / "fs/open.c"
        self.write(self.open, SOURCE)
        self.write(self.common / "include/linux/susfs.h",
                   "struct uts_namespace { int name; };\n"
                   "struct kstatfs { int flags; };\n" + UNICODE.removeprefix("extern ") + "\n")
        self.write(self.common / "include/linux/susfs_def.h",
                   "struct susfs_runtime_def { int flag; };\n")
        self.write(self.common / "fs/internal.h",
                   "#include <stdbool.h>\n#define __user\n"
                   "typedef unsigned int uid_t;\nstruct path { int value; };\n"
                   "int user_path_at(int, const char *, unsigned int, struct path *);\n")
        self.write(self.ksu / "kernel/policy/app_profile.c",
                   "void escape_to_root_for_init(void)\n{\n}\n")
        self.write(self.ksu / "kernel/policy/app_profile.h",
                   "void escape_to_root_for_init(void);\n")
        self.write(self.ksu / "kernel/feature/sucompat.c", "/* native API */\n")

    @staticmethod
    def write(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def run_helper(self, name, *args, ok=True):
        result = subprocess.run([sys.executable, str(HERE / name), *map(str, args)],
                                capture_output=True, text=True)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def sanitize(self):
        self.run_helper("sanitize-sukisu-40901-common-hooks.py", self.common, self.ksu)

    def normalize(self, *flags, ok=True):
        return self.run_helper("normalize-susfs-open-kmi.py", *flags, self.common, ok=ok)

    def test_old_order_does_not_restore_umbrella_header(self):
        # Old sequence: the normalizer succeeded, then the sanitizer undid it.
        self.normalize()
        self.sanitize()
        self.normalize("--check")
        self.assertNotIn("#include <linux/susfs.h>", self.open.read_text())

    def test_final_order_repairs_lookup_and_is_idempotent(self):
        self.open.write_text(BROAD + SOURCE)
        self.sanitize()
        self.normalize()
        first = self.open.read_bytes()
        self.sanitize()
        self.normalize()
        self.assertEqual(first, self.open.read_bytes())
        self.assertIn("res = user_path_at(dfd, filename, lookup_flags, &path);", first.decode())
        self.assertNotIn("fname", first.decode())
        self.assertNotIn("ksu_handle_faccessat", first.decode())

    def test_missing_unicode_declaration_is_restored_narrowly(self):
        self.open.write_text(SOURCE.replace(UNICODE + "\n", ""))
        self.sanitize()
        self.normalize()
        self.assertEqual(self.open.read_text().count(UNICODE), 1)
        self.assertNotIn("#include <linux/susfs.h>", self.open.read_text())

    def test_late_header_regression_is_rejected_without_mutation(self):
        self.sanitize()
        self.normalize()
        self.open.write_text(BROAD + self.open.read_text())
        before = self.open.read_bytes()
        self.normalize("--check", ok=False)
        self.assertEqual(before, self.open.read_bytes())

    def test_missing_hook_is_rejected(self):
        self.open.write_text(SOURCE.replace(UNICODE + "\n", ""))
        self.normalize(ok=False)

    def test_runtime_compiles_and_genksyms_types_remain_opaque(self):
        cc = os.environ.get("CC") or shutil.which("cc") or shutil.which("gcc")
        self.assertTrue(cc, "C compiler is mandatory for KMI regression tests")
        self.sanitize()
        self.normalize()
        command = [cc, "-DCONFIG_KSU_SUSFS", "-I" + str(self.common / "include")]
        subprocess.run(command + ["-std=gnu11", "-Wall", "-Werror",
                                  "-Wno-unused-function", "-Wno-unused-label", "-fsyntax-only",
                                  str(self.open)], check=True)
        for genksyms in (False, True):
            args = ["-D__GENKSYMS__"] if genksyms else []
            result = subprocess.run(command + args + ["-E", "-P", str(self.open)],
                                    capture_output=True, text=True, check=True)
            self.assertNotIn("struct uts_namespace {", result.stdout)
            self.assertNotIn("struct kstatfs {", result.stdout)
            self.assertEqual("struct susfs_runtime_def {" in result.stdout, not genksyms)
            self.assertIn("susfs_check_unicode_bypass(filename)", result.stdout)
            self.assertIn("susfs_is_hidden_name(filename", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
