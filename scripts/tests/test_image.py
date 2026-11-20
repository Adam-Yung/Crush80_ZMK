import hashlib
import os
import struct
import unittest

from crush80 import mcuimg
from crush80.mcumgr import parse_image_list

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def make_image(payload=b"\x13" * 1024, corrupt=False):
    hdr = struct.pack("<IIHHIIBBHI", mcuimg.IMAGE_MAGIC, 0, 0x200, 0, len(payload), 0, 1, 2, 3, 4)
    body = hdr + bytes(0x200 - len(hdr)) + payload
    digest = hashlib.sha256(body).digest()
    tlv = struct.pack("<BBH", mcuimg.TLV_SHA256, 0, 32) + digest
    data = body + struct.pack("<HH", mcuimg.TLV_INFO_MAGIC, 4 + len(tlv)) + tlv
    if corrupt:
        data = data[:300] + b"\xff" + data[301:]
    return data, digest.hex()


class ImageTest(unittest.TestCase):
    def test_valid(self):
        data, digest = make_image()
        img = mcuimg.parse_bytes(data)
        self.assertEqual(img.sha256, digest)
        self.assertEqual(img.version, "1.2.3+4")

    def test_corrupt_payload(self):
        with self.assertRaisesRegex(mcuimg.ImageError, "corrupt"):
            mcuimg.parse_bytes(make_image(corrupt=True)[0])

    def test_raw_bin_rejected(self):
        with self.assertRaisesRegex(mcuimg.ImageError, "signed"):
            mcuimg.parse_bytes(bytes(4096))

    def test_truncated_rejected(self):
        with self.assertRaises(mcuimg.ImageError):
            mcuimg.parse_bytes(make_image()[0][:-10])

    def test_too_big_rejected(self):
        with self.assertRaisesRegex(mcuimg.ImageError, "fit"):
            mcuimg.parse_bytes(make_image(b"\x00" * 0x70000)[0])

    def test_trailing_bytes_rejected(self):
        with self.assertRaises(mcuimg.ImageError):
            mcuimg.parse_bytes(make_image()[0] + b"\x00")

    def test_release_image_in_repo(self):
        path = os.path.join(REPO, "releases", "Crush80-No-RGB.bin")
        if os.path.exists(path):
            self.assertEqual(len(mcuimg.parse(path).sha256), 64)


class ImageListTest(unittest.TestCase):
    NEW = """Images:
 image=0 slot=0
    version: 0.3.0
    bootable: true
    flash_area_id: 1
    hash: AA11
    confirmed: true
    active: true
    pending: false
 image=0 slot=1
    version: 0.4.0
    hash: bb22
    confirmed: false
    active: false
    pending: true
Split status: N/A (0)
"""
    OLD = """Images:
 image=0 slot=0
    version: 0.3.0
    bootable: true
    flags: active confirmed
    hash: aa11
 image=0 slot=1
    version: 0.4.0
    flags: pending
    hash: bb22
"""

    def test_both_formats(self):
        for text in (self.NEW, self.OLD):
            s0, s1 = parse_image_list(text)
            self.assertEqual((s0.hash, s0.confirmed, s0.active, s0.pending), ("aa11", True, True, False))
            self.assertEqual((s1.hash, s1.confirmed, s1.pending), ("bb22", False, True))


if __name__ == "__main__":
    unittest.main()
