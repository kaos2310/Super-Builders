#!/bin/bash
set -euo pipefail

COMMON_TREE="${1:?common kernel tree}"
OVERLAY_ARCHIVE="${2:?Samsung ZZHL source port archive}"
EXPECTED_OVERLAY_SHA256="${3:?expected overlay SHA256}"
EXPECTED_AOSP_COMMIT="${4:?expected AOSP common base commit}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

[[ -e "$COMMON_TREE/.git" ]] || {
  echo "::error::Common kernel Git tree not found: $COMMON_TREE"
  exit 1
}
[[ -f "$OVERLAY_ARCHIVE" ]] || {
  echo "::error::Samsung source port archive not found: $OVERLAY_ARCHIVE"
  exit 1
}

ACTUAL_AOSP_COMMIT=$(git -C "$COMMON_TREE" rev-parse HEAD)
[[ "$ACTUAL_AOSP_COMMIT" == "$EXPECTED_AOSP_COMMIT" ]] || {
  echo "::error::Samsung source port base mismatch: $ACTUAL_AOSP_COMMIT != $EXPECTED_AOSP_COMMIT"
  exit 1
}
[[ -z "$(git -C "$COMMON_TREE" status --porcelain --untracked-files=all)" ]] || {
  echo "::error::Samsung source port requires a clean, freshly synced AOSP common tree"
  git -C "$COMMON_TREE" status --short
  exit 1
}

ACTUAL_OVERLAY_SHA256=$(sha256sum "$OVERLAY_ARCHIVE" | awk '{print $1}')
[[ "$ACTUAL_OVERLAY_SHA256" == "$EXPECTED_OVERLAY_SHA256" ]] || {
  echo "::error::Samsung source port SHA256 mismatch"
  echo "expected=$EXPECTED_OVERLAY_SHA256"
  echo "actual=$ACTUAL_OVERLAY_SHA256"
  exit 1
}

"$PYTHON_BIN" - "$COMMON_TREE" "$OVERLAY_ARCHIVE" <<'PY'
from __future__ import annotations

import csv
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import sys
import tarfile

root = Path(sys.argv[1]).resolve()
archive = Path(sys.argv[2]).resolve()


def safe_relative(raw: str) -> Path:
    posix = PurePosixPath(raw)
    if posix.is_absolute() or not posix.parts or ".." in posix.parts or "." in posix.parts:
        raise SystemExit(f"unsafe Samsung overlay path: {raw!r}")
    if "\\" in raw or posix.parts[0] == ".git":
        raise SystemExit(f"forbidden Samsung overlay path: {raw!r}")
    return Path(*posix.parts)


def git_blob(data: bytes) -> str:
    prefix = b"blob " + str(len(data)).encode("ascii") + b"\0"
    return hashlib.sha1(prefix + data).hexdigest()


members: dict[str, tuple[bytes, int]] = {}
with tarfile.open(archive, "r:xz") as source:
    for member in source:
        if not member.isfile():
            raise SystemExit(f"non-regular Samsung overlay member: {member.name!r}")
        safe_relative(member.name)
        if member.name in members:
            raise SystemExit(f"duplicate Samsung overlay member: {member.name!r}")
        extracted = source.extractfile(member)
        if extracted is None:
            raise SystemExit(f"cannot read Samsung overlay member: {member.name!r}")
        members[member.name] = (extracted.read(), member.mode & 0o777)

expected_metadata = {"SOURCE.txt", "manifest.tsv", "delete.txt"}
actual_metadata = {name for name in members if not name.startswith("files/")}
if actual_metadata != expected_metadata:
    raise SystemExit(
        f"unexpected Samsung overlay metadata: {sorted(actual_metadata ^ expected_metadata)}"
    )

source_text = members["SOURCE.txt"][0].decode("utf-8")
source_markers = (
    "Samsung source: SM-S928B_16_Opensource.zip / S928BXXS6DZG1",
    "Samsung package SHA256: 512c0a0b74646ddbb64ac8adea7c396c90458c2c12cf7f437e9d20282a33fa3c",
    "Target firmware: S928BXXU6ZZHL / EUX",
    "Target: e3q_eur_openx",
    "Chipset: pineapple",
    "AOSP common base: 4bd1b41bff8bb87bed8c3621fa2bb5b2e96f5d8c",
    "Port base: 0f62335d867d7ccc2933ff1e3c5ae6a244d12994",
    "Port method: three-way merge retaining AOSP 6.1.162 and Samsung DZG1 changes",
)
for marker in source_markers:
    if marker not in source_text:
        raise SystemExit(f"Samsung overlay source marker is missing: {marker}")

manifest_text = members["manifest.tsv"][0].decode("utf-8")
reader = csv.DictReader(io.StringIO(manifest_text), delimiter="\t")
expected_fields = ["status", "path", "aosp_git_blob", "ported_git_blob", "size"]
if reader.fieldnames != expected_fields:
    raise SystemExit(f"unexpected Samsung overlay manifest fields: {reader.fieldnames}")

manifest: dict[str, dict[str, str]] = {}
status_counts = {"changed": 0, "ported-only": 0}
for row in reader:
    relative = safe_relative(row["path"]).as_posix()
    if relative in manifest:
        raise SystemExit(f"duplicate Samsung overlay manifest path: {relative}")
    if row["status"] not in status_counts:
        raise SystemExit(f"unexpected Samsung overlay status: {row['status']}")
    if len(row["ported_git_blob"]) != 40:
        raise SystemExit(f"invalid ported Git blob for {relative}")
    base = root / safe_relative(relative)
    if row["status"] == "changed":
        if len(row["aosp_git_blob"]) != 40 or not base.is_file():
            raise SystemExit(f"missing pinned AOSP base file for {relative}")
        if git_blob(base.read_bytes()) != row["aosp_git_blob"]:
            raise SystemExit(f"pinned AOSP base Git blob mismatch: {relative}")
    elif row["aosp_git_blob"] != "-" or base.exists() or base.is_symlink():
        raise SystemExit(f"ported-only path already exists in pinned AOSP base: {relative}")
    archive_name = "files/" + relative
    if archive_name not in members:
        raise SystemExit(f"Samsung overlay payload is missing: {relative}")
    data = members[archive_name][0]
    if len(data) != int(row["size"]):
        raise SystemExit(f"Samsung overlay size mismatch: {relative}")
    if git_blob(data) != row["ported_git_blob"]:
        raise SystemExit(f"Samsung port Git blob mismatch: {relative}")
    manifest[relative] = row
    status_counts[row["status"]] += 1

payload_paths = {name.removeprefix("files/") for name in members if name.startswith("files/")}
if payload_paths != set(manifest):
    raise SystemExit("Samsung overlay payload and manifest path sets differ")
if status_counts != {"changed": 401, "ported-only": 421}:
    raise SystemExit(f"unexpected Samsung overlay counts: {status_counts}")

delete_paths = [line for line in members["delete.txt"][0].decode("utf-8").splitlines() if line]
if len(delete_paths) != 308 or len(set(delete_paths)) != 308:
    raise SystemExit(f"unexpected Samsung deletion count: {len(delete_paths)}")
for raw in delete_paths:
    relative = safe_relative(raw)
    target = root / relative
    if target.is_dir() and not target.is_symlink():
        raise SystemExit(f"Samsung deletion target unexpectedly became a directory: {raw}")

# The complete archive is validated before mutating the ephemeral synced tree.
for raw in delete_paths:
    target = root / safe_relative(raw)
    if target.exists() or target.is_symlink():
        target.unlink()

for relative, row in manifest.items():
    archive_name = "files/" + relative
    data, mode = members[archive_name]
    target = root / safe_relative(relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    os.chmod(target, mode)

for relative, row in manifest.items():
    target = root / safe_relative(relative)
    if git_blob(target.read_bytes()) != row["ported_git_blob"]:
        raise SystemExit(f"post-apply Samsung port mismatch: {relative}")

print(
    "Applied Samsung common source port for ZZHL: "
    f"{status_counts['changed']} changed, "
    f"{status_counts['ported-only']} added, {len(delete_paths)} removed"
)
PY

for SPEC in \
  "Makefile:36a79f031105375d5ef92f3789e7856d72c14a2431c3a5a06d7342297bebcca2" \
  "include/trace/hooks/xhci.h:fda469c283497303230ff7a145d26cc16a80cd8ea5bf4b4eff23705b59da4f29" \
  "drivers/android/vendor_hooks.c:26d3461006c0e4d475147245a53238e066c6be0d286769ce2729e1a230aa1142" \
  "drivers/usb/host/xhci-plat.c:adcb2f8a1c1d923d10908e2ddaaa80db2b5be75b47396613d248d6d4aa877347" \
  "android/abi_gki_aarch64_galaxy:8a33aa1742becd1b334bbfb16f88dbad5086a1220f14a586ea47589d7672ef2c"; do
  RELATIVE=${SPEC%%:*}
  EXPECTED=${SPEC#*:}
  ACTUAL=$(sha256sum "$COMMON_TREE/$RELATIVE" | awk '{print $1}')
  [[ "$ACTUAL" == "$EXPECTED" ]] || {
    echo "::error::Audited Samsung source-port hash mismatch: $RELATIVE"
    echo "expected=$EXPECTED"
    echo "actual=$ACTUAL"
    exit 1
  }
done

grep -qx 'VERSION = 6' "$COMMON_TREE/Makefile"
grep -qx 'PATCHLEVEL = 1' "$COMMON_TREE/Makefile"
grep -qx 'SUBLEVEL = 162' "$COMMON_TREE/Makefile"
echo "Verified SM-S928B Android 17 ZZHL source port on AOSP 6.1.162"
