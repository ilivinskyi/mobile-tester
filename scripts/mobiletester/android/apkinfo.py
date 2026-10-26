"""Inspecting APKs and split-APK bundles (.xapk, .apks) without the Android SDK.

Used before installing a build that didn't come from a store: who signed it, is every split signed
by the same key, and does it ask for permissions a normal app of its kind wouldn't.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import struct
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

_SIG_BLOCK_MAGIC = b"APK Sig Block 42"
_SCHEMES = {0x7109871A: "v2", 0xF05368C0: "v3", 0x1B93AD61: "v3.1"}

# Permissions and bindings that deserve a human look in a third-party app.
NOTABLE_PERMISSIONS = {
    "android.permission.BIND_ACCESSIBILITY_SERVICE", "android.permission.BIND_DEVICE_ADMIN",
    "android.permission.BIND_NOTIFICATION_LISTENER_SERVICE", "android.permission.SYSTEM_ALERT_WINDOW",
    "android.permission.REQUEST_INSTALL_PACKAGES", "android.permission.QUERY_ALL_PACKAGES",
    "android.permission.READ_SMS", "android.permission.SEND_SMS", "android.permission.RECEIVE_SMS",
    "android.permission.READ_CALL_LOG", "android.permission.CALL_PHONE", "android.permission.READ_CONTACTS",
    "android.permission.RECORD_AUDIO", "android.permission.MANAGE_EXTERNAL_STORAGE",
    "android.permission.PACKAGE_USAGE_STATS", "android.permission.READ_PHONE_STATE",
}


@dataclass
class ApkInfo:
    file: str
    package: str = ""
    version_name: str = ""
    version_code: str = ""
    schemes: list[str] = field(default_factory=list)
    cert_sha256: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    deep_links: list[str] = field(default_factory=list)


# --- binary manifest -------------------------------------------------------------------------

def _string_pool(data: bytes, offset: int) -> list[str]:
    _, header_size, _, count, _, flags, strings_start, _ = struct.unpack_from("<HHIIIIII", data, offset)
    utf8 = bool(flags & 0x100)
    offsets = struct.unpack_from(f"<{count}I", data, offset + header_size)
    base = offset + strings_start
    strings = []
    for off in offsets:
        p = base + off
        if utf8:
            p += 2 if data[p] & 0x80 else 1           # length in characters, unused
            n = data[p]
            if n & 0x80:
                n = ((n & 0x7F) << 8) | data[p + 1]
                p += 1
            strings.append(data[p + 1:p + 1 + n].decode("utf-8", "replace"))
        else:
            n = struct.unpack_from("<H", data, p)[0]
            if n & 0x8000:
                n = ((n & 0x7FFF) << 16) | struct.unpack_from("<H", data, p + 2)[0]
                p += 2
            strings.append(data[p + 2:p + 2 + n * 2].decode("utf-16le", "replace"))
    return strings


_TYPE_REFERENCE, _TYPE_STRING, _TYPE_INT_DEC, _TYPE_INT_HEX, _TYPE_BOOLEAN = 0x01, 0x03, 0x10, 0x11, 0x12


@dataclass(frozen=True)
class ResourceRef:
    """An attribute value that points into resources.arsc (e.g. android:label="@string/app_name")."""
    res_id: int


def _events(axml: bytes):
    """Yield ("start", tag, attributes) and ("end", tag, {}) in document order for a binary XML file."""
    pos = struct.unpack_from("<H", axml, 2)[0]  # skip the XML chunk header
    strings: list[str] = []
    while pos < len(axml):
        chunk_type, header_size, size = struct.unpack_from("<HHI", axml, pos)
        if chunk_type == 0x0001:
            strings = _string_pool(axml, pos)
        elif chunk_type == 0x0102:
            name = strings[struct.unpack_from("<I", axml, pos + 20)[0]]
            attr_start, attr_size, attr_count = struct.unpack_from("<HHH", axml, pos + 24)
            attrs: dict = {}
            for i in range(attr_count):
                a = pos + 16 + attr_start + i * attr_size
                _, a_name, raw, _, _, data_type, value = struct.unpack_from("<IIIHBBI", axml, a)
                key = strings[a_name] if a_name < len(strings) else ""
                if raw != 0xFFFFFFFF:
                    attrs[key] = strings[raw]
                elif data_type == _TYPE_BOOLEAN:
                    attrs[key] = value != 0
                elif data_type in (_TYPE_INT_DEC, _TYPE_INT_HEX):
                    attrs[key] = value
                elif data_type == _TYPE_REFERENCE:
                    attrs[key] = ResourceRef(value)
                else:
                    attrs[key] = raw
            yield "start", name, attrs
        elif chunk_type == 0x0103:
            yield "end", strings[struct.unpack_from("<I", axml, pos + 20)[0]], {}
        pos += size if size else header_size


def _elements(axml: bytes):
    """Yield (tag, {attribute: str | int | bool | ResourceRef}) for every start tag of a binary XML file."""
    for kind, name, attrs in _events(axml):
        if kind == "start":
            yield name, attrs


def parse_manifest(axml: bytes) -> tuple[dict, list[str]]:
    """(manifest attributes, permissions) from a binary AndroidManifest.xml.

    Permissions include <uses-permission> names and the `permission` guarding any component
    (that's how accessibility services and device admins show up).
    """
    manifest: dict = {}
    permissions: list[str] = []
    for name, attrs in _elements(axml):
        if name == "manifest" and not manifest:
            manifest = attrs
        elif name in ("uses-permission", "uses-permission-sdk-23") and isinstance(attrs.get("name"), str):
            permissions.append(attrs["name"])
        elif isinstance(attrs.get("permission"), str):
            permissions.append(attrs["permission"])
    return manifest, sorted(set(permissions))


_VIEW, _BROWSABLE = "android.intent.action.VIEW", "android.intent.category.BROWSABLE"
_PATH_KEYS = {"path": "", "pathPrefix": "*", "pathPattern": "", "pathSuffix": "", "pathAdvancedPattern": ""}


def _filter_links(data: list[dict], verified: bool) -> list[str]:
    """The URIs one intent filter accepts: every scheme with every host and path (that's how Android combines
    the <data> elements of a filter). `*` after a prefix means any path below it."""
    schemes = [d["scheme"] for d in data if isinstance(d.get("scheme"), str)]
    hosts = [d["host"] for d in data if isinstance(d.get("host"), str)]
    paths = [f"*{d[key]}" if key == "pathSuffix" else d[key] + star
             for d in data for key, star in _PATH_KEYS.items() if isinstance(d.get(key), str)]
    links = []
    for scheme in schemes:
        if not hosts:
            links.append(f"{scheme}:")
            continue
        for host in hosts:
            for path in paths or [""]:
                link = f"{scheme}://{host}{path}"
                links.append(link + (" (verified App Link)" if verified and scheme in ("http", "https") else ""))
    return links


def deep_links(axml: bytes) -> list[str]:
    """Links the app opens from a browser, a notification or another app: its VIEW + BROWSABLE intent filters."""
    links: list[str] = []
    actions: set[str] = set()
    categories: set[str] = set()
    data: list[dict] = []
    verified = False
    for kind, name, attrs in _events(axml):
        if name == "intent-filter" and kind == "start":
            actions, categories, data, verified = set(), set(), [], attrs.get("autoVerify") is True
        elif name == "intent-filter":
            if _VIEW in actions and _BROWSABLE in categories:
                links += [link for link in _filter_links(data, verified) if link not in links]
        elif kind == "start" and name == "action":
            actions.add(str(attrs.get("name", "")))
        elif kind == "start" and name == "category":
            categories.add(str(attrs.get("name", "")))
        elif kind == "start" and name == "data":
            data.append(attrs)
    return links


def application_label(axml: bytes) -> str | ResourceRef | None:
    """The <application android:label>: a literal string, or a reference to resolve with resource_string."""
    for name, attrs in _elements(axml):
        if name == "application":
            label = attrs.get("label")
            return label if isinstance(label, (str, ResourceRef)) else None
    return None


# --- resources.arsc --------------------------------------------------------------------------

_RES_TABLE_PACKAGE, _RES_TABLE_TYPE = 0x0200, 0x0201
_NO_ENTRY32, _NO_ENTRY16 = 0xFFFFFFFF, 0xFFFF
_FLAG_SPARSE, _FLAG_OFFSET16 = 0x01, 0x02
_ENTRY_COMPLEX, _ENTRY_COMPACT = 0x0001, 0x0008


def _entry_offset(arsc: bytes, chunk: int, header_size: int, flags: int, count: int, index: int) -> int | None:
    table = chunk + header_size
    if flags & _FLAG_SPARSE:
        for i in range(count):
            idx, off = struct.unpack_from("<HH", arsc, table + i * 4)
            if idx == index:
                return off * 4
        return None
    if index >= count:
        return None
    if flags & _FLAG_OFFSET16:
        off = struct.unpack_from("<H", arsc, table + index * 2)[0]
        return None if off == _NO_ENTRY16 else off * 4
    off = struct.unpack_from("<I", arsc, table + index * 4)[0]
    return None if off == _NO_ENTRY32 else off


def _entry_value(arsc: bytes, entry: int) -> tuple[int, int] | None:
    """(data type, data) of a simple resource entry; None for maps (styles, plurals)."""
    size, flags = struct.unpack_from("<HH", arsc, entry)
    if flags & _ENTRY_COMPACT:
        # Android 14+ compact entry: the flags' high byte is the type and the data follows the key.
        return flags >> 8, struct.unpack_from("<I", arsc, entry + 4)[0]
    if flags & _ENTRY_COMPLEX:
        return None
    _, _, data_type, data = struct.unpack_from("<HBBI", arsc, entry + size)
    return data_type, data


_PSEUDO_REGIONS = ("XA", "XB")  # Android's test locales: "[Çåméŕå]" and right-to-left mirrors


def resource_string(arsc: bytes, res_id: int, locale: str = "", _depth: int = 0) -> str | None:
    """Resolve a string resource like 0x7f11001c from a resources.arsc file.

    `locale` like "en-NL" or "en". Prefers that exact locale, then its language, then the default
    configuration, then any real locale. Pseudo-locales (en-XA, ar-XB) are never picked.
    """
    package_id, type_id, entry_index = res_id >> 24, (res_id >> 16) & 0xFF, res_id & 0xFFFF
    global_strings = _string_pool(arsc, struct.unpack_from("<H", arsc, 2)[0])
    pos = struct.unpack_from("<H", arsc, 2)[0]
    candidates: dict[str, tuple[int, int]] = {}
    while pos < len(arsc):
        chunk_type, header_size, size = struct.unpack_from("<HHI", arsc, pos)
        if chunk_type == _RES_TABLE_PACKAGE and struct.unpack_from("<I", arsc, pos + 8)[0] == package_id:
            inner, end = pos + header_size, pos + size
            while inner < end:
                c_type, c_header, c_size = struct.unpack_from("<HHI", arsc, inner)
                if c_type == _RES_TABLE_TYPE and arsc[inner + 8] == type_id:
                    flags = arsc[inner + 9]
                    count, entries_start = struct.unpack_from("<II", arsc, inner + 12)
                    # ResTable_config: size, mcc, mnc, then language[2] and country[2].
                    lang = arsc[inner + 28:inner + 30].decode("ascii", "ignore").strip("\x00")
                    region = arsc[inner + 30:inner + 32].decode("ascii", "ignore").strip("\x00")
                    offset = _entry_offset(arsc, inner, c_header, flags, count, entry_index)
                    if offset is not None and region not in _PSEUDO_REGIONS:
                        value = _entry_value(arsc, inner + entries_start + offset)
                        key = f"{lang}-{region}" if lang and region else lang
                        if value and key not in candidates:
                            candidates[key] = value
                inner += c_size or c_header
        pos += size or header_size
    language = locale.split("-")[0]
    for key in (locale, language, "", *candidates):
        if key in candidates:
            data_type, data = candidates[key]
            if data_type == _TYPE_STRING and data < len(global_strings):
                return global_strings[data]
            if data_type == _TYPE_REFERENCE and _depth < 3:
                return resource_string(arsc, data, locale, _depth + 1)
            return None
    return None


# --- signatures ------------------------------------------------------------------------------

def _prefixed(buf: bytes, pos: int) -> tuple[bytes, int]:
    n = struct.unpack_from("<I", buf, pos)[0]
    return buf[pos + 4:pos + 4 + n], pos + 4 + n


def signing_certificates(apk: bytes) -> tuple[list[str], list[bytes]]:
    """(schemes, DER certificates) from the APK Signing Block. Empty for v1-only or unsigned APKs."""
    eocd = apk.rfind(b"PK\x05\x06")
    if eocd < 0:
        return [], []
    cd_offset = struct.unpack_from("<I", apk, eocd + 16)[0]
    if apk[cd_offset - 16:cd_offset] != _SIG_BLOCK_MAGIC:
        return [], []
    size = struct.unpack_from("<Q", apk, cd_offset - 24)[0]
    block = apk[cd_offset - size - 8:cd_offset - 24]
    schemes, certs, pos = [], [], 8
    while pos < len(block):
        length, pair_id = struct.unpack_from("<QI", block, pos)
        value = block[pos + 12:pos + 8 + length]
        pos += 8 + length
        if pair_id not in _SCHEMES:
            continue
        schemes.append(_SCHEMES[pair_id])
        if certs:
            continue  # every scheme carries the same signer certificates
        signers, _ = _prefixed(value, 0)
        p = 0
        while p < len(signers):
            signer, p = _prefixed(signers, p)
            signed_data, _ = _prefixed(signer, 0)
            _, q = _prefixed(signed_data, 0)          # digests
            cert_seq, _ = _prefixed(signed_data, q)
            c = 0
            while c < len(cert_seq):
                cert, c = _prefixed(cert_seq, c)
                certs.append(cert)
    return schemes, certs


def certificate_subject(der: bytes) -> str:
    """Human-readable owner of a certificate, via keytool (JDK) or openssl when available."""
    with tempfile.NamedTemporaryFile(suffix=".der", delete=False) as fh:
        fh.write(der)
        path = fh.name
    try:
        if keytool := shutil.which("keytool"):
            out = subprocess.run([keytool, "-printcert", "-file", path], capture_output=True, text=True).stdout
            for line in out.splitlines():
                if line.strip().startswith(("Owner:", "Eigenaar:")):
                    return line.split(":", 1)[1].strip()
        if openssl := shutil.which("openssl"):
            out = subprocess.run([openssl, "x509", "-inform", "DER", "-in", path, "-noout", "-subject"],
                                 capture_output=True, text=True).stdout
            return out.strip().removeprefix("subject=").strip()
        return "(install a JDK or openssl to show the certificate owner)"
    finally:
        Path(path).unlink(missing_ok=True)


# --- files -----------------------------------------------------------------------------------

def _apks_in(path: Path) -> list[tuple[str, bytes]]:
    if path.suffix.lower() == ".apk":
        return [(path.name, path.read_bytes())]
    with zipfile.ZipFile(path) as bundle:
        return [(n, bundle.read(n)) for n in bundle.namelist() if n.lower().endswith(".apk")]


def inspect(path: Path) -> dict:
    infos: list[ApkInfo] = []
    subjects: dict[str, str] = {}
    for name, data in _apks_in(path):
        info = ApkInfo(file=name)
        info.schemes, certs = signing_certificates(data)
        for der in certs:
            digest = hashlib.sha256(der).hexdigest()
            info.cert_sha256.append(digest)
            if digest not in subjects:
                subjects[digest] = certificate_subject(der)
        with zipfile.ZipFile(io.BytesIO(data)) as apk:
            if "AndroidManifest.xml" in apk.namelist():
                axml = apk.read("AndroidManifest.xml")
                manifest, info.permissions = parse_manifest(axml)
                info.deep_links = deep_links(axml)
                info.package = str(manifest.get("package", ""))
                info.version_name = str(manifest.get("versionName", ""))
                info.version_code = str(manifest.get("versionCode", ""))
        infos.append(info)
    base = next((i for i in infos if i.version_name or i.permissions), infos[0] if infos else ApkInfo(file=""))
    signer_sets = {tuple(i.cert_sha256) for i in infos}
    return {
        "file": str(path),
        "package": base.package,
        "version_name": base.version_name,
        "version_code": base.version_code,
        "apks": [i.__dict__ for i in infos],
        "signers": {d: subjects[d] for d in subjects},
        "same_signer_for_all": len(signer_sets) == 1 and () not in signer_sets,
        "notable_permissions": sorted(p for p in base.permissions if p in NOTABLE_PERMISSIONS),
        "permissions": base.permissions,
        "deep_links": base.deep_links,
    }


def extract_bundle(path: Path, target: Path) -> list[Path]:
    """Write the APKs of a .xapk/.apks bundle to `target` for `adb install-multiple`."""
    target.mkdir(parents=True, exist_ok=True)
    files = []
    for name, data in _apks_in(path):
        out = target / Path(name).name
        out.write_bytes(data)
        files.append(out)
    return files


def to_text(result: dict) -> str:
    lines = [f"package: {result['package']}  version: {result['version_name']} ({result['version_code']})"]
    for apk in result["apks"]:
        signer = ", ".join(d[:16] + "..." for d in apk["cert_sha256"]) or "UNSIGNED / v1 only"
        lines.append(f"  {apk['file']}: {'+'.join(apk['schemes']) or '-'} signer {signer}")
    for digest, subject in result["signers"].items():
        lines.append(f"signer {digest}: {subject}")
    lines.append("all APKs signed by the same key: " + ("yes" if result["same_signer_for_all"] else "NO"))
    notable = result["notable_permissions"]
    lines.append("permissions of note: " + (", ".join(notable) if notable else "none"))
    lines.append(f"all permissions ({len(result['permissions'])}): " + json.dumps(result["permissions"]))
    links = result.get("deep_links") or []
    lines.append(f"deep links ({len(links)}):" if links else "deep links: none declared")
    lines += [f"  {link}" for link in links]
    return "\n".join(lines)
