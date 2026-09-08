#!/usr/bin/env python3
"""Apply the native UAPI-2 su-session backport to the pinned ReSukiSU tree."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
RESUKISU_PIN = "f1dd81dc96d7f3f6691e6ac8b50fba9ae8a2f17c"
SUSFS_PIN = "5727f79e3a7175cfb0e1a754fc2ed78eaf866237"
UPSTREAM = "153f88df3be2501d2d33364f8fe05247aecb3cef"
PORT_ID = "ReSukiSU-35119-SuSession-v1"
IMAGE_MARKER = b"ReSukiSU: su-session FD installation failed:"


def git(root, *args, check=True):
    result = subprocess.run(
        ["git", "-c", "core.safecrlf=false",
         "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8",
    )
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result


def patch_state(root, patch):
    if git(root, "apply", "--check", "--whitespace=nowarn", str(patch), check=False).returncode == 0:
        return "original"
    if git(root, "apply", "--reverse", "--check", "--whitespace=nowarn", str(patch), check=False).returncode == 0:
        return "applied"
    raise RuntimeError(f"Unknown or partial source state: {root} / {patch.name}")


def apply_pair(common, ksu, verify_only=False):
    pairs = [(ksu, HERE / "resukisu-35119-su-session.patch"),
             (common, HERE / "gki-6.1-su-session.patch")]
    # Check BOTH patches before changing either tree. No fuzz or rejected hunks.
    states = [patch_state(root, patch) for root, patch in pairs]
    if len(set(states)) != 1:
        raise RuntimeError(f"Partial cross-tree port rejected: {states}")
    if states[0] == "applied":
        return "already applied"
    if verify_only:
        raise RuntimeError("The su-session port has not been applied")
    # Preserve exact bytes, including CRLF, if either application fails.
    backup = {}
    for root, patch in pairs:
        for name in re.findall(r"^\+\+\+ b/(.+)$", patch.read_text(), re.M):
            path = root / name
            backup[path] = path.read_bytes()
    try:
        for root, patch in pairs:
            git(root, "apply", "--whitespace=nowarn", str(patch))
        if any(patch_state(root, patch) != "applied" for root, patch in pairs):
            raise RuntimeError("Post-application verification failed")
    except Exception:
        for path, content in backup.items():
            path.write_bytes(content)
        raise
    return "applied"


def validate_identity(common, ksu, susfs_commit):
    head = git(ksu, "rev-parse", "HEAD").stdout.strip()
    if head != RESUKISU_PIN:
        raise RuntimeError(f"ReSukiSU pin mismatch: {head}; required {RESUKISU_PIN}")
    if susfs_commit != SUSFS_PIN:
        raise RuntimeError(f"SUSFS base mismatch: {susfs_commit}; required {SUSFS_PIN}")
    if not re.search(r"KERNEL_SU_UAPI_VERSION\s*=\s*2\s*;", (ksu / "uapi/supercall.h").read_text()):
        raise RuntimeError("This backport requires the unchanged UAPI 2 header")
    # Compare normalized source text so Windows CRLF checkouts remain valid.
    for name in git(ksu, "ls-tree", "-r", "--name-only", "HEAD", "--", "uapi").stdout.splitlines():
        if (ksu / name).read_text(encoding="utf-8") != git(ksu, "show", f"HEAD:{name}").stdout:
            raise RuntimeError(f"Modified UAPI file rejected: {name}")
    if '#define SUSFS_VERSION "v2.3.0"' not in (common / "include/linux/susfs.h").read_text():
        raise RuntimeError("Expected SUSFS v2.3.0 source header")
    makefile = (common / "Makefile").read_text()
    if not re.search(r"^VERSION\s*=\s*6\s*$", makefile, re.M) or not re.search(r"^PATCHLEVEL\s*=\s*1\s*$", makefile, re.M):
        raise RuntimeError("Only the Linux 6.1 integration is supported")


def receipt(common, ksu):
    paths = [(ksu, "kernel/feature/sucompat.c"), (ksu, "kernel/supercall/dispatch.c"),
             (ksu, "kernel/supercall/supercall.c"), (common, "fs/exec.c")]
    return {
        "port": PORT_ID, "resukisu_commit": RESUKISU_PIN, "susfs_base": SUSFS_PIN,
        "upstream_exec_fix": UPSTREAM, "uapi": 2, "driver_name": "[ksu_driver]",
        "extra_session_commands": ["GET_WRAPPER_FD", "DISABLE_ESCAPE_TO_ROOT"],
        "patch_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.glob("*.patch")},
        "source_sha256": {p: hashlib.sha256((r / p).read_bytes()).hexdigest() for r, p in paths},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--common", type=Path, required=True)
    parser.add_argument("--ksu", type=Path, required=True)
    parser.add_argument("--susfs-commit", required=True)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--image", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    try:
        validate_identity(args.common, args.ksu, args.susfs_commit)
        state = apply_pair(args.common, args.ksu, args.verify_only)
        if args.image and IMAGE_MARKER not in args.image.read_bytes():
            raise RuntimeError("The kernel Image is missing the su-session exec marker")
        if args.config and "CONFIG_KSU_SUSFS=y" not in args.config.read_text().splitlines():
            raise RuntimeError("Final kernel configuration does not enable CONFIG_KSU_SUSFS=y")
        if args.receipt:
            data = receipt(args.common, args.ksu)
            if args.image:
                data["image_sha256"] = hashlib.sha256(args.image.read_bytes()).hexdigest()
            args.receipt.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"{PORT_ID}: {state}; UAPI 2; pinned base verified")
    except (RuntimeError, OSError) as error:
        parser.exit(1, f"su-session: {error}\n")


if __name__ == "__main__":
    main()
