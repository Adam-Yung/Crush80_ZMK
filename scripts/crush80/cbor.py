"""Minimal CBOR (RFC 8949) subset for SMP: unsigned/negative ints, bytes, text, arrays, maps, bool, null.

Kept in the standard library so the recovery tools run on a fresh machine with no pip install.
"""

import struct


def _head(major, n):
    if n < 24:
        return bytes([major << 5 | n])
    if n < 1 << 8:
        return bytes([major << 5 | 24, n])
    if n < 1 << 16:
        return bytes([major << 5 | 25]) + struct.pack(">H", n)
    if n < 1 << 32:
        return bytes([major << 5 | 26]) + struct.pack(">I", n)
    return bytes([major << 5 | 27]) + struct.pack(">Q", n)


def dumps(obj):
    if obj is None:
        return b"\xf6"
    if obj is True:
        return b"\xf5"
    if obj is False:
        return b"\xf4"
    if isinstance(obj, int):
        return _head(0, obj) if obj >= 0 else _head(1, -1 - obj)
    if isinstance(obj, (bytes, bytearray)):
        return _head(2, len(obj)) + bytes(obj)
    if isinstance(obj, str):
        raw = obj.encode()
        return _head(3, len(raw)) + raw
    if isinstance(obj, (list, tuple)):
        return _head(4, len(obj)) + b"".join(dumps(x) for x in obj)
    if isinstance(obj, dict):
        return _head(5, len(obj)) + b"".join(dumps(k) + dumps(v) for k, v in obj.items())
    raise TypeError(f"cannot encode {type(obj).__name__}")


def loads(data):
    obj, end = _decode(memoryview(data), 0)
    if end != len(data):
        raise ValueError("trailing bytes after CBOR item")
    return obj


def _decode(buf, pos):
    if pos >= len(buf):
        raise ValueError("truncated CBOR")
    initial = buf[pos]
    major, info = initial >> 5, initial & 0x1F
    pos += 1
    if major == 7 and info in (20, 21, 22):
        return {20: False, 21: True, 22: None}[info], pos
    if info < 24:
        n = info
    elif info in (24, 25, 26, 27):
        size = 1 << (info - 24)
        if pos + size > len(buf):
            raise ValueError("truncated CBOR")
        n = int.from_bytes(buf[pos:pos + size], "big")
        pos += size
    else:
        raise ValueError(f"unsupported CBOR item 0x{initial:02x}")

    if major == 0:
        return n, pos
    if major == 1:
        return -1 - n, pos
    if major in (2, 3):
        if pos + n > len(buf):
            raise ValueError("truncated CBOR")
        raw = bytes(buf[pos:pos + n])
        return (raw if major == 2 else raw.decode()), pos + n
    if major == 4:
        items = []
        for _ in range(n):
            item, pos = _decode(buf, pos)
            items.append(item)
        return items, pos
    if major == 5:
        out = {}
        for _ in range(n):
            key, pos = _decode(buf, pos)
            out[key], pos = _decode(buf, pos)
        return out, pos
    raise ValueError(f"unsupported CBOR major type {major}")
