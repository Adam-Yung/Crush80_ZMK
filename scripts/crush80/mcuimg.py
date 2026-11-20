"""Validate an MCUboot image file before it goes anywhere near the board."""

import hashlib
import struct
from dataclasses import dataclass

IMAGE_MAGIC = 0x96F3B83D
TLV_INFO_MAGIC = 0x6907
TLV_INFO_PROT_MAGIC = 0x6908
TLV_SHA256 = 0x10

# Slot 0 is 0x10000-0x80000 (448 KB incl. the swap trailer); see docs/features/flash-layout.md.
SLOT_SIZE = 0x70000
# Room for the MCUboot trailer (swap status, magic) at the end of the slot.
TRAILER_RESERVE = 0x1000 * 4


class ImageError(Exception):
    pass


@dataclass(frozen=True)
class Image:
    path: str
    size: int
    version: str
    sha256: str  # hex digest from the image's own TLV, equal to what `mcumgr image list` prints


def parse(path):
    """Parse and fully validate the image at `path`. Raises ImageError with the reason."""
    with open(path, "rb") as f:
        data = f.read()
    return parse_bytes(data, path)


def parse_bytes(data, path="<bytes>"):
    if len(data) < 32:
        raise ImageError("file too small to be an MCUboot image")
    magic, _load, hdr_size, prot_size, img_size, flags, major, minor, rev, build = struct.unpack(
        "<IIHHIIBBHI", data[:28])
    if magic != IMAGE_MAGIC:
        raise ImageError(
            f"bad magic 0x{magic:08x}: not a signed MCUboot image (use the *.signed.bin file, not zmk.bin)")
    if hdr_size != 0x200:
        raise ImageError(f"unexpected header size 0x{hdr_size:x}")
    body_end = hdr_size + img_size + prot_size
    if body_end + 4 > len(data):
        raise ImageError("image is truncated: header claims more bytes than the file holds")
    if len(data) + TRAILER_RESERVE > SLOT_SIZE:
        raise ImageError(f"image of {len(data)} bytes does not fit the {SLOT_SIZE} byte slot with its trailer")

    tlv_magic, tlv_total = struct.unpack("<HH", data[body_end:body_end + 4])
    if tlv_magic != TLV_INFO_MAGIC:
        raise ImageError("missing TLV area after the image body")
    if body_end + tlv_total > len(data):
        raise ImageError("TLV area runs past the end of the file")
    if body_end + tlv_total != len(data):
        raise ImageError("unexpected bytes after the TLV area")

    digest = None
    pos = body_end + 4
    while pos + 4 <= body_end + tlv_total:
        tlv_type, _pad, tlv_len = struct.unpack("<BBH", data[pos:pos + 4])
        if tlv_type == TLV_SHA256:
            digest = data[pos + 4:pos + 4 + tlv_len]
        pos += 4 + tlv_len
    if digest is None or len(digest) != 32:
        raise ImageError("no SHA-256 TLV in image")
    if hashlib.sha256(data[:body_end]).digest() != digest:
        raise ImageError("SHA-256 in the image does not match its contents: file is corrupt")

    return Image(path=path, size=len(data), version=f"{major}.{minor}.{rev}+{build}", sha256=digest.hex())
