"""科技感主题色板与插值工具。"""
import unittest

from signin.ui import theme


class MixTest(unittest.TestCase):
    def test_endpoints_and_middle(self):
        self.assertEqual(theme.mix("#000000", "#FFFFFF", 0.0), "#000000")
        self.assertEqual(theme.mix("#000000", "#FFFFFF", 1.0), "#FFFFFF")
        self.assertEqual(theme.mix("#000000", "#FFFFFF", 0.5), "#808080")

    def test_clamps_out_of_range(self):
        self.assertEqual(theme.mix("#102030", "#304050", -2.0), "#102030")
        self.assertEqual(theme.mix("#102030", "#304050", 2.0), "#304050")

    def test_rejects_bad_colors(self):
        with self.assertRaises(ValueError):
            theme.mix("#12345", "#000000", 0.5)
        with self.assertRaises(ValueError):
            theme.mix("zzzzzz", "#000000", 0.5)

    def test_shade(self):
        self.assertEqual(theme.shade("#808080", 0.5), "#404040")
        self.assertEqual(theme.shade("#808080", 2.0), "#FFFFFF")  # 溢出截断到白


class WaveTest(unittest.TestCase):
    def test_wave_endpoints(self):
        self.assertEqual(theme.wave(0.0, 2.0), 0.0)
        self.assertEqual(theme.wave(1.0, 2.0), 1.0)   # 半周期处到峰值
        self.assertEqual(theme.wave(2.0, 2.0), 0.0)

    def test_wave_pause_holds(self):
        self.assertEqual(theme.wave(0.05, 2.0, pause=0.2), 0.0)   # 起点停留
        self.assertEqual(theme.wave(1.9, 2.0, pause=0.2), 0.0)    # 终点停留
        self.assertEqual(theme.wave(1.0, 2.0, pause=0.2), 1.0)    # 停留结束后到峰值

    def test_wave_range(self):
        for i in range(60):
            v = theme.wave(i / 30, 2.0)
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.0)

    def test_loop_cycles(self):
        self.assertEqual(theme.loop(0.0, 3.0), 0.0)
        self.assertAlmostEqual(theme.loop(1.5, 3.0), 0.5)
        self.assertAlmostEqual(theme.loop(4.5, 3.0), 0.5)  # 跨周期取模


if __name__ == "__main__":
    unittest.main()
