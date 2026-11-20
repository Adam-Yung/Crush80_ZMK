import os, re, unittest

HDR = os.path.join(os.path.dirname(__file__), "..", "..", "zmk", "src", "rgb", "led_map_data.h")


class LedMap(unittest.TestCase):
    def setUp(self):
        t = open(HDR).read()
        body = re.search(r"c80_rc_to_led\[6\]\[16\] = \{(.*?)\};", t, re.S).group(1)
        self.grid = [[None if x.strip() == "C80_LED_NONE" else int(x) for x in row.split(",")]
                     for row in re.findall(r"\{(.*?)\},", body)]
        extras = re.search(r"c80_extra_leds\[\]\[3\] = \{(.*?)\};", t, re.S).group(1)
        self.extras = [tuple(map(int, e.split(","))) for e in re.findall(r"\{\s*(.*?)\s*\}", extras)]

    def test_shape(self):
        self.assertEqual(len(self.grid), 6)
        self.assertTrue(all(len(r) == 16 for r in self.grid))

    def test_86_keys_mapped(self):
        self.assertEqual(sum(1 for r in self.grid for x in r if x is not None), 86)

    def test_no_led_used_twice_and_all_in_key_range(self):
        leds = [x for r in self.grid for x in r if x is not None] + [e[2] for e in self.extras]
        self.assertEqual(len(leds), len(set(leds)))
        self.assertTrue(all(0 <= x < 92 for x in leds))

    def test_known_keys(self):
        # Esc, F1 and Caps Lock were checked on hardware by the upstream project (LED 0, 1, 51 + 52).
        self.assertEqual(self.grid[0][0], 0)
        self.assertEqual(self.grid[0][1], 1)
        self.assertEqual(self.grid[3][0], 51)
        self.assertIn((3, 0, 52), self.extras)
        self.assertEqual(sum(1 for e in self.extras if (e[0], e[1]) == (5, 5)), 2)  # Space has three LEDs


if __name__ == "__main__":
    unittest.main()
