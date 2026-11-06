#!/usr/bin/env python3
"""Check every effective SuSFS option and its userspace advertisement."""
import argparse
import json
import re
from pathlib import Path


def audit(common, ksu, config):
    definitions = set()
    for path in (common / "fs/Kconfig", ksu / "kernel/Kconfig"):
        definitions.update(re.findall(r"^config (KSU_SUSFS(?:_\w+)?)$", path.read_text(), re.M))
    if "KSU_SUSFS_HARDENED" in definitions:
        raise RuntimeError("Inert legacy HARDENED toggle remains defined")

    values = dict(re.findall(r"^CONFIG_(KSU_SUSFS(?:_\w+)?)=(\w+)$", config.read_text(), re.M))
    if set(values) != definitions or any(value != "y" for value in values.values()):
        raise RuntimeError("Effective SuSFS configuration differs from the full supported profile")

    source = (common / "fs/susfs.c").read_text()
    start = source.index("void susfs_get_enabled_features(")
    end = source.index("/* show_variant */", start)
    advertised = re.findall(r'copy_config_to_buf\("CONFIG_(KSU_SUSFS_\w+)\\n"', source[start:end])
    if len(advertised) != len(set(advertised)) or set(advertised) != definitions - {"KSU_SUSFS"}:
        raise RuntimeError("Userspace feature list does not match enabled SuSFS settings")
    for name in advertised:
        pattern = r'#ifdef CONFIG_' + name + r'\s+info->err = copy_config_to_buf\("CONFIG_' + name + r'\\n"'
        if not re.search(pattern, source[start:end]):
            raise RuntimeError("Feature advertisement has an incorrect build guard for " + name)
    return {
        "settings": {"CONFIG_" + name: value for name, value in sorted(values.items())},
        "enabled_options": len(values),
        "advertised_features": len(advertised),
        "hidden_name_advertised": "KSU_SUSFS_HIDDEN_NAME" in advertised,
        "inert_hardened_toggle_removed": True,
        "device_tested": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--common", type=Path, required=True)
    parser.add_argument("--ksu", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    result = audit(args.common, args.ksu, args.config)
    encoded = json.dumps(result, indent=2) + "\n"
    if args.receipt:
        args.receipt.write_text(encoded)
    print(encoded, end="")
