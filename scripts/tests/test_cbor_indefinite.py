import unittest

from crush80 import cbor


class IndefiniteCbor(unittest.TestCase):
    def test_real_echo_response_from_board(self):
        # Captured from the board: Zephyr SMP replies with an indefinite-length map.
        self.assertEqual(cbor.loads(bytes.fromhex("bf6172626869ff")), {"r": "hi"})

    def test_indefinite_map_with_rc_and_data(self):
        self.assertEqual(cbor.loads(bytes.fromhex("bf627263 00 64 64617461 42aabb ff".replace(" ", ""))), {"rc": 0, "data": b"\xaa\xbb"})

    def test_indefinite_array(self):
        self.assertEqual(cbor.loads(bytes.fromhex("9f0102ff")), [1, 2])

    def test_unterminated_rejected(self):
        with self.assertRaises(ValueError):
            cbor.loads(bytes.fromhex("bf61720"))

    def test_definite_still_works(self):
        self.assertEqual(cbor.loads(cbor.dumps({"off": 0, "len": 16})), {"off": 0, "len": 16})


if __name__ == "__main__":
    unittest.main()
