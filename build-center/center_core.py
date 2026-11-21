"""Shared network, immutable source resolution and checked download contracts."""
from __future__ import annotations

import hashlib
import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from ci.versioning import formula_from_kbuild, version_code

ROOT = Path(__file__).resolve().parent
SHA = re.compile(r"^[0-9a-f]{40}$")
MAX_DOWNLOAD = 512 * 1024 * 1024


class CenterError(RuntimeError):
    pass


def allowed_url(url: str, method: str = "GET", download: bool = False) -> bool:
    try:
        u = urllib.parse.urlsplit(url)
        if u.scheme != "https" or u.username or u.password or u.port not in (None, 443):
            return False
        if method == "POST":
            return u.hostname == "api.github.com" and bool(re.fullmatch(
                r"/repos/[\w.-]+/[\w.-]+/actions/workflows/build-center\.yml/dispatches", u.path))
        if method != "GET":
            return False
        if u.hostname == "api.github.com":
            return u.path=="/repositories/957055748" or u.path.startswith(("/repos/","/repositories/957055748/"))
        if u.hostname == "gitlab.com":
            return u.path.startswith(("/api/v4/projects/simonpunk%2Fsusfs4ksu/",
                                      "/simonpunk/susfs4ksu/-/archive/"))
        if download and u.hostname in ("github.com", "codeload.github.com"):
            return bool(re.fullmatch(r"/[\w.-]+/[\w.-]+/(?:releases/download|zip|tar\.gz)/.+", u.path))
    except (ValueError, TypeError):
        pass
    return False


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Never send a GitHub token to a redirect host."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        u = urllib.parse.urlsplit(newurl)
        if u.scheme != "https" or u.username or u.password:
            raise CenterError("Unsichere Download-Weiterleitung abgelehnt.")
        result = super().redirect_request(req, fp, code, msg, headers, newurl)
        if result is not None:
            result.remove_header("Authorization")
        return result


def request(url, token="", method="GET", data=None, *, binary=False, allow_http_errors=False):
    if not allowed_url(url, method, download=binary):
        raise CenterError("Diese Netzwerkadresse ist für die App nicht freigegeben.")
    headers = {"User-Agent": "KAOSLAB-SukiSU-Build-Center/1.0", "Accept": "application/vnd.github+json"}
    if urllib.parse.urlsplit(url).hostname == "api.github.com":
        headers["X-GitHub-Api-Version"] = "2022-11-28"
        if token:
            headers["Authorization"] = "Bearer " + token
    if binary:
        headers["Accept"] = "application/octet-stream"
    if data is not None:
        data = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.build_opener(SafeRedirect()).open(req, timeout=90 if binary else 35) as response:
            raw = response.read(MAX_DOWNLOAD + 1 if binary else 8 * 1024 * 1024)
            if binary and len(raw) > MAX_DOWNLOAD:
                raise CenterError("Download überschreitet das Größenlimit von 512 MiB.")
            result_headers = {k.lower(): v for k, v in response.headers.items() if k.lower() in (
                "link", "x-ratelimit-remaining", "x-ratelimit-reset", "retry-after", "etag")}
            if binary:
                return raw
            return {"status": response.status, "headers": result_headers,
                    "data": json.loads(raw) if raw else None}
    except urllib.error.HTTPError as exc:
        if allow_http_errors and not binary:
            try:
                detail = json.loads(exc.read(8192))
            except (ValueError, UnicodeDecodeError):
                detail = {}
            finally:
                exc.close()
            return {"status": exc.code,
                    "headers": {k.lower(): v for k, v in exc.headers.items() if k.lower() in (
                        "x-ratelimit-remaining", "x-ratelimit-reset", "retry-after")},
                    "data": {"message": detail.get("message", "")} if isinstance(detail, dict) else {}}
        exc.close()
        message = {401: "GitHub-Token ungültig oder abgelaufen.",
                   403: "Zugriff verweigert oder API-Limit erreicht.",
                   404: "Quelle oder Workflow nicht gefunden.",
                   410: "Dieses Artefakt ist abgelaufen.",
                   422: "GitHub hat den Build-Auftrag abgelehnt. Ref und Workflow-Eingaben prüfen."}.get(
                       exc.code, f"Netzwerkanfrage fehlgeschlagen (HTTP {exc.code}).")
        raise CenterError(message) from None
    except urllib.error.URLError as exc:
        raise CenterError("Verbindung fehlgeschlagen: " + str(exc.reason)) from None


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def checked_file(raw, name, expected="", kind="file"):
    """Verify the outer artifact digest, then return the actual flash ZIP."""
    if expected:
        digest = expected.removeprefix("sha256:").lower()
        if not re.fullmatch(r"[a-f0-9]{64}", digest) or sha256(raw) != digest:
            raise CenterError("SHA-256-Prüfung fehlgeschlagen. Datei wird nicht bereitgestellt.")
    safe_name = Path(name.replace("\\", "/")).name
    if not safe_name or safe_name in (".", ".."):
        raise CenterError("Ungültiger Dateiname.")
    if kind == "kernel-artifact":
        if not expected:
            raise CenterError("Für Kernel-Artefakte ist eine SHA-256-Prüfsumme erforderlich.")
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as outer:
                candidates = []
                for info in outer.infolist():
                    path = PurePosixPath(info.filename)
                    if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
                        raise CenterError("Unsicherer Pfad im Artefakt.")
                    if info.file_size > MAX_DOWNLOAD:
                        raise CenterError("Artefakt-Eintrag zu groß.")
                    if not info.is_dir() and info.filename.lower().endswith(".zip"):
                        candidates.append(info)
                if len(candidates) != 1:
                    raise CenterError("Strict-Artefakt enthält nicht genau eine flashbare ZIP.")
                info = candidates[0]
                raw = outer.read(info)
                safe_name = PurePosixPath(info.filename).name
        except zipfile.BadZipFile:
            raise CenterError("Beschädigte ZIP-Datei.") from None
    if kind in ('kernel', 'kernel-artifact'):
        if not expected:
            raise CenterError('Für Kernel-Pakete ist eine SHA-256-Prüfsumme erforderlich.')
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as inner:
                names = set(inner.namelist())
                if len(names) != len(inner.namelist()):
                    raise CenterError('Mehrdeutige Einträge im Kernel-Paket.')
                if "anykernel.sh" not in names or not any(
                    n in names for n in ("Image", "Image.gz", "Image.gz-dtb", "Image.lz4")):
                    raise CenterError("Kernel-ZIP enthält kein vollständiges AnyKernel3-Paket.")
                if "STRICT-KMI.txt" not in names:
                    raise CenterError("Nachweis des Strict-KMI-Profils fehlt im Kernel-Paket.")
                if 'FIRMWARE-TARGET.json' not in names or 'Image' not in names:
                    raise CenterError('Der geprüfte EZJB-Firmware-Nachweis fehlt.')
                receipt = json.loads(inner.read('FIRMWARE-TARGET.json'))
                if (receipt.get('firmware') != 'S928BXXU6EZJB' or receipt.get('csc') != 'EUX'
                        or receipt.get('profile') != 'S928BXXU6EZJB-EUX-android14-6.1.162'
                        or receipt.get('image_sha256') != sha256(inner.read('Image'))):
                    raise CenterError('Kernel-Image und EZJB-Firmware-Nachweis stimmen nicht überein.')
        except zipfile.BadZipFile:
            raise CenterError("Beschädigte ZIP-Datei.") from None
        except (ValueError, KeyError):
            raise CenterError('Ungültiger EZJB-Firmware-Nachweis.') from None
    return raw, safe_name, sha256(raw)


def resolve_sources(channel="main", token="", get=request, source_ref=None):
    if channel not in ("main", "release"):
        raise CenterError("Unbekannter Update-Kanal.")
    if source_ref is not None and (not SHA.fullmatch(source_ref) or channel != "main"):
        raise CenterError("Ein expliziter Quellstand erfordert eine vollständige Commit-ID im main-Kanal.")
    base = "https://api.github.com/repositories/957055748"
    repository=get(base,token)['data']
    if repository.get('id')!=957055748 or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository.get('full_name','')):
        raise CenterError('Offizielle SukiSU-Projektidentität konnte nicht bestätigt werden.')
    release = get(base + "/releases/latest", token)["data"]
    ref = source_ref or ("main" if channel == "main" else release["tag_name"])
    commit = get(base + "/commits/" + urllib.parse.quote(ref, safe=""), token)["data"]
    pin = commit["sha"]
    if not SHA.fullmatch(pin):
        raise CenterError("Ungültige SukiSU-Commit-ID.")
    if source_ref is not None and pin != source_ref:
        raise CenterError("Der aufgelöste SukiSU-Commit stimmt nicht mit dem Auftrag überein.")
    counts = get(base + f"/commits?sha={pin}&per_page=1", token)
    last = re.search(r"[?&]page=(\d+)[^>]*>; rel=\"last\"", counts["headers"].get("link", ""))
    count = int(last[1]) if last else len(counts["data"])
    if count < 2815:
        raise CenterError("Vollständige SukiSU-Commitanzahl fehlt in der API-Antwort.")
    kbuild = get(base + "/contents/kernel/Kbuild?ref=" + pin, token)["data"]
    import base64
    text = base64.b64decode(kbuild["content"]).decode()
    try:
        formula=formula_from_kbuild(text);code=version_code(count,formula)
    except ValueError as error:
        raise CenterError('SukiSU-Versionsformel konnte nicht eindeutig geprüft werden: '+str(error)) from None
    gitlab = "https://gitlab.com/api/v4/projects/simonpunk%2Fsusfs4ksu/repository"
    sus_commit = get(gitlab + "/commits/gki-android14-6.1")["data"]
    sus_pin = sus_commit["id"]
    if not SHA.fullmatch(sus_pin):
        raise CenterError("Ungültige SuSFS-Commit-ID.")
    header = get(gitlab + "/files/kernel_patches%2Finclude%2Flinux%2Fsusfs.h?ref=" + sus_pin)["data"]
    sus_text = base64.b64decode(header["content"]).decode()
    match = re.search(r'^#define\s+SUSFS_VERSION\s+"(v[\w.+-]+)"', sus_text, re.M)
    if not match:
        raise CenterError("SuSFS-Version konnte nicht aus dem offiziellen Header gelesen werden.")
    version = match[1]
    manager = next((a for a in release.get("assets", [])
                    if a["name"].endswith(".apk") and f"_{code}-" in a["name"]), None)
    tag = f"s928b-ezjb-suki{code}-susfs{version.removeprefix('v')}-{pin[:8]}-{sus_pin[:8]}"
    return {"schema": 1, "channel": "pinned" if source_ref else channel,
            "sukisu_requested_ref": source_ref, "sukisu_commit": pin, "sukisu_code": code,
            "sukisu_count": count, "sukisu_tag": release["tag_name"],
            "sukisu_version_formula":formula,
            "sukisu_repository":repository['full_name'],"sukisu_repository_id":957055748,
            "sukisu_message": commit["commit"]["message"].splitlines()[0],
            "susfs_commit": sus_pin, "susfs_version": version, "release_tag": tag,
            "profile": "S928BXXU6EZJB-EUX-android14-6.1.162", "firmware": "S928BXXU6EZJB", "manager": manager,
            "susfs_source_url": f"https://gitlab.com/simonpunk/susfs4ksu/-/archive/{sus_pin}/susfs4ksu-{sus_pin}.zip"}
