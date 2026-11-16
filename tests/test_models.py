"""结果模型与中文等宽对齐。"""
import unittest

from signin.core.models import CheckinResult, Status, display_width, pad


class WidthTest(unittest.TestCase):
    def test_chinese_counts_two(self):
        self.assertEqual(display_width('中文'), 4)
        self.assertEqual(display_width('abc'), 3)

    def test_pad_aligns_cjk(self):
        self.assertEqual(pad('豆包', 6), '豆包' + ' ' * 2)
        self.assertEqual(pad('Trae CN', 6), 'Trae CN')


class ResultTest(unittest.TestCase):
    def test_label_from_registry(self):
        import signin.platforms  # noqa: F401  触发注册
        self.assertEqual(CheckinResult('trae', Status.OK).label, 'Trae CN')

    def test_is_ok_covers_already(self):
        self.assertTrue(CheckinResult('x', Status.OK).is_ok)
        self.assertTrue(CheckinResult('x', Status.ALREADY).is_ok)
        self.assertFalse(CheckinResult('x', Status.FAILED).is_ok)

    def test_line_contains_status_and_credits(self):
        line = CheckinResult('qoder', Status.OK, 'ok', 120).line()
        self.assertIn('签到成功', line)
        self.assertIn('+120', line)

    def test_as_dict_serialises_status(self):
        data = CheckinResult('doubao', Status.SKIPPED, 'dry').as_dict()
        self.assertEqual(data['status'], 'skipped')


if __name__ == '__main__':
    unittest.main()
