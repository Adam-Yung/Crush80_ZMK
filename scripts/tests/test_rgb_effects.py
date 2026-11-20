"""Compiles zmk/src/rgb/effects.h with the host C compiler and checks the backlight maths."""
import os, shutil, subprocess, tempfile, unittest

HDR_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "zmk", "src", "rgb"))

PROGRAM = r"""
#include <stdio.h>
#include "effects.h"
int main(void) {
    for (int s = 0; s <= 255; s++) printf("keys %d %d\n", s, c80_gauge_keys((uint8_t)s));
    for (int i = 0; i < C80_GAUGE_KEYS; i++) printf("gauge %d %06x\n", i, (unsigned)c80_gauge_color(i));
    for (int p = 0; p <= 255; p++) printf("wave %d %d\n", p, c80_wave((uint8_t)p));
    printf("mix %06x %06x %06x\n", (unsigned)c80_mix(0x00D8FF, 0xFF2A8C, 0),
           (unsigned)c80_mix(0x00D8FF, 0xFF2A8C, 255), (unsigned)c80_mix(0x000000, 0xFEFEFE, 128));
    printf("phase %d %d %d %d\n", c80_ambient_phase(0, 0, 0, 0), c80_ambient_phase(3000, 0, 0, 0),
           c80_ambient_phase(0, 40, 0, 0), c80_ambient_phase(4000, 0, 0, 1));
    return 0;
}
"""


def compiler():
    return shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")


@unittest.skipUnless(compiler(), "no host C compiler")
class RgbEffects(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d = tempfile.mkdtemp()
        try:
            src, exe = os.path.join(d, "t.c"), os.path.join(d, "t")
            with open(src, "w") as f:
                f.write(PROGRAM)
            subprocess.run([compiler(), "-std=c99", "-Wall", "-Werror", "-I", HDR_DIR, src, "-o", exe],
                           check=True, timeout=60)
            out = subprocess.run([exe], check=True, timeout=10, capture_output=True, text=True).stdout
        finally:
            shutil.rmtree(d, ignore_errors=True)
        cls.rows = [line.split() for line in out.splitlines()]

    def get(self, kind):
        return [r[1:] for r in self.rows if r[0] == kind]

    def test_gauge_one_key_per_ten_percent(self):
        keys = {int(s): int(n) for s, n in self.get("keys")}
        self.assertEqual(keys[0], 1)    # never blank: a dead reading still shows one red key
        self.assertEqual(keys[19], 1)
        self.assertEqual(keys[20], 2)
        self.assertEqual(keys[90], 9)
        self.assertEqual(keys[99], 9)
        self.assertEqual(keys[100], 10)
        self.assertEqual(keys[255], 10)
        self.assertEqual(sorted(keys.values()), list(keys[s] for s in range(256)))  # monotonic

    def test_gauge_red_to_green(self):
        colours = [int(c, 16) for _, c in self.get("gauge")]
        self.assertEqual(colours[0], 0xFF0000)
        self.assertEqual(colours[-1], 0x00FF00)
        self.assertTrue(all(c & 0xFF == 0 for c in colours))  # no blue
        greens = [(c >> 8) & 0xFF for c in colours]
        self.assertEqual(greens, sorted(greens))

    def test_wave_range_and_shape(self):
        w = {int(p): int(v) for p, v in self.get("wave")}
        self.assertEqual(w[0], 0)
        self.assertEqual(max(w.values()), w[128])
        self.assertGreaterEqual(w[128], 250)
        self.assertTrue(all(0 <= v <= 255 for v in w.values()))
        self.assertTrue(all(w[p] <= w[p + 1] for p in range(127)))

    def test_mix_endpoints(self):
        a, b, mid = self.get("mix")[0]
        self.assertEqual(int(a, 16), 0x00D8FF)
        self.assertEqual(int(b, 16), 0xFF2A8C)
        self.assertEqual(int(mid, 16), 0x7F7F7F)

    def test_phase_moves(self):
        p0, p_half, p_x, p_win = map(int, self.get("phase")[0])
        self.assertEqual(p0, 0)
        self.assertEqual(p_half, 128)  # half of the 6 s macOS cycle
        self.assertEqual(p_x, 216)     # further right is earlier in the cycle: the wave runs left to right
        self.assertEqual(p_win, 128)   # half of the 8 s Windows cycle


if __name__ == "__main__":
    unittest.main()
