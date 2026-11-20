import struct
import unittest

from crush80 import cbor, smp


class CborTest(unittest.TestCase):
    def test_round_trip(self):
        for obj in [0, 23, 24, 255, 256, 65535, 65536, 2**32, -1, -25, b"", b"\x00" * 300, "rc", True, False, None,
                    {"off": 0x80000, "data": b"ab"}, [1, [2, {"k": "v"}]]]:
            self.assertEqual(cbor.loads(cbor.dumps(obj)), obj)

    def test_known_vectors(self):
        self.assertEqual(cbor.dumps({"rc": 0}), bytes.fromhex("a1627263" "00"))
        self.assertEqual(cbor.dumps(500), bytes.fromhex("1901f4"))

    def test_rejects_truncated_and_trailing(self):
        with self.assertRaises(ValueError):
            cbor.loads(bytes.fromhex("a16272"))
        with self.assertRaises(ValueError):
            cbor.loads(b"\x00\x00")


class FrameTest(unittest.TestCase):
    def test_crc_vector(self):
        self.assertEqual(smp.crc16_ccitt(b"123456789"), 0x31C3)

    def _response(self, seq, payload):
        return smp.encode_frame(smp.build_message(smp.OP_WRITE + 1, smp.GROUP_FLASH_MGMT, 0, seq, payload))

    def test_parse_single_and_multiline(self):
        small = self._response(7, {"rc": 0})
        big = self._response(8, {"rc": 0, "data": bytes(range(256))})
        self.assertGreater(big.count(b"\n"), 1)
        got = smp.FrameParser().feed(small + big)
        self.assertEqual([g[0] for g in got], [7, 8])
        self.assertEqual(got[1][1]["data"], bytes(range(256)))

    def test_log_noise_and_split_delivery(self):
        frame = self._response(9, {"rc": 0, "data": b"x" * 200})
        stream = b"[00:00:01] <inf> boot: hello\r\n" + frame + b"more log\r\n"
        parser = smp.FrameParser()
        out = []
        for i in range(0, len(stream), 7):
            out += parser.feed(stream[i:i + 7])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][0], 9)

    def test_bad_crc_is_dropped(self):
        frame = bytearray(self._response(1, {"rc": 0}))
        frame[10] ^= 0x01
        self.assertEqual(smp.FrameParser().feed(bytes(frame)), [])

    def test_request_response_over_fake_port(self):
        class Port:
            def __init__(self):
                self.out = b""

            def write(self, data):
                req = smp.FrameParser().feed(data)
                self.reply = req

            def flush(self):
                pass

            def read(self, n):
                if hasattr(self, "reply") and self.reply:
                    seq, payload = self.reply.pop()
                    return smp.encode_frame(smp.build_message(1, 64, 2, seq, {"rc": 0, "data": b"\xaa" * payload["len"]}))
                return b""

        client = smp.SerialSMP(Port())
        self.assertEqual(smp.flash_read(client, 0x10000, 16), b"\xaa" * 16)

    def test_timeout_raises(self):
        class Dead:
            def write(self, d): pass
            def flush(self): pass
            def read(self, n): return b""

        ticks = iter(range(0, 1000))
        client = smp.SerialSMP(Dead(), clock=lambda: next(ticks) / 10)
        with self.assertRaises(smp.SMPError):
            client.request(smp.OP_READ, 64, 2, {"off": 0, "len": 1}, timeout=1.0)

    def test_nonzero_rc_raises(self):
        class Err:
            def write(self, d): self.seq = smp.FrameParser().feed(d)[0][0]
            def flush(self): pass
            def read(self, n):
                return smp.encode_frame(smp.build_message(1, 64, 0, self.seq, {"rc": 3}))

        with self.assertRaises(smp.SMPError):
            smp.flash_erase(smp.SerialSMP(Err()), 0x10000, 0x1000)


if __name__ == "__main__":
    unittest.main()
