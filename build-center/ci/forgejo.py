"""Resolve the reviewed Nova build from its official Forgejo repository."""
from pathlib import Path
import subprocess

if __package__:
    from .versions import FORGEJO_REPOSITORY, FORGEJO_URL, identify
else:
    from versions import FORGEJO_REPOSITORY, FORGEJO_URL, identify


PIN = "54d6da4e7e792a7d0e70c4f5ec70f1ac1c32fa2b"
CODE = 35095
COUNT = 4099
TAG = "v3.0.0-r1"
BUILT_ZYGISK_PIN = "7431f46765390125393f5763e670072b46c0eafc"
PROFILE = "S928BXXU6EZJB-EUX-android14-6.1.162"


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], encoding="utf-8").strip()


def verify(source):
    if git(source, "remote", "get-url", "origin") != FORGEJO_URL:
        raise ValueError("Nova checkout did not come from the official Forgejo repository")
    if git(source, "rev-parse", "HEAD") != PIN:
        raise ValueError("Unexpected Nova commit")
    count = int(git(source, "rev-list", "--count", "HEAD"))
    identity = identify(git(source, "show", "HEAD:kernel/Kbuild"), count)
    if count != COUNT or identity["sukisu_code"] != CODE or identity["sukisu_family"] != "nova":
        raise ValueError("Unexpected Nova version mapping")
    gitlink = git(source, "ls-tree", "HEAD", "external/BuiltZygisk").split()
    if gitlink[:3] != ["160000", "commit", BUILT_ZYGISK_PIN]:
        raise ValueError("Nova BuiltZygisk gitlink differs from the reviewed source")
    return identity


def checkout(destination):
    subprocess.run(
        ["git", "clone", "--no-checkout", "--single-branch", "--branch", "main", FORGEJO_URL, str(destination)],
        check=True,
    )
    subprocess.run(["git", "-C", str(destination), "checkout", "--detach", PIN], check=True)
    verify(destination)


def resolve(source):
    from center_core import request, resolve_susfs

    source = Path(source)
    identity = verify(source)
    susfs = resolve_susfs(request)
    version = susfs["susfs_version"].removeprefix("v")
    pair = f"{PIN[:8]}-{susfs['susfs_commit'][:8]}"
    return {
        "schema": 1, **identity, **susfs,
        "sukisu_repository": FORGEJO_REPOSITORY, "sukisu_repository_url": FORGEJO_URL,
        "sukisu_source_kind": "official-forgejo-main",
        "channel": "main", "sukisu_requested_ref": None, "sukisu_commit": PIN,
        "sukisu_count": COUNT, "sukisu_tag": TAG,
        "sukisu_message": git(source, "show", "-s", "--format=%s", "HEAD"),
        "built_zygisk_commit": BUILT_ZYGISK_PIN,
        "release_tag": f"s928b-ezjb-suki{CODE}-susfs{version}-{pair}",
        "profile": PROFILE, "firmware": "S928BXXU6EZJB", "manager": None,
        "module_design": "zeromount-3d",
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    checkout(parser.parse_args().destination)
