"""Builders for Android's binary resource formats, so tests don't need real APK contents."""

import struct


def string_pool(strings: list[str]) -> bytes:
    """A UTF-16 string pool chunk (ResStringPool), as used in resources.arsc and binary XML."""
    data = b"".join(struct.pack("<H", len(s)) + s.encode("utf-16le") + b"\x00\x00" for s in strings)
    offsets, pos = [], 0
    for s in strings:
        offsets.append(pos)
        pos += 2 + len(s) * 2 + 2
    data += b"\x00" * (-len(data) % 4)
    header = 28
    starts = header + 4 * len(strings)
    body = struct.pack(f"<{len(strings)}I", *offsets) + data
    return struct.pack("<HHIIIIII", 0x0001, header, header + len(body), len(strings), 0, 0, starts, 0) + body


def binary_xml(elements: list[tuple[str, dict[str, str | int]]]) -> bytes:
    """A binary XML file (like a compiled AndroidManifest.xml) with these start tags and attributes.

    Strings become string values, ints become decimal integers.
    """
    strings: list[str] = []

    def index(s: str) -> int:
        if s not in strings:
            strings.append(s)
        return strings.index(s)

    chunks = b""
    for name, attrs in elements:
        name_index = index(name)
        attributes = b""
        for key, value in attrs.items():
            key_index = index(key)
            if isinstance(value, int):
                attributes += struct.pack("<IIIHBBI", 0xFFFFFFFF, key_index, 0xFFFFFFFF, 8, 0, 0x10, value)
            else:
                value_index = index(value)
                attributes += struct.pack("<IIIHBBI", 0xFFFFFFFF, key_index, value_index, 8, 0, 0x03, value_index)
        # ResXMLTree_attrExt: namespace, name, attributeStart, attributeSize, count, id/class/style indices.
        body = struct.pack("<IIHHHHHH", 0xFFFFFFFF, name_index, 20, 20, len(attrs), 0, 0, 0) + attributes
        chunks += struct.pack("<HHIII", 0x0102, 16, 16 + len(body), 1, 0xFFFFFFFF) + body
    payload = string_pool(strings) + chunks
    return struct.pack("<HHI", 0x0003, 8, 8 + len(payload)) + payload
