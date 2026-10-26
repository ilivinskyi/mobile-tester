"""resources.arsc lookups against tables built here, in the layouts Android uses."""

import struct

from binxml import string_pool as _string_pool
from mobiletester.android import apkinfo


def _type_chunk(type_id: int, values: dict[int, int], count: int, language: str = "", mode: str = "plain",
                region: str = "") -> bytes:
    """values: entry index -> global string index."""
    config = struct.pack("<IHH2s2s", 64, 0, 0, language.encode("ascii").ljust(2, b"\x00"),
                         region.encode("ascii").ljust(2, b"\x00")).ljust(64, b"\x00")
    header_size = 20 + len(config)
    entries, offsets = b"", {}
    for index, string_index in sorted(values.items()):
        offsets[index] = len(entries)
        if mode == "compact":
            entries += struct.pack("<HHI", 0, 0x0008 | (0x03 << 8), string_index)
        else:
            entries += struct.pack("<HHI", 8, 0, 0) + struct.pack("<HBBI", 8, 0, 0x03, string_index)
    if mode == "sparse":
        table = b"".join(struct.pack("<HH", i, off // 4) for i, off in sorted(offsets.items()))
        flags, entry_count = 0x01, len(offsets)
    else:
        table = b"".join(struct.pack("<I", offsets.get(i, 0xFFFFFFFF)) for i in range(count))
        flags, entry_count = 0, count
    entries_start = header_size + len(table)
    size = entries_start + len(entries)
    head = struct.pack("<HHIBBHII", 0x0201, header_size, size, type_id, flags, 0, entry_count, entries_start)
    return head + config + table + entries


def _table(strings: list[str], chunks: list[bytes], package_id: int = 0x7F) -> bytes:
    pool = _string_pool(strings)
    pkg_header = 288
    body = b"".join(chunks)
    package = struct.pack("<HHII", 0x0200, pkg_header, pkg_header + len(body), package_id)
    package += b"\x00" * 256 + b"\x00" * 20 + body
    return struct.pack("<HHII", 0x0002, 12, 12 + len(pool) + len(package), 1) + pool + package


def test_default_and_language_specific_string():
    arsc = _table(["Notes", "Notizen"], [_type_chunk(0x11, {2: 0}, 4), _type_chunk(0x11, {2: 1}, 4, "de")])
    assert apkinfo.resource_string(arsc, 0x7F110002) == "Notes"
    assert apkinfo.resource_string(arsc, 0x7F110002, "de") == "Notizen"
    assert apkinfo.resource_string(arsc, 0x7F110002, "fr") == "Notes"


def test_pseudo_locales_are_never_picked_and_regions_are_preferred():
    # Seen on a Pixel: a camera app whose only English label was the en-XA pseudo-locale "[Çåméŕå one]".
    arsc = _table(["[Çåméŕå]", "Camera", "Kamera (AT)"], [
        _type_chunk(0x11, {2: 0}, 4, "en", region="XA"),
        _type_chunk(0x11, {2: 1}, 4),
        _type_chunk(0x11, {2: 2}, 4, "de", region="AT"),
    ])
    assert apkinfo.resource_string(arsc, 0x7F110002, "en-NL") == "Camera"
    assert apkinfo.resource_string(arsc, 0x7F110002, "de-AT") == "Kamera (AT)"


def test_missing_entry_and_other_package():
    arsc = _table(["Notes"], [_type_chunk(0x11, {2: 0}, 4)])
    assert apkinfo.resource_string(arsc, 0x7F110003) is None
    assert apkinfo.resource_string(arsc, 0x01110002) is None


def test_sparse_and_compact_layouts():
    sparse = _table(["Maps"], [_type_chunk(0x0B, {500: 0}, 900, mode="sparse")])
    assert apkinfo.resource_string(sparse, 0x7F0B01F4) == "Maps"
    compact = _table(["Camera"], [_type_chunk(0x0B, {1: 0}, 2, mode="compact")])
    assert apkinfo.resource_string(compact, 0x7F0B0001) == "Camera"
