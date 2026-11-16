"""窗口点击兜底：坐标校验与窗口查找（不依赖第三方包）。"""
import unittest
from unittest import mock

from signin import gui


class ClickTest(unittest.TestCase):
    def test_ratio_out_of_range_is_rejected(self):
        self.assertFalse(gui.click_at_ratio("Trae CN", 1.2, 0.5))
        self.assertFalse(gui.click_at_ratio("Trae CN", 0.5, -0.1))

    def test_empty_title_is_rejected(self):
        self.assertFalse(gui.click_at_ratio("", 0.5, 0.5))

    def test_missing_window_returns_false(self):
        with mock.patch.object(gui, "find_window", return_value=0):
            self.assertFalse(gui.click_at_ratio("Trae CN", 0.5, 0.9))

    def test_empty_title_finds_nothing(self):
        self.assertEqual(gui.find_window(""), 0)


if __name__ == '__main__':
    unittest.main()
