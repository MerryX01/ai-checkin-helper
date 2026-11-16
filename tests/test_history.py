"""签到历史：给额度看板补「今天已经签到到账多少」，不跨进程丢失。"""
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from signin.core.models import CheckinResult, Status
from signin.services import history


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "history.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_and_read_latest_today(self):
        history.append([CheckinResult("qoder", Status.OK, "领到了", credits=100)],
                       when=datetime(2026, 11, 16, 9, 0), path=self.path)
        history.append([CheckinResult("qoder", Status.ALREADY, "今天已领", credits=100)],
                       when=datetime(2026, 11, 16, 10, 30), path=self.path)
        got = history.today_results(path=self.path, today=date(2026, 11, 16))
        self.assertEqual(got["qoder"].status, Status.ALREADY)
        self.assertEqual(got["qoder"].credits, 100)

    def test_old_records_are_filtered(self):
        history.append([CheckinResult("trae", Status.OK, "昨天", credits=100)],
                       when=datetime(2026, 11, 15, 10, 0), path=self.path)
        got = history.today_results(path=self.path, today=date(2026, 11, 16))
        self.assertEqual(got, {})

    def test_broken_line_does_not_break_reading(self):
        self.path.write_text('{"date":"2026-11-16","platform":"x","status":"ok","credits":1}\nnot json\n',
                            encoding="utf-8")
        got = history.today_results(path=self.path, today=date(2026, 11, 16))
        self.assertIn("x", got)
        self.assertEqual(got["x"].credits, 1)

    def test_write_keeps_one_line_per_result(self):
        history.append([
            CheckinResult("qoder", Status.OK, "q", credits=100),
            CheckinResult("trae", Status.ALREADY, "t", credits=200),
        ], when=datetime(2026, 11, 16, 11, 0), path=self.path)
        lines = self.path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[1])["platform"], "trae")


if __name__ == "__main__":
    unittest.main()
