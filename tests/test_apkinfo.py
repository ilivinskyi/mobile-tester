import io
import struct
import zipfile

from binxml import binary_xml
from mobiletester.android import apkinfo


def test_parse_binary_manifest():
    axml = binary_xml([
        ("manifest", {"versionCode": 420, "versionName": "4.2.0", "package": "com.example.pantry"}),
        ("uses-permission", {"name": "android.permission.CAMERA"}),
        ("uses-permission", {"name": "android.permission.INTERNET"}),
        ("application", {"label": "Pantry"}),
        ("service", {"name": ".SyncService", "permission": "android.permission.BIND_JOB_SERVICE"}),
    ])
    manifest, permissions = apkinfo.parse_manifest(axml)
    assert manifest["package"] == "com.example.pantry"
    assert manifest["versionName"] == "4.2.0" and manifest["versionCode"] == 420
    assert permissions == ["android.permission.BIND_JOB_SERVICE", "android.permission.CAMERA",
                           "android.permission.INTERNET"]
    assert not set(permissions) & apkinfo.NOTABLE_PERMISSIONS
    assert apkinfo.application_label(axml) == "Pantry"


def _prefixed(data: bytes) -> bytes:
    return struct.pack("<I", len(data)) + data


def _signed_zip(cert: bytes) -> bytes:
    """A minimal zip with an APK Signing Block (v2 scheme) carrying one certificate."""
    plain = io.BytesIO()
    with zipfile.ZipFile(plain, "w") as z:
        z.writestr("classes.dex", b"dex")
    data = plain.getvalue()
    eocd = data.rfind(b"PK\x05\x06")
    cd_offset = struct.unpack_from("<I", data, eocd + 16)[0]
    signed_data = _prefixed(b"") + _prefixed(_prefixed(cert))       # digests, certificates
    signer = _prefixed(signed_data)
    v2_value = _prefixed(_prefixed(signer))
    pair = struct.pack("<QI", 4 + len(v2_value), 0x7109871A) + v2_value
    size = len(pair) + 24
    block = struct.pack("<Q", size) + pair + struct.pack("<Q", size) + b"APK Sig Block 42"
    head, tail = data[:cd_offset], data[cd_offset:]
    new_eocd = tail.rfind(b"PK\x05\x06")
    tail = tail[:new_eocd + 16] + struct.pack("<I", cd_offset + len(block)) + tail[new_eocd + 20:]
    return head + block + tail


def test_signing_certificates_from_v2_block():
    schemes, certs = apkinfo.signing_certificates(_signed_zip(b"fake-der-cert"))
    assert schemes == ["v2"] and certs == [b"fake-der-cert"]


def test_unsigned_zip_has_no_certificates():
    plain = io.BytesIO()
    with zipfile.ZipFile(plain, "w") as z:
        z.writestr("a", b"b")
    assert apkinfo.signing_certificates(plain.getvalue()) == ([], [])


def test_extract_bundle(tmp_path):
    bundle = tmp_path / "app.xapk"
    with zipfile.ZipFile(bundle, "w") as z:
        z.writestr("base.apk", b"1")
        z.writestr("config.en.apk", b"2")
        z.writestr("manifest.json", b"{}")
    files = apkinfo.extract_bundle(bundle, tmp_path / "out")
    assert sorted(f.name for f in files) == ["base.apk", "config.en.apk"]
