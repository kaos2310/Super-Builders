#!/bin/bash
set -euo pipefail

KERNEL_ROOT="${1:?}"
KERNEL_VER="${2:?}"
SUFFIX="${3:-SukiSU}"

cd "$KERNEL_ROOT"

if [[ "$KERNEL_VER" == "5."* ]] || [[ "$KERNEL_VER" == "6.1" ]]; then
  perl -i -0777 -pe "s/(.*)echo \"\\\$res\"/\$1echo \"\\\$res-${SUFFIX}\"/s" ./common/scripts/setlocalversion
else
  perl -i -0777 -pe "s/(.*)echo \"\\\$\\{KERNELVERSION\\}\\\$\\{file_localversion\\}\\\$\\{config_localversion\\}\\\$\\{LOCALVERSION\\}\\\$\\{scm_version\\}\"/\$1echo \"\\\${KERNELVERSION}\\\${file_localversion}\\\${config_localversion}\\\${LOCALVERSION}-${SUFFIX}\\\${scm_version}\"/s" ./common/scripts/setlocalversion
fi

if [ -f "build/build.sh" ]; then
  sed -i 's/-dirty//' ./common/scripts/setlocalversion
else
  sed -i "/stable_scmversion_cmd/s/-maybe-dirty//g" ./build/kernel/kleaf/impl/stamp.bzl
  sed -i 's/-dirty//' ./common/scripts/setlocalversion
  rm -rf ./common/android/abi_gki_protected_exports_*
  perl -pi -e 's/^\s*"protected_exports_list"\s*:\s*"android\/abi_gki_protected_exports_aarch64",\s*$//;' ./common/BUILD.bazel
fi

# Keep CONFIG_KSU_SUSFS_ENABLE_LOG compiled in, but start each boot with
# logging disabled. The runtime setter remains untouched, so
# `ksu_susfs enable_log 1` and `ksu_susfs enable_log 0` continue to work.
SUSFS_SOURCE="./common/fs/susfs.c"
SUSFS_FRAGMENT="./common/arch/arm64/configs/sukisu_gki.fragment"

if [ -f "$SUSFS_SOURCE" ]; then
  python3 - "$SUSFS_SOURCE" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")

# SUSFS revisions use either a normal bool or a jump-label static key for the
# runtime logging state. Support both implementations and change only the
# boot default; never remove the runtime enable/disable path.
bool_declaration = re.compile(
    r"^(?P<indent>[ \t]*)(?P<prefix>(?:static[ \t]+)?bool[ \t]+"
    r"susfs_is_log_enabled(?:[ \t]+__read_mostly)?)"
    r"[ \t]*(?:=[ \t]*(?:true|false|0|1))?[ \t]*;[ \t]*$",
    re.MULTILINE,
)
static_key_declaration = re.compile(
    r"^(?P<indent>[ \t]*)DEFINE_STATIC_KEY_(?P<state>TRUE|FALSE)"
    r"\([ \t]*susfs_is_log_enabled[ \t]*\)[ \t]*;[ \t]*$",
    re.MULTILINE,
)

bool_matches = list(bool_declaration.finditer(text))
key_matches = list(static_key_declaration.finditer(text))
implementation_count = len(bool_matches) + len(key_matches)

if implementation_count != 1:
    candidates = [
        f"{line_no}: {line}"
        for line_no, line in enumerate(text.splitlines(), 1)
        if "susfs_is_log_enabled" in line
    ]
    detail = "\n".join(candidates) if candidates else "<no symbol occurrences>"
    raise SystemExit(
        "Expected exactly one SUSFS logging-state implementation, "
        f"found {implementation_count}:\n{detail}"
    )

setter = re.compile(
    r"\bvoid[ \t\r\n]+susfs_set_log[ \t]*\([ \t\r\n]*"
    r"bool[ \t]+enabled[ \t\r\n]*\)"
)
if not setter.search(text):
    raise SystemExit("SUSFS runtime logging setter susfs_set_log(bool enabled) is missing")

if key_matches:
    match = key_matches[0]
    default_off = (
        f"{match.group('indent')}"
        "DEFINE_STATIC_KEY_FALSE(susfs_is_log_enabled);"
    )
    text = text[: match.start()] + default_off + text[match.end() :]

    enable_call = re.compile(
        r"\bstatic_branch_enable[ \t]*\([ \t]*"
        r"&susfs_is_log_enabled[ \t]*\)[ \t]*;"
    )
    disable_call = re.compile(
        r"\bstatic_branch_disable[ \t]*\([ \t]*"
        r"&susfs_is_log_enabled[ \t]*\)[ \t]*;"
    )
    if not enable_call.search(text) or not disable_call.search(text):
        raise SystemExit(
            "SUSFS static-key runtime toggle is incomplete: "
            "static_branch_enable/disable is missing"
        )

    verified = list(static_key_declaration.finditer(text))
    if len(verified) != 1 or verified[0].group("state") != "FALSE":
        raise SystemExit("SUSFS static-key default-off verification failed")
    implementation = "static key"
else:
    match = bool_matches[0]
    default_off = f"{match.group('indent')}{match.group('prefix')} = false;"
    text = text[: match.start()] + default_off + text[match.end() :]

    assignment = re.compile(
        r"\bsusfs_is_log_enabled[ \t]*=[ \t]*enabled[ \t]*;"
    )
    if not assignment.search(text):
        raise SystemExit(
            "SUSFS bool runtime toggle is incomplete: "
            "susfs_is_log_enabled = enabled is missing"
        )

    verified = list(bool_declaration.finditer(text))
    if len(verified) != 1 or "= false;" not in verified[0].group(0):
        raise SystemExit("SUSFS bool default-off verification failed")
    implementation = "bool"

path.write_text(text, encoding="utf-8")
print(f"SUSFS logging default set to off ({implementation}): {default_off.strip()}")
print("SUSFS runtime toggle retained: enable_log 1 / enable_log 0")
PY
fi

if [ -f "$SUSFS_FRAGMENT" ]; then
  grep -qx 'CONFIG_KSU_SUSFS_ENABLE_LOG=y' "$SUSFS_FRAGMENT" || {
    echo "::error::CONFIG_KSU_SUSFS_ENABLE_LOG must remain enabled"
    exit 1
  }
fi

cd common
git config --global user.name "github-actions[bot]"
git config --global user.email "github-actions[bot]@users.noreply.github.com"
git add .
git commit -m "${SUFFIX}: Clean Build" || true
